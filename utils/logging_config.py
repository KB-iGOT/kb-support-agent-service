# utils/logging_config.py
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""

    # Color codes
    COLORS = {
        'DEBUG': '\033[36m',  # Cyan
        'INFO': '\033[32m',  # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',  # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m'  # Reset
    }

    def format(self, record):
        # Add color to levelname
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"

        return super().format(record)


def setup_logging(
        app_name: str = "karmayogi_agent",
        log_level: str = "INFO",
        log_dir: str = "logs",
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        backup_count: int = 30,  # Keep 30 days of logs
        enable_console: bool = True,
        enable_file: bool = True,
        enable_daily_rotation: bool = True
):
    """
    Setup comprehensive logging with daily rolling appender

    Args:
        app_name: Name of the application (used in log filenames)
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory to store log files
        max_bytes: Maximum size per log file before rotation
        backup_count: Number of backup files to keep
        enable_console: Whether to enable console logging
        enable_file: Whether to enable file logging
        enable_daily_rotation: Whether to use daily rotation vs size-based
    """

    # Create logs directory
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)

    # Clear existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Set root logging level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Create formatters
    detailed_formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    )

    colored_formatter = ColoredFormatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )

    handlers = []

    # Console Handler
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(colored_formatter)
        handlers.append(console_handler)

    # File Handlers
    if enable_file:
        if enable_daily_rotation:
            # Daily rotating file handler
            daily_file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=log_path / f"{app_name}.log",
                when='midnight',
                interval=1,
                backupCount=backup_count,
                encoding='utf-8'
            )
            daily_file_handler.setLevel(numeric_level)
            daily_file_handler.setFormatter(detailed_formatter)
            daily_file_handler.suffix = "%Y-%m-%d"  # Format: app.log.2024-01-15
            handlers.append(daily_file_handler)
        else:
            # Size-based rotating file handler
            rotating_file_handler = logging.handlers.RotatingFileHandler(
                filename=log_path / f"{app_name}.log",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            rotating_file_handler.setLevel(numeric_level)
            rotating_file_handler.setFormatter(detailed_formatter)
            handlers.append(rotating_file_handler)

        # Separate error log file (only ERROR and CRITICAL)
        error_file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_path / f"{app_name}-error.log",
            when='midnight',
            interval=1,
            backupCount=backup_count,
            encoding='utf-8'
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(detailed_formatter)
        error_file_handler.suffix = "%Y-%m-%d"
        handlers.append(error_file_handler)

        # Separate access log for HTTP requests
        access_file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_path / f"{app_name}-access.log",
            when='midnight',
            interval=1,
            backupCount=backup_count,
            encoding='utf-8'
        )
        access_file_handler.setLevel(logging.INFO)
        access_file_handler.setFormatter(simple_formatter)
        access_file_handler.suffix = "%Y-%m-%d"

        # Create separate logger for access logs
        access_logger = logging.getLogger("access")
        access_logger.setLevel(logging.INFO)
        access_logger.addHandler(access_file_handler)
        access_logger.propagate = False  # Don't propagate to root logger

    # Add all handlers to root logger
    for handler in handlers:
        root_logger.addHandler(handler)

    # Configure specific loggers
    configure_specific_loggers(numeric_level)

    # Log startup message
    logger = logging.getLogger(__name__)
    logger.info(f"Logging configured - Level: {log_level}, Daily Rotation: {enable_daily_rotation}")
    logger.info(f"Log directory: {log_path.absolute()}")
    logger.info(f"Handlers configured: {len(handlers)}")

    return log_path


def configure_specific_loggers(level):
    """Configure specific loggers with appropriate levels"""

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    # Set specific levels for application components
    logging.getLogger("agents").setLevel(level)
    logging.getLogger("utils").setLevel(level)
    logging.getLogger("fastapi").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_access_logger():
    """Get the access logger for HTTP request logging"""
    return logging.getLogger("access")


def log_request(method: str, path: str, status_code: int, duration_ms: float, user_id: str = None):
    """Log HTTP request in structured format"""
    access_logger = get_access_logger()
    user_info = f" | User: {user_id}" if user_id else ""
    access_logger.info(f"{method} {path} | {status_code} | {duration_ms:.2f}ms{user_info}")


def log_agent_activity(agent_name: str, action: str, user_id: str, details: str = None):
    """Log agent activity in structured format"""
    logger = logging.getLogger("agents")
    details_info = f" | {details}" if details else ""
    logger.info(f"Agent: {agent_name} | Action: {action} | User: {user_id}{details_info}")


def log_performance_metric(metric_name: str, value: float, unit: str = "ms", context: dict = None):
    """Log performance metrics"""
    logger = logging.getLogger("performance")
    context_info = f" | Context: {context}" if context else ""
    logger.info(f"Metric: {metric_name} | Value: {value:.2f}{unit}{context_info}")


# Context manager for logging performance
class LogExecutionTime:
    """Context manager to log execution time of code blocks"""

    def __init__(self, operation_name: str, logger_name: str = None):
        self.operation_name = operation_name
        self.logger = logging.getLogger(logger_name or __name__)
        self.start_time = None

    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.debug(f"Starting: {self.operation_name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds() * 1000

        if exc_type:
            self.logger.error(f"Failed: {self.operation_name} | Duration: {duration:.2f}ms | Error: {exc_val}")
        else:
            self.logger.info(f"Completed: {self.operation_name} | Duration: {duration:.2f}ms")


# Example usage functions
def setup_development_logging(log_dir: str = "logs", log_level: str = "DEBUG"):
    """Setup logging for development environment"""
    return setup_logging(
        app_name="karmayogi_dev",
        log_level=log_level,
        log_dir=log_dir,
        enable_console=True,
        enable_file=True,
        enable_daily_rotation=True
    )


def setup_production_logging(log_dir: str = "/var/log/karmayogi", log_level: str = "INFO"):
    """Setup logging for production environment"""
    return setup_logging(
        app_name="karmayogi_prod",
        log_level=log_level,
        log_dir=log_dir,
        max_bytes=50 * 1024 * 1024,  # 50MB
        backup_count=60,  # Keep 60 days
        enable_console=False,  # No console in production
        enable_file=True,
        enable_daily_rotation=True
    )


def cleanup_old_logs(log_dir: str, days_to_keep: int = 30):
    """Clean up old log files beyond retention policy"""
    log_path = Path(log_dir)
    if not log_path.exists():
        return

    import time
    cutoff_time = time.time() - (days_to_keep * 24 * 60 * 60)

    for log_file in log_path.glob("*.log*"):
        if log_file.stat().st_mtime < cutoff_time:
            try:
                log_file.unlink()
                print(f"Removed old log file: {log_file}")
            except OSError as e:
                print(f"Error removing {log_file}: {e}")