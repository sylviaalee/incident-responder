# Security Incident Response Runbook

## Overview
This runbook provides procedures for responding to security incidents including unauthorized access, data breaches, DDoS attacks, and suspicious activity.

**Use this runbook when:**
- Unauthorized access detected
- Potential data breach
- Malware or ransomware detected
- DDoS attack in progress
- Security vulnerability exploited
- Suspicious user activity

⚠️ **CRITICAL:** Security incidents require immediate escalation and legal/PR coordination.

---

## Incident Severity Classification

| Severity | Description | Examples | Response Time |
|----------|-------------|----------|---------------|
| **CRITICAL** | Active breach, data exposed | Database dump leaked, ransomware, active attacker | < 15 minutes |
| **HIGH** | Serious vulnerability exploited | Unauthorized admin access, SQL injection, privilege escalation | < 30 minutes |
| **MEDIUM** | Attempted breach or vulnerability | Failed login attempts, suspicious traffic, unpatched CVE | < 2 hours |
| **LOW** | Security hygiene issue | Weak password, outdated dependency, minor config issue | < 24 hours |

---

## Prerequisites
- Security incident commander authority
- Access to all system logs and monitoring
- Legal/compliance contact information
- PR/communications team contact
- Forensics tools and backup systems

---

## Phase 1: Initial Detection and Containment (0-15 minutes)

### Step 1: Confirm and Classify

**Gather initial information:**

```bash
# Check security alerts
kubectl logs -n monitoring alertmanager-0 | grep -i security

# Check intrusion detection system
sudo tail -100 /var/log/ids/alerts.log

# Check failed authentication attempts
sudo grep "Failed password" /var/log/auth.log | tail -50

# Check unusual sudo usage
sudo grep -i sudo /var/log/auth.log | tail -50
```

**Document in security incident ticket:**
```
## Security Incident
Time Detected: [timestamp]
Detection Method: [alert/manual/report]
Affected Systems: [list]
Potential Impact: [data/access/availability]
Initial Classification: [CRITICAL/HIGH/MEDIUM/LOW]
```

---

### Step 2: Declare Security Incident

**In Slack #security-incidents:**
```bash
/incident declare-security critical "Unauthorized database access detected"

# This automatically:
# - Creates #security-incident-[ID] channel
# - Pages security on-call
# - Notifies legal and compliance
# - Enables audit logging
# - Locks down change management
```

---

### Step 3: Immediate Containment

**Priority: Stop the attack in progress**

**A. Block attacking IP addresses:**
```bash
# Add to firewall blocklist
sudo iptables -A INPUT -s 203.0.113.42 -j DROP

# Block at AWS security group level
aws ec2 revoke-security-group-ingress \
  --group-id sg-12345678 \
  --protocol tcp \
  --port 22 \
  --cidr 203.0.113.42/32

# Block at WAF level
aws wafv2 update-ip-set \
  --name blocked-ips \
  --scope REGIONAL \
  --id abcd-1234 \
  --addresses 203.0.113.42/32
```

---

**B. Terminate compromised sessions:**
```bash
# Kill database sessions from suspicious IPs
psql -h db-prod-primary.internal -c "
  SELECT pg_terminate_backend(pid) 
  FROM pg_stat_activity 
  WHERE client_addr = '203.0.113.42';
"

# Revoke API tokens
kubectl exec -n production redis-0 -- redis-cli DEL "session:compromised-user-id"

# Force logout all sessions (nuclear option)
kubectl exec -n production redis-0 -- redis-cli FLUSHDB
```

---

**C. Disable compromised accounts:**
```bash
# Disable user account
psql -h db-prod-primary.internal -c "
  UPDATE users SET active = false 
  WHERE email = 'compromised@example.com';
"

# Revoke database user access
psql -h db-prod-primary.internal -c "
  REVOKE ALL PRIVILEGES ON DATABASE production FROM suspicious_user;
  ALTER ROLE suspicious_user NOLOGIN;
"

# Disable service account
kubectl patch serviceaccount suspicious-sa -n production -p '{"automountServiceAccountToken": false}'
```

---

