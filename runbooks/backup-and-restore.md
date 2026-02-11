# Backup and Restore Runbook

## Overview
This runbook covers procedures for backing up and restoring critical production data, including databases, file storage, and configuration.

**Use this runbook when:**
- Performing routine backups
- Restoring from backup after data loss
- Testing backup integrity
- Migrating data between environments

---

## Prerequisites
- Database admin access
- AWS S3 access for backup storage
- kubectl access to production cluster
- PGP keys for encrypted backups

---

## Backup Overview

### What Gets Backed Up

| Component | Frequency | Retention | Location | Encrypted |
|-----------|-----------|-----------|----------|-----------|
| PostgreSQL DB | Every 6 hours | 30 days | S3 | Yes |
| Redis snapshots | Daily | 7 days | S3 | No |
| File uploads | Continuous | 90 days | S3 | Yes |
| Configuration | On change | Indefinite | Git + S3 | No |
| Kubernetes state | Daily | 14 days | S3 | No |

---

### Backup Schedule

```
Daily (02:00 UTC):
- Full PostgreSQL backup
- Redis snapshot
- Kubernetes etcd snapshot
- Configuration snapshot

Every 6 hours (02:00, 08:00, 14:00, 20:00 UTC):
- Incremental PostgreSQL backup

Continuous:
- File uploads (via S3 versioning)
- Transaction logs (WAL)
```

---

## Procedure 1: Manual Database Backup

### PostgreSQL Full Backup

```bash
# SSH to database server
ssh db-prod-primary-01.internal

# Create backup directory
sudo mkdir -p /backup/manual/$(date +%Y%m%d)

# Run pg_dump (full database)
sudo -u postgres pg_dump -Fc production > \
  /backup/manual/$(date +%Y%m%d)/production_$(date +%Y%m%d_%H%M%S).dump

# Verify backup created
ls -lh /backup/manual/$(date +%Y%m%d)/

# Encrypt backup
gpg --encrypt --recipient backup@company.com \
  /backup/manual/$(date +%Y%m%d)/production_$(date +%Y%m%d_%H%M%S).dump

# Upload to S3
aws s3 cp /backup/manual/$(date +%Y%m%d)/production_$(date +%Y%m%d_%H%M%S).dump.gpg \
  s3://company-backups/database/manual/$(date +%Y%m%d)/

# Verify upload
aws s3 ls s3://company-backups/database/manual/$(date +%Y%m%d)/
```

---

### PostgreSQL Backup with pg_basebackup

**For large databases (faster than pg_dump):**

```bash
# Create backup using base backup
sudo -u postgres pg_basebackup \
  -h db-prod-primary-01.internal \
  -D /backup/basebackup/$(date +%Y%m%d) \
  -Ft -z -P

# This creates a tar.gz of the entire data directory
# Includes WAL files for point-in-time recovery

# Upload to S3
aws s3 sync /backup/basebackup/$(date +%Y%m%d) \
  s3://company-backups/database/basebackup/$(date +%Y%m%d)/

# Document backup metadata
cat > /backup/basebackup/$(date +%Y%m%d)/metadata.txt <<EOF
Backup Time: $(date)
Database Version: $(psql -V)
Database Size: $(du -sh /var/lib/postgresql/14/main)
Backup Method: pg_basebackup
Backup Location: s3://company-backups/database/basebackup/$(date +%Y%m%d)/
EOF
```

---

### Specific Table Backup

```bash
# Backup specific table(s)
sudo -u postgres pg_dump -Fc production \
  -t users -t orders -t payments > \
  /backup/tables_$(date +%Y%m%d_%H%M%S).dump

# Backup specific schema
sudo -u postgres pg_dump -Fc production \
  -n public > \
  /backup/schema_public_$(date +%Y%m%d_%H%M%S).dump
```

---

## Procedure 2: Redis Backup

### Manual Redis Snapshot

```bash
# Connect to Redis
kubectl exec -it redis-master-0 -n production -- redis-cli

# Trigger immediate save
BGSAVE

# Check save status
LASTSAVE

# Exit Redis
exit

# Copy RDB file from pod
kubectl cp production/redis-master-0:/data/dump.rdb \
  ./redis_backup_$(date +%Y%m%d_%H%M%S).rdb

# Upload to S3
aws s3 cp redis_backup_$(date +%Y%m%d_%H%M%S).rdb \
  s3://company-backups/redis/manual/$(date +%Y%m%d)/
```

---

## Procedure 3: File Storage Backup

**File uploads are stored in S3 with versioning enabled**

### Verify S3 Versioning

