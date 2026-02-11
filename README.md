# Production Runbooks

This directory contains operational runbooks for managing production infrastructure and responding to incidents.

## Available Runbooks

### Core Operations

1. **[Deployment Rollback](./deployment-rollback.md)**
   - Roll back failed deployments
   - Handle deployment issues
   - Restore previous versions
   - **Use when:** Deployment causes errors or degraded performance

2. **[Application Scaling](./application-scaling.md)**
   - Scale applications under load
   - Handle traffic spikes
   - Pre-scale for planned events
   - **Use when:** High load, planned traffic increases, or performance issues

3. **[Cache Clearing](./cache-clearing.md)**
   - Clear Redis cache
   - Invalidate CDN cache
   - Clear database query cache
   - **Use when:** Stale data, cache corruption, or after emergency data fixes

### Database Operations

4. **[Database Failover](./database-failover.md)**
   - Fail over to secondary database
   - Handle primary database failure
   - Switch database instances
   - **Use when:** Database is down, corrupted, or needs maintenance

5. **[Backup and Restore](./backup-and-restore.md)**
   - Create manual backups
   - Restore from backup
   - Test backup integrity
   - **Use when:** Need to restore data, test backups, or before risky operations

### Security & Infrastructure

6. **[Security Incident Response](./security-incident-response.md)**
   - Respond to security breaches
   - Handle unauthorized access
   - Contain and eradicate threats
   - **Use when:** Security breach, unauthorized access, or suspicious activity

7. **[SSL Certificate Renewal](./ssl-certificate-renewal.md)**
   - Renew SSL/TLS certificates
   - Handle expired certificates
   - Update certificate configuration
   - **Use when:** Certificate expiring soon or already expired

### Incident Management

8. **[Incident Response](./incident-response.md)**
   - General incident response framework
   - Coordinate incident resolution
   - Communication templates
   - **Use when:** Any production incident occurs

## Quick Reference

### Common Scenarios

| Scenario | Runbook | Priority |
|----------|---------|----------|
| Deployment caused errors | [Deployment Rollback](./deployment-rollback.md) | HIGH |
| Database is down | [Database Failover](./database-failover.md) | CRITICAL |
| Users seeing old data | [Cache Clearing](./cache-clearing.md) | MEDIUM |
| High traffic/slow response | [Application Scaling](./application-scaling.md) | HIGH |
| Need to restore data | [Backup and Restore](./backup-and-restore.md) | HIGH |
| Security breach | [Security Incident Response](./security-incident-response.md) | CRITICAL |
| SSL certificate expired | [SSL Certificate Renewal](./ssl-certificate-renewal.md) | HIGH |
| General incident | [Incident Response](./incident-response.md) | VARIES |

## Emergency Contacts

### On-Call Rotation
- **PagerDuty:** https://company.pagerduty.com
- **On-Call Phone:** +1-555-0123

### Team Leads
- **Engineering Lead:** Sarah Chen - @sarah.chen / +1-555-0145
- **DevOps Lead:** Mike Rodriguez - @mike.rodriguez / +1-555-0156
- **Security Lead:** Alex Kim - @alex.kim / +1-555-0178
- **DBA Lead:** Jessica Wang - @jessica.wang / +1-555-0198

### Escalation
- **VP Engineering:** Michael Park - @michael.park / +1-555-0100
- **CTO:** Lisa Johnson - @lisa.johnson / +1-555-0101
- **CEO:** David Kim - +1-555-0001 (SEV-1 only)

## Incident Declaration

### In Slack
```
/incident declare sev-2 "Brief description of issue"
```

### Severity Levels
- **SEV-1:** Complete outage, data breach - Response: < 5 min
- **SEV-2:** Major degradation - Response: < 15 min
- **SEV-3:** Minor impact - Response: < 1 hour
- **SEV-4:** Minimal impact - Response: < 24 hours

## Monitoring Dashboards

- **Overall Health:** https://metrics.company.com/d/overview
- **Application Performance:** https://metrics.company.com/d/app-performance
- **Database Performance:** https://metrics.company.com/d/database
- **Cache Performance:** https://metrics.company.com/d/cache
- **Security Dashboard:** https://metrics.company.com/d/security

## Common Tools and Access

### Required Access
- Production VPN: `sudo openvpn --config production.ovpn`
- kubectl: `kubectl config use-context production`
- AWS Console: https://console.aws.amazon.com
- Database: `psql -h db-prod-primary.internal -U admin production`

### Useful Commands

**Check system health:**
```bash
# Application pods
kubectl get pods -n production

# Pod resource usage
kubectl top pods -n production

# Recent events
kubectl get events -n production --sort-by='.lastTimestamp' | head -20

# Application metrics
curl https://api.company.com/metrics
```

**Check logs:**
```bash
# Application logs
kubectl logs -n production -l app=productionapi --tail=100

# Follow logs
kubectl logs -n production -l app=productionapi -f

# Database logs
ssh db-prod-primary-01.internal "sudo tail -100 /var/log/postgresql/postgresql-14-main.log"
```

## Runbook Maintenance

### Review Schedule
- **Monthly:** All runbooks reviewed for accuracy
- **Quarterly:** Full test of critical procedures
- **After incidents:** Update based on lessons learned

### Contributing
1. Create branch: `git checkout -b update-runbook-name`
2. Make changes to runbook
3. Test procedures in staging
4. Create pull request with description
5. Get review from team lead
6. Merge and announce in #engineering

### Runbook Template
When creating new runbooks, follow this structure:
1. Overview (what/when to use)
2. Prerequisites
3. Procedure with clear steps
4. Verification steps
5. Common issues and solutions
6. Contacts
7. Related runbooks

## Additional Resources

- **Production Architecture:** https://docs.company.com/architecture
- **Security Policies:** https://docs.company.com/security
- **On-Call Handbook:** https://docs.company.com/oncall
- **Post-Mortem Archive:** https://docs.company.com/postmortems

---

**Last Updated:** 2025-02-11  
**Maintained By:** DevOps Team  
**Questions:** Post in #devops or #engineering