"""Maximum Order Quantity Control"""

from typing import Tuple, Any, Dict
from gce.controls.base_control import BaseControl


class MaxOrderQuantity(BaseControl):
    """Control: Maximum allowed order quantity"""
    
    def __init__(self, limit: int):
        """
        Initialize Max Order Quantity control.
        
        Args:
            limit: Maximum allowed order quantity
        """
        super().__init__("MaxOrderQuantity", limit)
    
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, Any, Any]:
        """
        Validate order quantity against limit.
        
        Validation Rules:
        - Pass: ORD <= LMT
        - Fail: ORD > LMT
        
        Args:
            order: Order to validate
            context: Context dict with caches
            
        Returns:
            (passed: bool, message: str, limit: int, order_qty: int)
        """
        order_qty = order.quantity
        limit = self.limit
        
        if order_qty <= limit:
            return (True, f"Order quantity OK: {order_qty} <= {limit}", limit, order_qty)
        else:
            msg = f"Order size is too big, LMT={limit}, ORD={order_qty}"
            return (False, msg, limit, order_qty)