```bash
# Check versioning status
aws s3api get-bucket-versioning --bucket company-uploads

# Should return: "Status": "Enabled"

# List versions of a file
aws s3api list-object-versions \
  --bucket company-uploads \
  --prefix uploads/2025/02/document.pdf
```

---

### Manual File Backup

```bash
# Sync entire bucket to backup location
aws s3 sync s3://company-uploads/ \
  s3://company-backups/files/$(date +%Y%m%d)/ \
  --storage-class GLACIER_IR

# Or create a snapshot of current state
aws s3api create-bucket \
  --bucket company-uploads-snapshot-$(date +%Y%m%d)

aws s3 sync s3://company-uploads/ \
  s3://company-uploads-snapshot-$(date +%Y%m%d)/
```

---

## Procedure 4: Configuration Backup

### Kubernetes Configuration

```bash
# Backup all ConfigMaps
kubectl get configmap -n production -o yaml > \
  backup/k8s/configmaps_$(date +%Y%m%d).yaml

# Backup all Secrets (encrypted)
kubectl get secret -n production -o yaml | \
  gpg --encrypt --recipient backup@company.com > \
  backup/k8s/secrets_$(date +%Y%m%d).yaml.gpg

# Backup all Deployments
kubectl get deployment -n production -o yaml > \
  backup/k8s/deployments_$(date +%Y%m%d).yaml

# Backup entire namespace
kubectl get all -n production -o yaml > \
  backup/k8s/namespace_production_$(date +%Y%m%d).yaml

# Upload to S3
aws s3 sync backup/k8s/ \
  s3://company-backups/kubernetes/$(date +%Y%m%d)/
```

---

### Application Configuration

```bash
# Configuration files are version controlled in Git
# Create tagged backup

cd /repos/config
git tag backup-$(date +%Y%m%d-%H%M%S)
git push origin --tags

# Also backup to S3
tar -czf config_$(date +%Y%m%d).tar.gz .
aws s3 cp config_$(date +%Y%m%d).tar.gz \
  s3://company-backups/config/
```

---

## Procedure 5: Database Restore

### ⚠️ CRITICAL - DESTRUCTIVE OPERATION

**Before restoring, always:**
1. Create a backup of current state
2. Notify team in #incidents channel
3. Put application in maintenance mode
4. Document reason for restore in incident ticket

---

### Restore from pg_dump

```bash
# 1. Backup current database first!
sudo -u postgres pg_dump -Fc production > \
  /backup/pre-restore/production_$(date +%Y%m%d_%H%M%S).dump

# 2. Put application in maintenance mode
kubectl scale deployment/productionapi --replicas=0 -n production

# 3. Drop and recreate database (or just drop specific tables)
sudo -u postgres psql -c "DROP DATABASE production;"
sudo -u postgres psql -c "CREATE DATABASE production;"

# 4. Restore from backup
sudo -u postgres pg_restore -d production \
  /backup/production_20250210_140000.dump

# Or restore from S3:
aws s3 cp s3://company-backups/database/manual/20250210/production_20250210_140000.dump.gpg - | \
  gpg --decrypt | \
  sudo -u postgres pg_restore -d production

# 5. Verify data
sudo -u postgres psql production -c "SELECT count(*) FROM users;"
sudo -u postgres psql production -c "SELECT max(created_at) FROM orders;"

# 6. Restart application
kubectl scale deployment/productionapi --replicas=5 -n production

# 7. Verify application health
curl https://api.company.com/health
```

---

### Restore Specific Tables

```bash
# Restore only specific tables (doesn't drop other tables)
sudo -u postgres pg_restore -d production \
  -t users -t orders \
  /backup/tables_20250210_140000.dump

# Or restore with --clean (drops table first)
sudo -u postgres pg_restore -d production --clean \
  -t users \
  /backup/tables_20250210_140000.dump
```

---

### Point-in-Time Recovery (PITR)

**Restore database to specific timestamp:**

```bash
# 1. Restore base backup
sudo -u postgres pg_basebackup \
  -D /var/lib/postgresql/14/pitr \
  -Fp

# 2. Create recovery.conf
cat > /var/lib/postgresql/14/pitr/recovery.conf <<EOF
restore_command = 'cp /backup/wal/%f %p'
recovery_target_time = '2025-02-10 14:30:00'
recovery_target_action = 'promote'
EOF

# 3. Stop current database
sudo systemctl stop postgresql

# 4. Replace data directory (backup current first!)
sudo mv /var/lib/postgresql/14/main /var/lib/postgresql/14/main.bak
sudo mv /var/lib/postgresql/14/pitr /var/lib/postgresql/14/main

# 5. Start PostgreSQL
sudo systemctl start postgresql

# 6. Monitor recovery
sudo tail -f /var/log/postgresql/postgresql-14-main.log

# Database will recover to specified time and then promote
```

