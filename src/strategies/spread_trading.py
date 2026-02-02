"""
Spread Trading Strategy - Market agnostic
Trades bid/ask spreads on any market with orderbook
"""

from typing import Dict, List, Optional
from strategy_framework import BaseStrategy
from datetime import datetime
import logging

logger = logging.getLogger('SpreadTrading')


class SpreadTradingStrategy(BaseStrategy):
    """
    Market-agnostic spread trading strategy
    Works on any market: weather, sports, politics, crypto, etc.
    
    Strategy:
    - Find markets with wide bid-ask spreads
    - Place limit orders at best bid (buy) or best ask (sell)
    - Capture the spread as profit
    - Works on ALL 8,225+ series, not just weather
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "SpreadTrading"
        self.min_spread = 0.02  # Minimum 2% spread
        self.max_position = config.get('max_position_size', 5)
        self.active_orders = {}  # Track placed orders
    
    async def scan(self) -> List[Dict]:
        """Scan ALL markets for spread opportunities"""
        opportunities = []
        
        # Get ALL markets (not just weather)
        logger.info("  SpreadTrading: Scanning all Kalshi markets...")
        markets = self.client.get_markets(limit=1000, status='open')
        
        # Filter for markets with sufficient volume
        liquid_markets = [m for m in markets if m.get('volume', 0) > 200]
        
        logger.info(f"  SpreadTrading: Found {len(liquid_markets)} liquid markets (vol > $200)")
        
        checked = 0
        for market in liquid_markets[:100]:  # Check top 100 for more opportunities
            ticker = market.get('ticker', '')
            checked += 1
            
            # Skip if already have position
            if ticker in self.active_orders:
                continue
            
            # Get orderbook
            try:
                orderbook_response = self.client.get_orderbook(ticker)
                if not orderbook_response:
                    continue
                # Kalshi returns {'orderbook': {'yes': [...], 'no': [...]}}
                orderbook = orderbook_response.get('orderbook', {})
            except Exception as e:
                logger.debug(f"  SpreadTrading: Error fetching orderbook for {ticker}: {e}")
                continue
            
            # Analyze spread
            opp = self._analyze_spread(ticker, market, orderbook)
            if opp:
                opportunities.append(opp)
                logger.info(f"  SpreadTrading: Found opportunity {ticker} - spread: {opp['spread']:.1%}")
        
        logger.info(f"  SpreadTrading: Checked {checked} markets, found {len(opportunities)} spread opportunities")
        return opportunities
    
    def _analyze_spread(self, ticker: str, market: Dict, orderbook: Dict) -> Optional[Dict]:
        """Analyze orderbook for spread opportunity"""
        
        yes_bids = orderbook.get('yes', [])
        no_bids = orderbook.get('no', [])
        
        if not yes_bids or not no_bids:
            return None
        
        # Get best prices - Kalshi format: [[price_cents, volume], ...]
        if isinstance(yes_bids[0], list):
            best_bid = yes_bids[0][0] / 100  # First element is price in cents
            best_ask = (100 - no_bids[0][0]) / 100  # NO price converted to YES price
        else:
            best_bid = yes_bids[0].get('price', 0) / 100
            best_ask = 100 - no_bids[0].get('price', 100) / 100
        
        # Calculate spread
        spread = best_ask - best_bid
        
        # Look for wide spreads on cheap markets
        if spread < self.min_spread or best_bid > 0.20:  # Only cheap markets (<20%)
            return None
        
        # Determine if this is a good opportunity
        # Buy at bid, sell at ask
        potential_profit = spread / best_bid if best_bid > 0 else 0
        
        if potential_profit < 0.05:  # Need at least 5% profit
            return None
        
        return {
            'ticker': ticker,
            'market': market.get('title', 'Unknown'),
            'side': 'buy',
            'entry_price': best_bid,
            'target_price': best_ask,
            'spread': spread,
            'expected_profit': potential_profit,
            'strategy': 'spread_trading'
        }
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute spread trades (real or simulated)"""
        executed = 0
        
        for opp in opportunities:
            ticker = opp['ticker']
            entry_price = int(opp['entry_price'] * 100)  # Convert to cents
            
            if self.dry_run:
                # SIMULATED: Record position without executing
                self.record_position(
                    ticker=ticker,
                    side='YES',
                    contracts=min(self.max_position, 5),
                    entry_price=entry_price,
                    market_title=opp['market']
                )
                logger.info(f"    [SIMULATED] ✓ Would place limit: {ticker} at {opp['entry_price']:.1%}")
            else:
                # REAL: Place limit order via Kalshi API
                try:
                    self.client.create_order(
                        ticker=ticker,
                        side='buy',
                        contracts=min(self.max_position, 5),
                        price=entry_price
                    )
                    self.record_position(
                        ticker=ticker,
                        side='YES',
                        contracts=min(self.max_position, 5),
                        entry_price=entry_price,
                        market_title=opp['market']
                    )
                    logger.info(f"    [REAL] ✓ Placed limit: {ticker} at {opp['entry_price']:.1%}")
                except Exception as e:
                    logger.error(f"    [REAL] ✗ Failed to place limit {ticker}: {e}")
                    continue
            
            # Track for monitoring
            trade = {
                'ticker': ticker,
                'market': opp['market'],
                'side': opp['side'],
                'entry': opp['entry_price'],
                'target': opp['target_price'],
                'size': min(self.max_position, 5),
                'expected_profit': opp['expected_profit'],
                'timestamp': datetime.now().isoformat(),
                'status': 'open',
                'simulated': self.dry_run
            }
            self.record_trade(trade)
            self.active_orders[ticker] = trade
            executed += 1
        
        return executed
    
    async def check_and_exit(self):
        """Check if any positions should be exited"""
        for ticker, position in list(self.active_orders.items()):
            if position.get('status') != 'open':
                continue
            
            # Get current orderbook
            orderbook_response = self.client.get_orderbook(ticker)
            if not orderbook_response:
                continue
            
            orderbook = orderbook_response.get('orderbook', {})
            yes_bids = orderbook.get('yes', [])
            if yes_bids:
                if isinstance(yes_bids[0], list):
                    current_bid = yes_bids[0][0] / 100
                else:
                    current_bid = yes_bids[0].get('price', 0) / 100
                
                # Exit if price reached target
                if current_bid >= position['target']:
                    profit = (current_bid - position['entry']) * position['size']
                    position['status'] = 'closed'
                    position['exit_price'] = current_bid
                    position['profit'] = profit
                    logger.info(f"    ✓ Closed {ticker}: profit ${profit:.2f}")
    
    def get_performance(self) -> Dict:
        """Get performance metrics"""
        if not self.trades:
            return {'total_pnl': 0, 'win_rate': 0, 'trades': 0, 'open_positions': 0}
        
        closed_trades = [t for t in self.trades if t.get('status') == 'closed']
        open_trades = [t for t in self.trades if t.get('status') == 'open']
        
        total_pnl = sum(t.get('profit', 0) for t in closed_trades)
        win_rate = sum(1 for t in closed_trades if t.get('profit', 0) > 0) / len(closed_trades) if closed_trades else 0
        
        return {
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'trades': len(closed_trades),
            'open_positions': len(open_trades)
        }
