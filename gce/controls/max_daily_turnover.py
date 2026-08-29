"""Maximum Daily Turnover Control"""

from typing import Tuple, Any, Dict, Optional, List
from gce.controls.base_control import BaseControl


class MaxDailyTurnover(BaseControl):
    """
    Control: Maximum allowed gross daily turnover (total traded value of Buys and Sells).
    
    Allows gross daily turnover up to configured limit size (LMT).
    Order Consideration = Order Quantity * Reference Price * FX Rate
    Projected Daily Turnover (ORD) = Current Accumulated Turnover + Order Consideration
    
    Reference price logic:
    - Limit orders: Limit price (order.price)
    - Market orders:
      - Buy side: Ask (Bo) -> Last -> Open -> Close
      - Sell side: Bid (Bb) -> Last -> Open -> Close
      
    FX rate (xr rate):
    - 1.0 if order currency matches limit currency
    - Resolved via context or yfinance / PXFeeder if order currency differs from limit currency
    """
    
    SELL_SIDES = {
        "S", "SELL", 
        "SS", "SHORT_SELL", "SHORT SELL", "SHORT-SELL",
        "SSE", "SHORT_SELL_EXEMPT", "SHORT SELL EXEMPT", "SHORT-SELL-EXEMPT"
    }

    def __init__(self, limit: float = 0.0, limit_currency: str = "HKD",
                 price_hierarchy_buy: Optional[List[str]] = None,
                 price_hierarchy_sell: Optional[List[str]] = None):
        super().__init__("MaxDailyTurnover", float(limit))
        self.limit_currency = limit_currency.upper()
        self.price_hierarchy_buy = price_hierarchy_buy or ["ask", "last", "open_price", "close"]
        self.price_hierarchy_sell = price_hierarchy_sell or ["bid", "last", "open_price", "close"]
    
    def _get_reference_price(self, order: Any, context: Dict[str, Any]) -> float:
        """Determine reference price according to order type, side, and market data hierarchy."""
        order_type = str(getattr(order, 'order_type', 'LMT')).upper()
        if order_type in ('LMT', 'LIMIT'):
            return float(getattr(order, 'price', 0.0) or 0.0)
        
        symbol = getattr(order, 'symbol', '') or getattr(order, 'ric', '')
        price_cache = context.get('prices') or context.get('price_cache')
        
        price_data = None
        if price_cache:
            if hasattr(price_cache, 'get_price'):
                price_data = price_cache.get_price(symbol)
            elif isinstance(price_cache, dict):
                price_data = price_cache.get(symbol)
        
        side = str(getattr(order, 'side', 'B')).upper().strip()
        is_sell = side in self.SELL_SIDES
        hierarchy = self.price_hierarchy_sell if is_sell else self.price_hierarchy_buy
        
        if price_data:
            def extract_price_by_field(field: str) -> float:
                if hasattr(price_data, field):
                    val = getattr(price_data, field)
                    if val is not None and float(val) > 0:
                        return float(val)
                elif isinstance(price_data, dict) and field in price_data:
                    val = price_data[field]
                    if val is not None and float(val) > 0:
                        return float(val)
                return 0.0
            
            for field in hierarchy:
                field_lower = field.lower()
                price = 0.0
                if field_lower in ('ask', 'bo', 'best_offer', 'offer'):
                    price = extract_price_by_field('ask') or extract_price_by_field('offer')
                elif field_lower in ('bid', 'bb', 'best_bid'):
                    price = extract_price_by_field('bid')
                elif field_lower == 'last':
                    price = extract_price_by_field('last')
                elif field_lower in ('open', 'open_price'):
                    price = extract_price_by_field('open_price') or extract_price_by_field('open')
                elif field_lower == 'close':
                    price = extract_price_by_field('close')
                
                if price > 0:
                    return price
        
        return float(getattr(order, 'price', 0.0) or 0.0)

    def _get_fx_rate(self, order_currency: str, limit_currency: str, context: Dict[str, Any]) -> float:
        """Resolve FX conversion rate from Order Currency to Limit Currency."""
        order_curr = (order_currency or "HKD").upper().strip()
        limit_curr = (limit_currency or "HKD").upper().strip()
        
        if order_curr == limit_curr:
            return 1.0
            
        pxfeeder = context.get('pxfeeder')
        if pxfeeder and hasattr(pxfeeder, 'get_fx_rate'):
            rate = pxfeeder.get_fx_rate(order_curr, limit_curr)
            if rate and rate > 0:
                return float(rate)
                
        prices = context.get('prices')
        if prices and hasattr(prices, 'get_fx_rate'):
            rate = prices.get_fx_rate(order_curr, limit_curr)
            if rate and rate > 0:
                return float(rate)
                
        return 1.0

    def validate(self, order: Any, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, float, float]:
        """
        Validate if incoming order consideration + current accumulated turnover exceeds the limit.
        """
        context = context or {}
        limit = float(self.limit)
        
        # Limit of 0 means control is disabled for this rule
        if limit <= 0:
            return True, "Control passed (limit disabled)", 0.0, 0.0
            
        rule_limits = context.get('rule_limits') or {}
        limit_currency = rule_limits.get('Currency') or self.limit_currency
        order_currency = getattr(order, 'currency', 'HKD') or 'HKD'
        
        ref_price = self._get_reference_price(order, context)
        quantity = getattr(order, 'quantity', 0) or 0
        fx_rate = self._get_fx_rate(order_currency, limit_currency, context)
        
        order_consideration = quantity * ref_price * fx_rate
        
        # Retrieve accumulated turnover from PositionCache for this rule pattern
        positions_cache = context.get('positions')
        current_turnover = 0.0
        
        if positions_cache:
            if hasattr(positions_cache, 'get_turnover_for_pattern'):
                current_turnover = positions_cache.get_turnover_for_pattern(rule_limits, currency=limit_currency)
            elif hasattr(positions_cache, 'get_position'):
                pos = positions_cache.get_position(rule_limits)
                if pos:
                    current_turnover = pos.gross_turnover()
        
        projected_turnover = current_turnover + order_consideration
        
        if projected_turnover > limit:
            msg = f"Max Daily Turnover exceeds limit, LMT={limit}, ORD={projected_turnover:.2f}"
            return False, msg, limit, projected_turnover
            
        return True, "Control passed", limit, projected_turnover
