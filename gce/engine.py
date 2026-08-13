"""GCE Engine - Control orchestrator and execution pipeline."""

from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
from gce.controls.base_control import BaseControl, ControlExecution, ControlResult
from gce.cache.order_cache import Order, OrderStatus


class ControlRegistry:
    """Registry for managing controls."""
    
    def __init__(self):
        """Initialize control registry."""
        self.controls: Dict[str, BaseControl] = {}
        self.execution_order: List[str] = []
    
    def register(self, control_name: str, control: BaseControl) -> None:
        """
        Register a control.
        
        Args:
            control_name: Unique control identifier
            control: Control instance
        """
        self.controls[control_name] = control
        if control_name not in self.execution_order:
            self.execution_order.append(control_name)
    
    def unregister(self, control_name: str) -> bool:
        """Unregister a control."""
        if control_name in self.controls:
            del self.controls[control_name]
            self.execution_order.remove(control_name)
            return True
        return False
    
    def get_control(self, control_name: str) -> Optional[BaseControl]:
        """Get a control by name."""
        return self.controls.get(control_name)
    
    def get_all_controls(self) -> Dict[str, BaseControl]:
        """Get all registered controls."""
        return self.controls.copy()
    
    def set_execution_order(self, order: List[str]) -> None:
        """Set the execution order of controls."""
        # Validate all controls exist
        for ctrl_name in order:
            if ctrl_name not in self.controls:
                raise ValueError(f"Control '{ctrl_name}' not registered")
        self.execution_order = order
    
    def __len__(self):
        return len(self.controls)


class ControlExecutionPipeline:
    """Pipeline for executing controls."""
    
    def __init__(self, registry: ControlRegistry):
        """
        Initialize pipeline.
        
        Args:
            registry: ControlRegistry instance
        """
        self.registry = registry
        self.last_execution: List[ControlExecution] = []
    
    def execute_all(self, order: Order, context: Dict[str, Any], 
                   stop_on_fail: bool = False) -> Tuple[bool, List[ControlExecution]]:
        """
        Execute all registered controls.
        
        Args:
            order: Order to validate
            context: Context dict with caches (instruments, prices, positions, etc.)
            stop_on_fail: Stop execution on first failure (default: False)
            
        Returns:
            (all_passed: bool, execution_results: List[ControlExecution])
        """
        results = []
        all_passed = True
        
        for control_name in self.registry.execution_order:
            control = self.registry.get_control(control_name)
            if not control:
                continue
            
            # Execute control
            execution = control.execute(order, context)
            results.append(execution)
            
            if not execution.passed:
                all_passed = False
                if stop_on_fail:
                    break
        
        self.last_execution = results
        return all_passed, results
    
    def execute_specific(self, order: Order, context: Dict[str, Any],
                        control_names: List[str]) -> Tuple[bool, List[ControlExecution]]:
        """
        Execute specific controls.
        
        Args:
            order: Order to validate
            context: Context dict
            control_names: List of control names to execute
            
        Returns:
            (all_passed: bool, execution_results: List[ControlExecution])
        """
        results = []
        all_passed = True
        
        for control_name in control_names:
            control = self.registry.get_control(control_name)
            if not control:
                continue
            
            execution = control.execute(order, context)
            results.append(execution)
            
            if not execution.passed:
                all_passed = False
        
        self.last_execution = results
        return all_passed, results
    
    def get_last_execution(self) -> List[ControlExecution]:
        """Get results from last execution."""
        return self.last_execution
    
    def print_execution_results(self, results: List[ControlExecution], verbose: bool = False):
        """Print execution results."""
        total = len(results)
        passed = len([r for r in results if r.passed])
        failed = total - passed
        total_time = sum(r.execution_time_ms for r in results)
        
        print(f"\n{'='*70}")
        print(f"CONTROL EXECUTION RESULTS")
        print(f"{'='*70}")
        print(f"Total Controls: {total} | Passed: {passed} | Failed: {failed}")
        print(f"Total Execution Time: {total_time:.2f}ms")
        print(f"-"*70)
        
        for result in results:
            status_icon = "✓" if result.passed else "✗"
            print(f"{status_icon} {result.control_name}: {result.message}")
            if verbose:
                print(f"   LMT={result.limit_value}, ORD={result.order_value}")
                print(f"   Execution Time: {result.execution_time_ms:.2f}ms")
        
        print(f"{'='*70}\n")


class GCEEngine:
    """Global Compliance Engine - Main orchestrator."""
    
    def __init__(self):
        """Initialize GCE Engine."""
        self.registry = ControlRegistry()
        self.pipeline = ControlExecutionPipeline(self.registry)
        self.caches = {}  # Context for controls
    
    def register_control(self, control_name: str, control: BaseControl) -> None:
        """Register a control."""
        self.registry.register(control_name, control)
    
    def unregister_control(self, control_name: str) -> bool:
        """Unregister a control."""
        return self.registry.unregister(control_name)
    
    def set_context(self, context: Dict[str, Any]) -> None:
        """Set execution context (caches)."""
        self.caches = context
    
    def validate_order(self, order: Order, is_new: bool = True, 
                       stop_on_fail: bool = False) -> Tuple[bool, List[ControlExecution]]:
        """
        Validate order against all controls.
        
        Args:
            order: Order to validate
            is_new: Whether this is a new order (vs amend)
            stop_on_fail: Stop on first failure
            
        Returns:
            (passed: bool, execution_results: List[ControlExecution])
        """
        # Execute all controls
        passed, results = self.pipeline.execute_all(
            order, 
            self.caches,
            stop_on_fail=stop_on_fail
        )
        
        # Update order status based on validation
        if not passed:
            order.status = OrderStatus.REJECTED.value
        
        return passed, results
    
    def get_control_summary(self, results: List[ControlExecution]) -> Dict[str, Any]:
        """Get summary of control execution."""
        total = len(results)
        passed = len([r for r in results if r.passed])
        failed = total - passed
        total_time = sum(r.execution_time_ms for r in results)
        
        failures = [r.message for r in results if not r.passed]
        
        return {
            "total_controls": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": f"{(passed/total*100):.2f}%" if total > 0 else "0%",
            "total_execution_time_ms": total_time,
            "failures": failures,
            "status": "APPROVED" if failed == 0 else "REJECTED"
        }
    
    def __repr__(self):
        ctrl_count = len(self.registry)
        return f"GCEEngine(controls={ctrl_count})"


