-- cleanup_old_enrollments.sql
-- SQL script to delete enrollment records older than 2 days
-- This script is designed to run directly on PostgreSQL VM via cron job

\set ON_ERROR_STOP on

-- Log the cleanup operation start
DO $$
BEGIN
    RAISE NOTICE 'Starting cleanup of enrollment records older than 2 days at %', NOW();
END $$;

-- Count records to be deleted (for logging)
DO $$
DECLARE
    record_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO record_count 
    FROM user_enrollments 
    WHERE inserted_on < NOW() - INTERVAL '2 days';
    
    RAISE NOTICE 'Found % records older than 2 days to delete', record_count;
END $$;

-- Delete old records and log the result
DO $$
DECLARE
    deleted_count INTEGER;
BEGIN
    WITH deleted_records AS (
        DELETE FROM user_enrollments 
        WHERE inserted_on < NOW() - INTERVAL '2 days'
        RETURNING id
    )
    SELECT COUNT(*) INTO deleted_count FROM deleted_records;
    
    RAISE NOTICE 'Successfully deleted % enrollment records older than 2 days', deleted_count;
    
    -- Insert cleanup log entry (optional - create table if needed)
    -- You can uncomment this if you want to track cleanup operations
    /*
    INSERT INTO cleanup_log (operation_type, records_affected, operation_time)
    VALUES ('enrollment_cleanup', deleted_count, NOW());
    */
END $$;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Cleanup operation completed at %', NOW();
END $$;