---

## Procedure 6: Redis Restore

### Restore from RDB Backup

```bash
# 1. Scale down Redis (or put in maintenance mode)
kubectl scale statefulset redis --replicas=0 -n production

# 2. Download backup from S3
aws s3 cp s3://company-backups/redis/manual/20250210/redis_backup_20250210_140000.rdb \
  ./restore/dump.rdb

# 3. Copy to Redis pod (after scaling back up to 1)
kubectl scale statefulset redis --replicas=1 -n production
kubectl wait --for=condition=ready pod/redis-0 -n production

# Stop Redis temporarily
kubectl exec -it redis-0 -n production -- redis-cli SHUTDOWN NOSAVE

# Copy backup file
kubectl cp restore/dump.rdb production/redis-0:/data/dump.rdb

# Restart Redis pod
kubectl delete pod redis-0 -n production

# 4. Verify data
kubectl exec -it redis-0 -n production -- redis-cli
DBSIZE
GET test-key
exit

# 5. Scale back to normal
kubectl scale statefulset redis --replicas=3 -n production
```

---

## Procedure 7: File Storage Restore

### Restore Specific Files

```bash
# Restore a specific file from S3 versioning
aws s3api get-object \
  --bucket company-uploads \
  --key uploads/2025/02/document.pdf \
  --version-id "3/L4kqtJlcpXroDTDmJ+rmSpXd3dIbrHY+MTRCxf3vjVBH40Nr8X8gdRQBpUMLUo" \
  restored_document.pdf

# Copy back to original location
aws s3 cp restored_document.pdf \
  s3://company-uploads/uploads/2025/02/document.pdf
```

---

### Restore Entire Bucket

```bash
# Restore from backup bucket
aws s3 sync s3://company-backups/files/20250210/ \
  s3://company-uploads/ \
  --delete

# Or restore from snapshot
aws s3 sync s3://company-uploads-snapshot-20250210/ \
  s3://company-uploads/ \
  --delete
```

---

## Verification Procedures

### Database Backup Verification

```bash
# Test restore to temporary database
sudo -u postgres createdb test_restore

sudo -u postgres pg_restore -d test_restore \
  /backup/production_20250210_140000.dump

# Run validation queries
sudo -u postgres psql test_restore -c "
  SELECT 'users' as table, count(*) from users
  UNION ALL
  SELECT 'orders', count(*) from orders
  UNION ALL
  SELECT 'products', count(*) from products;
"

# Check for data integrity
sudo -u postgres psql test_restore -c "
  SELECT count(*) as orphaned_orders 
  FROM orders o 
  WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = o.user_id);
"

# Should return 0 orphaned orders

# Clean up
sudo -u postgres dropdb test_restore
```

---

### Automated Backup Testing

**Run monthly backup restore tests:**

```bash
# Automated restore test script
#!/bin/bash

BACKUP_FILE=$(aws s3 ls s3://company-backups/database/automated/ | tail -1 | awk '{print $4}')

echo "Testing backup: $BACKUP_FILE"

# Download
aws s3 cp s3://company-backups/database/automated/$BACKUP_FILE /tmp/test_backup.dump

# Create test DB
sudo -u postgres createdb backup_test_$(date +%Y%m%d)

# Restore
sudo -u postgres pg_restore -d backup_test_$(date +%Y%m%d) /tmp/test_backup.dump

# Validate
RESULT=$(sudo -u postgres psql backup_test_$(date +%Y%m%d) -t -c "SELECT count(*) FROM users;")

if [ $RESULT -gt 0 ]; then
  echo "✓ Backup restore test PASSED - $RESULT users found"
  exit 0
else
  echo "✗ Backup restore test FAILED - No users found"
  exit 1
fi

# Clean up
sudo -u postgres dropdb backup_test_$(date +%Y%m%d)
rm /tmp/test_backup.dump
```

---

## Backup Monitoring

### Check Backup Status

```bash
# List recent backups
aws s3 ls s3://company-backups/database/automated/ \
  --recursive | tail -10

# Check backup sizes
aws s3 ls s3://company-backups/database/automated/ \
  --recursive --human-readable --summarize

# Verify latest backup timestamp
LATEST=$(aws s3 ls s3://company-backups/database/automated/ | tail -1 | awk '{print $1, $2}')
echo "Latest backup: $LATEST"

# Should be within last 6 hours
```

