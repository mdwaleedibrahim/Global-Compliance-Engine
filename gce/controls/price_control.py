"""Maximum Order Price Control"""

from typing import Tuple, Any, Dict
from gce.controls.base_control import BaseControl


class MaxOrderPrice(BaseControl):
    """Control: Maximum allowed order price"""
    
    def __init__(self, limit: float):
        """
        Initialize Max Order Price control.
        
        Args:
            limit: Maximum allowed order price
        """
        super().__init__("MaxOrderPrice", limit)
    
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, Any, Any]:
        """
        Validate order price against limit.
        
        Validation Rules:
        - Pass: ORD <= LMT
        - Fail: ORD > LMT
        
        Args:
            order: Order to validate
            context: Context dict with caches
            
        Returns:
            (passed: bool, message: str, limit: float, order_price: float)
        """
        order_price = order.price or 0.0
        limit = self.limit
        
        if order_price <= limit:
            return (True, f"Order price OK: {order_price} <= {limit}", limit, order_price)
        else:
            msg = f"Order price is too big, LMT={limit}, ORD={order_price}"
            return (False, msg, limit, order_price)
