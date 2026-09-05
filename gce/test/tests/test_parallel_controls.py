"""Test suite for parallel control execution and performance optimization."""

import unittest
import time
from gce.main.engine import GCEEngine, GCE
from gce.main.controls.quantity_control import MaxOrderQuantity
from gce.main.controls.price_control import MaxOrderPrice
from gce.main.controls.base_control import BaseControl
from gce.main.cache.order_cache import Order, OrderStatus
from gce.main.utils.order_generator import MockOrderGenerator


class SlowControl(BaseControl):
    """Simulated control with slight latency to demonstrate parallel speedup."""
    
    def __init__(self, name: str, delay_ms: float = 5.0, pass_val: bool = True):
        super().__init__(name, limit=100.0)
        self.delay_sec = delay_ms / 1000.0
        self.pass_val = pass_val

    def validate(self, order, context):
        time.sleep(self.delay_sec)
        if self.pass_val:
            return True, f"{self.control_name} OK", self.limit, 50.0
        else:
            return False, f"{self.control_name} FAIL", self.limit, 150.0


class TestParallelControls(unittest.TestCase):
    """Test parallel control execution correctness and performance."""

    def setUp(self):
        self.engine = GCEEngine(max_workers=8)
        self.gen = MockOrderGenerator(seed=42)

    def tearDown(self):
        self.engine.shutdown()

    def test_parallel_vs_sequential_correctness(self):
        """Verify parallel and sequential control execution yield identical validation results."""
        self.engine.register_control("c1", MaxOrderQuantity(limit=1000))
        self.engine.register_control("c2", MaxOrderPrice(limit=500))
        self.engine.set_context({})
        
        # Passing order
        pass_order = self.gen.generate_order(quantity=100, price=400.0)
        seq_passed, seq_results = self.engine.validate_order(pass_order, parallel=False)
        par_passed, par_results = self.engine.validate_order(pass_order, parallel=True)
        
        self.assertEqual(seq_passed, par_passed)
        self.assertEqual(len(seq_results), len(par_results))
        
        # Failing order
        fail_order = self.gen.generate_order(quantity=2000, price=600.0)
        seq_passed_f, _ = self.engine.validate_order(fail_order, parallel=False)
        par_passed_f, _ = self.engine.validate_order(fail_order, parallel=True)
        
        self.assertFalse(seq_passed_f)
        self.assertFalse(par_passed_f)

    def test_parallel_performance_benchmark(self):
        """Benchmark parallel vs sequential execution time for multiple controls."""
        engine = GCEEngine(max_workers=8)
        # Register 5 controls with 5ms latency each
        for i in range(5):
            engine.register_control(f"ctrl_{i}", SlowControl(f"ctrl_{i}", delay_ms=5.0))
        engine.set_context({})
        
        order = self.gen.generate_order(quantity=100, price=440.0)
        
        # Sequential timing (5 controls * 5ms = ~25ms per validation)
        start_seq = time.time()
        for _ in range(10):
            engine.validate_order(order, parallel=False)
        seq_time = time.time() - start_seq

        # Parallel timing (5 controls run concurrently in ~5ms total per validation)
        start_par = time.time()
        for _ in range(10):
            engine.validate_order(order, parallel=True)
        par_time = time.time() - start_par

        engine.shutdown()

        self.assertLess(par_time, seq_time, "Parallel control execution should be faster than sequential")
        print(f"\n[Performance Benchmark]")
        print(f"  Sequential execution (10 runs, 5 controls): {seq_time*1000:.2f}ms")
        print(f"  Parallel execution   (10 runs, 5 controls): {par_time*1000:.2f}ms")
        print(f"  Speedup factor: {seq_time/par_time:.2f}x")


if __name__ == "__main__":
    unittest.main()
