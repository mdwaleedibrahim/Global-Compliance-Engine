"""Structured logging for GCE with nanosecond precision timestamps."""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from logging.handlers import TimedRotatingFileHandler
import time
import queue
import threading


class GCEFormatter(logging.Formatter):
    """Custom formatter for GCE logs with nanosecond precision and conditional Order ID tracking."""
    
    LOG_FORMAT = "%(asctime)s [GCE] [%(order_id)s] [%(levelname)s] %(message)s"
    
    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None, style: str = '%'):
        super().__init__(fmt=fmt or self.LOG_FORMAT, datefmt=datefmt, style=style)
    
    def format(self, record):
        """Format log record with nanosecond precision timestamp and conditional order_id."""
        timestamp_ns = int(time.time_ns())
        seconds = timestamp_ns // 1_000_000_000
        nanoseconds = timestamp_ns % 1_000_000_000
        
        dt = datetime.fromtimestamp(seconds)
        timestamp = dt.strftime('%Y-%m-%d %H:%M:%S')
        timestamp = f"{timestamp}.{nanoseconds:09d}"
        
        record.asctime = timestamp
        order_id = getattr(record, 'order_id', None)
        
        # Task 2: Show Order ID details in order logs only; remove [-] from non-order logs
        if order_id and order_id != "-":
            fmt = f"%(asctime)s [GCE] [{order_id}] [%(levelname)s] %(message)s"
        else:
            fmt = "%(asctime)s [GCE] [%(levelname)s] %(message)s"
            
        self._style._fmt = fmt
        return super().format(record)


class RejectionFormatter:
    """Formatter for control rejection messages."""
    
    @staticmethod
    def format_rejection(control_name: str, limit_value: Any, 
                        order_value: Any, reason: str) -> str:
        """Format rejection message."""
        return f"{control_name}: {reason} (LMT={limit_value}, ORD={order_value})"
    
    @staticmethod
    def format_rejection_summary(rejections: List[str]) -> str:
        """Format summary of all rejections."""
        return ", ".join(rejections)
    
    @staticmethod
    def format_control_result(control_name: str, passed: bool, 
                             limit_value: Any, order_value: Any,
                             message: str, rule_id: Optional[Any] = None) -> str:
        """
        Format control validation result.
        
        Task 1: Include DBid of rule before status e.g. [123456] [PASS] QtyControl
        """
        status = "PASS" if passed else "FAIL"
        rule_tag = f"[{rule_id}] " if rule_id is not None and str(rule_id).strip() != "" else ""
        return f"{rule_tag}[{status}] {control_name}: {message} | LMT={limit_value}, ORD={order_value}"


