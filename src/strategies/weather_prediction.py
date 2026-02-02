"""
Weather Prediction Strategy
Original strategy: Predict weather, calculate EV, trade if edge exists
"""

from typing import Dict, List
from strategy_framework import BaseStrategy
import logging

logger = logging.getLogger('WeatherPrediction')


class WeatherPredictionStrategy(BaseStrategy):
    """
    Predicts weather outcomes and trades when EV > threshold
    """
    
    def __init__(self, config: Dict, client, market_scanner, position_manager=None):
        super().__init__(config, client, position_manager)
        self.scanner = market_scanner
        self.min_ev = config.get('min_ev_threshold', 0.05)
        self.name = "WeatherPrediction"
    
    async def scan(self) -> List[Dict]:
        """Scan for weather market opportunities"""
        # Use existing market scanner logic
        opportunities, _ = await self.scanner._scan_kalshi()
        
        # Filter for weather markets only
        weather_opps = [
            opp for opp in opportunities 
            if opp.get('category') == 'weather' and opp.get('expected_value', 0) > self.min_ev
        ]
        
        logger.info(f"  WeatherPrediction: Found {len(weather_opps)} opportunities")
        return weather_opps
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute trades on opportunities (real or simulated)"""
        executed = 0
        
        for opp in opportunities:
            # Check if we should trade based on allocation
            position_size = self._calculate_position_size(opp)
            
            if position_size > 0:
                ticker = opp.get('ticker')
                market_price = int(opp.get('market_price', 50) * 100)  # Convert to cents
                
                if self.dry_run:
                    # SIMULATED: Record position without executing
                    self.record_position(
                        ticker=ticker,
                        side='YES',
                        contracts=int(position_size),
                        entry_price=market_price,
                        market_title=opp.get('market', ''),
                        expected_settlement=opp.get('settlement_time')
                    )
                    logger.info(f"    [SIMULATED] ✓ Would execute: {ticker} (EV: {opp.get('expected_value'):.1%})")
                else:
                    # REAL: Execute via Kalshi API
                    try:
                        self.client.create_order(
                            ticker=ticker,
                            side='buy',
                            contracts=int(position_size),
                            price=market_price
                        )
                        self.record_position(
                            ticker=ticker,
                            side='YES',
                            contracts=int(position_size),
                            entry_price=market_price,
                            market_title=opp.get('market', '')
                        )
                        logger.info(f"    [REAL] ✓ Executed: {ticker} (EV: {opp.get('expected_value'):.1%})")
                    except Exception as e:
                        logger.error(f"    [REAL] ✗ Failed to execute {ticker}: {e}")
                        continue
                
                # Record for performance tracking
                trade = {
                    'ticker': ticker,
                    'market': opp.get('market'),
                    'size': position_size,
                    'expected_value': opp.get('expected_value'),
                    'simulated': self.dry_run
                }
                self.record_trade(trade)
                executed += 1
        
        return executed
    
    def _calculate_position_size(self, opportunity: Dict) -> float:
        """Calculate position size based on EV and bankroll"""
        ev = opportunity.get('expected_value', 0)
        
        if ev < self.min_ev:
            return 0
        
        # Simple sizing: larger EV = larger position
        max_position = self.config.get('max_position_size', 5)  # $5 max for testing
        size = min(max_position, max(1, ev * 100))  # $1 per 1% EV
        
        return size
    
    def get_performance(self) -> Dict:
        """Get performance metrics"""
        if not self.trades:
            return {'total_pnl': 0, 'win_rate': 0, 'trades': 0}
        
        # Calculate P&L (simulated for now)
        total_pnl = sum(t.get('expected_value', 0) * t.get('size', 0) for t in self.trades)
        win_rate = sum(1 for t in self.trades if t.get('expected_value', 0) > 0) / len(self.trades)
        
        return {
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'trades': len(self.trades)
        }
