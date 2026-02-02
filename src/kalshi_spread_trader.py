"""
Kalshi Spread Trading Strategy

Based on X thread research - successful bots trade spreads, not just predict.

Key Insights:
1. Don't predict - trade orderbook spread
2. Buy ultra-cheap brackets (0.3-3%)
3. Trade around forecast updates
4. Tiny edges (0.7%), high volume
5. Real-time orderbook monitoring

Kalshi Implementation:
- Monitor YES/NO orderbooks
- Find markets priced at 1-3% with high probability outcomes
- Place limit orders to buy cheap
- Sell when forecast updates shift probability
"""

import asyncio
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class OrderbookLevel:
    """Represents a level in the orderbook"""
    price: float  # Price in cents (0-100)
    count: int    # Number of contracts
    side: str     # 'yes' or 'no'


@dataclass
class SpreadOpportunity:
    """A spread trading opportunity"""
    ticker: str
    market_title: str
    side: str           # 'yes' or 'no'
    entry_price: float  # Price to buy at
    target_price: float # Price to sell at
    expected_profit: float
    confidence: float
    rationale: str


class KalshiSpreadTrader:
    """
    Implements spread trading strategy on Kalshi
    
    Strategy:
    1. Find markets with wide spreads (bid-ask gap)
    2. Buy at/below best bid for likely outcomes
    3. Sell when probability updates or at ask
    4. Focus on cheap markets (1-10%) with clear forecasts
    """
    
    def __init__(self, client):
        self.client = client
        self.min_edge = 0.02  # Minimum 2% edge
        self.max_position = 10  # Max $10 per trade (testing)
        self.active_orders = {}  # Track placed orders
    
    async def find_spread_opportunities(self) -> List[SpreadOpportunity]:
        """
        Find spread trading opportunities
        
        Looks for:
        - Markets priced 1-10%
        - Wide bid-ask spreads
        - High probability outcomes based on forecast
        """
        opportunities = []
        
        # Get weather markets
        markets = self.client.get_markets(limit=100, status='open')
        
        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '').lower()
            
            # Only weather/temp markets
            if 'temp' not in title and 'high' not in ticker.lower():
                continue
            
            # Check if it's a cheap market
            last_price = market.get('last_price', 50)
            if last_price > 15 or last_price < 1:  # Skip expensive or illiquid
                continue
            
            # Get orderbook
            orderbook = self.client.get_orderbook(ticker)
            if not orderbook:
                continue
            
            # Analyze spread
            opp = self._analyze_spread(ticker, title, orderbook, last_price)
            if opp:
                opportunities.append(opp)
        
        return opportunities
    
    def _analyze_spread(self, ticker: str, title: str, orderbook: Dict, last_price: float) -> Optional[SpreadOpportunity]:
        """Analyze orderbook for spread opportunity"""
        
        yes_bids = orderbook.get('yes', [])
        yes_asks = orderbook.get('no', [])  # NO asks = YES offers
        
        if not yes_bids or not yes_asks:
            return None
        
        # Get best bid and ask
        best_bid = yes_bids[0].get('price', 0) if yes_bids else 0
        best_ask = 100 - yes_asks[0].get('price', 100) if yes_asks else 100
        
        # Calculate spread
        spread = best_ask - best_bid
        
        # Look for wide spreads (>5 cents) on cheap markets
        if spread < 5 or best_bid > 10:
            return None
        
        # For cheap markets with wide spreads:
        # Buy at best_bid (or below), target best_ask
        entry = best_bid
        target = best_ask
        expected_profit = (target - entry) / entry if entry > 0 else 0
        
        if expected_profit < self.min_edge:
            return None
        
        return SpreadOpportunity(
            ticker=ticker,
            market_title=title,
            side='yes',
            entry_price=entry,
            target_price=target,
            expected_profit=expected_profit,
            confidence=0.7,
            rationale=f"Wide spread: bid={best_bid}¢, ask={best_ask}¢, edge={expected_profit:.1%}"
        )
    
    async def place_limit_order(self, opp: SpreadOpportunity) -> bool:
        """Place a limit order to enter position"""
        
        # In simulation mode, just log
        print(f"[SIM] Placing limit order: {opp.ticker}")
        print(f"  Side: {opp.side}")
        print(f"  Price: {opp.entry_price}¢")
        print(f"  Size: ${self.max_position}")
        print(f"  Target: {opp.target_price}¢")
        print(f"  Expected profit: {opp.expected_profit:.1%}")
        
        # Track order
        self.active_orders[opp.ticker] = {
            'entry_time': datetime.now(),
            'entry_price': opp.entry_price,
            'target_price': opp.target_price,
            'status': 'open'
        }
        
        return True
    
    async def check_and_exit_positions(self):
        """Check if any positions should be exited"""
        
        for ticker, position in list(self.active_orders.items()):
            if position['status'] != 'open':
                continue
            
            # Get current orderbook
            orderbook = self.client.get_orderbook(ticker)
            if not orderbook:
                continue
            
            yes_bids = orderbook.get('yes', [])
            if yes_bids:
                current_bid = yes_bids[0].get('price', 0)
                
                # Exit if price reached target
                if current_bid >= position['target_price']:
                    print(f"[SIM] Exiting {ticker} at {current_bid}¢ (target: {position['target_price']}¢)")
                    position['status'] = 'closed'
                    position['exit_price'] = current_bid
                    position['exit_time'] = datetime.now()
    
    def get_performance_summary(self) -> Dict:
        """Get trading performance summary"""
        closed = [p for p in self.active_orders.values() if p['status'] == 'closed']
        
        if not closed:
            return {'trades': 0, 'profit': 0}
        
        total_profit = sum(
            (p['exit_price'] - p['entry_price']) / p['entry_price']
            for p in closed
        )
        
        return {
            'trades': len(closed),
            'profit': total_profit,
            'avg_profit_per_trade': total_profit / len(closed) if closed else 0
        }
