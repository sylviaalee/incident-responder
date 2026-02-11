# Cache Clearing Runbook

## Overview
This runbook covers procedures for clearing various caches in production when stale data issues occur.

**Use this runbook when:**
- Users report seeing outdated content
- Configuration changes aren't reflected
- After emergency data corrections
- Cache corruption suspected
- Memory pressure on cache servers

---

## Cache Architecture

Our caching infrastructure has multiple layers:

1. **Application Cache (Redis)** - Session data, API responses
2. **CDN Cache (CloudFront)** - Static assets, API responses
3. **Database Query Cache** - PostgreSQL query results
4. **Application Memory Cache** - In-process caching

---

## Prerequisites
- Production access (via VPN)
- kubectl access to production cluster
- AWS CLI configured with production credentials
- Monitoring dashboard access

---

## Quick Reference

| Cache Type | Impact | Recovery Time | Risk Level |
|------------|--------|---------------|------------|
| Single key | Minimal | Instant | Low |
| Pattern match | Low-Medium | < 30 seconds | Low |
| Full Redis | High | 1-2 minutes | Medium |
| CDN cache | High | 5-15 minutes | Low |
| Database cache | Medium | < 1 minute | Medium |

---

## Procedure 1: Clear Specific Cache Keys

**Use when:** You know the exact cache key(s) to clear

### Redis Cache

```bash
# Connect to Redis
kubectl exec -it redis-master-0 -n production -- redis-cli

# Clear specific key
DEL user:sessions:user_12345

# Clear multiple keys
DEL product:123 product:456 product:789

# Verify deletion
EXISTS user:sessions:user_12345
# Should return: (integer) 0

# Exit Redis
exit
```

**Expected impact:** Minimal - only affects specific cached items

---

### CDN Cache (CloudFront)

```bash
# Invalidate specific paths
aws cloudfront create-invalidation \
  --distribution-id E1234567890ABC \
  --paths "/api/users/12345" "/api/products/123"

# Check invalidation status
aws cloudfront get-invalidation \
  --distribution-id E1234567890ABC \
  --id I1234567890DEF
```

**Expected impact:** 5-10 minutes for global propagation

---

## Procedure 2: Clear Cache by Pattern

**Use when:** You need to clear multiple related keys

### Redis Pattern Deletion

```bash
# Connect to Redis
kubectl exec -it redis-master-0 -n production -- redis-cli

# Find keys matching pattern
KEYS user:sessions:*
# Review the list carefully before deleting!

# Delete all matching keys (USE CAREFULLY)
redis-cli --scan --pattern "user:sessions:*" | xargs redis-cli DEL

# For large datasets, use safer pipeline approach:
redis-cli --scan --pattern "product:*" | head -1000 | xargs redis-cli DEL
```

⚠️ **WARNING:** KEYS command blocks Redis on large datasets. Use SCAN in production.

**Safer approach with SCAN:**

```bash
# Scan and delete in batches
redis-cli --scan --pattern "cache:api:*" | while read key; do
  redis-cli DEL "$key"
done
```

---

### CDN Pattern Invalidation

```bash
# Invalidate all API responses
aws cloudfront create-invalidation \
  --distribution-id E1234567890ABC \
  --paths "/api/*"

# Invalidate all images
aws cloudfront create-invalidation \
  --distribution-id E1234567890ABC \
  --paths "/images/*"

# Check invalidation progress
aws cloudfront get-invalidation \
  --distribution-id E1234567890ABC \
  --id I1234567890DEF
```

---

## Procedure 3: Full Cache Flush

**Use when:** Major data corruption or emergency

⚠️ **HIGH IMPACT OPERATION** - Requires incident commander approval

### Full Redis Flush

```bash
# Check current memory usage first
kubectl exec -it redis-master-0 -n production -- redis-cli INFO memory

# ⚠️ FLUSH ALL KEYS (REQUIRES APPROVAL)
kubectl exec -it redis-master-0 -n production -- redis-cli FLUSHDB

# Verify
kubectl exec -it redis-master-0 -n production -- redis-cli DBSIZE
# Should return: (integer) 0
```

**Expected impact:**
- All users will experience cache misses
- Database load will spike temporarily
- Response times will increase for 2-5 minutes
- Auto-recovery as cache repopulates

**Mitigation:**
```bash
# Scale up application pods before flush
kubectl scale deployment/productionapi --replicas=10 -n production

# Perform flush
kubectl exec -it redis-master-0 -n production -- redis-cli FLUSHDB

# Monitor metrics
watch kubectl top pods -n production

# Scale back down after recovery (5-10 min)
kubectl scale deployment/productionapi --replicas=5 -n production
```

---

### Full CDN Cache Invalidation

```bash
# Invalidate everything (USE WITH CAUTION)
aws cloudfront create-invalidation \
  --distribution-id E1234567890ABC \
  --paths "/*"

# Monitor invalidation
aws cloudfront get-invalidation \
  --distribution-id E1234567890ABC \
  --id <invalidation-id>
```

