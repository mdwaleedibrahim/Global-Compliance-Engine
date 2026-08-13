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
    
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, int, int]:
        """
        Validate order quantity against limit.
        
        Validation Rules:
        - Pass: ORD <= LMT
        - Fail: ORD > LMT
        
        Args:
            order: Order to validate
            context: Context dict with caches
            
        Returns:
            (passed: bool, message: str, value: int, limit: int)
        """
        order_qty = order.quantity
        limit = self.limit
        
        if order_qty <= limit:
            return (True, f"Order quantity OK: ORD={order_qty} <= LMT={limit}", order_qty, limit)
        else:
            return (False, f"Order size is too big, ORD={order_qty} > LMT={limit}", order_qty, limit)
