# SSL Certificate Renewal Runbook

## Overview
This runbook covers the procedures for renewing SSL/TLS certificates before they expire.

**Use this runbook when:**
- Certificate expiration is approaching (<30 days)
- Certificate has expired (emergency)
- Adding new domains/subdomains
- Updating to new certificate authority

---

## Prerequisites
- AWS Console access (Certificate Manager)
- kubectl access to production cluster
- DNS management access (Route53)
- Slack notification bot token

---

## Certificate Inventory

| Domain | Type | Provider | Expiration | Auto-Renew |
|--------|------|----------|------------|------------|
| api.company.com | Wildcard | AWS ACM | 2025-03-15 | Yes |
| *.company.com | Wildcard | AWS ACM | 2025-04-01 | Yes |
| company.com | Single | Let's Encrypt | 2025-02-28 | Yes |
| admin.company.com | Single | AWS ACM | 2025-03-20 | Yes |

---

## Monitoring and Alerts

### Check Certificate Expiration

```bash
# Check via OpenSSL
echo | openssl s_client -servername api.company.com \
  -connect api.company.com:443 2>/dev/null | \
  openssl x509 -noout -dates

# Check all certificates
for domain in api.company.com company.com admin.company.com; do
  echo "=== $domain ==="
  echo | openssl s_client -servername $domain \
    -connect $domain:443 2>/dev/null | \
    openssl x509 -noout -enddate
done

# Check AWS ACM certificates
aws acm list-certificates --certificate-statuses ISSUED
```

---

### Automated Monitoring

**Certificate expiration check runs daily:**
```bash
# View monitoring script
cat /scripts/cert-monitor.sh

# Manually run check
/scripts/cert-monitor.sh

# Check when last alert was sent
grep "Certificate expiring" /var/log/cert-monitor.log | tail -5
```

**Alerts sent:**
- 30 days before expiration: Warning to #infrastructure
- 14 days before expiration: Warning to #infrastructure and @devops-team
- 7 days before expiration: Critical to #incidents and page on-call
- 3 days before expiration: Critical to #incidents and escalate to leadership

---

## Procedure 1: AWS Certificate Manager (ACM) Renewal

**Good news:** ACM certificates auto-renew if DNS validation is set up correctly.

### Verify Auto-Renewal Setup

```bash
# Check certificate validation status
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:123456789012:certificate/abc-123-def

# Look for:
# - Status: ISSUED
# - Type: AMAZON_ISSUED  
# - RenewalEligibility: ELIGIBLE
# - ValidationMethod: DNS
```

**If validation records are missing:**

```bash
# Get DNS validation records
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:123456789012:certificate/abc-123-def \
  --query 'Certificate.DomainValidationOptions[*].ResourceRecord'

# Add to Route53
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch file://dns-validation.json
```

**dns-validation.json:**
```json
{
  "Changes": [{
    "Action": "CREATE",
    "ResourceRecordSet": {
      "Name": "_validation.api.company.com",
      "Type": "CNAME",
      "TTL": 300,
      "ResourceRecords": [{"Value": "validation.acm.amazonaws.com"}]
    }
  }]
}
```

---

### Manual ACM Certificate Renewal

**If auto-renewal fails:**

```bash
# Request new certificate
aws acm request-certificate \
  --domain-name api.company.com \
  --subject-alternative-names "*.api.company.com" \
  --validation-method DNS \
  --idempotency-token api-company-2025-02

# Note the CertificateArn from output

# Get validation records
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:123456789012:certificate/new-cert-123

# Add validation records to DNS (as above)

# Wait for validation (usually 5-30 minutes)
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:123456789012:certificate/new-cert-123 \
  --query 'Certificate.Status'

# Once status is "ISSUED", update load balancer
aws elbv2 modify-listener \
  --listener-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/api-lb/abc123/def456 \
  --certificates CertificateArn=arn:aws:acm:us-east-1:123456789012:certificate/new-cert-123

# Verify
curl -v https://api.company.com 2>&1 | grep "expire date"
```

---

## Procedure 2: Let's Encrypt Certificate Renewal

**For certificates managed by cert-manager in Kubernetes:**

