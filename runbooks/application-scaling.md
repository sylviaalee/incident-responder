# Application Scaling Runbook

## Overview
This runbook covers procedures for scaling applications to handle increased load, whether planned (product launches, marketing campaigns) or unplanned (viral traffic, attacks).

**Use this runbook when:**
- Expecting traffic spike (planned event)
- Currently experiencing high load
- Proactive scaling before peak hours
- Performance degradation under load

---

## Prerequisites
- kubectl access to production cluster
- AWS Console access (for EC2, RDS, etc.)
- Access to monitoring dashboards
- PagerDuty access for on-call escalation

---

## Current Architecture Overview

**Application Tier:**
- Deployment: `productionapi`
- Current replicas: 5
- Auto-scaling: Enabled (min: 5, max: 20)
- Target CPU: 70%
- Target Memory: 80%

**Database Tier:**
- Primary: `db-prod-primary-01` (db.r6g.xlarge)
- Read replicas: 2
- Connection pool: 50 per instance

**Cache Tier:**
- Redis cluster: 3 nodes
- Memory: 4GB per node
- Eviction policy: allkeys-lru

---

## Quick Reference

| Scenario | Action | Time | Risk |
|----------|--------|------|------|
| CPU >80% sustained | Scale up pods | 2 min | Low |
| Memory >85% | Scale up pods | 2 min | Low |
| DB connections >80% | Increase pool size | 5 min | Medium |
| Expected 5x traffic | Pre-scale everything | 30 min | Low |
| Emergency overload | Shed load + scale | 5 min | Medium |

---

## Phase 1: Assessment (2-5 minutes)

### Step 1: Check Current Load

```bash
# Application metrics
kubectl top pods -n production -l app=productionapi

# Current replica count
kubectl get deployment productionapi -n production

# Check HPA (Horizontal Pod Autoscaler)
kubectl get hpa -n production

# Request rate
curl https://api.company.com/metrics | jq '.requests_per_second'
```

**Document current state:**
```
Current Replicas: ___
CPU Usage: ___% average
Memory Usage: ___% average
Request Rate: ___ req/sec
Error Rate: ___%
Response Time: ___ ms
```

---

### Step 2: Identify Bottleneck

**Application bottleneck:**
```bash
# High CPU/Memory on pods
kubectl top pods -n production -l app=productionapi

# Pod status (check for OOMKilled, CrashLoopBackOff)
kubectl get pods -n production -l app=productionapi
```

**Database bottleneck:**
```bash
# Connection count
psql -h db-prod-primary.internal -c \
  "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"

# Slow queries
psql -h db-prod-primary.internal -c \
  "SELECT query, calls, mean_exec_time FROM pg_stat_statements 
   ORDER BY mean_exec_time DESC LIMIT 5;"

# Lock contention
psql -h db-prod-primary.internal -c \
  "SELECT count(*) FROM pg_locks WHERE NOT granted;"
```

**Cache bottleneck:**
```bash
# Redis memory usage
kubectl exec -it redis-master-0 -n production -- redis-cli INFO memory

# Cache hit rate
kubectl exec -it redis-master-0 -n production -- redis-cli INFO stats \
  | grep keyspace_hits
```

**Network/Load balancer:**
```bash
# ALB metrics
aws elbv2 describe-target-health \
  --target-group-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/api-tg/abc123

# Check for unhealthy targets
```

---

## Phase 2: Immediate Scaling (5-10 minutes)

### Scenario A: Scale Application Pods

**Manual scale (immediate):**
```bash
# Scale to 10 replicas
kubectl scale deployment/productionapi --replicas=10 -n production

# Verify scaling
kubectl get pods -n production -l app=productionapi

# Monitor rollout
kubectl rollout status deployment/productionapi -n production

# Wait for all pods to be ready (1-2 minutes)
watch kubectl get pods -n production -l app=productionapi
```

---

