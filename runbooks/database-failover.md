# Database Failover Runbook

## Overview
This runbook covers failing over from primary to secondary database in case of primary database failure or degradation.

**Use this runbook when:**
- Primary database is unresponsive
- Primary database performance is severely degraded
- Planned maintenance on primary database
- Primary database corruption detected

---

## Prerequisites
- Database admin access (both primary and secondary)
- Access to monitoring dashboards
- VPN connection to production network
- Incident ticket created

---

## Architecture Overview

```
Primary Database (Write):    db-prod-primary-01 (us-east-1a)
Secondary Database (Read):   db-prod-secondary-01 (us-east-1b)
Replication Lag Target:      < 2 seconds
```

---

## Pre-Failover Checks

### 1. Verify Secondary Database Health

```bash
# SSH to secondary database
ssh db-prod-secondary-01.internal

# Check replication status
sudo -u postgres psql -c "SELECT now() - pg_last_xact_replay_timestamp() AS replication_lag;"
```

**Expected:** Replication lag < 10 seconds  
**If > 30 seconds:** Wait for replication to catch up before failover

---

### 2. Check Application Impact

```bash
# Check active database connections
psql -h db-prod-primary-01 -U admin -d production -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

# Check pending transactions
psql -h db-prod-primary-01 -U admin -d production -c "SELECT count(*) FROM pg_stat_activity WHERE state IN ('idle in transaction', 'active');"
```

**Document:**
- Active connections: _______________
- Pending transactions: _______________
- Expected impact: _______________

---

## Failover Procedure

### Phase 1: Prepare Secondary Database (5-10 minutes)

**Step 1.1: Promote secondary to primary**

```bash
# SSH to secondary database
ssh db-prod-secondary-01.internal

# Stop replication and promote
sudo -u postgres /usr/lib/postgresql/14/bin/pg_ctl promote -D /var/lib/postgresql/14/main

# Verify promotion
sudo -u postgres psql -c "SELECT pg_is_in_recovery();"
```

**Expected Output:** `f` (false) - database is now primary

---

**Step 1.2: Update DNS records**

```bash
# Update DNS to point to new primary
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch file://dns-failover.json

# Verify DNS propagation (wait 60 seconds)
dig db-prod-primary.company.internal
```

**Expected:** DNS now points to db-prod-secondary-01

---

### Phase 2: Update Application Configuration (2-5 minutes)

**Step 2.1: Update application database connection strings**

```bash
# Update Kubernetes secrets
kubectl create secret generic db-connection \
  --from-literal=host=db-prod-secondary-01.internal \
  --from-literal=port=5432 \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart application pods to pick up new connection
kubectl rollout restart deployment/productionapi -n production
```

---

**Step 2.2: Verify application connectivity**

```bash
# Check application logs
kubectl logs -n production -l app=productionapi --tail=50

# Run health check
curl https://api.company.com/health
```

**Expected Output:**
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "v2.16.0"
}
```

---

### Phase 3: Monitor and Validate (10-15 minutes)

**Step 3.1: Monitor application metrics**

Check dashboards:
- Error rates: https://metrics.company.com/errors
- Database query latency: https://metrics.company.com/db-latency
- Connection pool status: https://metrics.company.com/db-connections

**Success Criteria:**
- ✓ Error rate < 0.5%
- ✓ Query latency < 50ms
- ✓ No connection pool exhaustion

---

**Step 3.2: Run validation queries**

```bash
# Test write operations
psql -h db-prod-secondary-01.internal -U admin -d production -c \
  "INSERT INTO health_check (timestamp, status) VALUES (NOW(), 'ok');"

# Test read operations
psql -h db-prod-secondary-01.internal -U admin -d production -c \
  "SELECT * FROM health_check ORDER BY timestamp DESC LIMIT 5;"

# Check for replication conflicts (should be none)
psql -h db-prod-secondary-01.internal -U admin -d production -c \
  "SELECT * FROM pg_stat_database_conflicts WHERE datname = 'production';"
```

---

## Post-Failover Tasks

### Immediate (Within 1 hour)

1. **Update documentation:**
   - Update architecture diagrams
   - Mark old primary as down in monitoring
   - Update on-call playbooks

2. **Communication:**
   - Post in #engineering: "Database failover completed successfully"
   - Update status page
   - Email stakeholders with summary

3. **Backup verification:**
```bash
# Verify backups are running on new primary
sudo -u postgres pg_basebackup -h db-prod-secondary-01.internal -D /backup/$(date +%Y%m%d)
```

---

### Short-term (Within 24 hours)

1. **Investigate old primary:**
   - Determine root cause of failure
   - Check disk space: `df -h`
   - Check system logs: `journalctl -u postgresql`
   - Review slow query logs

2. **Set up new secondary:**
   - If old primary is salvageable, rebuild as secondary
   - Otherwise, provision new instance
   - Configure streaming replication

---

### Long-term (Within 1 week)

1. **Post-mortem:**
   - Schedule team meeting
   - Document lessons learned
   - Create action items for prevention

2. **Capacity planning:**
   - Review database sizing
   - Check if additional replicas needed
   - Evaluate auto-failover solutions

---

## Rollback Procedure

**If failover causes issues, rollback steps:**

1. **Stop writes to new primary:**
```bash
# Set database to read-only
psql -h db-prod-secondary-01.internal -U admin -d production -c \
  "ALTER DATABASE production SET default_transaction_read_only = on;"
```

2. **Point application back to old primary:**
```bash
# Revert DNS changes
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch file://dns-rollback.json

# Update K8s secrets
kubectl create secret generic db-connection \
  --from-literal=host=db-prod-primary-01.internal \
  --dry-run=client -o yaml | kubectl apply -f -
```

3. **Restart applications:**
```bash
kubectl rollout restart deployment/productionapi -n production
```

---

## Common Issues

### Issue: Secondary database has significant replication lag

**Solution:**
- Wait for replication to catch up
- If urgent, consider accepting data loss window
- Document decision in incident ticket

---

### Issue: Application can't connect to new primary

**Cause:** Security group or firewall rules

**Solution:**
```bash
# Check security groups
aws ec2 describe-security-groups --group-ids sg-xxxxx

# Add application servers to allowed list
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 5432 \
  --source-group sg-yyyyy
```

---

### Issue: Replication conflicts after failover

**Cause:** Timing issues with in-flight transactions

**Solution:**
```bash
# Identify conflicts
psql -h db-prod-secondary-01.internal -c \
  "SELECT * FROM pg_stat_database_conflicts;"

# Resolve by restarting affected connections
SELECT pg_terminate_backend(pid) FROM pg_stat_activity 
WHERE state = 'idle in transaction' AND xact_start < NOW() - INTERVAL '5 minutes';
```

---

## Emergency Contacts

**Database Team:**
- DBA Lead: Jessica Wang - @jessica.wang (Slack) / +1-555-0198
- DBA On-Call: PagerDuty rotation

**Infrastructure Team:**
- Infrastructure Lead: Tom Martinez - @tom.martinez (Slack)

**Escalation:**
- VP Engineering: +1-555-0100

---

## Related Runbooks
- [Database Backup and Restore](./database-backup-restore.md)
- [Deployment Rollback](./deployment-rollback.md)
- [Incident Response](./incident-response.md)

---

**Last Updated:** 2025-02-11  
**Owner:** Database Team  
**Review Schedule:** Quarterly