"""Example Usage - Complete demonstration of GCE system."""

import sys
from gce.engine import GCEEngine
from gce.controls.quantity_control import MaxOrderQuantity
from gce.controls.price_control import MaxOrderPrice
from gce.logger import GCELogger
from gce.cache.order_cache import Order
from utils.order_generator import MockOrderGenerator
from utils.price_updater import PriceUpdater
from gce.cache.price_cache import PriceCache


def example_basic_validation():
    """Example 1: Basic order validation."""
    print("\n" + "="*70)
    print("EXAMPLE 1: Basic Order Validation")
    print("="*70)
    
    # Initialize engine
    engine = GCEEngine()
    
    # Register controls
    engine.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))
    engine.register_control("MaxOrderPrice", MaxOrderPrice(limit=500))
    
    # Set context
    engine.set_context({})
    
    # Create test order
    order = Order(
        order_id="ORD_001",
        ric="0700.HK",
        symbol="0700.HK",
        quantity=100,
        price=440.0,
        side="B",
        order_type="LMT",
        trader="Waleed",
        account="APAC_EQTY_CASH",
        client="TestClient",
        desk="Equity_apac"
    )
    
    print(f"\nValidating Order: {order}")
    
    # Validate
    passed, results = engine.validate_order(order, is_new=True)
    
    print(f"\nValidation Result: {'APPROVED' if passed else 'REJECTED'}")
    for result in results:
        print(f"  {result}")
    
    return passed


def example_rejection_scenarios():
    """Example 2: Orders that get rejected."""
    print("\n" + "="*70)
    print("EXAMPLE 2: Rejection Scenarios")
    print("="*70)
    
    engine = GCEEngine()
    engine.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))
    engine.register_control("MaxOrderPrice", MaxOrderPrice(limit=500))
    engine.set_context({})
    
    gen = MockOrderGenerator()
    
    # Test cases
    test_cases = {
        "Oversized Quantity": gen.generate_order(symbol="0700.HK", quantity=5000, price=440.0),
        "Oversized Price": gen.generate_order(symbol="0700.HK", quantity=100, price=1500.0),
        "Valid Order": gen.generate_order(symbol="0700.HK", quantity=100, price=440.0),
    }
    
    for test_name, order in test_cases.items():
        passed, results = engine.validate_order(order, is_new=True)
        
        status = "✓ PASSED" if passed else "✗ REJECTED"
        print(f"\n{test_name}: {status}")
        
        for result in results:
            status_icon = "✓" if result.passed else "✗"
            print(f"  {status_icon} {result.control_name}: {result.message}")


def example_batch_validation():
    """Example 3: Batch order validation."""
    print("\n" + "="*70)
    print("EXAMPLE 3: Batch Order Validation")
    print("="*70)
    
    engine = GCEEngine()
    engine.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))
    engine.register_control("MaxOrderPrice", MaxOrderPrice(limit=500))
    engine.set_context({})
    
    gen = MockOrderGenerator(seed=42)
    
    # Generate 10 random orders
    orders = gen.generate_orders(count=10)
    
    print(f"\nValidating {len(orders)} orders...")
    
    approved = 0
    rejected = 0
    
    for order in orders:
        passed, results = engine.validate_order(order)
        if passed:
            approved += 1
        else:
            rejected += 1
    
    print(f"\nResults:")
    print(f"  Approved: {approved}")
    print(f"  Rejected: {rejected}")
    print(f"  Approval Rate: {(approved/len(orders)*100):.1f}%")