**Adjust HPA (for sustained load):**
```bash
# Increase max replicas
kubectl patch hpa productionapi -n production --patch \
  '{"spec":{"maxReplicas":30}}'

# Lower CPU threshold for more aggressive scaling
kubectl patch hpa productionapi -n production --patch \
  '{"spec":{"targetCPUUtilizationPercentage":60}}'

# Verify changes
kubectl describe hpa productionapi -n production
```

---

### Scenario B: Scale Database

**Increase connection pool:**
```bash
# Check current max connections
psql -h db-prod-primary.internal -c "SHOW max_connections;"

# Increase (requires reload)
psql -h db-prod-primary.internal -c \
  "ALTER SYSTEM SET max_connections = 200;"

# Reload configuration
psql -h db-prod-primary.internal -c "SELECT pg_reload_conf();"

# Verify
psql -h db-prod-primary.internal -c "SHOW max_connections;"
```

**Scale up database instance (longer process):**
```bash
# Current instance type
aws rds describe-db-instances \
  --db-instance-identifier db-prod-primary-01 \
  --query 'DBInstances[0].DBInstanceClass'

# Modify instance type (requires brief downtime)
aws rds modify-db-instance \
  --db-instance-identifier db-prod-primary-01 \
  --db-instance-class db.r6g.2xlarge \
  --apply-immediately

# Monitor modification
aws rds describe-db-instances \
  --db-instance-identifier db-prod-primary-01 \
  --query 'DBInstances[0].DBInstanceStatus'

# Takes 5-15 minutes
```

**Route more read traffic to replicas:**
```bash
# Update application config to use read replicas
kubectl set env deployment/productionapi -n production \
  READ_DB_HOSTS="db-prod-read-01.internal,db-prod-read-02.internal"

# Verify distribution
psql -h db-prod-read-01.internal -c \
  "SELECT count(*) FROM pg_stat_activity;"
```

---

### Scenario C: Scale Cache (Redis)

**Increase Redis memory:**
```bash
# Check current memory
kubectl exec -it redis-master-0 -n production -- redis-cli CONFIG GET maxmemory

# Increase memory limit
kubectl exec -it redis-master-0 -n production -- \
  redis-cli CONFIG SET maxmemory 8gb

# Verify
kubectl exec -it redis-master-0 -n production -- redis-cli INFO memory
```

**Add Redis replicas:**
```bash
# Scale Redis StatefulSet
kubectl scale statefulset redis --replicas=5 -n production

# Verify
kubectl get pods -n production -l app=redis

# Update application to use additional nodes
kubectl set env deployment/productionapi -n production \
  REDIS_NODES="redis-0:6379,redis-1:6379,redis-2:6379,redis-3:6379,redis-4:6379"
```

---

### Scenario D: Optimize Cache Strategy

**Increase cache TTL temporarily:**
```bash
# Update application config
kubectl set env deployment/productionapi -n production \
  CACHE_TTL=3600

# Rolling restart to apply
kubectl rollout restart deployment/productionapi -n production
```

**Pre-warm cache for known traffic:**
```bash
# Run cache warming script
kubectl run cache-warmer --rm -i --restart=Never \
  --image=productionapi:v2.16.0 \
  -- python scripts/warm_cache.py --top-products 1000
```

---

## Phase 3: Load Shedding (Emergency)

**Use when scaling isn't fast enough:**

### Enable Rate Limiting

```bash
# Apply aggressive rate limits
kubectl apply -f configs/rate-limit-strict.yaml

# Verify
curl -I https://api.company.com/api/test
# Should see: X-RateLimit-Limit: 50
```

**rate-limit-strict.yaml:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rate-limit-config
  namespace: production
data:
  global_limit: "50"
  per_ip_limit: "10"
  burst: "20"
```

---

### Disable Non-Critical Features

```bash
# Disable recommendation engine
kubectl set env deployment/productionapi -n production \
  ENABLE_RECOMMENDATIONS=false

