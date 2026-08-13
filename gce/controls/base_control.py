"""Base Control Framework - Abstract control class for limit checks."""

from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional
from enum import Enum
from datetime import datetime


class ControlResult(Enum):
    """Control execution result status."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


class BaseControl(ABC):
    """
    Abstract base class for all limit controls.
    
    Each control validates a specific limit (e.g., max quantity, max price).
    """
    
    def __init__(self, control_name: str, limit: Any):
        """
        Initialize control.
        
        Args:
            control_name: Name of the control (e.g., "MaxOrderQuantity")
            limit: Limit value (varies by control type)
        """
        self.control_name = control_name
        self.limit = limit
        self.last_result = None
        self.last_execution_time = 0.0
    
    @abstractmethod
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, Any, Any]:
        """
        Validate order against control limit.
        
        Args:
            order: Order object to validate
            context: Context dict with caches (instruments, prices, positions, etc.)
            
        Returns:
            Tuple: (passed: bool, message: str, limit_value: Any, order_value: Any)
        """
        pass
    
    def execute(self, order: Any, context: Dict[str, Any]) -> 'ControlExecution':
        """
        Execute control with timing and result tracking.
        
        Args:
            order: Order to validate
            context: Context dict
            
        Returns:
            ControlExecution object with full execution details
        """
        start_time = datetime.now()
        
        try:
            passed, message, limit_val, order_val = self.validate(order, context)
            
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            result = ControlExecution(
                control_name=self.control_name,
                passed=passed,
                message=message,
                limit_value=limit_val,
                order_value=order_val,
                status=ControlResult.PASS if passed else ControlResult.FAIL,
                execution_time_ms=execution_time * 1000,
                timestamp=start_time.isoformat()
            )
            
            self.last_result = result
            self.last_execution_time = execution_time
            
            return result
            
        except Exception as e:
            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            
            result = ControlExecution(
                control_name=self.control_name,
                passed=False,
                message=f"Control execution error: {str(e)}",
                limit_value=self.limit,
                order_value=None,
                status=ControlResult.FAIL,
                execution_time_ms=execution_time * 1000,
                timestamp=start_time.isoformat(),
                error=str(e)
            )
            
            self.last_result = result
            self.last_execution_time = execution_time
            
            return result
    
    def __repr__(self):
        return f"{self.control_name}(limit={self.limit})"


class ControlExecution:
    """Result of a single control execution."""
    
    def __init__(self, control_name: str, passed: bool, message: str, 
                 limit_value: Any, order_value: Any, status: ControlResult,
                 execution_time_ms: float, timestamp: str, error: Optional[str] = None):
        self.control_name = control_name
        self.passed = passed
        self.message = message
        self.limit_value = limit_value
        self.order_value = order_value
        self.status = status
        self.execution_time_ms = execution_time_ms
        self.timestamp = timestamp
        self.error = error
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "control_name": self.control_name,
            "passed": self.passed,
            "message": self.message,
            "limit_value": self.limit_value,
            "order_value": self.order_value,
            "status": self.status.value,
            "execution_time_ms": self.execution_time_ms,
            "timestamp": self.timestamp,
            "error": self.error
        }
    
    def __repr__(self):
        status_str = "✓" if self.passed else "✗"
        return f"{status_str} {self.control_name}: {self.message} ({self.execution_time_ms:.2f}ms)"
