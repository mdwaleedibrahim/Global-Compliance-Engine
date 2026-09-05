"""Test suite for distributed validation and horizontal scaling in GCE."""

import unittest
from gce.main.distributed import DistributedValidationRouter, ValidatorNode, LoadBalancingStrategy
from gce.main.engine import GCEEngine
from gce.main.controls.quantity_control import MaxOrderQuantity
from gce.main.controls.price_control import MaxOrderPrice
from gce.main.utils.order_generator import MockOrderGenerator


class TestDistributedValidation(unittest.TestCase):
    """Test distributed validation cluster routing, horizontal scaling, and batch execution."""

    def setUp(self):
        self.gen = MockOrderGenerator(seed=42)
        self.router = DistributedValidationRouter(strategy=LoadBalancingStrategy.ROUND_ROBIN)

        # Spin up 3 validator nodes in the cluster
        for i in range(1, 4):
            engine = GCEEngine()
            engine.register_control("max_qty", MaxOrderQuantity(limit=1000))
            engine.register_control("max_price", MaxOrderPrice(limit=500))
            engine.set_context({})
            self.router.register_node(node_id=f"node_{i}", engine=engine)

    def tearDown(self):
        self.router.shutdown()

    def test_round_robin_routing(self):
        """Verify round-robin order distribution across cluster nodes."""
        self.router.strategy = LoadBalancingStrategy.ROUND_ROBIN
        order1 = self.gen.generate_order(symbol="0700.HK", quantity=100, price=400.0)
        order2 = self.gen.generate_order(symbol="9988.HK", quantity=200, price=100.0)
        order3 = self.gen.generate_order(symbol="3690.HK", quantity=300, price=150.0)
        order4 = self.gen.generate_order(symbol="AAPL", quantity=50, price=180.0)

        p1, _, n1 = self.router.validate_order(order1)
        p2, _, n2 = self.router.validate_order(order2)
        p3, _, n3 = self.router.validate_order(order3)
        p4, _, n4 = self.router.validate_order(order4)

        self.assertTrue(p1 and p2 and p3 and p4)
        self.assertEqual(n1, "node_1")
        self.assertEqual(n2, "node_2")
        self.assertEqual(n3, "node_3")
        self.assertEqual(n4, "node_1")  # Wrapped round robin

    def test_symbol_hash_routing(self):
        """Verify symbol hash routing consistently maps same symbol to same node."""
        self.router.strategy = LoadBalancingStrategy.SYMBOL_HASH
        order_a1 = self.gen.generate_order(symbol="0700.HK", quantity=100, price=400.0)
        order_a2 = self.gen.generate_order(symbol="0700.HK", quantity=200, price=410.0)

        _, _, node_a1 = self.router.validate_order(order_a1)
        _, _, node_a2 = self.router.validate_order(order_a2)

        self.assertEqual(node_a1, node_a2, "Orders for same symbol should route to same node")

    def test_distributed_batch_validation(self):
        """Verify concurrent batch validation across cluster nodes."""
        orders = self.gen.generate_orders(count=30)
        batch_results = self.router.validate_batch_distributed(orders)

        self.assertEqual(len(batch_results), 30)
        
        # Verify cluster stats aggregated across nodes
        stats = self.router.get_cluster_stats()
        self.assertEqual(stats["total_nodes"], 3)
        self.assertEqual(stats["total_requests"], 30)
        self.assertGreater(stats["passed_requests"], 0)

    def test_dynamic_horizontal_scaling(self):
        """Test adding and removing nodes dynamically from cluster."""
        initial_nodes = self.router.get_cluster_stats()["total_nodes"]
        self.assertEqual(initial_nodes, 3)

        # Scale out: Add node_4
        engine4 = GCEEngine()
        engine4.register_control("max_qty", MaxOrderQuantity(limit=1000))
        self.router.register_node("node_4", engine4)
        self.assertEqual(self.router.get_cluster_stats()["total_nodes"], 4)

        # Scale in: Unregister node_1
        unregistered = self.router.unregister_node("node_1")
        self.assertTrue(unregistered)
        self.assertEqual(self.router.get_cluster_stats()["total_nodes"], 3)


if __name__ == "__main__":
    unittest.main()
