"""Position Reconciler - Reconciles positions with orders and market data."""

from typing import Dict, List, Tuple, Optional
from gce.cache.order_cache import OrderCache, Order, OrderStatus
from gce.cache.position_cache import PositionCache, Position
from dataclasses import dataclass
from datetime import datetime


@dataclass
class ReconciliationReport:
    """Reconciliation report data."""
    timestamp: str
    symbol: str
    trader: str
    account: str
    
    # Order metrics
    total_orders: int
    live_orders: int
    filled_orders: int
    total_order_qty: int
    total_filled_qty: int
    
    # Position metrics
    position_exists: bool
    net_quantity: int
    net_value: float
    buy_exposure: float
    sell_exposure: float
    
    # Reconciliation results
    qty_variance: int
    value_variance: float
    status: str  # MATCH, VARIANCE, MISSING_POSITION
    issues: List[str]


class PositionReconciler:
    """Reconciles positions against orders."""
    
    def __init__(self, order_cache: OrderCache, position_cache: PositionCache):
        """
        Initialize reconciler.
        
        Args:
            order_cache: OrderCache instance
            position_cache: PositionCache instance
        """
        self.order_cache = order_cache
        self.position_cache = position_cache
    
    def reconcile_symbol(self, symbol: str, trader: str = None) -> ReconciliationReport:
        """
        Reconcile position for a symbol.
        
        Args:
            symbol: Instrument symbol
            trader: Optional trader filter
            
        Returns:
            ReconciliationReport
        """
        # Get orders
        orders = self.order_cache.get_orders_by_symbol(symbol)
        if trader:
            orders = [o for o in orders if o.trader == trader]
        
        # Get position
        if trader:
            position = self.position_cache.get_position(symbol, trader)
        else:
            position = self.position_cache.get_position(symbol)
        
        # Calculate order-based metrics
        live_orders = [o for o in orders if o.status == OrderStatus.LIVE]
        filled_orders = [o for o in orders if o.status in (OrderStatus.FILL, OrderStatus.PARTIAL_FILL)]
        
        total_buy_qty = sum(o.quantity for o in orders if o.side == 'B')
        total_sell_qty = sum(o.quantity for o in orders if o.side == 'S')
        total_filled_buy = sum(o.filled for o in filled_orders if o.side == 'B')
        total_filled_sell = sum(o.filled for o in filled_orders if o.side == 'S')
        
        order_net_qty = (total_buy_qty - total_filled_buy) - (total_sell_qty - total_filled_sell)
        
        # Get position metrics
        position_exists = position is not None
        pos_net_qty = position.net_quantity() if position_exists else 0
        pos_net_value = position.net_value() if position_exists else 0.0
        
        # Calculate variance
        qty_variance = order_net_qty - pos_net_qty
        value_variance = 0.0  # TODO: calculate based on market prices
        
        # Determine status
        issues = []
        if not position_exists and (total_buy_qty > 0 or total_sell_qty > 0):
            issues.append("Position cache missing for symbol with active orders")
            status = "MISSING_POSITION"
        elif qty_variance != 0:
            issues.append(f"Quantity variance: order_qty={order_net_qty}, pos_qty={pos_net_qty}")
            status = "VARIANCE"
        else:
            status = "MATCH"
        
        report = ReconciliationReport(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            trader=trader or "ALL",
            account=orders[0].account if orders else "UNKNOWN",
            total_orders=len(orders),
            live_orders=len(live_orders),
            filled_orders=len(filled_orders),
            total_order_qty=total_buy_qty + total_sell_qty,
            total_filled_qty=total_filled_buy + total_filled_sell,
            position_exists=position_exists,
            net_quantity=pos_net_qty,
            net_value=pos_net_value,
            buy_exposure=position.buy_exposure if position_exists else 0.0,
            sell_exposure=position.sell_exposure if position_exists else 0.0,
            qty_variance=qty_variance,
            value_variance=value_variance,
            status=status,
            issues=issues
        )
        
        return report
    
    def reconcile_all(self) -> List[ReconciliationReport]:
        """Reconcile all positions."""
        reports = []
        
        # Get all unique symbols
        symbols = set()
        for order in self.order_cache.get_all_orders():
            symbols.add(order.symbol)
        
        for symbol in symbols:
            report = self.reconcile_symbol(symbol)
            reports.append(report)
        
        return reports
    
    def get_reconciliation_summary(self, reports: List[ReconciliationReport]) -> Dict:
        """Get summary of reconciliation reports."""
        total = len(reports)
        matched = len([r for r in reports if r.status == "MATCH"])
        variance = len([r for r in reports if r.status == "VARIANCE"])
        missing = len([r for r in reports if r.status == "MISSING_POSITION"])
        
        total_qty_variance = sum(abs(r.qty_variance) for r in reports)
        total_value_variance = sum(abs(r.value_variance) for r in reports)
        
        return {
            "total_positions": total,
            "matched": matched,
            "variance": variance,
            "missing": missing,
            "match_rate": f"{(matched/total*100):.2f}%" if total > 0 else "0%",
            "total_qty_variance": total_qty_variance,
            "total_value_variance": total_value_variance,
            "status": "OK" if variance == 0 and missing == 0 else "ISSUES DETECTED"
        }
    
    def print_report(self, report: ReconciliationReport):
        """Print reconciliation report."""
        print(f"\n{'='*70}")
        print(f"RECONCILIATION REPORT - {report.timestamp}")
        print(f"{'='*70}")
        print(f"Symbol: {report.symbol} | Trader: {report.trader} | Account: {report.account}")
        print(f"-"*70)
        print(f"Orders:     Total={report.total_orders}, Live={report.live_orders}, Filled={report.filled_orders}")
        print(f"Order Qty:  Total={report.total_order_qty}, Filled={report.total_filled_qty}")
        print(f"Position:   Exists={report.position_exists}, Net_Qty={report.net_quantity}, Net_Val={report.net_value:.2f}")
        print(f"Variance:   Qty={report.qty_variance}, Value={report.value_variance:.2f}")
        print(f"Status:     {report.status}")
        if report.issues:
            print(f"Issues:")
            for issue in report.issues:
                print(f"  - {issue}")
        print(f"{'='*70}")