# Disable analytics tracking
kubectl set env deployment/productionapi -n production \
  ENABLE_ANALYTICS=false

# Disable email notifications (queue instead)
kubectl set env deployment/productionapi -n production \
  EMAIL_MODE=queue

# Rolling restart
kubectl rollout restart deployment/productionapi -n production
```

---

### Serve Cached/Static Responses

```bash
# Enable aggressive caching at CDN level
aws cloudfront update-distribution \
  --id E1234567890ABC \
  --default-ttl 3600 \
  --max-ttl 7200

# Enable stale-while-revalidate
curl -X POST https://api.company.com/admin/cache/policy \
  -d '{"stale_while_revalidate": true, "stale_ttl": 600}'
```

---

## Phase 4: Planned Scaling (Pre-event)

**Use this for known traffic spikes (product launches, sales, etc.)**

### T-Minus 2 Hours: Pre-scale Everything

**Scale application:**
```bash
# Pre-scale to expected load
kubectl scale deployment/productionapi --replicas=15 -n production

# Increase HPA max
kubectl patch hpa productionapi -n production --patch \
  '{"spec":{"maxReplicas":40}}'
```

**Warm up database:**
```bash
# Increase connection pool
psql -h db-prod-primary.internal -c \
  "ALTER SYSTEM SET max_connections = 300;"
psql -h db-prod-primary.internal -c "SELECT pg_reload_conf();"

# Pre-warm query cache
psql -h db-prod-primary.internal -f scripts/cache_warmup.sql
```

**Warm up cache:**
```bash
# Pre-populate cache with likely requests
kubectl run cache-warmer --rm -i --restart=Never \
  --image=productionapi:v2.16.0 \
  -- python scripts/warm_cache.py --scenario product_launch
```

**Increase monitoring frequency:**
```bash
# Increase Prometheus scrape interval
kubectl edit configmap prometheus-config -n monitoring
# Change: scrape_interval: 5s (from 15s)

# Reload Prometheus
kubectl delete pod -n monitoring -l app=prometheus
```

---

### T-Minus 30 Minutes: Final Checks

**Run load test:**
```bash
# Synthetic load test
kubectl run load-test --rm -i --restart=Never \
  --image=loadtest:latest \
  -- loadtest --rps 1000 --duration 60s https://api.company.com/api/products

# Verify metrics stay healthy
```

**Checklist:**
- [ ] Application scaled to baseline load
- [ ] Database connections increased
- [ ] Cache warmed with likely data
- [ ] Rate limits configured but not too strict
- [ ] Monitoring dashboards open
- [ ] Team on standby in Slack
- [ ] Rollback plan documented

---

### During Event: Active Monitoring

**Watch key metrics every 5 minutes:**
```bash
# Quick status check script
watch -n 5 '
  echo "=== Pods ==="
  kubectl get pods -n production -l app=productionapi | grep -c Running
  echo "=== CPU ==="
  kubectl top pods -n production -l app=productionapi | awk "{sum+=\$2} END {print sum/NR}"
  echo "=== Requests ==="
  curl -s https://api.company.com/metrics | jq .requests_per_second
  echo "=== Errors ==="
  curl -s https://api.company.com/metrics | jq .error_rate
'
```

**Be ready to:**
- Scale up further if CPU/memory >80%
- Enable rate limiting if error rate >2%
- Shed non-critical load if needed
- Escalate to on-call if metrics degrade

---

## Phase 5: Scale Down (Post-event)

**Don't scale down immediately - wait for traffic to stabilize**

### T-Plus 2 Hours: Gradual Scale Down

```bash
# Reduce by 20% every 30 minutes
kubectl scale deployment/productionapi --replicas=12 -n production
# Wait 30 min, monitor metrics

kubectl scale deployment/productionapi --replicas=9 -n production
# Wait 30 min, monitor metrics