---

### Backup Alerts

**Prometheus alerts configured:**

```yaml
- alert: DatabaseBackupMissing
  expr: time() - backup_last_success_timestamp > 21600  # 6 hours
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "Database backup is overdue"

- alert: BackupTestFailed
  expr: backup_test_success == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Backup restore test failed"
```

---

## Disaster Recovery

### Complete System Restore (Worst Case)

**If entire system needs rebuilding:**

**1. Provision new infrastructure (1-2 hours):**
```bash
# Provision via Terraform
cd terraform/production
terraform apply

# Or via CloudFormation
aws cloudformation create-stack \
  --stack-name production-rebuild \
  --template-body file://infrastructure.yaml
```

**2. Restore database (30-60 minutes):**
```bash
# Get latest backup
LATEST_BACKUP=$(aws s3 ls s3://company-backups/database/automated/ | tail -1 | awk '{print $4}')

# Restore to new database
aws s3 cp s3://company-backups/database/automated/$LATEST_BACKUP - | \
  gpg --decrypt | \
  sudo -u postgres pg_restore -d production
```

**3. Restore application configuration (15 minutes):**
```bash
# Restore Kubernetes state
aws s3 cp s3://company-backups/kubernetes/latest/ . --recursive
kubectl apply -f deployments/
kubectl apply -f configmaps/
kubectl apply -f secrets/
```

**4. Restore file storage (varies by size):**
```bash
# Files are already in S3, just need to verify access
aws s3 ls s3://company-uploads/ --recursive | head
```

**5. Verify and test (30 minutes):**
```bash
# Run health checks
./scripts/health_check.sh

# Test critical user flows
./scripts/integration_tests.sh
```

**Total estimated time:** 3-5 hours

---

## Backup Retention Policy

### Automated Cleanup

```bash
# Delete backups older than 30 days
aws s3 ls s3://company-backups/database/automated/ | \
  awk '$1 < "'$(date -d '30 days ago' +%Y-%m-%d)'" {print $4}' | \
  xargs -I {} aws s3 rm s3://company-backups/database/automated/{}

# Or use S3 lifecycle policy (recommended)
aws s3api put-bucket-lifecycle-configuration \
  --bucket company-backups \
  --lifecycle-configuration file://lifecycle.json
```

**lifecycle.json:**
```json
{
  "Rules": [
    {
      "Id": "DeleteOldBackups",
      "Status": "Enabled",
      "Prefix": "database/automated/",
      "Expiration": {
        "Days": 30
      }
    },
    {
      "Id": "ArchiveToGlacier",
      "Status": "Enabled",
      "Prefix": "database/automated/",
      "Transitions": [
        {
          "Days": 7,
          "StorageClass": "GLACIER_IR"
        }
      ]
    }
  ]
}
```

---

## Common Issues

### Issue: Backup file too large for disk space

**Solution:**
```bash
# Stream directly to S3 without local storage
sudo -u postgres pg_dump -Fc production | \
  gzip | \
  aws s3 cp - s3://company-backups/database/streaming/production_$(date +%Y%m%d_%H%M%S).dump.gz
```

---

### Issue: Restore fails with "ERROR: role does not exist"

**Solution:**
```bash
# Create missing roles first
sudo -u postgres psql -c "CREATE ROLE app_user WITH LOGIN PASSWORD 'password';"
sudo -u postgres psql -c "CREATE ROLE readonly;"

# Then restore
sudo -u postgres pg_restore -d production backup.dump
```

---

### Issue: GPG decryption fails

**Solution:**
```bash
# Import correct GPG key
gpg --import /secure/backup-private-key.asc

# Verify key
gpg --list-keys backup@company.com

# Test decryption
gpg --decrypt backup.dump.gpg > test.dump
```

---

## Emergency Contacts

**Backup/Restore Issues:**
- DBA Lead: Jessica Wang - @jessica.wang / +1-555-0198
- DevOps Lead: Mike Rodriguez - @mike.rodriguez / +1-555-0156

**AWS Issues:**
- Infrastructure Lead: Tom Martinez - @tom.martinez / +1-555-0167

**Security (encrypted backups):**
- Security Lead: Alex Kim - @alex.kim / +1-555-0178

---

## Related Runbooks
- [Database Failover](./database-failover.md)
- [Incident Response](./incident-response.md)
- [Disaster Recovery Plan](./disaster-recovery.md)

---

**Last Updated:** 2025-02-11  
**Owner:** Database Team / DevOps Team  
**Review Schedule:** Quarterly, and after any failed backup