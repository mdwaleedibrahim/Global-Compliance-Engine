"""Last Price Tolerance Control"""

from typing import Tuple, Any, Dict
from gce.controls.base_control import BaseControl
from gce.controls.config_helper import LimitCheckerConfig

SELL_SIDES = {
    "S", "SELL", 
    "SS", "SHORT_SELL", "SHORT SELL", "SHORT-SELL",
    "SSE", "SHORT_SELL_EXEMPT", "SHORT SELL EXEMPT", "SHORT-SELL-EXEMPT"
}


class LastPriceTolerance(BaseControl):
    """
    Control: Last Price Tolerance (LPT).
    
    Allows order price deviation percentage from Last price up to configured limit size.
    LPT % = abs((Last price - Reference price) / Last price) * 100
    
    LMT value is taken from LastPriceTolerance in RMS limits (datamgr).
    Supports price field override per exchange session (lpt_xsession1, lpt_xsession2, etc.).
    """

    def __init__(self, limit: float = 0.0):
        super().__init__("LastPriceTolerance", float(limit))
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

    def _get_target_last_price(self, order: Any, price_data: Any, datamgr: Any, config: Any) -> float:
        if not price_data:
            return 0.0

        exchange = getattr(order, 'exchange', '') or getattr(order, 'ric', '')
        session_status = "Xsession1"
        if datamgr and hasattr(datamgr, 'get_session_status'):
            time_arg = getattr(order, 'time', None) or getattr(order, 'timestamp', None)
            session_status = datamgr.get_session_status(exchange, time_arg)

        # Extract session key e.g. Xsession1 -> lpt_xsession1
        sess_key = "lpt_xsession1"
        if "session" in session_status.lower():
            for num in ("1", "2", "3", "4", "5"):
                if num in session_status:
                    sess_key = f"lpt_xsession{num}"
                    break

        field_name = config.get(sess_key, "last").lower().strip() if hasattr(config, 'get') else "last"

        # Attribute lookup order for configured field name
        possible_attrs = [field_name]
        if field_name == "open":
            possible_attrs = ["open_price", "open", "Open"]
        elif field_name in ("last", "close", "bid", "ask", "mid"):
            possible_attrs = [field_name, field_name.capitalize(), field_name.upper()]
        else:
            possible_attrs = [field_name, field_name.capitalize(), field_name.upper(), f"{field_name}_price"]

        for attr in possible_attrs:
            if hasattr(price_data, attr):
                val = getattr(price_data, attr)
                if val is not None and float(val or 0.0) > 0:
                    return float(val)
            elif isinstance(price_data, dict):
                if attr in price_data and price_data[attr] is not None and float(price_data[attr] or 0.0) > 0:
                    return float(price_data[attr])

        return 0.0

    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, float, float]:
        datamgr = context.get('datamgr') if context else None
        if datamgr and hasattr(datamgr, 'get_matching_limits'):
            matched = datamgr.get_matching_limits(order)
            limit = float(matched.get('LastPriceTolerance', 0.0) or 0.0)
        else:
            limit = self.limit

        if limit == 0.0:
            return (True, "Control LastPriceTolerance disabled (LMT=0)", 0.0, 0.0)

        config = context.get('config') or self.config_loader
        symbol = getattr(order, 'symbol', '') or getattr(order, 'ric', '')
        prices = context.get('prices') or context.get('price_cache')
        price_data = None
        if prices:
            if hasattr(prices, 'get_price'):
                price_data = prices.get_price(symbol)
            elif isinstance(prices, dict):
                price_data = prices.get(symbol)

        target_last_price = self._get_target_last_price(order, price_data, datamgr, config)

        # Exception handling for missing Last price
        if target_last_price <= 0.0:
            action = config.get('invalid_last_price_action', 'ignore').lower() if hasattr(config, 'get') else 'ignore'
            if action == 'reject':
                return (False, "Last price is missing", limit, 0.0)
            else:
                return (True, "Last price is missing", limit, 0.0)

        ref_price = self._get_reference_price(order, price_data)
        ord_pct = abs((target_last_price - ref_price) / target_last_price) * 100.0

        if ord_pct <= limit:
            return (True, f"Last Price Tolerance OK: ORD={ord_pct:.2f}% <= LMT={limit}%", limit, ord_pct)
        else:
            msg = f"Last Price Tolerance exceeds limit, LMT={limit}, ORD={ord_pct:.2f}"
            return (False, msg, limit, ord_pct)
