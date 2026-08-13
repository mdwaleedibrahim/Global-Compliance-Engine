"""Structured logging for GCE with nanosecond precision timestamps."""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from logging.handlers import RotatingFileHandler
import time
import queue
import threading


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
    """Structured logger for GCE with parallel off-critical-path async logging."""
    
    def __init__(self, name: str = "GCE", log_dir: str = "logs", 
                 console: bool = True, file: bool = True,
                 max_bytes: int = 10_485_760, backup_count: int = 5,
                 async_logging: bool = True):
        """
        Initialize GCE Logger.
        
        Args:
            name: Logger name
            log_dir: Directory for log files
            console: Enable console logging
            file: Enable file logging
            max_bytes: Max file size before rotation (default 10MB)
            backup_count: Number of backup files to keep
            async_logging: Enable parallel background thread logging off critical path
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        
        self.rejection_formatter = RejectionFormatter()
        self.rejections: List[str] = []
        self.start_time: Optional[datetime] = None
        self.async_logging = async_logging
        
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
            
        # Parallel queue and background worker thread
        if self.async_logging:
            self.log_queue: queue.Queue = queue.Queue()
            self._stop_event = threading.Event()
            self.worker_thread = threading.Thread(
                target=self._log_worker,
                name="GCELoggerWorker",
                daemon=True
            )
            self.worker_thread.start()

    def _log_worker(self):
        """Background worker thread to format and write logs off critical path."""
        while not self._stop_event.is_set() or not self.log_queue.empty():
            try:
                item = self.log_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            
            if item is None:
                self.log_queue.task_done()
                break
                
            level, msg = item
            try:
                if level == "INFO":
                    self.logger.info(msg)
                elif level == "WARNING":
                    self.logger.warning(msg)
                elif level == "ERROR":
                    self.logger.error(msg)
                elif level == "DEBUG":
                    self.logger.debug(msg)
            except Exception as e:
                sys.stderr.write(f"Logger worker error: {e}\n")
            finally:
                self.log_queue.task_done()

    def _enqueue_log(self, level: str, msg: str):
        """Enqueue log message for parallel background processing."""
        if self.async_logging:
            self.log_queue.put((level, msg))
        else:
            if level == "INFO":
                self.logger.info(msg)
            elif level == "WARNING":
                self.logger.warning(msg)
            elif level == "ERROR":
                self.logger.error(msg)
            elif level == "DEBUG":
                self.logger.debug(msg)
    
    def lmt_check_start(self):
        """Log limit check start."""
        self.start_time = datetime.now()
        self.rejections = []
        self._enqueue_log("INFO", "LMT_CHECK_START")
    
    def lmt_check_new(self):
        """Log new order limit check."""
        self._enqueue_log("INFO", "LMT_CHECK_NEW")
    
    def lmt_check_amend(self):
        """Log amend order limit check."""
        self._enqueue_log("INFO", "LMT_CHECK_AMEND")
    
    def control_passed(self, control_name: str, limit_value: Any, 
                      order_value: Any):
        """Log control pass with limit and order values."""
        msg = self.rejection_formatter.format_control_result(
            control_name, True, limit_value, order_value,
            "Control passed"
        )
        self._enqueue_log("INFO", msg)
    
    def control_failed(self, control_name: str, limit_value: Any, 
                      order_value: Any, reason: str):
        """Log control failure with details."""
        msg = self.rejection_formatter.format_control_result(
            control_name, False, limit_value, order_value, reason
        )
        self._enqueue_log("WARNING", msg)
        
        # Track rejection for summary
        rejection = self.rejection_formatter.format_rejection(
            control_name, limit_value, order_value, reason
        )
        self.rejections.append(rejection)
    
    def lmt_check_summary(self, total: int, passed: int, failed: int):
        """Log limit check summary."""
        self._enqueue_log("INFO", f"{total} controls validated, {passed} passed, {failed} failed")
    
    def lmt_check_over(self, elapsed_time: float):
        """Log limit check completion with elapsed time."""
        self._enqueue_log("INFO", f"LMT_CHECK_OVER in {elapsed_time*1000:.2f}ms")
    
    def log_rejections(self):
        """Log all rejections as comma-separated summary."""
        if self.rejections:
            summary = self.rejection_formatter.format_rejection_summary(self.rejections)
            self._enqueue_log("INFO", summary)
    
    def info(self, msg: str):
        """Log info message."""
        self._enqueue_log("INFO", msg)
    
    def debug(self, msg: str):
        """Log debug message."""
        self._enqueue_log("DEBUG", msg)
    
    def warning(self, msg: str):
        """Log warning message."""
        self._enqueue_log("WARNING", msg)
    
    def error(self, msg: str):
        """Log error message."""
        self._enqueue_log("ERROR", msg)
    
    def get_rejections(self) -> List[str]:
        """Get list of all rejections from current session."""
        return self.rejections.copy()
    
    def clear_rejections(self):
        """Clear rejection tracking."""
        self.rejections = []

    def flush(self):
        """Block until all queued log messages are processed."""
        if self.async_logging:
            self.log_queue.join()

    def shutdown(self):
        """Flush remaining logs and shut down the parallel worker thread."""
        if self.async_logging and hasattr(self, 'worker_thread') and self.worker_thread.is_alive():
            self.flush()
            self._stop_event.set()
            self.log_queue.put(None)
            self.worker_thread.join(timeout=2.0)

