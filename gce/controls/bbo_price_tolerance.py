"""BBO Price Tolerance Control"""

from typing import Tuple, Any, Dict
from gce.controls.base_control import BaseControl
from gce.controls.config_helper import LimitCheckerConfig

SELL_SIDES = {
    "S", "SELL", 
    "SS", "SHORT_SELL", "SHORT SELL", "SHORT-SELL",
    "SSE", "SHORT_SELL_EXEMPT", "SHORT SELL EXEMPT", "SHORT-SELL-EXEMPT"
}


class BBOPriceTolerance(BaseControl):
    """
    Control: BBO Price Tolerance (BBOPT).
    
    Allows order price deviation percentage from Best Bid / Best Offer (Ask) price up to configured limit size.
    For Buy: BBO % = abs((Ask price - Reference price) / Ask price) * 100
    For Sell: BBO % = abs((Bid price - Reference price) / Bid price) * 100
    
    LMT value is taken from BBOPriceTolerance in RMS limits (datamgr).
    """

    def __init__(self, limit: float = 0.0):
        super().__init__("BBOPriceTolerance", float(limit))
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
            limit = float(matched.get('BBOPriceTolerance', 0.0) or 0.0)
        else:
            limit = float(self.limit)

        if limit == 0.0:
            return (True, "Control BBOPriceTolerance disabled (LMT=0)", 0.0, 0.0)

        config = context.get('config') or self.config_loader
        symbol = getattr(order, 'symbol', '') or getattr(order, 'ric', '')
        prices = context.get('prices') or context.get('price_cache')
        price_data = None
        if prices:
            if hasattr(prices, 'get_price'):
                price_data = prices.get_price(symbol)
            elif isinstance(prices, dict):
                price_data = prices.get(symbol)

        side = str(getattr(order, 'side', 'B') or 'B').upper().strip()
        is_sell = side in SELL_SIDES

        bbo_price = 0.0
        if price_data:
            field = "bid" if is_sell else "ask"
            dict_key = "Bid" if is_sell else "Ask"
            if hasattr(price_data, field):
                bbo_price = float(getattr(price_data, field, 0.0) or 0.0)
            elif isinstance(price_data, dict):
                bbo_price = float(price_data.get(dict_key, price_data.get(field, 0.0)) or 0.0)

        # Exception handling for missing BBO price
        if bbo_price <= 0.0:
            action = config.get('invalid_bbo_price_action', 'reject').lower() if hasattr(config, 'get') else 'reject'
            if action == 'reject':
                return (False, "BBO price is missing", limit, 0.0)
            else:
                return (True, "BBO price is missing", limit, 0.0)

        ref_price = self._get_reference_price(order, price_data)
        ord_pct = abs((bbo_price - ref_price) / bbo_price) * 100.0

        if ord_pct <= limit:
            return (True, f"BBO Price Tolerance OK: ORD={ord_pct:.2f}% <= LMT={limit}%", limit, ord_pct)
        else:
            msg = f"BBO Price Tolerance exceeds limit, LMT={limit}, ORD={ord_pct:.2f}"
            return (False, msg, limit, ord_pct)