**D. Isolate affected systems:**
```bash
# Isolate compromised pod
kubectl label pod compromised-pod-123 quarantine=true
kubectl delete pod compromised-pod-123 -n production

# Scale down compromised deployment
kubectl scale deployment suspicious-app --replicas=0 -n production

# Disconnect from network (extreme cases)
kubectl patch service compromised-service -p '{"spec":{"type":"ClusterIP"}}'
```

---

## Phase 2: Investigation and Evidence Collection (15-60 minutes)

### Step 4: Preserve Evidence

⚠️ **DO NOT** destroy logs or modify systems before collecting evidence

**Collect logs immediately:**
```bash
# Create forensics directory with timestamp
mkdir -p /forensics/incident-$(date +%Y%m%d-%H%M%S)
cd /forensics/incident-$(date +%Y%m%d-%H%M%S)

# Capture all application logs
kubectl logs -n production --all-containers --prefix=true \
  --since=24h > application-logs.txt

# Capture database logs
ssh db-prod-primary-01.internal \
  "sudo tar -czf /tmp/db-logs.tar.gz /var/log/postgresql/"
scp db-prod-primary-01.internal:/tmp/db-logs.tar.gz .

# Capture system logs
for host in app-01 app-02 app-03; do
  ssh $host "sudo tar -czf /tmp/system-logs.tar.gz /var/log/"
  scp $host:/tmp/system-logs.tar.gz system-logs-$host.tar.gz
done

# Capture network traffic (if available)
kubectl exec -n monitoring netflow-collector -- \
  tcpdump -w /tmp/capture.pcap -c 10000
kubectl cp monitoring/netflow-collector:/tmp/capture.pcap network-capture.pcap

# Hash all evidence files
sha256sum * > evidence-checksums.txt
```

---

**Database query logs:**
```bash
# Export query history from compromised timeframe
psql -h db-prod-primary.internal -c "
  COPY (
    SELECT * FROM pg_stat_statements 
    WHERE last_executed > NOW() - INTERVAL '24 hours'
    ORDER BY last_executed DESC
  ) TO STDOUT CSV HEADER
" > database-queries.csv

# Check for suspicious queries
psql -h db-prod-primary.internal -c "
  SELECT query, calls, mean_exec_time, 
         last_executed, userid, dbid
  FROM pg_stat_statements 
  WHERE query LIKE '%DROP%' 
     OR query LIKE '%DELETE%' 
     OR query LIKE '%UPDATE%'
     OR query LIKE '%information_schema%'
  ORDER BY last_executed DESC;
" > suspicious-queries.txt
```

---

**Access logs:**
```bash
# Export API access logs
kubectl logs -n production -l app=productionapi \
  --since=24h | grep -E "POST|PUT|DELETE|PATCH" > api-access-logs.txt

# Export authentication logs
kubectl logs -n production auth-service-xxx \
  --since=24h | grep -i "login\|auth\|token" > auth-logs.txt

# Check sudo usage
ssh app-01 "sudo grep -i sudo /var/log/auth.log" > sudo-usage.txt
```

---

**System state capture:**
```bash
# Snapshot compromised pod (before deletion)
kubectl debug compromised-pod-123 -n production \
  --image=busybox --target=compromised-pod-123 \
  -- sh -c "tar -czf /tmp/pod-snapshot.tar.gz /proc /etc /var"

kubectl cp production/compromised-pod-123:/tmp/pod-snapshot.tar.gz pod-snapshot.tar.gz

# Capture running processes (before termination)
kubectl exec -n production compromised-pod-123 -- ps aux > process-list.txt

# Capture network connections
kubectl exec -n production compromised-pod-123 -- netstat -tuln > network-connections.txt
```

---

### Step 5: Timeline Construction

**Build attack timeline:**
```bash
# First suspicious activity
grep "203.0.113.42" application-logs.txt | head -1

# Failed authentication attempts
grep -i "failed\|unauthorized" auth-logs.txt | wc -l

# Successful compromise
grep -i "success\|authenticated" auth-logs.txt | grep "203.0.113.42"

# Privilege escalation
grep -i "admin\|root\|sudo" system-logs-*.txt

# Data access
grep -i "SELECT\|export\|download" database-queries.csv
```

