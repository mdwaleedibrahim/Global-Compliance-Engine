"""Maximum Order Quantity Control"""

from typing import Tuple, Any, Dict
from gce.controls.base_control import BaseControl


class MaxOrderQuantity(BaseControl):
    """Control: Maximum allowed order quantity"""
    
    def __init__(self, limit: int = 0):
        """
        Initialize Max Order Quantity control.
        
        Args:
            limit: Configured fallback limit when datamgr is not provided in context.
        """
        super().__init__("MaxOrderQuantity", limit)
    
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, int, int]:
        """
        Validate order quantity against limit.
        
        LMT is always taken from MaxOrderSize in datamgr RMS limits when datamgr is present.
        """
        order_qty = int(getattr(order, 'quantity', 0) or 0)

        datamgr = context.get('datamgr') if context else None
        if datamgr and hasattr(datamgr, 'get_matching_limits'):
            matched = datamgr.get_matching_limits(order)
            limit = int(matched.get('MaxOrderSize', 0) or 0)
        else:
            limit = self.limit

        if limit == 0:
            return (True, "Control MaxOrderQuantity disabled (LMT=0)", 0, order_qty)

        if order_qty <= limit:
            return (True, f"Order quantity OK: ORD={order_qty} <= LMT={limit}", limit, order_qty)
        else:
            return (False, f"Order size is too big, ORD={order_qty} > LMT={limit}", limit, order_qty)
