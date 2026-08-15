"""Maximum Order Price Control"""

from typing import Tuple, Any, Dict
from gce.controls.base_control import BaseControl


class MaxOrderPrice(BaseControl):
    """Control: Maximum allowed order price"""
    
    def __init__(self, limit: float = 0.0):
        """
        Initialize Max Order Price control.
        
        Args:
            limit: Configured fallback limit when datamgr is not provided in context.
        """
        super().__init__("MaxOrderPrice", float(limit))
    
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, float, float]:
        """
        Validate order price against limit.
        
        LMT is always taken from MaxOrderPrice in datamgr RMS limits when datamgr is present.
        """
        order_price = float(getattr(order, 'price', 0.0) or 0.0)

        datamgr = context.get('datamgr') if context else None
        if datamgr and hasattr(datamgr, 'get_matching_limits'):
            matched = datamgr.get_matching_limits(order)
            limit = float(matched.get('MaxOrderPrice', 0.0) or 0.0)
            if limit == 0.0 and self.limit > 0.0:
                limit = float(self.limit)
        else:
            limit = float(self.limit)

        if limit == 0.0:
            return (True, "Control MaxOrderPrice disabled (LMT=0)", 0.0, order_price)
        
        if order_price <= limit:
            return (True, f"Order price OK: ORD={order_price} <= LMT={limit}", limit, order_price)
        else:
            return (False, f"Order price is too big, ORD={order_price} > LMT={limit}", limit, order_price)