**Document timeline in incident channel:**
```
## Attack Timeline
[12:34:15] First failed login attempt from 203.0.113.42
[12:35:22] 47 failed attempts in 1 minute (brute force)
[12:36:45] Successful login - credentials compromised
[12:37:12] Privilege escalation - admin token obtained
[12:38:00] Database query - users table exported
[12:38:30] Large data download - 500MB transferred
[12:39:00] Attack detected - containment initiated
```

---

## Phase 3: Eradication (1-4 hours)

### Step 6: Remove Attacker Access

**Change all credentials:**
```bash
# Rotate database passwords
psql -h db-prod-primary.internal -c "
  ALTER ROLE app_user WITH PASSWORD 'new_secure_password_12345';
  ALTER ROLE admin WITH PASSWORD 'new_admin_password_67890';
"

# Rotate API keys
kubectl create secret generic api-keys \
  --from-literal=stripe_key=sk_new_stripe_key \
  --from-literal=aws_key=AKIA_new_aws_key \
  --dry-run=client -o yaml | kubectl apply -f -

# Rotate JWT signing keys
kubectl create secret generic jwt-secret \
  --from-literal=signing_key=$(openssl rand -base64 32) \
  --dry-run=client -o yaml | kubectl apply -f -

# Restart applications to pick up new secrets
kubectl rollout restart deployment/productionapi -n production
```

---

**Revoke all sessions:**
```bash
# Expire all user sessions
psql -h db-prod-primary.internal -c "
  UPDATE sessions SET expires_at = NOW() WHERE expires_at > NOW();
"

# Clear session cache
kubectl exec -n production redis-0 -- redis-cli --scan --pattern "session:*" | \
  xargs kubectl exec -n production redis-0 -- redis-cli DEL

# Force re-authentication for all users
kubectl exec -n production redis-0 -- redis-cli SET force_reauth true EX 3600
```

---

**Close backdoors:**
```bash
# Check for unauthorized SSH keys
for host in app-01 app-02 app-03 db-prod-primary-01; do
  echo "=== $host ==="
  ssh $host "sudo cat /root/.ssh/authorized_keys"
  ssh $host "sudo find /home -name authorized_keys -exec cat {} \;"
done

# Check for unauthorized users
ssh db-prod-primary-01.internal "sudo cat /etc/passwd | grep -v nologin | grep -v false"

# Check for unauthorized cron jobs
for host in app-01 app-02 app-03; do
  echo "=== $host ==="
  ssh $host "sudo crontab -l"
  ssh $host "sudo find /etc/cron.* -type f"
done

# Check for suspicious processes
kubectl exec -n production $(kubectl get pods -n production -l app=productionapi -o name | head -1) \
  -- ps aux | grep -v "\[" | grep -v "python\|java\|node"
```

---

### Step 7: Patch Vulnerabilities

**Apply security patches:**
```bash
# Update system packages
for host in app-01 app-02 app-03; do
  ssh $host "sudo apt update && sudo apt upgrade -y"
done

# Update Docker images
docker build -t productionapi:v2.16.1-security .
docker push productionapi:v2.16.1-security

kubectl set image deployment/productionapi \
  productionapi=productionapi:v2.16.1-security \
  -n production

# Update dependencies
cd /repos/productionapi
npm audit fix --force
pip install --upgrade -r requirements.txt

# Redeploy with updates
./deploy.sh --environment production --version v2.16.1-security
```

---

**Harden security configuration:**
```bash
# Enable MFA for all admin accounts
# (manual process via admin panel)

# Restrict database access by IP
psql -h db-prod-primary.internal -c "
  REVOKE ALL ON DATABASE production FROM public;
  GRANT CONNECT ON DATABASE production TO app_user;
"

# Update pg_hba.conf to whitelist IPs only
ssh db-prod-primary-01.internal "sudo cat >> /etc/postgresql/14/main/pg_hba.conf" <<EOF
# Application servers only
host    production    app_user    10.0.1.0/24    scram-sha-256
host    production    app_user    10.0.2.0/24    scram-sha-256
# Deny all others
host    all          all         0.0.0.0/0      reject
EOF

# Reload PostgreSQL
ssh db-prod-primary-01.internal "sudo systemctl reload postgresql"

# Enable request signing for API
kubectl set env deployment/productionapi -n production \
  REQUIRE_REQUEST_SIGNING=true
```

