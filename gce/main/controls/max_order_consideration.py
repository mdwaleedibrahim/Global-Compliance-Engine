"""Maximum Order Consideration Control"""

from typing import Tuple, Any, Dict, Optional, List
from gce.main.controls.base_control import BaseControl


class MaxOrderConsideration(BaseControl):
    """
    Control: Maximum allowed order consideration (order value).
    
    Allows order value up to configured limit size (LMT).
    Order Value (ORD) = Order Quantity * Reference Price * xr rate
    
    Reference price logic (configurable hierarchy per side):
    - Limit orders: Limit price (order.price)
    - Market orders:
      - Buy side (default): Ask (Bo) -> Last -> Open -> Close
      - Sell side (default, including Short Sell & Short Sell Exempt): Bid (Bb) -> Last -> Open -> Close
      
    FX rate (xr rate):
    - 1.0 if order currency matches limit currency
    - Resolved via context or yfinance if order currency differs from limit currency
    """
    
    SELL_SIDES = {
        "S", "SELL", 
        "SS", "SHORT_SELL", "SHORT SELL", "SHORT-SELL",
        "SSE", "SHORT_SELL_EXEMPT", "SHORT SELL EXEMPT", "SHORT-SELL-EXEMPT"
    }

    def __init__(self, limit: float = 0.0, limit_currency: str = "HKD",
                 price_hierarchy_buy: Optional[List[str]] = None,
                 price_hierarchy_sell: Optional[List[str]] = None):
        """
        Initialize Max Order Consideration control.
        
        Args:
            limit: Maximum allowed order consideration value
            limit_currency: Currency of the limit (e.g. 'HKD', 'USD')
            price_hierarchy_buy: Custom price field priority for Buy orders (default: ['ask', 'last', 'open_price', 'close'])
            price_hierarchy_sell: Custom price field priority for Sell orders (default: ['bid', 'last', 'open_price', 'close'])
        """
        super().__init__("MaxOrderConsideration", float(limit))
        self.limit_currency = limit_currency.upper()
        self.price_hierarchy_buy = price_hierarchy_buy or ["ask", "last", "open_price", "close"]
        self.price_hierarchy_sell = price_hierarchy_sell or ["bid", "last", "open_price", "close"]
    
    def _get_reference_price(self, order: Any, context: Dict[str, Any]) -> float:
        """Determine reference price according to order type, side, and market data hierarchy."""
        order_type = str(getattr(order, 'order_type', 'LMT')).upper()
        if order_type in ('LMT', 'LIMIT'):
            return float(getattr(order, 'price', 0.0) or 0.0)
        
        # Market order reference price lookup
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
                f = field.lower().strip()
                attr_names = []
                dict_keys = []
                if f in ('ask', 'bo'):
                    attr_names = ['ask']
                    dict_keys = ['Ask', 'ask']
                elif f in ('bid', 'bb'):
                    attr_names = ['bid']
                    dict_keys = ['Bid', 'bid']
                elif f in ('last',):
                    attr_names = ['last']
                    dict_keys = ['Last', 'last']
                elif f in ('open', 'open_price', 'openprice'):
                    attr_names = ['open_price', 'open']
                    dict_keys = ['Open', 'open']
                elif f in ('close',):
                    attr_names = ['close']
                    dict_keys = ['Close', 'close']
                else:
                    attr_names = [f]
                    dict_keys = [f, f.capitalize()]
                
                for attr in attr_names:
                    if hasattr(price_data, attr):
                        val = getattr(price_data, attr)
                        if val is not None and float(val) > 0:
                            return float(val)
                
                if isinstance(price_data, dict):
                    for key in dict_keys:
                        if key in price_data:
                            val = price_data[key]
                            if val is not None and float(val) > 0:
                                return float(val)
                return 0.0
            
            for field in hierarchy:
                px = extract_price_by_field(field)
                if px > 0:
                    return px
        
        # Fallback if price data unavailable
        return float(getattr(order, 'price', 0.0) or 0.0)
    
    def _get_fx_rate(self, order_currency: str, context: Dict[str, Any]) -> float:
        """Resolve FX rate to convert order currency to limit currency."""
        order_curr = order_currency.upper()
        if order_curr == self.limit_currency:
            return 1.0
        
        # 1. Query PXFeeder if provided in context
        pxfeeder = context.get('pxfeeder')
        if pxfeeder and hasattr(pxfeeder, 'get_fx_rate'):
            rate = pxfeeder.get_fx_rate(order_curr, self.limit_currency)
            if rate > 0:
                return rate

        # 2. Check explicit fx_rates dict in context (e.g. {'HKD/USD': 0.13, 'HKDUSD': 0.13})
        fx_rates = context.get('fx_rates', {})
        pair_slash = f"{order_curr}/{self.limit_currency}"
        pair_direct = f"{order_curr}{self.limit_currency}"
        if pair_slash in fx_rates:
            return float(fx_rates[pair_slash])
        if pair_direct in fx_rates:
            return float(fx_rates[pair_direct])
        
        return 1.0
    
    def validate(self, order: Any, context: Dict[str, Any]) -> Tuple[bool, str, float, float]:
        """
        Validate order consideration against limit.
        
        Pass: ORD <= LMT
        Fail: ORD > LMT
        
        Rejection message template:
        Order Value is too big, LMT=$LMT, ORD=$ORD
        """
        order_qty = int(getattr(order, 'quantity', 0) or 0)
        order_currency = str(getattr(order, 'currency', 'HKD') or 'HKD')
        
        ref_price = self._get_reference_price(order, context)
        xr_rate = self._get_fx_rate(order_currency, context)
        
        ord_val = order_qty * ref_price * xr_rate

        datamgr = context.get('datamgr') if context else None
        if datamgr and hasattr(datamgr, 'get_matching_limits'):
            matched = datamgr.get_matching_limits(order)
            limit = float(matched.get('MaxOrderValue', 0.0) or 0.0)
        else:
            limit = float(self.limit)

        if limit == 0.0:
            return (True, "Control MaxOrderConsideration disabled (LMT=0)", 0.0, ord_val)
        
        if ord_val <= limit:
            return (True, f"Order consideration OK: ORD={ord_val} <= LMT={limit}", limit, ord_val)
        else:
            msg = f"Order Value is too big, LMT={limit}, ORD={ord_val}"
            return (False, msg, limit, ord_val)
