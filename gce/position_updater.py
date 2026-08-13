"""Position Cache Updater - Updates positions based on order fills."""

from typing import Optional, Dict, Tuple
from gce.cache.position_cache import PositionCache, Position
from gce.cache.order_cache import Order, OrderStatus
from datetime import datetime


class PositionUpdater:
    """Updates position cache when orders are filled."""
    
    def __init__(self, position_cache: PositionCache):
        """
        Initialize position updater.
        
        Args:
            position_cache: PositionCache instance to update
        """
        self.position_cache = position_cache
    
    def update_position_from_order(self, order: Order, filled_qty: int) -> Tuple[bool, str]:
        """
        Update position based on order execution.
        
        Args:
            order: Order object with fill information
            filled_qty: Quantity that was filled
            
        Returns:
            (success: bool, message: str)
        """
        if filled_qty <= 0:
            return False, "Fill quantity must be positive"
        
        if filled_qty > order.quantity:
            return False, f"Fill qty {filled_qty} exceeds order qty {order.quantity}"
        
        # Get or create position
        position = self.position_cache.get_position(order.symbol, order.trader)
        if not position:
            position = self._create_position_from_order(order)
            self.position_cache.add_position(order.symbol, position)
        
        # Update position based on side
        success, msg = self._apply_fill(position, order.side, filled_qty, order.price)
        
        if success:
            self.position_cache.save_to_csv("cache/PositionsCache.csv")
        
        return success, msg
    
    def _create_position_from_order(self, order: Order) -> Position:
        """Create new position from order."""
        return Position(
            symbol=order.symbol,
            ric=order.ric if hasattr(order, 'ric') else order.symbol,
            trader=order.trader,
            account=order.account,
            client=order.client,
            desk=order.desk
        )
    
    def _apply_fill(self, position: Position, side: str, qty: int, price: float) -> Tuple[bool, str]:
        """Apply fill to position."""
        try:
            if side.upper() == 'B':
                # Update buy side
                position.buy_volume += qty
                position.buy_value += qty * price
                position.buy_open += qty
                position.buy_open_value += qty * price
                
                # Calculate USD values
                xr = position.xr or 1.0
                position.buy_value_usd = position.buy_value * xr
                position.buy_open_value_usd = position.buy_open_value * xr
                
                msg = f"BUY: Added {qty} @ {price}, net_qty={position.net_quantity()}"
                
            elif side.upper() == 'S':
                # Update sell side
                position.sell_volume += qty
                position.sell_value += qty * price
                position.sell_open += qty
                position.sell_open_value += qty * price
                
                # Calculate USD values
                xr = position.xr or 1.0
                position.sell_value_usd = position.sell_value * xr
                position.sell_open_value_usd = position.sell_open_value * xr
                
                msg = f"SELL: Added {qty} @ {price}, net_qty={position.net_quantity()}"
            else:
                return False, f"Invalid side: {side}"
            
            position.timestamp = datetime.now().isoformat()
            return True, msg
            
        except Exception as e:
            return False, f"Error applying fill: {str(e)}"
    
    def reconcile_position(self, symbol: str, trader: str, 
                          expected_qty: int, expected_value: float) -> Tuple[bool, Dict]:
        """
        Reconcile position against expected values.
        
        Args:
            symbol: Instrument symbol
            trader: Trader name
            expected_qty: Expected net quantity
            expected_value: Expected net value
            
        Returns:
            (reconciled: bool, details: dict)
        """
        position = self.position_cache.get_position(symbol, trader)
        if not position:
            return False, {"error": f"Position not found for {symbol}/{trader}"}
        
        actual_qty = position.net_quantity()
        actual_value = position.net_value()
        
        qty_match = actual_qty == expected_qty
        value_match = abs(actual_value - expected_value) < 0.01  # Allow small rounding
        
        details = {
            "symbol": symbol,
            "trader": trader,
            "qty_match": qty_match,
            "actual_qty": actual_qty,
            "expected_qty": expected_qty,
            "qty_variance": actual_qty - expected_qty,
            "value_match": value_match,
            "actual_value": actual_value,
            "expected_value": expected_value,
            "value_variance": actual_value - expected_value,
            "status": "RECONCILED" if (qty_match and value_match) else "VARIANCE DETECTED"
        }
        
        return qty_match and value_match, details
