"""Close Price Tolerance Control"""

from typing import Tuple, Any, Dict
from gce.controls.base_control import BaseControl
from gce.controls.config_helper import LimitCheckerConfig

SELL_SIDES = {
    "S", "SELL", 
    "SS", "SHORT_SELL", "SHORT SELL", "SHORT-SELL",
    "SSE", "SHORT_SELL_EXEMPT", "SHORT SELL EXEMPT", "SHORT-SELL-EXEMPT"
}


class ClosePriceTolerance(BaseControl):
    """
    Control: Close Price Tolerance (CPT).
    
    Allows order price deviation percentage from Close price up to configured limit size.
    CPT % = abs((Close price - Reference price) / Close price) * 100
    
    LMT value is taken from ClosePriceTolerance in RMS limits (datamgr).
    """

    def __init__(self, limit: float = 0.0):
        super().__init__("ClosePriceTolerance", float(limit))
        self.config_loader = LimitCheckerConfig()

    def _get_reference_price(self, order: Any, price_data: Any) -> float:
        order_type = str(getattr(order, 'order_type', 'LMT') or 'LMT').upper()
        if order_type in ('LMT', 'LIMIT'):
            return float(getattr(order, 'price', 0.0) or 0.0)
        
        if not price_data:
            return float(getattr(order, 'price', 0.0) or 0.0)

        side = str(getattr(order, 'side', 'B') or 'B').upper().strip()
        is_sell = side in SELL_SIDES
        hierarchy = ["bid", "last", "open_price", "close"] if is_sell else ["ask", "last", "open_price", "close"]

        for field in hierarchy:
            val = None
            if hasattr(price_data, field):
                val = getattr(price_data, field)
            elif isinstance(price_data, dict):
                val = price_data.get(field) or price_data.get(field.capitalize())
            if val is not None:
                try:
                    f_val = float(val)
                    if f_val > 0:
                        return f_val
                except (ValueError, TypeError):
                    pass

        return float(getattr(order, 'price', 0.0) or 0.0)

    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, float, float]:
        datamgr = context.get('datamgr') if context else None
        if datamgr and hasattr(datamgr, 'get_matching_limits'):
            matched = datamgr.get_matching_limits(order)
            limit = float(matched.get('ClosePriceTolerance', 0.0) or 0.0)
            if limit == 0.0 and self.limit > 0.0:
                limit = float(self.limit)
        else:
            limit = float(self.limit)

        if limit == 0.0:
            return (True, "Control ClosePriceTolerance disabled (LMT=0)", 0.0, 0.0)

        symbol = getattr(order, 'symbol', '') or getattr(order, 'ric', '')
        prices = context.get('prices') or context.get('price_cache')
        price_data = None
        if prices:
            if hasattr(prices, 'get_price'):
                price_data = prices.get_price(symbol)
            elif isinstance(prices, dict):
                price_data = prices.get(symbol)

        close_price = 0.0
        if price_data:
            if hasattr(price_data, 'close'):
                close_price = float(getattr(price_data, 'close', 0.0) or 0.0)
            elif isinstance(price_data, dict):
                close_price = float(price_data.get('Close', price_data.get('close', 0.0)) or 0.0)

        # Exception handling for missing Close price
        if close_price <= 0.0:
            config = context.get('config') or self.config_loader
            action = config.get('invalid_close_price_action', 'ignore').lower() if hasattr(config, 'get') else 'ignore'
            if action == 'reject':
                return (False, "Close price is missing", limit, 0.0)
            else:
                return (True, "Close price is missing", limit, 0.0)

        ref_price = self._get_reference_price(order, price_data)
        ord_pct = abs((close_price - ref_price) / close_price) * 100.0

        if ord_pct <= limit:
            return (True, f"Close Price Tolerance OK: ORD={ord_pct:.2f}% <= LMT={limit}%", limit, ord_pct)
        else:
            msg = f"Close Price Tolerance exceeds limit, LMT={limit}, ORD={ord_pct:.2f}"
            return (False, msg, limit, ord_pct)
