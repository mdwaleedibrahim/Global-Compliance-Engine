from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from gce.controls.base_control import BaseControl, ControlExecution, ControlResult
from gce.cache.order_cache import Order, OrderStatus
from gce.cache import InstrumentCache, PriceCache, OrderCache, PositionCache
from gce.logger import GCELogger


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
    """Pipeline for executing controls concurrently or sequentially."""
    
    def __init__(self, registry: ControlRegistry, max_workers: int = 8):
        """
        Initialize pipeline.
        
        Args:
            registry: ControlRegistry instance
            max_workers: Number of worker threads for parallel control execution
        """
        self.registry = registry
        self.last_execution: List[ControlExecution] = []
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="GCEControlWorker")
    
    def execute_all(self, order: Order, context: Dict[str, Any], 
                   stop_on_fail: bool = False, parallel: bool = True) -> Tuple[bool, List[ControlExecution]]:
        """
        Execute all registered controls.
        
        Args:
            order: Order to validate
            context: Context dict with caches (instruments, prices, positions, etc.)
            stop_on_fail: Stop execution on first failure (default: False)
            parallel: Execute controls concurrently in parallel (default: True)
            
        Returns:
            (all_passed: bool, execution_results: List[ControlExecution])
        """
        results = []
        all_passed = True
        controls_to_run = [self.registry.get_control(name) for name in self.registry.execution_order if self.registry.get_control(name)]
        
        if not controls_to_run:
            self.last_execution = []
            return True, []

        if parallel and len(controls_to_run) > 1:
            futures = [self.executor.submit(ctrl.execute, order, context) for ctrl in controls_to_run]
            for future in futures:
                try:
                    execution = future.result()
                    results.append(execution)
                    if not execution.passed:
                        all_passed = False
                except Exception as e:
                    all_passed = False
        else:
            for control in controls_to_run:
                execution = control.execute(order, context)
                results.append(execution)
                
                if not execution.passed:
                    all_passed = False
                    if stop_on_fail:
                        break
        
        self.last_execution = results
        return all_passed, results
    
    def execute_specific(self, order: Order, context: Dict[str, Any],
                        control_names: List[str], parallel: bool = True) -> Tuple[bool, List[ControlExecution]]:
        """
        Execute specific controls.
        
        Args:
            order: Order to validate
            context: Context dict
            control_names: List of control names to execute
            parallel: Execute controls concurrently in parallel (default: True)
            
        Returns:
            (all_passed: bool, execution_results: List[ControlExecution])
        """
        results = []
        all_passed = True
        controls_to_run = [self.registry.get_control(name) for name in control_names if self.registry.get_control(name)]
        
        if not controls_to_run:
            self.last_execution = []
            return True, []

        if parallel and len(controls_to_run) > 1:
            futures = [self.executor.submit(ctrl.execute, order, context) for ctrl in controls_to_run]
            for future in futures:
                try:
                    execution = future.result()
                    results.append(execution)
                    if not execution.passed:
                        all_passed = False
                except Exception as e:
                    all_passed = False
        else:
            for control in controls_to_run:
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

    def shutdown(self):
        """Shutdown thread pool executor."""
        self.executor.shutdown(wait=False)


class GCEEngine:
    """Global Compliance Engine - Main orchestrator."""
    
    def __init__(self, max_workers: int = 8):
        """Initialize GCE Engine."""
        self.registry = ControlRegistry()
        self.pipeline = ControlExecutionPipeline(self.registry, max_workers=max_workers)
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
                       stop_on_fail: bool = False, parallel: bool = True) -> Tuple[bool, List[ControlExecution]]:
        """
        Validate order against all controls.
        
        Args:
            order: Order to validate
            is_new: Whether this is a new order (vs amend)
            stop_on_fail: Stop on first failure
            parallel: Execute controls in parallel
            
        Returns:
            (passed: bool, execution_results: List[ControlExecution])
        """
        passed, results = self.pipeline.execute_all(
            order, 
            self.caches,
            stop_on_fail=stop_on_fail,
            parallel=parallel
        )
        
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

    def shutdown(self):
        """Shutdown engine pipeline workers."""
        self.pipeline.shutdown()
    
    def __repr__(self):
        ctrl_count = len(self.registry)
        return f"GCEEngine(controls={ctrl_count})"