### Check cert-manager Status

```bash
# Check cert-manager pods
kubectl get pods -n cert-manager

# Check certificate status
kubectl get certificate -n production

# Check certificate details
kubectl describe certificate company-com-tls -n production
```

**Expected output:**
```
Status:
  Conditions:
    Type:    Ready
    Status:  True
  Not After: 2025-05-15T10:30:00Z
```

---

### Trigger Manual Renewal

```bash
# Delete certificate secret to force renewal
kubectl delete secret company-com-tls -n production

# cert-manager will automatically recreate it

# Monitor renewal process
kubectl logs -n cert-manager -l app=cert-manager -f

# Verify new certificate
kubectl get certificate company-com-tls -n production
```

---

### Troubleshoot Failed Renewal

**Common issue: HTTP-01 challenge failing**

```bash
# Check challenge status
kubectl get challenges -n production

# Check ingress for ACME challenge
kubectl get ingress -n production

# Manual test of challenge endpoint
curl http://company.com/.well-known/acme-challenge/test

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager | grep -i error
```

**Solution if HTTP-01 challenge blocked:**
```bash
# Switch to DNS-01 challenge (requires DNS provider credentials)
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: company-com-tls
  namespace: production
spec:
  secretName: company-com-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - company.com
    - www.company.com
  acme:
    config:
    - dns01:
        provider: route53
      domains:
      - company.com
      - www.company.com
EOF
```

---

## Procedure 3: CloudFront Certificate Update

**For CDN certificates:**

```bash
# List current CloudFront distributions
aws cloudfront list-distributions

# Update distribution with new certificate
aws cloudfront update-distribution \
  --id E1234567890ABC \
  --viewer-certificate '{
    "ACMCertificateArn": "arn:aws:acm:us-east-1:123456789012:certificate/new-cert-123",
    "SSLSupportMethod": "sni-only",
    "MinimumProtocolVersion": "TLSv1.2_2021"
  }' \
  --if-match <ETag>

# Wait for deployment (10-15 minutes)
aws cloudfront get-distribution --id E1234567890ABC \
  --query 'Distribution.Status'

# Verify certificate
curl -v https://cdn.company.com 2>&1 | grep "expire date"
```

---

## Procedure 4: Emergency Expired Certificate

**If certificate has already expired:**

⚠️ **CRITICAL - Service is likely down or showing security warnings**

### Immediate Actions (0-5 minutes)

**1. Assess impact:**
```bash
# Check if site is accessible
curl -k https://api.company.com/health  # -k ignores cert errors

# Check error logs
kubectl logs -n production -l app=productionapi --tail=100 | grep -i tls
```

**2. Post emergency notification:**
```
@here URGENT: SSL certificate for api.company.com has EXPIRED
Users seeing security warnings. Working on immediate renewal.
ETA: 15-30 minutes
```

**3. Quick renewal for ACM certificates:**
```bash
# If existing ACM cert expired due to validation failure:
# Re-validate IMMEDIATELY

# Get validation records
aws acm describe-certificate \
  --certificate-arn arn:aws:acm:us-east-1:123456789012:certificate/abc-123-def

# Add/update DNS validation records in Route53
# This should auto-renew the cert within 5-10 minutes

# OR request new certificate (faster)
aws acm request-certificate \
  --domain-name api.company.com \
  --subject-alternative-names "*.api.company.com" \
  --validation-method DNS

# Add validation records, wait for ISSUED status
# Update load balancer with new certificate ARN
```

**4. For Let's Encrypt (immediate fix):**
```bash
# Force immediate renewal
kubectl delete certificate company-com-tls -n production

# Scale down cert-manager to force refresh
kubectl scale deployment cert-manager --replicas=0 -n cert-manager
kubectl scale deployment cert-manager --replicas=1 -n cert-manager

# Monitor
kubectl logs -n cert-manager -l app=cert-manager -f
```

---

## Verification Checklist

After renewal, verify:

