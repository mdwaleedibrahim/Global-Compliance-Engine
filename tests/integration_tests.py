"""Integration Tests - Comprehensive test suite for GCE."""

import time
from typing import List, Tuple
from gce.engine import GCEEngine
from gce.controls.quantity_control import MaxOrderQuantity
from gce.controls.price_control import MaxOrderPrice
from gce.cache.order_cache import Order, OrderCache
from gce.cache.position_cache import PositionCache
from gce.cache.price_cache import PriceCache
from gce.position_updater import PositionUpdater
from gce.reconciler import PositionReconciler
from utils.order_generator import MockOrderGenerator
from utils.price_updater import PriceUpdater


class IntegrationTestSuite:
    """Comprehensive integration tests for GCE."""
    
    def __init__(self, verbose: bool = False):
        """
        Initialize test suite.
        
        Args:
            verbose: Print detailed output
        """
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self.tests_run = 0
    
    def assert_true(self, condition: bool, test_name: str) -> bool:
        """
        Assert condition is true.
        
        Args:
            condition: Condition to test
            test_name: Name of test
            
        Returns:
            True if assertion passes
        """
        self.tests_run += 1
        if condition:
            self.passed += 1
            if self.verbose:
                print(f"✓ {test_name}")
            return True
        else:
            self.failed += 1
            if self.verbose:
                print(f"✗ {test_name}")
            return False
    
    def assert_equal(self, actual, expected, test_name: str) -> bool:
        """Assert actual equals expected."""
        return self.assert_true(actual == expected, f"{test_name} (expected {expected}, got {actual})")
    
    def assert_not_equal(self, actual, expected, test_name: str) -> bool:
        """Assert actual not equals expected."""
        return self.assert_true(actual != expected, f"{test_name} (should not equal {expected})")
    
    def test_order_generator(self) -> bool:
        """Test mock order generator."""
        print("\n=== ORDER GENERATOR TESTS ===")
        
        gen = MockOrderGenerator(seed=42)
        
        # Test single order
        order = gen.generate_order(symbol="0700.HK", quantity=100, price=440.0)
        self.assert_equal(order.symbol, "0700.HK", "Single order symbol")
        self.assert_equal(order.quantity, 100, "Single order quantity")
        
        # Test multiple orders
        orders = gen.generate_orders(count=10)
        self.assert_equal(len(orders), 10, "Generate 10 orders")
        
        # Test buy/sell pair
        buy, sell = gen.generate_buy_sell_pair(symbol="0700.HK", quantity=100, price=440.0)
        self.assert_equal(buy.side, "B", "Buy order side")
        self.assert_equal(sell.side, "S", "Sell order side")
        self.assert_equal(buy.quantity, sell.quantity, "Buy/sell same quantity")
        
        # Test rejection cases
        test_cases = gen.generate_rejection_test_cases()
        self.assert_true("oversized_quantity" in test_cases, "Rejection test cases generated")
        
        return self.failed == 0
    
    def test_controls_framework(self) -> bool:
        """Test control framework and execution."""
        print("\n=== CONTROLS FRAMEWORK TESTS ===")
        
        engine = GCEEngine()
        
        # Register controls
        qty_control = MaxOrderQuantity(limit=1000)
        price_control = MaxOrderPrice(limit=500)
        
        engine.register_control("qty_limit", qty_control)
        engine.register_control("price_limit", price_control)
        
        self.assert_equal(len(engine.registry), 2, "Two controls registered")
        
        # Create test orders
        gen = MockOrderGenerator(seed=42)
        
        # Should pass
        pass_order = gen.generate_order(quantity=100, price=440.0)
        engine.set_context({})
        passed, results = engine.validate_order(pass_order)
        
        self.assert_true(passed, "Order passes all controls")
        self.assert_equal(len(results), 2, "Two controls executed")
        
        # Should fail quantity
        fail_qty_order = gen.generate_order(quantity=2000, price=440.0)
        passed, results = engine.validate_order(fail_qty_order)
        
        self.assert_true(not passed, "Order fails quantity control")
        failed_controls = [r for r in results if not r.passed]
        self.assert_true(len(failed_controls) > 0, "At least one control failed")
        
        # Should fail price
        fail_price_order = gen.generate_order(quantity=100, price=1000.0)
        passed, results = engine.validate_order(fail_price_order)
        
        self.assert_true(not passed, "Order fails price control")
        
        return self.failed == 0
    
    def test_order_cache(self) -> bool:
        """Test order cache operations."""
        print("\n=== ORDER CACHE TESTS ===")
        
        order_cache = OrderCache()
        gen = MockOrderGenerator(seed=42)
        
        # Create and add order
        order = gen.generate_order()
        result = order_cache.create_order(order)
        self.assert_true(result, "Order created in cache")
        
        # Retrieve order
        retrieved = order_cache.get_order(order.order_id)
        self.assert_equal(retrieved.order_id, order.order_id, "Order retrieved by ID")
        
        # Update fill
        result = order_cache.update_filled_quantity(order.order_id, 50)
        self.assert_true(result, "Fill quantity updated")
        
        retrieved = order_cache.get_order(order.order_id)
        self.assert_equal(retrieved.filled, 50, "Fill quantity correct")
        
        return self.failed == 0
    
    def test_position_management(self) -> bool:
        """Test position tracking and updates."""
        print("\n=== POSITION MANAGEMENT TESTS ===")
        
        position_cache = PositionCache()
        order_cache = OrderCache()
        updater = PositionUpdater(position_cache)
        gen = MockOrderGenerator(seed=42)
        
        # Create and fill order
        order = gen.generate_order(symbol="0700.HK", quantity=100, price=440.0, side="B")
        order_cache.create_order(order)
        
        # Update position from order
        success, msg = updater.update_position_from_order(order, 50)
        self.assert_true(success, "Position updated from order")
        
        # Reconcile position
        reconciler = PositionReconciler(order_cache, position_cache)
        report = reconciler.reconcile_symbol("0700.HK")
        
        self.assert_true(report is not None, "Reconciliation report generated")
        
        return self.failed == 0
    
    def test_price_updates(self) -> bool:
        """Test price cache updates."""
        print("\n=== PRICE UPDATE TESTS ===")
        
        price_cache = PriceCache()
        updater = PriceUpdater(price_cache)
        
        # Add sample price
        price_cache.prices["0700.HK"] = {
            "RIC": "0700.HK",
            "Bid": 440.0,
            "Ask": 441.0,
            "Last": 440.5,
            "Close": 450.0,
            "Open": 446.0
        }
        
        # Update single price
        result = updater.update_single_price("0700.HK", bid=445.0, ask=446.0)
        self.assert_true(result, "Single price updated")
        
        price = price_cache.get_price("0700.HK")
        self.assert_equal(price["Bid"], 445.0, "Bid price updated correctly")
        
        # Adjust by percent
        result = updater.adjust_price_by_percent("0700.HK", 0.05)  # +5%
        self.assert_true(result, "Price adjusted by percentage")
        
        price = price_cache.get_price("0700.HK")
        self.assert_true(price["Bid"] > 445.0, "Price increased by 5%")
        
        return self.failed == 0
    
    def test_performance(self) -> Tuple[bool, dict]:
        """Test system performance."""
        print("\n=== PERFORMANCE TESTS ===")
        
        engine = GCEEngine()
        engine.register_control("qty_limit", MaxOrderQuantity(limit=1000))
        engine.register_control("price_limit", MaxOrderPrice(limit=500))
        engine.set_context({})
        
        gen = MockOrderGenerator(seed=42)
        
        # Benchmark: 1000 validations
        orders = gen.generate_orders(count=1000)
        
        start = time.time()
        for order in orders:
            engine.validate_order(order)
        elapsed = time.time() - start
        
        avg_time = (elapsed / len(orders)) * 1000  # ms
        
        self.assert_true(avg_time < 10, f"Average validation time < 10ms (got {avg_time:.2f}ms)")
        
        metrics = {
            "total_orders": len(orders),
            "total_time_sec": elapsed,
            "avg_time_ms": avg_time,
            "orders_per_sec": len(orders) / elapsed
        }
        
        if self.verbose:
            print(f"  Total Orders: {metrics['total_orders']}")
            print(f"  Total Time: {metrics['total_time_sec']:.3f}s")
            print(f"  Avg Time: {metrics['avg_time_ms']:.2f}ms")
            print(f"  Throughput: {metrics['orders_per_sec']:.0f} orders/sec")
        
        return self.failed == 0, metrics
    
    def run_all_tests(self) -> dict:
        """Run all integration tests."""
        print("\n" + "="*70)
        print("GCE INTEGRATION TEST SUITE")
        print("="*70)
        
        self.test_order_generator()
        self.test_controls_framework()
        self.test_order_cache()
        self.test_position_management()
        self.test_price_updates()
        perf_pass, perf_metrics = self.test_performance()
        
        summary = {
            "total_tests": self.tests_run,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": f"{(self.passed/self.tests_run*100):.1f}%" if self.tests_run > 0 else "0%",
            "status": "PASSED" if self.failed == 0 else "FAILED",
            "performance": perf_metrics
        }
        
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        print(f"Total Tests: {summary['total_tests']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Pass Rate: {summary['pass_rate']}")
        print(f"Status: {summary['status']}")
        print("="*70 + "\n")
        
        return summary


if __name__ == "__main__":
    suite = IntegrationTestSuite(verbose=True)
    results = suite.run_all_tests()