class GCE:
    """Global Compliance Engine - Pre-trade order control system with parallel control execution."""
    
    def __init__(self, instrument_csv: str = "HK-ListOfSecurities.csv",
                 price_csv: str = "PriceCache.csv",
                 order_csv: str = "OrderCache.csv",
                 position_csv: str = "PositionsCache.csv",
                 log_dir: str = "logs",
                 max_workers: int = 8):
        """
        Initialize GCE with cache files and parallel worker pool.
        """
        self.logger = GCELogger(log_dir=log_dir)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="GCEControlExec")
        
        # Load caches
        try:
            self.instruments = InstrumentCache(instrument_csv)
            self.logger.info(f"Loaded {self.instruments.count()} instruments")
        except FileNotFoundError as e:
            self.logger.error(f"Failed to load instruments: {e}")
            self.instruments = InstrumentCache()
        
        try:
            symbols = list(self.instruments.instruments.keys()) if self.instruments.count() > 0 else None
            self.prices = PriceCache(csv_path=price_csv, fetch_yfinance=True, symbols=symbols, auto_save=True)
            self.logger.info(f"Loaded/fetched {self.prices.count()} prices in cache")
        except Exception as e:
            self.logger.error(f"Failed to initialize price cache: {e}")
            self.prices = PriceCache()
        
        try:
            self.orders = OrderCache(csv_path=order_csv, instrument_cache=self.instruments)
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
        """Register a limit control function."""
        self.controls[control_name] = control_func

    def _run_single_control(self, control_name: str, control_func: callable, order: Order):
        """Helper to run single control safely."""
        try:
            result = control_func(order, self.instruments, self.prices, self.positions)
            if isinstance(result, tuple) and len(result) == 4:
                passed, msg, limit, value = result
            else:
                passed, msg = result
                limit = value = None
            return (control_name, passed, msg, limit, value, None)
        except Exception as e:
            err_msg = f"Control error: {e}"
            return (control_name, False, err_msg, None, None, e)
    
    def validate_order(self, order: Order, is_new: bool = True, parallel: bool = True) -> Tuple[bool, List[str]]:
        """
        Validate order against all registered controls.
        
        Limit checking is performed on the critical path (concurrently in parallel if parallel=True).
        Once limit checking completes, logging events are dispatched to the parallel logger path.
        
        Args:
            order: Order to validate
            is_new: True for new order, False for amend
            parallel: Whether to execute controls in parallel
            
        Returns:
            (passed: bool, rejection_messages: List[str])
        """
        start_time = time.time()
        self.rejection_messages = []
        
        # --- CRITICAL PATH: Limit checking execution ---
        control_results = []
        passed_count = 0
        failed_count = 0

        if parallel and len(self.controls) > 1:
            futures = [
                self.executor.submit(self._run_single_control, c_name, c_func, order)
                for c_name, c_func in self.controls.items()
            ]
            for future in futures:
                c_name, passed, msg, limit, value, err = future.result()
                control_results.append((c_name, passed, msg, limit, value, err))
                if passed:
                    passed_count += 1
                else:
                    self.rejection_messages.append(msg)
                    failed_count += 1
        else:
            for control_name, control_func in self.controls.items():
                res = self._run_single_control(control_name, control_func, order)
                c_name, passed, msg, limit, value, err = res
                control_results.append(res)
                if passed:
                    passed_count += 1
                else:
                    self.rejection_messages.append(msg)
                    failed_count += 1
        
        elapsed_time = time.time() - start_time
        order_passed = (failed_count == 0)
        
        # Update order state & cache on critical path
        if order_passed:
            order.status = OrderStatus.LIVE
            self.orders.add_order(order)
        else:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "; ".join(self.rejection_messages)
            self.orders.add_order(order)
        
        # --- PARALLEL LOGGING PATH: Post-checking async log dispatch ---
        self.logger.lmt_check_start()
        if is_new:
            self.logger.lmt_check_new()
        else:
            self.logger.lmt_check_amend()
            
        for control_name, passed, msg, limit, value, err in control_results:
            if err is not None:
                self.logger.error(f"Error in control {control_name}: {err}")
            elif passed:
                if limit is not None and value is not None:
                    self.logger.control_passed(control_name, limit, value)
            else:
                self.logger.control_failed(control_name, limit, value, msg)
        
        total_controls = len(self.controls)
        self.logger.lmt_check_summary(total_controls, passed_count, failed_count)
        self.logger.log_rejections()
        self.logger.lmt_check_over(elapsed_time)
        
        return order_passed, self.rejection_messages
    
    def save_state(self, order_csv: str = "OrderCache.csv", 
                   position_csv: str = "PositionsCache.csv") -> None:
        """Save caches to CSV files"""
        self.orders.save_to_csv(order_csv)
        self.positions.save_to_csv(position_csv)
        self.logger.info(f"State saved: orders={order_csv}, positions={position_csv}")

    def get_risk_report(self):
        """Generate comprehensive risk report snapshot."""
        from gce.analytics import RiskAnalytics
        return RiskAnalytics.calculate_risk_report(
            order_cache=self.orders,
            position_cache=self.positions,
            price_cache=self.prices,
            logger_rejections=self.logger.get_rejections()
        )

    def shutdown(self):
        """Shutdown thread pool executor and logger."""
        self.executor.shutdown(wait=False)
        self.logger.shutdown()