---

## Phase 4: Recovery (2-8 hours)

### Step 8: Restore Normal Operations

**Gradual restoration:**
```bash
# 1. Verify all security patches applied
kubectl get pods -n production -o jsonpath='{.items[*].spec.containers[*].image}'

# 2. Run security scan
kubectl run security-scan --rm -i --restart=Never \
  --image=aquasec/trivy:latest \
  -- image productionapi:v2.16.1-security

# 3. Enable monitoring with extra scrutiny
kubectl apply -f monitoring/enhanced-security-alerts.yaml

# 4. Gradually restore traffic
# Start with 10% traffic
kubectl patch service productionapi -p '{"spec":{"sessionAffinity":"ClientIP"}}'
# Monitor for 30 minutes

# Scale up to 50%
kubectl scale deployment/productionapi --replicas=5 -n production
# Monitor for 30 minutes

# Full restoration
kubectl scale deployment/productionapi --replicas=10 -n production
```

---

### Step 9: Enhanced Monitoring

**Enable additional security monitoring:**
```bash
# Enable audit logging
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: audit-policy
  namespace: kube-system
data:
  audit-policy.yaml: |
    apiVersion: audit.k8s.io/v1
    kind: Policy
    rules:
    - level: RequestResponse
      resources:
      - group: ""
        resources: ["secrets", "configmaps"]
EOF

# Enable database query logging
psql -h db-prod-primary.internal -c "
  ALTER SYSTEM SET log_statement = 'all';
  ALTER SYSTEM SET log_connections = 'on';
  ALTER SYSTEM SET log_disconnections = 'on';
"
psql -h db-prod-primary.internal -c "SELECT pg_reload_conf();"

# Enable detailed API logging
kubectl set env deployment/productionapi -n production \
  LOG_LEVEL=DEBUG \
  LOG_REQUESTS=true \
  LOG_RESPONSES=true
```

---

**Set up real-time alerts:**
```bash
# Alert on suspicious database queries
cat >> /monitoring/prometheus/alerts.yml <<EOF
- alert: SuspiciousQueryPattern
  expr: rate(pg_stat_statements_calls{query=~".*DROP|DELETE|information_schema.*"}[5m]) > 0
  labels:
    severity: critical
  annotations:
    summary: "Suspicious SQL query detected"

- alert: UnauthorizedAccess
  expr: rate(http_requests_total{status="401"}[5m]) > 10
  labels:
    severity: warning
  annotations:
    summary: "High rate of unauthorized access attempts"
EOF
```

---

## Phase 5: Post-Incident (24-48 hours)

### Step 10: Impact Assessment

**Determine data exposure:**
```bash
# Check what data was accessed
psql -h db-prod-primary.internal -c "
  SELECT table_name, 
         count(*) as queries,
         max(last_executed) as last_access
  FROM pg_stat_statements
  WHERE userid = (SELECT oid FROM pg_roles WHERE rolname = 'compromised_user')
    AND last_executed > '2025-02-11 12:30:00'
  GROUP BY table_name
  ORDER BY queries DESC;
"

# Check file downloads
aws s3api list-objects-v2 \
  --bucket company-uploads \
  --prefix uploads/ \
  --query "Contents[?LastModified>=\`2025-02-11T12:30:00\`]"
```

**Document affected data:**
```
## Data Breach Assessment
Compromised:
- User table: 10,000 records (emails, hashed passwords, names)
- Order table: 5,000 records (order details, no payment info)
- Not compromised: Payment data (stored separately, not accessed)

Total affected users: 10,000
Data exported: 500MB
Sensitive data included: Email addresses, phone numbers, names
```

---

### Step 11: Notifications

**Legal and compliance notifications:**
```
TO: legal@company.com, compliance@company.com
SUBJECT: URGENT - Security Incident Notification

A security incident occurred on 2025-02-11 involving unauthorized 
access to production database. Preliminary assessment indicates:
- 10,000 user records accessed
- Data includes: emails, names, phone numbers
- No payment information compromised
- Attack contained within 30 minutes
- Full forensic report pending

Requires legal review for breach notification obligations.
```

---

