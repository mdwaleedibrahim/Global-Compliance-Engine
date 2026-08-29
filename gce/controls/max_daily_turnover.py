"""Maximum Daily Turnover Control"""

from typing import Any, Dict, Tuple

from gce.controls.base_control import BaseControl


class MaxDailyTurnover(BaseControl):
    """Control: maximum allowed daily turnover for an order key group."""

    def __init__(self, limit: float = 0.0):
        super().__init__("MaxDailyTurnover", float(limit))

    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, float, float]:
        """Validate executed order turnover against the daily limit."""
        order_qty = float(getattr(order, 'quantity', 0) or 0)
        order_price = float(getattr(order, 'price', 0.0) or 0.0)
        order_currency = str(getattr(order, 'currency', 'HKD') or 'HKD')

        # Use the order value as the turnover proxy when no richer context is supplied.
        order_value = order_qty * order_price

        datamgr = context.get('datamgr') if context else None
        if datamgr and hasattr(datamgr, 'get_matching_limits'):
            matched = datamgr.get_matching_limits(order)
            limit = float(matched.get('MaxDailyTurnover', 0.0) or 0.0)
            if limit == 0.0:
                limit = float(matched.get('MaxDailyValue', 0.0) or 0.0)
        else:
            limit = float(self.limit)

        if limit == 0.0:
            return (True, "Control MaxDailyTurnover disabled (LMT=0)", 0.0, order_value)

        if order_value <= limit:
            return (True, f"Daily turnover OK: ORD={order_value} <= LMT={limit} ({order_currency})", limit, order_value)
        return (False, f"Daily turnover is too big, ORD={order_value} > LMT={limit} ({order_currency})", limit, order_value)
