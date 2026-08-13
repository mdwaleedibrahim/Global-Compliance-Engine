"""Distributed Validation - Horizontal scaling and cluster routing for GCE engines."""

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from gce.engine import GCEEngine
from gce.cache.order_cache import Order, OrderStatus
from gce.controls.base_control import ControlExecution


class LoadBalancingStrategy(Enum):
    """Load balancing strategies for routing order validations across cluster nodes."""
    ROUND_ROBIN = "ROUND_ROBIN"
    LEAST_BUSY = "LEAST_BUSY"
    SYMBOL_HASH = "SYMBOL_HASH"


class ValidatorNode:
    """Represents a single validator node in the distributed GCE cluster."""

    def __init__(self, node_id: str, engine: Optional[GCEEngine] = None):
        """
        Initialize a cluster validator node.
        
        Args:
            node_id: Unique identifier for the node
            engine: GCEEngine instance running on this node
        """
        self.node_id = node_id
        self.engine = engine or GCEEngine()
        self.active_requests = 0
        self.total_requests = 0
        self.passed_requests = 0
        self.failed_requests = 0
        self._lock = threading.Lock()

    def validate_order(self, order: Order, is_new: bool = True,
                       stop_on_fail: bool = False, parallel: bool = True) -> Tuple[bool, List[ControlExecution]]:
        """
        Execute order validation on this worker node.
        """
        with self._lock:
            self.active_requests += 1
            self.total_requests += 1

        try:
            passed, results = self.engine.validate_order(
                order, is_new=is_new, stop_on_fail=stop_on_fail, parallel=parallel
            )
            with self._lock:
                if passed:
                    self.passed_requests += 1
                else:
                    self.failed_requests += 1
            return passed, results
        finally:
            with self._lock:
                self.active_requests -= 1

    def get_stats(self) -> Dict[str, Any]:
        """Get performance statistics for this node."""
        with self._lock:
            return {
                "node_id": self.node_id,
                "active_requests": self.active_requests,
                "total_requests": self.total_requests,
                "passed_requests": self.passed_requests,
                "failed_requests": self.failed_requests,
                "registered_controls": len(self.engine.registry)
            }

    def shutdown(self):
        """Shutdown engine worker threads on this node."""
        if hasattr(self.engine, 'shutdown'):
            self.engine.shutdown()


class DistributedValidationRouter:
    """
    Router and orchestrator for horizontally scaling GCE validation across multiple worker nodes.
    """

    def __init__(self, strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN, max_cluster_workers: int = 16):
        """
        Initialize DistributedValidationRouter.
        
        Args:
            strategy: Routing strategy for load balancing
            max_cluster_workers: Thread pool size for cluster-wide async batch execution
        """
        self.strategy = strategy
        self.nodes: Dict[str, ValidatorNode] = {}
        self.node_keys: List[str] = []
        self._rr_index = 0
        self._lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_cluster_workers, thread_name_prefix="GCEClusterWorker")

    def register_node(self, node_id: str, engine: Optional[GCEEngine] = None) -> ValidatorNode:
        """
        Register a new validator node in the cluster (Horizontal Scaling).
        """
        with self._lock:
            if node_id in self.nodes:
                return self.nodes[node_id]
            node = ValidatorNode(node_id=node_id, engine=engine)
            self.nodes[node_id] = node
            self.node_keys.append(node_id)
            return node

    def unregister_node(self, node_id: str) -> bool:
        """
        Unregister a validator node from the cluster.
        """
        with self._lock:
            if node_id in self.nodes:
                node = self.nodes.pop(node_id)
                self.node_keys.remove(node_id)
                node.shutdown()
                return True
            return False

    def select_node(self, order: Optional[Order] = None) -> ValidatorNode:
        """
        Select a node based on the configured load balancing strategy.
        """
        with self._lock:
            if not self.nodes:
                raise RuntimeError("No active validator nodes available in cluster")

            if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
                node_id = self.node_keys[self._rr_index % len(self.node_keys)]
                self._rr_index += 1
                return self.nodes[node_id]

            elif self.strategy == LoadBalancingStrategy.LEAST_BUSY:
                # Find node with minimum active requests
                best_node = min(self.nodes.values(), key=lambda n: n.active_requests)
                return best_node

            elif self.strategy == LoadBalancingStrategy.SYMBOL_HASH:
                symbol = order.symbol if order else "DEFAULT"
                hash_val = int(hashlib.md5(symbol.encode('utf-8')).hexdigest(), 16)
                node_id = self.node_keys[hash_val % len(self.node_keys)]
                return self.nodes[node_id]

            # Default fallback
            return self.nodes[self.node_keys[0]]

    def validate_order(self, order: Order, is_new: bool = True,
                       stop_on_fail: bool = False, parallel: bool = True) -> Tuple[bool, List[ControlExecution], str]:
        """
        Route and validate a single order on the selected cluster node.
        
        Returns:
            (passed: bool, execution_results: List[ControlExecution], node_id: str)
        """
        node = self.select_node(order=order)
        passed, results = node.validate_order(order, is_new=is_new, stop_on_fail=stop_on_fail, parallel=parallel)
        return passed, results, node.node_id

    def validate_batch_distributed(self, orders: List[Order], is_new: bool = True,
                                   parallel_per_order: bool = True) -> List[Tuple[Order, bool, List[ControlExecution], str]]:
        """
        Distribute a batch of orders concurrently across the cluster worker nodes.
        
        Returns:
            List of (order, passed, results, node_id) tuples
        """
        if not orders:
            return []

        futures = []
        for order in orders:
            node = self.select_node(order=order)
            future = self.executor.submit(
                node.validate_order, order, is_new, False, parallel_per_order
            )
            futures.append((order, node.node_id, future))

        batch_results = []
        for order, node_id, future in futures:
            passed, results = future.result()
            batch_results.append((order, passed, results, node_id))

        return batch_results

    def get_cluster_stats(self) -> Dict[str, Any]:
        """
        Get aggregated metrics and statistics for the cluster.
        """
        with self._lock:
            nodes_stats = [node.get_stats() for node in self.nodes.values()]
            total_requests = sum(s["total_requests"] for s in nodes_stats)
            passed_requests = sum(s["passed_requests"] for s in nodes_stats)
            failed_requests = sum(s["failed_requests"] for s in nodes_stats)
            active_requests = sum(s["active_requests"] for s in nodes_stats)

            return {
                "total_nodes": len(self.nodes),
                "strategy": self.strategy.value,
                "total_requests": total_requests,
                "passed_requests": passed_requests,
                "failed_requests": failed_requests,
                "active_requests": active_requests,
                "nodes": nodes_stats
            }

    def shutdown(self):
        """Shutdown all cluster nodes and executor threads."""
        with self._lock:
            for node in self.nodes.values():
                node.shutdown()
        self.executor.shutdown(wait=False)