# Legacy GCE class for backward compatibility
import time
from gce.cache import InstrumentCache, PriceCache, OrderCache, PositionCache
from gce.logger import GCELogger


class GCE:
    """Global Compliance Engine - Pre-trade order control system"""
    
    def __init__(self, instrument_csv: str = "HK-ListOfSecurities.csv",
                 price_csv: str = "PriceCache.csv",
                 order_csv: str = "OrderCache.csv",
                 position_csv: str = "PositionsCache.csv",
                 log_dir: str = "logs"):
        """
        Initialize GCE with cache files
        
        Args:
            instrument_csv: Path to instrument static data CSV
            price_csv: Path to price cache CSV
            order_csv: Path to order cache CSV
            position_csv: Path to position cache CSV
            log_dir: Directory for log files
        """
        self.logger = GCELogger(log_dir=log_dir)
        
        # Load caches
        try:
            self.instruments = InstrumentCache(instrument_csv)
            self.logger.info(f"Loaded {self.instruments.count()} instruments")
        except FileNotFoundError as e:
            self.logger.error(f"Failed to load instruments: {e}")
            self.instruments = InstrumentCache()
        
        try:
            self.prices = PriceCache(price_csv)
            self.logger.info(f"Loaded {self.prices.count()} prices")
        except FileNotFoundError as e:
            self.logger.error(f"Failed to load prices: {e}")
            self.prices = PriceCache()
        
        try:
            self.orders = OrderCache(order_csv)
            self.logger.info(f"Loaded {self.orders.count()} orders")
        except FileNotFoundError as e:
            self.logger.error(f"Failed to load orders: {e}")
            self.orders = OrderCache()
        
        try:
            self.positions = PositionCache(position_csv)
            self.logger.info(f"Loaded {self.positions.count()} positions")
        except FileNotFoundError as e:
            self.logger.error(f"Failed to load positions: {e}")
            self.positions = PositionCache()
        
        self.controls: Dict[str, callable] = {}
        self.rejection_messages: List[str] = []
    
    def register_control(self, control_name: str, control_func: callable) -> None:
        """
        Register a limit control function
        
        Args:
            control_name: Name of the control
            control_func: Control function that returns (pass: bool, message: str, limit: any, value: any)
        """
        self.controls[control_name] = control_func
    
    def validate_order(self, order: Order, is_new: bool = True) -> Tuple[bool, List[str]]:
        """
        Validate order against all registered controls
        
        Args:
            order: Order to validate
            is_new: True for new order, False for amend
            
        Returns:
            (passed: bool, rejection_messages: List[str])
        """
        start_time = time.time()
        self.rejection_messages = []
        
        self.logger.lmt_check_start()
        
        if is_new:
            self.logger.lmt_check_new()
        else:
            self.logger.lmt_check_amend()
        
        passed_count = 0
        failed_count = 0
        
        # Run all controls
        for control_name, control_func in self.controls.items():
            try:
                result = control_func(order, self.instruments, self.prices, self.positions)
                
                if isinstance(result, tuple) and len(result) == 4:
                    passed, msg, limit, value = result
                else:
                    # Backward compatibility
                    passed, msg = result
                    limit = value = None
                
                if passed:
                    if limit is not None and value is not None:
                        self.logger.control_passed(control_name, limit, value)
                    passed_count += 1
                else:
                    self.logger.control_failed(control_name, msg)
                    self.rejection_messages.append(msg)
                    failed_count += 1
            except Exception as e:
                self.logger.error(f"Error in control {control_name}: {e}")
                failed_count += 1
                self.rejection_messages.append(f"Control error: {e}")
        
        total_controls = len(self.controls)
        self.logger.lmt_check_summary(total_controls, passed_count, failed_count)
        
        if self.rejection_messages:
            rejection_msg = ", ".join(self.rejection_messages)
            self.logger.info(rejection_msg)
        
        elapsed_time = time.time() - start_time
        self.logger.lmt_check_over(elapsed_time)
        
        order_passed = failed_count == 0
        
        # Update order status
        if order_passed:
            order.status = OrderStatus.LIVE
            self.orders.add_order(order)
        else:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "; ".join(self.rejection_messages)
            self.orders.add_order(order)
        
        return order_passed, self.rejection_messages
    
    def save_state(self, order_csv: str = "OrderCache.csv", 
                   position_csv: str = "PositionsCache.csv") -> None:
        """Save caches to CSV files"""
        self.orders.save_to_csv(order_csv)
        self.positions.save_to_csv(position_csv)
        self.logger.info(f"State saved: orders={order_csv}, positions={position_csv}")