**User notification (if required):**
```
SUBJECT: Important Security Notice

We're writing to inform you of a security incident that may have 
affected your account. On February 11, 2025, we detected unauthorized 
access to our systems.

What happened:
An unauthorized party gained access to some user account information.

What information was involved:
Your email address, name, and phone number may have been accessed.

What we're doing:
- We've resolved the security issue and enhanced our security measures
- We've reset your password as a precaution
- We're offering 12 months of free credit monitoring

What you should do:
- Reset your password when you next log in
- Enable two-factor authentication (we now require this)
- Monitor your accounts for suspicious activity

For questions: security@company.com
```

---

### Step 12: Post-Mortem and Improvements

**Security post-mortem template:**
```
## Security Incident Post-Mortem
Incident ID: SEC-2025-02-11-001
Date: 2025-02-11
Duration: 30 minutes (detection to containment)
Impact: 10,000 users

### What Happened
[Detailed technical description]

### Root Cause
- Weak password policy allowed brute force
- No rate limiting on login attempts
- No MFA enforcement for admin accounts
- Insufficient database access controls

### What Went Well
- Quick detection (5 minutes)
- Effective containment (no ongoing access)
- Good evidence preservation
- Clear communication

### What Went Poorly
- Delayed notification to legal
- Unclear escalation procedures
- Manual blocking process too slow

### Action Items
1. [HIGH] Implement MFA for all accounts - @alex.kim - Due: 2025-02-15
2. [HIGH] Add rate limiting to auth endpoints - @sarah.chen - Due: 2025-02-18
3. [MEDIUM] Automate IP blocking via WAF - @mike.rodriguez - Due: 2025-02-25
4. [MEDIUM] Implement database access audit trail - @jessica.wang - Due: 2025-03-01
5. [LOW] Update security incident runbook - @alex.kim - Due: 2025-02-20
```

---

## Common Attack Patterns

### SQL Injection

**Detection:**
```bash
# Check for SQL injection patterns in logs
grep -Ei "(union select|' or '1'='1|exec\(|drop table)" application-logs.txt
```

**Mitigation:**
```bash
# Enable parameterized queries only
# Update application code to use prepared statements
# Enable ModSecurity WAF rules for SQL injection
kubectl apply -f waf/sql-injection-rules.yaml
```

---

### Brute Force Attack

**Detection:**
```bash
# High rate of failed logins
grep "Failed password" auth-logs.txt | cut -d' ' -f11 | sort | uniq -c | sort -rn
```

**Mitigation:**
```bash
# Enable fail2ban
sudo apt install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban

# Configure rate limiting
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: rate-limit
data:
  limit: "5r/m"  # 5 requests per minute per IP
EOF
```

---

### DDoS Attack

**Detection:**
```bash
# Unusual traffic spike
kubectl logs -n monitoring metrics-server | grep requests_per_second
```

**Mitigation:**
```bash
# Enable AWS Shield
aws shield create-protection \
  --name production-api \
  --resource-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/api-lb

# Enable CloudFlare DDoS protection (if using CF)
curl -X PATCH "https://api.cloudflare.com/client/v4/zones/ZONE_ID/settings/ddos_protection" \
  -H "Authorization: Bearer TOKEN" \
  -d '{"value":"on"}'
```

---

## Emergency Contacts

**Security Team:**
- Security Lead: Alex Kim - @alex.kim / +1-555-0178
- Security Engineer: Lisa Park - @lisa.park / +1-555-0189

**Legal & Compliance:**
- General Counsel: Richard Brown - richard.brown@company.com / +1-555-0200
- Compliance Officer: Maria Garcia - maria.garcia@company.com / +1-555-0201

**Executive Escalation:**
- CTO: Lisa Johnson - +1-555-0101
- CEO: David Kim - +1-555-0001

**External:**
- FBI Cyber Division: +1-555-0300 (for major breaches)
- AWS Security: Case via AWS Console
- External Security Firm: SecureOps Inc - +1-555-0400

---

## Related Runbooks
- [Incident Response](./incident-response.md)
- [Backup and Restore](./backup-and-restore.md)
- [Database Failover](./database-failover.md)

---

**Last Updated:** 2025-02-11  
**Owner:** Security Team  
**Review Schedule:** Quarterly, and after each security incident