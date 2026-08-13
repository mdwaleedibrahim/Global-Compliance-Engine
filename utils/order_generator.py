"""Mock Order Generator - Create test orders for development and testing."""

import random
import uuid
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from gce.cache.order_cache import Order


class MockOrderGenerator:
    """Generate mock orders for testing and development."""
    
    DEFAULT_SYMBOLS = [
        "0001.HK", "0005.HK", "0011.HK", "0012.HK", "0016.HK",
        "0017.HK", "0019.HK", "0023.HK", "0027.HK", "0066.HK",
        "0101.HK", "0700.HK"
    ]
    
    DEFAULT_TRADERS = ["Waleed", "Ahmed", "Sarah", "John", "Lisa"]
    DEFAULT_DESKS = ["Equity_apac", "Equity_emea", "Equity_americas"]
    DEFAULT_ACCOUNTS = ["APAC_EQTY_CASH", "EMEA_EQTY_CASH", "AM_EQTY_CASH"]
    DEFAULT_CLIENTS = ["TestClient", "Client_A", "Client_B", "Client_C"]
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize order generator.
        
        Args:
            seed: Random seed for reproducibility
        """
        if seed is not None:
            random.seed(seed)
        self.order_counter = 0
    
    def generate_order(self, 
                      symbol: Optional[str] = None,
                      quantity: Optional[int] = None,
                      price: Optional[float] = None,
                      side: str = "B",
                      order_type: str = "LMT",
                      trader: Optional[str] = None,
                      account: Optional[str] = None,
                      client: Optional[str] = None,
                      order_id: Optional[str] = None,
                      **kwargs) -> Order:
        """
        Generate single mock order.
        
        Args:
            symbol: Stock symbol (random if None)
            quantity: Order quantity (random if None)
            price: Order price (random if None)
            side: B or S (default: B)
            order_type: LMT or MKT (default: LMT)
            trader: Trader name (random if None)
            account: Account ID (random if None)
            client: Client name (random if None)
            order_id: Order ID (generated if None)
            **kwargs: Additional order fields
            
        Returns:
            Order object
        """
        self.order_counter += 1
        symbol = symbol or random.choice(self.DEFAULT_SYMBOLS)
        quantity = quantity or random.randint(10, 1000)
        price = price or round(random.uniform(50, 500), 2)
        trader = trader or random.choice(self.DEFAULT_TRADERS)
        account = account or random.choice(self.DEFAULT_ACCOUNTS)
        client = client or random.choice(self.DEFAULT_CLIENTS)
        order_id = order_id or f"ORD_{uuid.uuid4().hex[:8].upper()}"
        
        order = Order(
            order_id=order_id,
            ric=symbol,
            symbol=symbol,
            quantity=quantity,
            price=price,
            side=side,
            order_type=order_type,
            trader=trader,
            account=account,
            client=client,
            desk=kwargs.get('desk', random.choice(self.DEFAULT_DESKS)),
            currency=kwargs.get('currency', 'HKD'),
            timestamp=kwargs.get('timestamp', datetime.now().isoformat())
        )
        
        return order
    
    def generate_orders(self, 
                       count: int = 10,
                       symbols: Optional[List[str]] = None,
                       quantities: Optional[List[int]] = None,
                       prices: Optional[List[float]] = None,
                       sides: Optional[List[str]] = None,
                       fill_rate: float = 0.0,
                       **kwargs) -> List[Order]:
        """
        Generate multiple mock orders.
        
        Args:
            count: Number of orders to generate
            symbols: List of symbols to randomly pick from
            quantities: List of quantities to randomly pick from
            prices: List of prices to randomly pick from
            sides: List of sides (B/S) to randomly pick from
            fill_rate: Percentage of orders to mark as filled (0.0-1.0)
            **kwargs: Additional order fields
            
        Returns:
            List of Order objects
        """
        symbols = symbols or self.DEFAULT_SYMBOLS
        quantities = quantities or [100, 500, 1000, 2000, 5000]
        prices = prices or [100, 200, 300, 400, 500]
        sides = sides or ["B", "S"]
        
        orders = []
        for i in range(count):
            order = self.generate_order(
                symbol=random.choice(symbols),
                quantity=random.choice(quantities),
                price=random.choice(prices),
                side=random.choice(sides),
                order_id=f"ORD_{datetime.now().strftime('%Y%m%d')}_{i+1:04d}",
                **kwargs
            )
            
            # Randomly fill some orders
            if random.random() < fill_rate:
                filled = random.randint(0, order.quantity)
                order.filled = filled
                order.open_qty = order.quantity - filled
            
            orders.append(order)
        
        return orders
    
    def generate_buy_sell_pair(self, 
                              symbol: Optional[str] = None,
                              quantity: Optional[int] = None,
                              price: Optional[float] = None,
                              **kwargs) -> tuple:
        """
        Generate matching buy and sell orders.
        
        Args:
            symbol: Stock symbol
            quantity: Order quantity (same for both)
            price: Order price (same for both)
            **kwargs: Additional fields
            
        Returns:
            Tuple of (buy_order, sell_order)
        """
        symbol = symbol or random.choice(self.DEFAULT_SYMBOLS)
        quantity = quantity or random.randint(10, 1000)
        price = price or round(random.uniform(50, 500), 2)
        
        buy_order = self.generate_order(
            symbol=symbol,
            quantity=quantity,
            price=price,
            side="B",
            **kwargs
        )
        
        sell_order = self.generate_order(
            symbol=symbol,
            quantity=quantity,
            price=price,
            side="S",
            order_id=f"ORD_{uuid.uuid4().hex[:8].upper()}",
            **kwargs
        )
        
        return buy_order, sell_order
    
    def generate_order_sequence(self,
                               symbol: str,
                               base_quantity: int,
                               num_orders: int = 5,
                               quantity_variance: float = 0.2,
                               **kwargs) -> List[Order]:
        """
        Generate sequence of orders for same symbol (e.g., partial fills).
        
        Args:
            symbol: Stock symbol
            base_quantity: Base order quantity
            num_orders: Number of orders in sequence
            quantity_variance: Variance in quantities (0.0-1.0)
            **kwargs: Additional fields
            
        Returns:
            List of Order objects in sequence
        """
        orders = []
        
        for i in range(num_orders):
            # Vary quantity
            qty_variance = int(base_quantity * quantity_variance * random.uniform(-1, 1))
            qty = max(1, base_quantity + qty_variance)
            
            order = self.generate_order(
                symbol=symbol,
                quantity=qty,
                order_id=f"ORD_{symbol}_{i+1:03d}",
                **kwargs
            )
            orders.append(order)
        
        return orders
    
    def generate_rejection_test_cases(self) -> Dict[str, Order]:
        """
        Generate test cases designed to trigger rejections.
        
        Returns:
            Dict mapping test case name to Order
        """
        return {
            "oversized_quantity": self.generate_order(
                symbol="0700.HK",
                quantity=10000,  # Very large
                price=440.0
            ),
            "oversized_price": self.generate_order(
                symbol="0700.HK",
                quantity=100,
                price=5000.0  # Very high
            ),
            "normal_buy": self.generate_order(
                symbol="0700.HK",
                quantity=100,
                price=440.0,
                side="B"
            ),
            "normal_sell": self.generate_order(
                symbol="0700.HK",
                quantity=100,
                price=440.0,
                side="S"
            ),
            "market_order": self.generate_order(
                symbol="0700.HK",
                quantity=100,
                price=None,
                order_type="MKT"
            ),
            "minimum_size": self.generate_order(
                symbol="0700.HK",
                quantity=1,
                price=440.0
            ),
            "maximum_price": self.generate_order(
                symbol="0700.HK",
                quantity=100,
                price=9999.99
            ),
        }