def example_with_logging():
    """Example 4: Order validation with structured logging."""
    print("\n" + "="*70)
    print("EXAMPLE 4: Order Validation with Logging")
    print("="*70)
    
    # Initialize logger
    logger = GCELogger(console=True, file=False)
    
    # Create engine
    engine = GCEEngine()
    engine.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))
    engine.register_control("MaxOrderPrice", MaxOrderPrice(limit=500))
    engine.set_context({})
    
    # Create orders
    gen = MockOrderGenerator()
    
    print("\nValidating Orders with Logging:")
    
    # Valid order
    logger.lmt_check_start()
    logger.lmt_check_new()
    
    order = gen.generate_order(quantity=100, price=440.0)
    passed, results = engine.validate_order(order)
    
    for result in results:
        if result.passed:
            logger.control_passed(result.control_name, result.limit_value, result.order_value)
        else:
            logger.control_failed(result.control_name, result.limit_value, result.order_value, result.message)
    
    logger.lmt_check_summary(len(results), sum(1 for r in results if r.passed), 
                            sum(1 for r in results if not r.passed))
    logger.lmt_check_over(0.001)
    
    print(f"\n✓ Order validation complete. Check logs/GCE.log for details.")


def example_custom_controls():
    """Example 5: Creating and using custom controls."""
    print("\n" + "="*70)
    print("EXAMPLE 5: Custom Control - Maximum Notional Value")
    print("="*70)
    
    from gce.controls.base_control import BaseControl
    from typing import Dict, Any, Tuple
    
    class MaxNotionalValue(BaseControl):
        """Control: Maximum notional value (qty * price)."""
        
        def __init__(self, limit: float):
            super().__init__("MaxNotionalValue", limit)
        
        def validate(self, order: Order, context: Dict[str, Any]) -> Tuple[bool, str, Any, Any]:
            notional = order.quantity * order.price
            limit = self.limit
            
            if notional <= limit:
                return (True, f"Notional OK", limit, notional)
            else:
                return (False, f"Notional too high", limit, notional)
    
    # Create engine with custom control
    engine = GCEEngine()
    engine.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))
    engine.register_control("MaxOrderPrice", MaxOrderPrice(limit=500))
    engine.register_control("max_notional", MaxNotionalValue(limit=100000))
    engine.set_context({})
    
    gen = MockOrderGenerator()
    
    # Test order
    order = gen.generate_order(quantity=500, price=200.0)  # Notional = 100,000
    
    passed, results = engine.validate_order(order)
    
    print(f"\nOrder: {order.quantity} @ {order.price} (Notional: {order.quantity * order.price})")
    print(f"Result: {'APPROVED' if passed else 'REJECTED'}\n")
    
    for result in results:
        status = "✓" if result.passed else "✗"
        print(f"  {status} {result.control_name}: {result.message}")
        print(f"     LMT={result.limit_value}, ORD={result.order_value}")


def example_performance_benchmark():
    """Example 6: Performance benchmarking."""
    print("\n" + "="*70)
    print("EXAMPLE 6: Performance Benchmark")
    print("="*70)
    
    import time
    
    engine = GCEEngine()
    engine.register_control("MaxOrderQuantity", MaxOrderQuantity(limit=1000))
    engine.register_control("MaxOrderPrice", MaxOrderPrice(limit=500))
    engine.set_context({})
    
    gen = MockOrderGenerator(seed=42)
    
    # Generate test orders
    test_sizes = [100, 500, 1000, 5000]
    
    print("\nThroughput Benchmark:")
    print(f"{'Order Count':<15} {'Time (sec)':<15} {'Orders/sec':<15} {'Avg (ms)':<15}")
    print("-" * 60)
    
    for count in test_sizes:
        orders = gen.generate_orders(count=count)
        
        start = time.time()
        for order in orders:
            engine.validate_order(order)
        elapsed = time.time() - start
        
        throughput = count / elapsed
        avg_ms = (elapsed / count) * 1000
        
        print(f"{count:<15} {elapsed:<15.3f} {throughput:<15.0f} {avg_ms:<15.2f}")


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("GCE (Global Compliance Engine) - COMPREHENSIVE EXAMPLES")
    print("="*70)
    
    try:
        example_basic_validation()
        example_rejection_scenarios()
        example_batch_validation()
        example_with_logging()
        example_custom_controls()
        example_performance_benchmark()
        
        print("\n" + "="*70)
        print("ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
