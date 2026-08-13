"""Structured logging for GCE with nanosecond precision timestamps."""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from logging.handlers import RotatingFileHandler
import time


class GCEFormatter(logging.Formatter):
    """Custom formatter for GCE logs with nanosecond precision."""
    
    LOG_FORMAT = "%(asctime)s [GCE] [%(levelname)s] %(message)s"
    
    def format(self, record):
        """Format log record with nanosecond precision timestamp."""
        # Get nanosecond timestamp
        timestamp_ns = int(time.time_ns())
        seconds = timestamp_ns // 1_000_000_000
        nanoseconds = timestamp_ns % 1_000_000_000
        
        dt = datetime.fromtimestamp(seconds)
        timestamp = dt.strftime('%Y-%m-%d %H:%M:%S')
        timestamp = f"{timestamp}.{nanoseconds:09d}"
        
        record.asctime = timestamp
        return super().format(record)


class RejectionFormatter:
    """Formatter for control rejection messages."""
    
    @staticmethod
    def format_rejection(control_name: str, limit_value: Any, 
                        order_value: Any, reason: str) -> str:
        """
        Format rejection message.
        
        Args:
            control_name: Name of the control that rejected
            limit_value: The limit value
            order_value: The order value that violated limit
            reason: Rejection reason
            
        Returns:
            Formatted rejection message
        """
        return f"{control_name}: {reason} (LMT={limit_value}, ORD={order_value})"
    
    @staticmethod
    def format_rejection_summary(rejections: List[str]) -> str:
        """
        Format summary of all rejections.
        
        Args:
            rejections: List of rejection messages
            
        Returns:
            Comma-separated rejection summary
        """
        return ", ".join(rejections)
    
    @staticmethod
    def format_control_result(control_name: str, passed: bool, 
                             limit_value: Any, order_value: Any,
                             message: str) -> str:
        """
        Format control validation result.
        
        Args:
            control_name: Control name
            passed: Whether control passed
            limit_value: Limit value
            order_value: Order value
            message: Result message
            
        Returns:
            Formatted result message
        """
        status = "PASS" if passed else "FAIL"
        return f"[{status}] {control_name}: {message} | LMT={limit_value}, ORD={order_value}"


class GCELogger:
    """Structured logger for GCE with comprehensive logging capabilities."""
    
    def __init__(self, name: str = "GCE", log_dir: str = "logs", 
                 console: bool = True, file: bool = True,
                 max_bytes: int = 10_485_760, backup_count: int = 5):
        """
        Initialize GCE Logger.
        
        Args:
            name: Logger name
            log_dir: Directory for log files
            console: Enable console logging
            file: Enable file logging
            max_bytes: Max file size before rotation (default 10MB)
            backup_count: Number of backup files to keep
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        
        self.rejection_formatter = RejectionFormatter()
        self.rejections: List[str] = []
        self.start_time: Optional[datetime] = None
        
        formatter = GCEFormatter(GCEFormatter.LOG_FORMAT)
        
        # Console handler
        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        # File handler with rotation
        if file:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            
            log_file = log_path / "GCE.log"
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=max_bytes,
                backupCount=backup_count
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
    
    def lmt_check_start(self):
        """Log limit check start."""
        self.start_time = datetime.now()
        self.rejections = []
        self.logger.info("LMT_CHECK_START")
    
    def lmt_check_new(self):
        """Log new order limit check."""
        self.logger.info("LMT_CHECK_NEW")
    
    def lmt_check_amend(self):
        """Log amend order limit check."""
        self.logger.info("LMT_CHECK_AMEND")
    
    def control_passed(self, control_name: str, limit_value: Any, 
                      order_value: Any):
        """Log control pass with limit and order values."""
        msg = self.rejection_formatter.format_control_result(
            control_name, True, limit_value, order_value,
            "Control passed"
        )
        self.logger.info(msg)
    
    def control_failed(self, control_name: str, limit_value: Any, 
                      order_value: Any, reason: str):
        """Log control failure with details."""
        msg = self.rejection_formatter.format_control_result(
            control_name, False, limit_value, order_value, reason
        )
        self.logger.warning(msg)
        
        # Track rejection for summary
        rejection = self.rejection_formatter.format_rejection(
            control_name, limit_value, order_value, reason
        )
        self.rejections.append(rejection)
    
    def lmt_check_summary(self, total: int, passed: int, failed: int):
        """Log limit check summary."""
        self.logger.info(f"{total} controls validated, {passed} passed, {failed} failed")
    
    def lmt_check_over(self, elapsed_time: float):
        """Log limit check completion with elapsed time."""
        self.logger.info(f"LMT_CHECK_OVER in {elapsed_time*1000:.2f}ms")
    
    def log_rejections(self):
        """Log all rejections as comma-separated summary."""
        if self.rejections:
            summary = self.rejection_formatter.format_rejection_summary(self.rejections)
            self.logger.info(summary)
    
    def info(self, msg: str):
        """Log info message."""
        self.logger.info(msg)
    
    def debug(self, msg: str):
        """Log debug message."""
        self.logger.debug(msg)
    
    def warning(self, msg: str):
        """Log warning message."""
        self.logger.warning(msg)
    
    def error(self, msg: str):
        """Log error message."""
        self.logger.error(msg)
    
    def get_rejections(self) -> List[str]:
        """Get list of all rejections from current session."""
        return self.rejections.copy()
    
    def clear_rejections(self):
        """Clear rejection tracking."""
        self.rejections = []
