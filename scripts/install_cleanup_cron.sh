#!/bin/bash

# install_cleanup_cron.sh
# Installation script for setting up the enrollment cleanup cron job on PostgreSQL VM

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="/opt/enrollment-cleanup"
LOG_DIR="/var/log/enrollment_cleanup"
CRON_TIME="0 2 * * *"  # Daily at 2 AM

# Database configuration (you can modify these)
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-karmayogi_db}"
DB_USER="${DB_USER:-stuser}"
DB_PASSWORD="${DB_PASSWORD:-stUser12}"

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run as root (use sudo)"
        exit 1
    fi
}

# Install PostgreSQL client if not present
install_psql() {
    if ! command -v psql &> /dev/null; then
        print_warning "PostgreSQL client not found. Installing..."
        
        # Detect OS and install accordingly
        if [ -f /etc/redhat-release ]; then
            # RHEL/CentOS/Fedora
            yum install -y postgresql || dnf install -y postgresql
        elif [ -f /etc/debian_version ]; then
            # Debian/Ubuntu
            apt-get update && apt-get install -y postgresql-client
        else
            print_error "Unsupported OS. Please install PostgreSQL client manually."
            exit 1
        fi
    else
        print_status "PostgreSQL client is already installed"
    fi
}

# Create directories
create_directories() {
    print_status "Creating directories..."
    
    mkdir -p "$SCRIPT_DIR"
    mkdir -p "$LOG_DIR"
    
    # Set proper permissions
    chmod 755 "$SCRIPT_DIR"
    chmod 755 "$LOG_DIR"
}

# Copy scripts
copy_scripts() {
    print_status "Copying scripts to $SCRIPT_DIR..."
    
    # Get the directory where this install script is located
    CURRENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
    
    # Copy SQL and shell scripts
    cp "$CURRENT_DIR/cleanup_old_enrollments.sql" "$SCRIPT_DIR/"
    cp "$CURRENT_DIR/cleanup_enrollments.sh" "$SCRIPT_DIR/"
    
    # Make shell script executable
    chmod +x "$SCRIPT_DIR/cleanup_enrollments.sh"
    
    print_status "Scripts copied successfully"
}

# Test database connection
test_connection() {
    print_status "Testing database connection..."
    
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT COUNT(*) FROM user_enrollments;" &> /dev/null
    
    if [ $? -eq 0 ]; then
        print_status "Database connection successful"
    else
        print_error "Database connection failed. Please check your database configuration."
        print_error "Host: $DB_HOST, Port: $DB_PORT, Database: $DB_NAME, User: $DB_USER"
        exit 1
    fi
}

# Setup cron job
setup_cron() {
    print_status "Setting up cron job..."
    
    # Create environment file for cron
    ENV_FILE="$SCRIPT_DIR/db_env"
    cat > "$ENV_FILE" << EOF
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
EOF
    
    # Secure the environment file
    chmod 600 "$ENV_FILE"
    
    # Update the cleanup script to source the environment file
    sed -i "1a\\# Source environment variables\n[ -f \"$ENV_FILE\" ] && source \"$ENV_FILE\"" "$SCRIPT_DIR/cleanup_enrollments.sh"
    
    # Add cron job
    CRON_ENTRY="$CRON_TIME $SCRIPT_DIR/cleanup_enrollments.sh"
    
    # Check if cron job already exists
    if crontab -l 2>/dev/null | grep -q "cleanup_enrollments.sh"; then
        print_warning "Cron job already exists. Updating..."
        # Remove existing entry and add new one
        (crontab -l 2>/dev/null | grep -v "cleanup_enrollments.sh"; echo "$CRON_ENTRY") | crontab -
    else
        # Add new cron job
        (crontab -l 2>/dev/null; echo "$CRON_ENTRY") | crontab -
    fi
    
    print_status "Cron job added: $CRON_ENTRY"
}

# Run initial test
run_test() {
    print_status "Running initial test cleanup (dry run mode)..."
    
    # Create a test version of the SQL that just counts records
    TEST_SQL="$SCRIPT_DIR/test_cleanup.sql"
    cat > "$TEST_SQL" << 'EOF'
-- Test cleanup script - just count records to be deleted
DO $$
DECLARE
    record_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO record_count 
    FROM user_enrollments 
    WHERE inserted_on < NOW() - INTERVAL '2 days';
    
    RAISE NOTICE 'Would delete % records older than 2 days', record_count;
END $$;
EOF
    
    # Run test
    PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -f "$TEST_SQL"
    
    # Clean up test file
    rm "$TEST_SQL"
}

# Main installation function
main() {
    echo "=== Enrollment Cleanup Cron Job Installer ==="
    echo ""
    
    print_status "Database Configuration:"
    echo "  Host: $DB_HOST"
    echo "  Port: $DB_PORT"
    echo "  Database: $DB_NAME"
    echo "  User: $DB_USER"
    echo "  Schedule: $CRON_TIME (Daily at 2 AM)"
    echo ""
    
    read -p "Continue with installation? (y/N): " -n 1 -r
    echo ""
    
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Installation cancelled"
        exit 0
    fi
    
    # Run installation steps
    check_root
    install_psql
    create_directories
    copy_scripts
    test_connection
    setup_cron
    run_test
    
    echo ""
    print_status "Installation completed successfully!"
    echo ""
    echo "Next steps:"
    echo "1. Check cron job: crontab -l"
    echo "2. Monitor logs: tail -f $LOG_DIR/cleanup_$(date +%Y%m%d).log"
    echo "3. Manual run: $SCRIPT_DIR/cleanup_enrollments.sh"
    echo ""
    print_warning "The cleanup will run daily at 2:00 AM"
}

# Run main function
main "$@"