class GCELogger:
    """Structured logger for GCE with parallel off-critical-path async logging."""
    
    def __init__(self, name: str = "GCE", log_dir: str = "logs", 
                 console: bool = True, file: bool = True,
                 max_bytes: int = 10_485_760, backup_count: int = 30,
                 async_logging: bool = True):
        """
        Initialize GCE Logger.
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers = []
        
        self.rejection_formatter = RejectionFormatter()
        self.rejections: List[str] = []
        self.start_time: Optional[datetime] = None
        self.async_logging = async_logging
        self.current_order_id = "-"
        
        formatter = GCEFormatter()
        
        # Console handler
        if console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)
        
        # File handler with daily rotation (Task 3)
        if file:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            
            log_file = log_path / "GCE.log"
            file_handler = TimedRotatingFileHandler(
                log_file,
                when='midnight',
                interval=1,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.suffix = "%Y-%m-%d"
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
                
            if len(item) == 3:
                level, msg, ord_id = item
            else:
                level, msg = item
                ord_id = getattr(self, 'current_order_id', '-')

            extra = {'order_id': ord_id or '-'}
            try:
                if level == "INFO":
                    self.logger.info(msg, extra=extra)
                elif level == "WARNING":
                    self.logger.warning(msg, extra=extra)
                elif level == "ERROR":
                    self.logger.error(msg, extra=extra)
                elif level == "DEBUG":
                    self.logger.debug(msg, extra=extra)
            except Exception as e:
                sys.stderr.write(f"Logger worker error: {e}\n")
            finally:
                self.log_queue.task_done()

    def _enqueue_log(self, level: str, msg: str, order_id: Optional[str] = None):
        """Enqueue log message for parallel background processing."""
        target_ord_id = order_id or getattr(self, 'current_order_id', '-') or '-'
        if self.async_logging:
            self.log_queue.put((level, msg, target_ord_id))
        else:
            extra = {'order_id': target_ord_id}
            if level == "INFO":
                self.logger.info(msg, extra=extra)
            elif level == "WARNING":
                self.logger.warning(msg, extra=extra)
            elif level == "ERROR":
                self.logger.error(msg, extra=extra)
            elif level == "DEBUG":
                self.logger.debug(msg, extra=extra)
    
    def lmt_check_start(self, order_id: str = ""):
        """Log limit check start."""
        self.start_time = datetime.now()
        self.rejections = []
        if order_id:
            self.current_order_id = str(order_id)
        self._enqueue_log("INFO", "LMT_CHECK_START")
    
    def _format_order_check_line(self, check_type: str, order: Optional[Any] = None) -> str:
        """Format LMT_CHECK_NEW or LMT_CHECK_AMEND with full order parameters."""
        if not order:
            return check_type

        side = str(getattr(order, 'side', '') or '').strip()
        ric = str(getattr(order, 'ric', getattr(order, 'symbol', '')) or '').strip()
        qty = getattr(order, 'quantity', 0)
        ordertype = str(getattr(order, 'order_type', '') or '').strip()
        price = getattr(order, 'price', 0.0)
        currency = str(getattr(order, 'currency', 'HKD') or 'HKD').strip()

        product = str(getattr(order, 'product', '') or '').strip()
        app = str(getattr(order, 'application', '') or '').strip()
        flow = str(getattr(order, 'flow', '') or '').strip()
        trader = str(getattr(order, 'trader', '') or '').strip()
        desk = str(getattr(order, 'desk', '') or '').strip()
        account = str(getattr(order, 'account', '') or '').strip()
        client = str(getattr(order, 'client', '') or '').strip()
        exchange = str(getattr(order, 'exchange', '') or '').strip()
        underlying = str(getattr(order, 'underlying', '') or '').strip()
        algo = str(getattr(order, 'algo_strategy', getattr(order, 'algo', '')) or '').strip()
        tif = str(getattr(order, 'tif', '') or '').strip()

        pipe_details = f"{product}|{app}|{flow}|{trader}|{desk}|{account}|{client}|{exchange}|{underlying}|{algo}|{tif}"
        return f"{check_type} {side} {ric} {qty}@{ordertype} {price} {currency} PAFTDACXUAT {pipe_details}"

    def lmt_check_new(self, order: Optional[Any] = None):
        """Log new order limit check."""
        msg = self._format_order_check_line("LMT_CHECK_NEW", order)
        self._enqueue_log("INFO", msg)
    
    def lmt_check_amend(self, order: Optional[Any] = None):
        """Log amend order limit check."""
        msg = self._format_order_check_line("LMT_CHECK_AMEND", order)
        self._enqueue_log("INFO", msg)

    def lmt_mktdat(self, ric: str, last: Any = 0.0, bid: Any = 0.0, ask: Any = 0.0, open_px: Any = 0.0, close: Any = 0.0, order_id: str = ""):
        """Log market data prices line (LMT_MKTDAT)."""
        msg = f"LMT_MKTDAT {ric} Last={last}, Bid={bid}, Ask={ask}, Open={open_px}, Close={close}"
        self._enqueue_log("INFO", msg, order_id=order_id or self.current_order_id)
    
    def _format_duration(self, elapsed_ns: float) -> str:
        """
        Format elapsed nanoseconds dynamically:
        - If >= 1 second (1,000,000,000 ns) -> show in seconds (s)
        - If < 1 second and >= 1 millisecond (1,000,000 ns) -> show in milliseconds (ms)
        - If < 1 millisecond and >= 1 microsecond (1,000 ns) -> show in microseconds (μs)
        - If < 1 microsecond -> show in nanoseconds (ns)
        """
        if elapsed_ns >= 1_000_000_000:
            val = elapsed_ns / 1_000_000_000.0
            return f"{val:.2f} s"
        elif elapsed_ns >= 1_000_000:
            val = elapsed_ns / 1_000_000.0
            return f"{val:.2f} ms"
        elif elapsed_ns >= 1_000:
            val = elapsed_ns / 1000.0
            return f"{val:.2f} μs"
        else:
            return f"{int(elapsed_ns)} ns"

    def control_passed(self, control_name: str, limit_value: Any,
                      order_value: Any, caller_location: str = "",
                      elapsed_ns: Optional[Any] = None,
                      rule_id: Optional[Any] = None):
        """Log control pass with limit, order values, caller location, elapsed time, and rule DBId."""
        msg = self.rejection_formatter.format_control_result(
            control_name, True, limit_value, order_value,
            "Control passed", rule_id=rule_id
        )
        if caller_location or elapsed_ns is not None:
            if isinstance(elapsed_ns, (int, float)):
                timing = self._format_duration(float(elapsed_ns))
            elif elapsed_ns:
                timing = str(elapsed_ns)
            else:
                timing = ""
            suffix = f"{caller_location} {timing}".strip()
            msg = f"{msg} {{{suffix}}}"
        self._enqueue_log("INFO", msg)
    
    def control_failed(self, control_name: str, limit_value: Any,
                      order_value: Any, reason: str, caller_location: str = "",
                      elapsed_ns: Optional[Any] = None,
                      rule_id: Optional[Any] = None):
        """Log control failure with details, caller location, elapsed time, and rule DBId."""
        msg = self.rejection_formatter.format_control_result(
            control_name, False, limit_value, order_value, reason, rule_id=rule_id
        )
        if caller_location or elapsed_ns is not None:
            if isinstance(elapsed_ns, (int, float)):
                timing = self._format_duration(float(elapsed_ns))
            elif elapsed_ns:
                timing = str(elapsed_ns)
            else:
                timing = ""
            suffix = f"{caller_location} {timing}".strip()
            msg = f"{msg} {{{suffix}}}"
        # Logged as INFO to remove [WARNING] before [FAIL]
        self._enqueue_log("INFO", msg)

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
        formatted = self._format_duration(elapsed_time * 1_000_000_000.0)
        self._enqueue_log("INFO", f"LMT_CHECK_OVER in {formatted}")
        self.current_order_id = "-"
    
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

