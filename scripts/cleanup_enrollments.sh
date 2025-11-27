#!/bin/bash

# cleanup_enrollments.sh
# Shell script to execute enrollment cleanup on PostgreSQL VM
# This script connects to the PostgreSQL database and runs the cleanup SQL

# Database connection parameters
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-karmayogi_db}"
DB_USER="${DB_USER:-stuser}"
DB_PASSWORD="${DB_PASSWORD:-stUser12}"

# Logging configuration
LOG_DIR="/var/log/enrollment_cleanup"
LOG_FILE="$LOG_DIR/cleanup_$(date +%Y%m%d).log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
SQL_FILE="$SCRIPT_DIR/cleanup_old_enrollments.sql"

# Create log directory if it doesn't exist
mkdir -p "$LOG_DIR"

# Function to log messages
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Function to check if PostgreSQL is running
check_postgres() {
    if ! command -v psql &> /dev/null; then
        log_message "ERROR: psql command not found. Please install PostgreSQL client."
        exit 1
    fi
    
    # Test connection
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1;" &> /dev/null
    if [ $? -ne 0 ]; then
        log_message "ERROR: Cannot connect to PostgreSQL database."
        log_message "Connection details: Host=$DB_HOST, Port=$DB_PORT, DB=$DB_NAME, User=$DB_USER"
        exit 1
    fi
}

# Function to run cleanup
run_cleanup() {
    log_message "Starting enrollment records cleanup..."
    
    # Check if SQL file exists
    if [ ! -f "$SQL_FILE" ]; then
        log_message "ERROR: SQL file not found: $SQL_FILE"
        exit 1
    fi
    
    # Execute the cleanup SQL
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$SQL_FILE" 2>&1 | tee -a "$LOG_FILE"
    
    local exit_code=${PIPESTATUS[0]}
    
    if [ $exit_code -eq 0 ]; then
        log_message "Cleanup completed successfully."
    else
        log_message "ERROR: Cleanup failed with exit code $exit_code"
        exit $exit_code
    fi
}

# Function to rotate old log files (keep last 30 days)
rotate_logs() {
    find "$LOG_DIR" -name "cleanup_*.log" -type f -mtime +30 -delete 2>/dev/null
}

# Main execution
main() {
    log_message "=== Enrollment Cleanup Script Started ==="
    log_message "PID: $$"
    log_message "Script: $0"
    log_message "SQL File: $SQL_FILE"
    
    # Check prerequisites
    check_postgres
    
    # Run the cleanup
    run_cleanup
    
    # Rotate old logs
    rotate_logs
    
    log_message "=== Enrollment Cleanup Script Completed ==="
}

# Execute main function
main "$@"