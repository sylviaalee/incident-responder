# Deployment Rollback Runbook

## Overview
This runbook covers the procedures for rolling back a failed deployment to production.

**Use this runbook when:**
- A deployment causes elevated error rates (>2%)
- Response times degrade significantly (>500ms average)
- Critical functionality is broken
- Security vulnerability is discovered in new version

---

## Prerequisites
- Access to production deployment system
- kubectl access to production cluster
- Access to deployment logs
- Incident commander assigned

---

## Procedure

### 1. Identify Current and Previous Versions

```bash
# Check current running version
kubectl get deployments -n production -o wide

# Check deployment history
kubectl rollout history deployment/productionapi -n production
```

**Expected Output:**
- Current version number
- Previous stable version number
- Deployment revision numbers

---

### 2. Assess Impact

**Check metrics dashboard:**
- Error rate: https://metrics.company.com/errors
- Response time: https://metrics.company.com/latency
- Active users: https://metrics.company.com/users

**Document:**
- Time issue started: _______________
- Affected users/requests: _______________
- Error types observed: _______________

---

### 3. Initiate Rollback

**Option A: Automated Rollback (Recommended)**

```bash
# Trigger automated rollback via deployment system
./deploy.sh rollback --environment production --target-version v2.15.1

# Monitor rollback progress
./deploy.sh status --deployment-id <deployment-id>
```

**Option B: Manual Rollback**

```bash
# Rollback to previous revision
kubectl rollout undo deployment/productionapi -n production

# Verify rollback
kubectl rollout status deployment/productionapi -n production

# Check pods are running
kubectl get pods -n production -l app=productionapi
```

---

### 4. Monitor Recovery

**Wait 5 minutes, then check:**

```bash
# Check error rates
curl https://api.company.com/metrics/errors

# Check response times
curl https://api.company.com/metrics/latency

# Check pod health
kubectl get pods -n production -l app=productionapi
```

**Success criteria:**
- ✓ Error rate < 0.5%
- ✓ Response time < 200ms
- ✓ All pods in Running state
- ✓ Health checks passing

---

### 5. Post-Rollback Actions

**Immediate:**
1. Update status page: https://status.company.com
2. Notify stakeholders via Slack #incidents channel
3. Update incident ticket with timeline

**Within 1 hour:**
1. Create post-incident report
2. Document root cause
3. Create tickets for fixes
4. Schedule post-mortem meeting

**Within 24 hours:**
1. Fix issues in rolled-back version
2. Test fixes in staging
3. Plan re-deployment

---

## Rollback Decision Matrix

| Error Rate | Response Time | Action |
|------------|---------------|--------|
| < 1% | < 300ms | Monitor, consider rollback |
| 1-2% | 300-500ms | Prepare for rollback |
| 2-5% | 500ms-1s | **ROLLBACK IMMEDIATELY** |
| > 5% | > 1s | **ROLLBACK IMMEDIATELY** |

---

## Common Issues

### Issue: Rollback fails with "ImagePullBackOff"

**Cause:** Previous Docker image not available in registry

**Solution:**
```bash
# List available images
docker images | grep productionapi

# If image missing, rebuild from git tag
git checkout v2.15.1
docker build -t productionapi:v2.15.1 .
docker push registry.company.com/productionapi:v2.15.1
```

---

### Issue: Database migrations block rollback

**Cause:** Forward-only migrations applied

**Solution:**
1. Check if migration is reversible
2. If reversible, run down migration:
```bash
./migrate down 1 --database production
```
3. If not reversible, consult with DBA team
4. May need data recovery from backup

---

### Issue: Pods crash loop after rollback

**Cause:** Configuration mismatch

**Solution:**
```bash
# Check config maps
kubectl get configmap -n production

# Restore previous config
kubectl apply -f configs/production/v2.15.1/

# Restart deployment
kubectl rollout restart deployment/productionapi -n production
```

---

## Contacts

**During Business Hours (9am-5pm ET):**
- Engineering Lead: Sarah Chen - @sarah.chen (Slack)
- DevOps Lead: Mike Rodriguez - @mike.rodriguez (Slack)

**After Hours:**
- On-call Engineer: PagerDuty alert will be sent
- Emergency: Call on-call hotline: +1-555-0123

---

## Related Runbooks
- [Database Failover](./database-failover.md)
- [Incident Response](./incident-response.md)
- [Production Access](./production-access.md)

---

**Last Updated:** 2025-02-11  
**Owner:** DevOps Team  
**Review Schedule:** Monthly