**Cost warning:** Each invalidation after first 1,000 paths per month costs $0.005 per path

---

## Procedure 4: Database Query Cache

**Use when:** Query results are stale

### PostgreSQL Query Cache

```bash
# Connect to database
psql -h db-prod-primary.internal -U admin -d production

-- Clear entire query cache
DISCARD PLANS;

-- Clear specific table cache
SELECT pg_stat_reset_single_table_counters('public', 'products');

-- Clear all statistics (includes cache)
SELECT pg_stat_reset();

-- Verify cache is cleared
SELECT * FROM pg_stat_user_tables WHERE relname = 'products';
```

---

## Procedure 5: Application Memory Cache

**Use when:** In-memory cache is stale

### Rolling Restart Method (Zero Downtime)

```bash
# Check current status
kubectl get pods -n production -l app=productionapi

# Rolling restart to clear in-memory caches
kubectl rollout restart deployment/productionapi -n production

# Monitor restart progress
kubectl rollout status deployment/productionapi -n production

# Verify all pods are healthy
kubectl get pods -n production -l app=productionapi
```

**Expected downtime:** None (rolling restart)  
**Duration:** 2-3 minutes

---

### Force Pod Restart (Emergency)

```bash
# Get all pod names
kubectl get pods -n production -l app=productionapi -o name

# Delete all pods (they will be recreated)
kubectl delete pods -n production -l app=productionapi

# Wait for pods to come back
kubectl wait --for=condition=ready pod -l app=productionapi -n production --timeout=120s
```

**Expected downtime:** 30-60 seconds  
**Use only when:** Rolling restart isn't fast enough

---

## Monitoring During Cache Clear

### Key Metrics to Watch

```bash
# Redis hit rate
kubectl exec -it redis-master-0 -n production -- redis-cli INFO stats | grep keyspace

# Database connections
psql -h db-prod-primary.internal -c "SELECT count(*) FROM pg_stat_activity;"

# Application response times
curl https://api.company.com/metrics | jq .response_time_ms
```

**Alert thresholds:**
- Redis hit rate drops below 80% - Normal during cache clear
- Database connections > 80 - Scale up application
- Response time > 500ms - May need to throttle traffic

---

## Post-Cache-Clear Validation

### Validation Checklist

**1. Verify new data is served:**
```bash
# Test API endpoint
curl https://api.company.com/api/products/123

# Check response headers for cache status
curl -I https://api.company.com/api/products/123 | grep -i cache
```

**2. Check metrics:**
- Error rate: https://metrics.company.com/errors
- Cache hit rate: https://metrics.company.com/cache-hits
- Response time: https://metrics.company.com/latency

**3. Verify user experience:**
- Test key user flows manually
- Check for reported issues in support channels
- Monitor #engineering Slack for alerts

---

## Common Issues

### Issue: Cache fills up immediately after clearing

**Cause:** Cache warming or high traffic

**Solution:**
```bash
# Check Redis memory
kubectl exec -it redis-master-0 -n production -- redis-cli INFO memory

# If memory high, check key distribution
kubectl exec -it redis-master-0 -n production -- redis-cli --bigkeys

# Consider increasing maxmemory
kubectl edit configmap redis-config -n production
# Set: maxmemory 4gb
```

---

### Issue: Application errors after cache clear

**Cause:** Cache dependency in code

**Solution:**
```bash
# Check application logs
kubectl logs -n production -l app=productionapi --tail=100

# Look for null pointer or cache miss errors
# May need to restart application to reinitialize
kubectl rollout restart deployment/productionapi -n production
```

---

### Issue: CDN still serving old content

**Cause:** Invalidation not complete or additional edge locations

**Solution:**
```bash
# Check invalidation status
aws cloudfront get-invalidation --distribution-id E1234567890ABC --id <id>

# If "Completed" but still seeing old content:
# Try cache-busting with query parameters
curl "https://cdn.company.com/image.jpg?v=$(date +%s)"

# Or invalidate with different path format
aws cloudfront create-invalidation \
  --distribution-id E1234567890ABC \
  --paths "/image.jpg" "/image.jpg?*"
```

---

## Emergency Contacts

**Cache Issues:**
- DevOps Lead: Mike Rodriguez - @mike.rodriguez
- Backend Lead: Sarah Chen - @sarah.chen

**Database Issues:**
- DBA Lead: Jessica Wang - @jessica.wang

**On-Call:** PagerDuty alert

---

## Related Runbooks
- [Database Failover](./database-failover.md)
- [Performance Degradation](./performance-degradation.md)
- [Incident Response](./incident-response.md)

---

**Last Updated:** 2025-02-11  
**Owner:** DevOps Team  
**Review Schedule:** Quarterly