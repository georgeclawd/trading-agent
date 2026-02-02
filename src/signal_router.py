"""
Signal Router - Routes trading signals to best execution platform
Polymarket for signals, Kalshi for execution
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradingSignal:
    """A detected trading opportunity"""
    source: str  # 'polymarket', 'weather_api', 'kalshi_internal'
    market_type: str  # 'weather', 'crypto', 'sports', 'politics'
    event_description: str
    confidence: float  # 0-1
    expected_return: float  # %
    recommended_action: str  # 'buy_yes', 'buy_no', 'arbitrage'
    rationale: str
    timestamp: datetime


class SignalRouter:
    """
    Routes signals to appropriate execution platform
    
    Priority:
    1. Kalshi (primary execution) - regulated, legal, simple
    2. Polymarket (signal only) - for whale watching
    """
    
    def __init__(self, kalshi_client, polymarket_watcher):
        self.kalshi = kalshi_client
        self.poly_watcher = polymarket_watcher
        
    async def get_all_signals(self) -> List[TradingSignal]:
        """
        Collect signals from all sources
        
        Sources:
        - Weather API predictions
        - Polymarket whale watching
        - Kalshi internal opportunities
        """
        signals = []
        
        # 1. Weather signals (high confidence)
        weather_sigs = await self._get_weather_signals()
        signals.extend(weather_sigs)
        
        # 2. Polymarket whale signals
        whale_sigs = await self._get_whale_signals()
        signals.extend(whale_sigs)
        
        # 3. Arbitrage opportunities
        arb_sigs = await self._get_arbitrage_signals()
        signals.extend(arb_sigs)
        
        # Sort by expected return
        signals.sort(key=lambda x: x.expected_return, reverse=True)
        
        return signals
    
    async def _get_weather_signals(self) -> List[TradingSignal]:
        """Generate signals from weather predictions"""
        # TODO: Integrate with Open-Meteo
        # Compare forecast vs market pricing
        return []
    
    async def _get_whale_signals(self) -> List[TradingSignal]:
        """Generate signals from Polymarket whale activity"""
        # Use whale watcher to detect unusual activity
        whale_trades = await self.poly_watcher.scan_for_whale_trades()
        
        signals = []
        for trade in whale_trades:
            # Check if we can execute on Kalshi
            kalshi_market = await self._find_kalshi_equivalent(trade)
            
            if kalshi_market:
                signal = TradingSignal(
                    source='polymarket_whale',
                    market_type=self._categorize_market(trade.market_name),
                    event_description=trade.market_name,
                    confidence=min(trade.anomaly_score / 5, 0.95),
                    expected_return=0.05,  # Conservative 5%
                    recommended_action=f"buy_{trade.outcome.lower()}",
                    rationale=f"Whale {trade.wallet[:10]}... trading against {trade.retail_sentiment}",
                    timestamp=datetime.now()
                )
                signals.append(signal)
        
        return signals
    
    async def _get_arbitrage_signals(self) -> List[TradingSignal]:
        """Find arbitrage opportunities on Kalshi"""
        # Look for YES + NO < $1 opportunities
        # This is pure math arbitrage
        return []
    
    async def _find_kalshi_equivalent(self, whale_trade) -> Optional[Dict]:
        """
        Find equivalent Kalshi market for a Polymarket event
        
        This is the KEY function for cross-platform strategy
        """
        # TODO: Implement market matching logic
        # Normalize event names and compare
        return None
    
    def _categorize_market(self, market_name: str) -> str:
        """Categorize market by type"""
        name = market_name.lower()
        
        if any(x in name for x in ['rain', 'snow', 'temp', 'weather']):
            return 'weather'
        elif any(x in name for x in ['btc', 'eth', 'bitcoin', 'crypto']):
            return 'crypto'
        elif any(x in name for x in ['nfl', 'nba', 'soccer', 'win']):
            return 'sports'
        elif any(x in name for x in ['election', 'trump', 'biden']):
            return 'politics'
        else:
            return 'other'
    
    async def execute_signal(self, signal: TradingSignal, 
                           position_size: float) -> Dict:
        """
        Execute a trading signal on Kalshi
        
        Always execute on Kalshi (legal, regulated)
        """
        # Find the market on Kalshi
        markets = self.kalshi.get_markets()
        
        # Find matching market
        target_market = None
        for market in markets:
            if self._markets_match(signal.event_description, market):
                target_market = market
                break
        
        if not target_market:
            return {
                'success': False,
                'error': 'No matching Kalshi market found'
            }
        
        # Execute the trade
        ticker = target_market['ticker']
        side = 'yes' if 'yes' in signal.recommended_action else 'no'
        
        # Get current price
        orderbook = self.kalshi.get_orderbook(ticker)
        if not orderbook:
            return {'success': False, 'error': 'Could not get orderbook'}
        
        # Calculate price (buy at market or limit)
        # TODO: Implement smart order routing
        
        # Place order
        result = self.kalshi.place_order(
            market_id=ticker,
            side=side,
            price=50,  # TODO: Calculate optimal price
            count=int(position_size)
        )
        
        return result
    
    def _markets_match(self, signal_desc: str, kalshi_market: Dict) -> bool:
        """Check if signal matches Kalshi market"""
        kalshi_title = kalshi_market.get('title', '').lower()
        signal_lower = signal_desc.lower()
        
        # Simple matching for now
        # TODO: Implement better semantic matching
        
        # Extract key terms
        signal_terms = set(signal_lower.split())
        kalshi_terms = set(kalshi_title.split())
        
        # Check overlap
        overlap = signal_terms.intersection(kalshi_terms)
        
        # Require at least 3 matching terms
        return len(overlap) >= 3
