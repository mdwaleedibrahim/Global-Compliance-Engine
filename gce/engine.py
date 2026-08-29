from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from pathlib import Path

from gce.controls.base_control import BaseControl, ControlExecution, ControlResult
from gce.cache.order_cache import Order, OrderStatus
from gce.cache import InstrumentCache, PriceCache, OrderCache, PositionCache
from gce.logger import GCELogger
from gce.pxfeeder import PXFeeder
from gce.datamgr import DataMgr


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
            self.datamgr = DataMgr(static_dir="Instrument Static", dat_path="InstrumentStatic.dat")
            self.logger.info(f"Loaded {self.datamgr.count()} static instruments in DataMgr")
        except Exception as e:
            self.logger.error(f"Failed to initialize DataMgr: {e}")
            self.datamgr = DataMgr(auto_load=False)

        try:
            self.instruments = InstrumentCache(instrument_csv)
            self.logger.info(f"Loaded {self.instruments.count()} instruments")
        except FileNotFoundError as e:
            self.logger.error(f"Failed to load instruments: {e}")
            self.instruments = InstrumentCache()
        
        try:
            symbols = list(self.instruments.instruments.keys())[:10] if self.instruments.count() > 0 else None
            self.pxfeeder = PXFeeder(dat_path="PriceCache.dat", symbols=symbols, fetch_on_start=True)
            self.prices = PriceCache(dat_path="PriceCache.dat", csv_path=price_csv, fetch_yfinance=False, symbols=symbols, auto_save=True)
            self.logger.info(f"Loaded/fetched {self.prices.count()} prices in cache via PXFeeder")
        except Exception as e:
            self.logger.error(f"Failed to initialize price cache / PXFeeder: {e}")
            self.pxfeeder = PXFeeder(fetch_on_start=False, auto_start_bg=False)
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
        
        # OMS-driven subscription: subscribe all RICs with active orders to PXFeeder
        try:
            live_orders = self.orders.get_open_orders()
            live_rics = list({o.ric for o in live_orders if o.ric})
            if live_rics and hasattr(self, 'pxfeeder') and self.pxfeeder:
                added = self.pxfeeder.subscribe_many(live_rics, fetch_now=False)
                self.logger.info(f"Subscribed {added} new RICs from {len(live_rics)} active OMS orders to PXFeeder")
        except Exception as e:
            self.logger.error(f"Failed to subscribe OMS active order RICs: {e}")

        self.controls: Dict[str, callable] = {}
        self.rejection_messages: List[str] = []
    
    def register_control(self, control_name: str, control_func: callable) -> None:
        """Register a limit control function."""
        self.controls[control_name] = control_func

    def _run_single_control(self, control_name: str, control_func: callable, order: Order):
        """Helper to run single control safely."""
        try:
            # Inject pxfeeder and datamgr into context if control expects it
            context = {
                'instruments': self.instruments,
                'prices': self.prices,
                'positions': self.positions,
                'pxfeeder': self.pxfeeder,
                'datamgr': self.datamgr,
                'fx_rates': self.pxfeeder.get_all_fx_rates()
            }
            func_to_inspect = getattr(control_func, 'validate', control_func)
            start_ns = time.time_ns()
            if hasattr(control_func, 'validate'):
                result = control_func.validate(order, context)
            else:
                result = control_func(order, self.instruments, self.prices, self.positions)
            elapsed_ns = time.time_ns() - start_ns

            code = getattr(func_to_inspect, '__code__', None)
            if code:
                caller_loc = f"{Path(code.co_filename).name}:{code.co_firstlineno}"
            else:
                caller_loc = ""

            if isinstance(result, tuple) and len(result) == 4:
                passed, msg, limit, value = result
            else:
                passed, msg = result
                limit = value = None
            return (control_name, passed, msg, limit, value, None, caller_loc, elapsed_ns)
        except Exception as e:
            err_msg = f"Control error: {e}"
            return (control_name, False, err_msg, None, None, e, "", 0)
    
    def validate_order(self, order: Order, is_new: bool = True, parallel: bool = True) -> Tuple[bool, List[str]]:
        """
        Validate order against registered controls, driven by the Rule Engine.

        Steps:
          1. Derive order attributes from order fields + Instrument Cache
          2. Select ALL applicable RMS rules (Enabled=Y, matching *, $, exact)
          3. For each matched rule, execute controls using THAT rule's own limits
          4. Order passes only if it passes every matched rule

        Args:
            order: Order to validate
            is_new: True for new order, False for amend
            parallel: Whether to execute controls in parallel

        Returns:
            (passed: bool, rejection_messages: List[str])
        """
        from gce.rule_engine import RuleEngine

        start_time = time.time()
        self.rejection_messages = []

        # --- On-demand price subscription ---
        # If the order's RIC has no cached price, subscribe and fetch it now
        ric = getattr(order, 'ric', getattr(order, 'symbol', '')) or ''
        if ric and hasattr(self, 'pxfeeder') and self.pxfeeder:
            px = self.pxfeeder.get_price(ric)
            if not px:
                self.pxfeeder.subscribe(ric, fetch_now=True)
                self.logger.info(f"On-demand price subscription for {ric}")

        # --- Rule Engine: select matched rules ---
        rule_engine = RuleEngine()
        attrs = rule_engine.build_order_attrs(order, self.datamgr)
        with self.datamgr._lock:
            all_rules = list(self.datamgr._rms_limits)
        selected_rules = rule_engine.select_rules(attrs, all_rules)

        # Base context (shared caches, no rule-specific datamgr yet)
        base_context = {
            'instruments': self.instruments,
            'prices': self.prices,
            'positions': self.positions,
            'pxfeeder': self.pxfeeder,
            'datamgr': self.datamgr,
            'fx_rates': self.pxfeeder.get_all_fx_rates() if hasattr(self.pxfeeder, 'get_all_fx_rates') else {},
        }

        # Build one context per rule (each with its own limits injected via _SingleRuleDataMgr)
        rule_contexts = rule_engine.get_per_rule_contexts(selected_rules, base_context)

        # --- CRITICAL PATH: Execute controls once per rule ---
        all_control_results = []  # (rule_id, c_name, passed, msg, limit, value, err, caller_loc, elapsed_ns)
        total_passed = 0
        total_failed = 0

        limit_mapped = self._get_limit_mapped_controls()

        def _run(c_name, c_func, ctx):
            try:
                func_to_inspect = getattr(c_func, 'validate', c_func)
                start_ns = time.time_ns()
                if hasattr(c_func, 'validate'):
                    result = c_func.validate(order, ctx)
                else:
                    result = c_func(order, self.instruments, self.prices, self.positions)
                elapsed_ns = time.time_ns() - start_ns
                code = getattr(func_to_inspect, '__code__', None)
                caller_loc = f"{Path(code.co_filename).name}:{code.co_firstlineno}" if code else ""
                if isinstance(result, tuple) and len(result) == 4:
                    passed, msg, limit, value = result
                else:
                    passed, msg = result
                    limit = value = None
                return (c_name, passed, msg, limit, value, None, caller_loc, elapsed_ns)
            except Exception as e:
                return (c_name, False, f"Control error: {e}", None, None, e, "", 0)

        for rule_ctx in rule_contexts:
            rule_id = rule_ctx.get('rule_id')
            rule_limits = rule_ctx.get('rule_limits', {})

            # Determine active controls for this specific rule (limit > 0 or no limit mapping)
            active_limits = rule_engine.get_active_control_limits(rule_limits, list(self.controls.keys()))
            controls_to_run = {
                name: func for name, func in self.controls.items()
                if name in active_limits or name not in limit_mapped
            }

            rule_results = []
            if parallel and len(controls_to_run) > 1:
                futures = [
                    self.executor.submit(_run, c_name, c_func, rule_ctx)
                    for c_name, c_func in controls_to_run.items()
                ]
                for future in futures:
                    rule_results.append(future.result())
            else:
                for c_name, c_func in controls_to_run.items():
                    rule_results.append(_run(c_name, c_func, rule_ctx))

            for res in rule_results:
                c_name, passed, msg, limit, value, err, caller_loc, elapsed_ns = res
                all_control_results.append((rule_id, *res))
                if passed:
                    total_passed += 1
                else:
                    # Annotate message with rule ID when multiple rules apply
                    annotated = f"[Rule {rule_id}] {msg}" if rule_id is not None and len(rule_contexts) > 1 else msg
                    self.rejection_messages.append(annotated)
                    total_failed += 1

        elapsed_time = time.time() - start_time
        order_passed = (total_failed == 0)

        # Update order state & cache
        if order_passed:
            order.status = OrderStatus.LIVE
            self.orders.add_order(order)
            
            # Update PositionCache for each matched rule pattern
            ref_px = float(getattr(order, 'price', 0.0) or 0.0)
            if not ref_px and ric:
                if hasattr(self, 'prices') and self.prices:
                    px_item = self.prices.get_price(ric)
                    if px_item:
                        ref_px = float(getattr(px_item, 'last', 0.0) or getattr(px_item, 'close', 0.0) or 0.0)
            order_cond = float(getattr(order, 'quantity', 0) or 0) * ref_px
            if hasattr(self, 'positions') and self.positions:
                for rule_ctx in rule_contexts:
                    rule_keys = rule_ctx.get('rule_limits')
                    self.positions.update_position_from_order(
                        order=order,
                        rule_keys=rule_keys,
                        consideration=order_cond,
                        xr_rate=1.0
                    )
                try:
                    self.positions.save_to_csv("PositionsCache.csv")
                except Exception as e:
                    self.logger.error(f"Failed to auto-save PositionsCache.csv: {e}")
        else:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "; ".join(self.rejection_messages)
            self.orders.add_order(order)

        # --- ATOMIC ASYNC LOGGING BATCH ---
        # Collect all validation log entries into an atomic batch so concurrent order logs never mix
        order_id_val = getattr(order, 'order_id', '') or getattr(order, 'ric', '') or ''
        log_batch: List[Tuple[str, str]] = []

        log_batch.append(("INFO", "LMT_CHECK_START"))

        check_type = "LMT_CHECK_NEW" if is_new else "LMT_CHECK_AMEND"
        log_batch.append(("INFO", self.logger._format_order_check_line(check_type, order)))

        px_obj = None
        ric = getattr(order, 'ric', getattr(order, 'symbol', '')) or ''
        if ric:
            if hasattr(self, 'prices') and self.prices:
                px_obj = self.prices.get_price(ric)
            if not px_obj and hasattr(self, 'pxfeeder') and self.pxfeeder:
                px_obj = self.pxfeeder.get_price(ric)

        last_px = getattr(px_obj, 'last', 0.0) if px_obj else 0.0
        bid_px = getattr(px_obj, 'bid', 0.0) if px_obj else 0.0
        ask_px = getattr(px_obj, 'ask', 0.0) if px_obj else 0.0
        open_px = getattr(px_obj, 'open_price', getattr(px_obj, 'open', 0.0)) if px_obj else 0.0
        close_px = getattr(px_obj, 'close', 0.0) if px_obj else 0.0
        log_batch.append(("INFO", f"LMT_MKTDAT {ric} Last={last_px}, Bid={bid_px}, Ask={ask_px}, Open={open_px}, Close={close_px}"))

        for rule_id, c_name, passed, msg, limit, value, err, caller_loc, elapsed_ns in all_control_results:
            if err is not None:
                log_batch.append(("ERROR", f"[rule={rule_id}] Error in control {c_name}: {err}"))
            else:
                formatted_msg = self.logger.rejection_formatter.format_control_result(
                    c_name, passed, limit, value,
                    "Control passed" if passed else msg,
                    rule_id=rule_id
                )
                if caller_loc or elapsed_ns is not None:
                    if isinstance(elapsed_ns, (int, float)):
                        timing = self.logger._format_duration(float(elapsed_ns))
                    elif elapsed_ns:
                        timing = str(elapsed_ns)
                    else:
                        timing = ""
                    suffix = f"{caller_loc} {timing}".strip()
                    formatted_msg = f"{formatted_msg} {{{suffix}}}"
                log_batch.append(("INFO", formatted_msg))

        log_batch.append(("INFO", f"{total_passed + total_failed} controls validated, {total_passed} passed, {total_failed} failed"))

        if self.rejection_messages:
            summary = self.logger.rejection_formatter.format_rejection_summary(self.rejection_messages)
            log_batch.append(("INFO", summary))

        formatted_total = self.logger._format_duration(elapsed_time * 1_000_000_000.0)
        log_batch.append(("INFO", f"LMT_CHECK_OVER in {formatted_total}"))

        # Enqueue the complete order batch atomically to parallel async queue off critical path
        self.logger.log_order_batch(order_id_val, log_batch)

        return order_passed, self.rejection_messages

    @staticmethod
    def _get_limit_mapped_controls() -> set:
        """Controls that have a limit column mapping — skipped if limit=0."""
        return {
            'MaxOrderQuantity', 'MaxOrderPrice', 'MaxOrderConsideration',
            'BBOPriceTolerance', 'ClosePriceTolerance', 'LastPriceTolerance',
            'MaxDailyTurnover',
            'max_qty', 'max_price', 'max_consideration',
            'bbo_tolerance', 'close_tolerance', 'last_tolerance',
            'max_turnover',
        }
    
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
        """Shutdown thread pool executor, pxfeeder background thread, and logger."""
        if hasattr(self, 'pxfeeder') and self.pxfeeder:
            self.pxfeeder.stop()
        self.executor.shutdown(wait=False)
        self.logger.shutdown()