kubectl scale deployment/productionapi --replicas=7 -n production
# Wait 30 min, monitor metrics

# Return to normal (5)
kubectl scale deployment/productionapi --replicas=5 -n production
```

**Reset HPA:**
```bash
kubectl patch hpa productionapi -n production --patch \
  '{"spec":{"maxReplicas":20,"targetCPUUtilizationPercentage":70}}'
```

**Reset database:**
```bash
psql -h db-prod-primary.internal -c \
  "ALTER SYSTEM SET max_connections = 100;"
psql -h db-prod-primary.internal -c "SELECT pg_reload_conf();"
```

---

## Monitoring and Metrics

### Key Dashboards

**Grafana dashboards to monitor:**
- Overall Health: https://metrics.company.com/d/overview
- Application Performance: https://metrics.company.com/d/app-performance
- Database Performance: https://metrics.company.com/d/database
- Cache Performance: https://metrics.company.com/d/cache

---

### Key Metrics

**Application:**
- Requests per second (RPS)
- Error rate (%)
- Response time (p50, p95, p99)
- Pod CPU/Memory usage

**Database:**
- Active connections
- Query latency
- Slow query count
- Replication lag

**Cache:**
- Hit rate (%)
- Memory usage
- Evictions per second
- Key count

---

## Auto-Scaling Configuration

### Current HPA Configuration

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: productionapi
  namespace: production
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: productionapi
  minReplicas: 5
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
      - type: Percent
        value: 50
        periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
      - type: Pods
        value: 1
        periodSeconds: 60
```

---

## Common Issues

### Issue: Pods stuck in Pending state

**Cause:** Insufficient cluster resources

**Solution:**
```bash
# Check node capacity
kubectl describe nodes | grep -A 5 "Allocated resources"

# Check for resource constraints
kubectl get events -n production | grep FailedScheduling

# Add more nodes (if using managed node groups)
aws eks update-nodegroup-config \
  --cluster-name production \
  --nodegroup-name main-nodes \
  --scaling-config minSize=3,maxSize=10,desiredSize=6
```

---

### Issue: New pods crash on startup

**Cause:** Resource limits too low or dependencies unavailable

**Solution:**
```bash
# Check pod logs
kubectl logs -n production <pod-name>

# Check resource limits
kubectl describe pod -n production <pod-name> | grep -A 5 Limits

# Increase resource limits temporarily
kubectl set resources deployment/productionapi -n production \
  --limits=cpu=2,memory=4Gi \
  --requests=cpu=1,memory=2Gi
```

---

### Issue: Database connection pool exhausted

**Cause:** Not enough connections for scaled application

**Solution:**
```bash
# Calculate required connections: (pods * connections_per_pod) + buffer
# Example: (15 pods * 10 conn/pod) + 50 buffer = 200

# Increase max_connections
psql -h db-prod-primary.internal -c \
  "ALTER SYSTEM SET max_connections = 200;"
psql -h db-prod-primary.internal -c "SELECT pg_reload_conf();"

# Also increase connection pool in application
kubectl set env deployment/productionapi -n production \
  DB_POOL_SIZE=10 \
  DB_POOL_MAX=15
```

---

## Emergency Contacts

**Scaling Issues:**
- DevOps Lead: Mike Rodriguez - @mike.rodriguez / +1-555-0156
- Backend Lead: Sarah Chen - @sarah.chen / +1-555-0145

**Database Scaling:**
- DBA Lead: Jessica Wang - @jessica.wang / +1-555-0198

**On-Call:** PagerDuty rotation

---

## Related Runbooks
- [Incident Response](./incident-response.md)
- [Database Failover](./database-failover.md)
- [Cache Clearing](./cache-clearing.md)
- [Performance Degradation](./performance-degradation.md)

---

**Last Updated:** 2025-02-11  
**Owner:** DevOps Team  
**Review Schedule:** Monthly, and before known high-traffic events