```bash
# 1. Certificate expiration date
echo | openssl s_client -servername api.company.com \
  -connect api.company.com:443 2>/dev/null | \
  openssl x509 -noout -dates

# 2. Certificate chain validity
echo | openssl s_client -servername api.company.com \
  -connect api.company.com:443 2>/dev/null | \
  openssl x509 -noout -text | grep -i "ca issuers"

# 3. Browser test
# Open https://api.company.com in browser
# Click lock icon → Certificate → Verify expiration date

# 4. SSL Labs test (comprehensive)
# Visit: https://www.ssllabs.com/ssltest/analyze.html?d=api.company.com
# Should get A or A+ rating

# 5. Check all environments
for env in production staging dev; do
  echo "=== $env ==="
  curl -v https://api.$env.company.com 2>&1 | grep "expire date"
done
```

**Success criteria:**
- ✓ Certificate valid for at least 60 days
- ✓ Certificate chain complete
- ✓ No browser security warnings
- ✓ SSL Labs rating A or higher
- ✓ All environments updated

---

## Post-Renewal Tasks

### Update Documentation

```bash
# Update certificate inventory in runbook
vim /docs/runbooks/ssl-certificate-renewal.md

# Update certificate tracker spreadsheet
# https://docs.company.com/infrastructure/certificates

# Update monitoring alerts if expiration date changed
```

---

### Notification

**Post in Slack #infrastructure:**
```
✅ Certificate Renewed: api.company.com
New expiration: 2025-06-15
Auto-renew: Enabled
SSL Labs Rating: A+
No action required until 2025-05-15
```

---

### Schedule Next Review

```bash
# Add calendar reminder 45 days before expiration
# Add monitoring alert 30 days before expiration
```

---

## Common Issues

### Issue: ACM certificate stuck in "Pending Validation"

**Cause:** DNS validation records not propagated

**Solution:**
```bash
# Check DNS propagation
dig _validation.api.company.com CNAME

# If not found, verify Route53 record created correctly
aws route53 list-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  | grep validation

# Wait up to 30 minutes for DNS propagation
# Or lower TTL temporarily:
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch file://lower-ttl.json
```

---

### Issue: cert-manager renewal failing with rate limit

**Cause:** Let's Encrypt rate limits (5 renewals per week per domain)

**Solution:**
```bash
# Check rate limit status
# Visit: https://crt.sh/?q=company.com

# Use staging environment to test
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    ...
EOF

# Once working, switch back to production issuer
```

---

### Issue: New certificate not being picked up by application

**Cause:** Application needs restart to reload certificates

**Solution:**
```bash
# Rolling restart
kubectl rollout restart deployment/productionapi -n production

# Or reload nginx/ingress
kubectl exec -n ingress-nginx ingress-nginx-controller-xxx -- nginx -s reload
```

---

## Preventive Measures

### Automated Renewal Best Practices

1. **Use DNS validation** (more reliable than HTTP-01)
2. **Enable ACM auto-renewal** for AWS-hosted services
3. **Use cert-manager** for Kubernetes workloads
4. **Set up monitoring** with 30-day advance warning
5. **Document all certificates** in central inventory
6. **Test renewal process** in staging quarterly

---

### Monitoring Setup

```bash
# Add Prometheus alert
cat >> /monitoring/prometheus/alerts.yml <<EOF
- alert: SSLCertificateExpiring
  expr: probe_ssl_earliest_cert_expiry - time() < 30 * 24 * 60 * 60
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "SSL certificate expiring in {{ \$value | humanizeDuration }}"
EOF
```

---

## Emergency Contacts

**Certificate Issues:**
- DevOps Lead: Mike Rodriguez - @mike.rodriguez / +1-555-0156
- Infrastructure Lead: Tom Martinez - @tom.martinez / +1-555-0167

**Security Team:**
- Security Lead: Alex Kim - @alex.kim / +1-555-0178

**Vendor Support:**
- AWS Support: Case via AWS Console
- Let's Encrypt: Community forums only

---

## Related Runbooks
- [DNS Management](./dns-management.md)
- [Incident Response](./incident-response.md)
- [Load Balancer Configuration](./load-balancer-config.md)

---

**Last Updated:** 2025-02-11  
**Owner:** Infrastructure Team  
**Review Schedule:** Quarterly