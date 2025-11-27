# Enrollment Records Cleanup - PostgreSQL VM Cron Job

This directory contains scripts to automatically clean up old enrollment records from the `user_enrollments` table on the PostgreSQL VM.

## Files

### 1. `cleanup_old_enrollments.sql`
- Pure SQL script that deletes records older than 2 days
- Uses PostgreSQL's `inserted_on` timestamp column
- Includes logging with `RAISE NOTICE` statements
- Can be executed directly with `psql`

### 2. `cleanup_enrollments.sh`
- Shell script wrapper for the SQL cleanup
- Handles database connection and logging
- Creates rotation for log files (keeps 30 days)
- Includes error handling and connection testing

### 3. `install_cleanup_cron.sh`
- Automated installation script for the cron job
- Sets up directories, permissions, and cron schedule
- Tests database connectivity before installation
- Configures environment variables securely

### 4. `crontab_example.txt`
- Example crontab entries with different schedules
- Shows how to set environment variables for cron

## Installation

### Option 1: Automated Installation (Recommended)
```bash
# Copy scripts to PostgreSQL VM
scp scripts/* user@postgres-vm:/tmp/

# SSH to PostgreSQL VM
ssh user@postgres-vm

# Run installer as root
sudo /tmp/install_cleanup_cron.sh
```

### Option 2: Manual Installation
```bash
# 1. Copy scripts to a permanent location
sudo mkdir -p /opt/enrollment-cleanup
sudo cp cleanup_old_enrollments.sql /opt/enrollment-cleanup/
sudo cp cleanup_enrollments.sh /opt/enrollment-cleanup/
sudo chmod +x /opt/enrollment-cleanup/cleanup_enrollments.sh

# 2. Create log directory
sudo mkdir -p /var/log/enrollment_cleanup

# 3. Set up environment variables (edit as needed)
sudo tee /opt/enrollment-cleanup/db_env << EOF
DB_HOST=localhost
DB_PORT=5432
DB_NAME=karmayogi_db
DB_USER=stuser
DB_PASSWORD=stUser12
EOF
sudo chmod 600 /opt/enrollment-cleanup/db_env

# 4. Add to crontab
sudo crontab -e
# Add this line:
0 2 * * * /opt/enrollment-cleanup/cleanup_enrollments.sh
```

## Configuration

### Database Connection
Edit the environment variables in the shell script or create a `.env` file:
- `DB_HOST`: PostgreSQL server hostname (default: localhost)
- `DB_PORT`: PostgreSQL port (default: 5432)
- `DB_NAME`: Database name (default: karmayogi_db)
- `DB_USER`: Database username (default: stuser)
- `DB_PASSWORD`: Database password (default: stUser12)

### Cleanup Retention
To change the retention period from 2 days to a different value:
1. Edit `cleanup_old_enrollments.sql`
2. Change `INTERVAL '2 days'` to your desired interval (e.g., `INTERVAL '7 days'`)

### Cron Schedule
Default schedule: Daily at 2:00 AM (`0 2 * * *`)

Other options:
- Every 12 hours: `0 */12 * * *`
- Weekly on Sunday: `0 3 * * 0`
- Every 6 hours: `0 */6 * * *`

## Testing

### Test Database Connection
```bash
/opt/enrollment-cleanup/cleanup_enrollments.sh
```

### Check What Would Be Deleted (Dry Run)
```bash
# Connect to PostgreSQL and run:
psql -h localhost -U stuser -d karmayogi_db -c "
SELECT COUNT(*) as records_to_delete 
FROM user_enrollments 
WHERE inserted_on < NOW() - INTERVAL '2 days';"
```

### Manual Cleanup Execution
```bash
sudo /opt/enrollment-cleanup/cleanup_enrollments.sh
```

## Monitoring

### View Logs
```bash
# Today's log
tail -f /var/log/enrollment_cleanup/cleanup_$(date +%Y%m%d).log

# All recent logs
ls -la /var/log/enrollment_cleanup/

# Search for errors
grep -i error /var/log/enrollment_cleanup/*.log
```

### Check Cron Job Status
```bash
# List current cron jobs
sudo crontab -l

# Check cron service status
systemctl status crond    # RHEL/CentOS
systemctl status cron     # Debian/Ubuntu

# View cron logs
journalctl -u crond       # RHEL/CentOS
journalctl -u cron        # Debian/Ubuntu
```

## Troubleshooting

### Common Issues

1. **Connection Failed**
   - Check database credentials in environment variables
   - Verify PostgreSQL is running: `systemctl status postgresql`
   - Test network connectivity: `telnet DB_HOST DB_PORT`

2. **Permission Denied**
   - Ensure scripts have execute permissions: `chmod +x cleanup_enrollments.sh`
   - Check log directory permissions: `ls -la /var/log/enrollment_cleanup/`

3. **Cron Job Not Running**
   - Check cron service: `systemctl status crond`
   - Verify crontab entry: `sudo crontab -l`
   - Check system logs: `journalctl -u crond`

4. **SQL Errors**
   - Verify table exists: `\dt user_enrollments` in psql
   - Check column names: `\d user_enrollments` in psql
   - Test SQL manually in psql

### Log File Locations
- Main logs: `/var/log/enrollment_cleanup/cleanup_YYYYMMDD.log`
- System cron logs: `/var/log/cron` or `journalctl -u crond`

## Security Considerations

1. **Database Credentials**: Stored in `/opt/enrollment-cleanup/db_env` with 600 permissions
2. **Log Files**: Automatically rotated (30-day retention)
3. **Script Permissions**: Only executable by root
4. **Network**: Ensure PostgreSQL only accepts connections from authorized hosts

## Performance Impact

- **Low Impact**: Uses timestamp index for efficient deletion
- **Timing**: Runs at 2 AM when database usage is typically low
- **Batch Size**: Deletes all qualifying records in one operation
- **Logging**: Minimal overhead with structured logging

## Maintenance

### Updating Scripts
1. Update files in `/opt/enrollment-cleanup/`
2. Test manually before next scheduled run
3. Monitor logs after updates

### Changing Schedule
```bash
sudo crontab -e
# Modify the time in the cron entry
```

### Backup Before Large Cleanups
```bash
# Create backup before major changes
pg_dump -h localhost -U stuser -d karmayogi_db -t user_enrollments > backup_enrollments_$(date +%Y%m%d).sql
```