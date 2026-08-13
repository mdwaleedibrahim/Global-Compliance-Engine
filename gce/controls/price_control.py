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
    
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, float, float]:
        """
        Validate order price against limit.
        
        Validation Rules:
        - Pass: ORD <= LMT
        - Fail: ORD > LMT
        
        Args:
            order: Order to validate
            context: Context dict with caches
            
        Returns:
            (passed: bool, message: str, order_price: float, limit: float)
        """
        order_price = order.price or 0.0
        limit = self.limit
        
        if order_price <= limit:
            return (True, f"Order price OK: ORD={order_price} <= LMT={limit}", order_price, limit)
        else:
            return (False, f"Order price is too big, ORD={order_price} > LMT={limit}", order_price, limit)
