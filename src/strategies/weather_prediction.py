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
    
    def __init__(self, config: Dict, client, market_scanner):
        super().__init__(config, client)
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
        """Execute trades on opportunities"""
        executed = 0
        
        for opp in opportunities:
            # Check if we should trade based on allocation
            position_size = self._calculate_position_size(opp)
            
            if position_size > 0:
                # Simulate trade (replace with actual execution)
                trade = {
                    'ticker': opp.get('ticker'),
                    'market': opp.get('market'),
                    'size': position_size,
                    'expected_value': opp.get('expected_value'),
                    'simulated': True
                }
                self.record_trade(trade)
                executed += 1
                logger.info(f"    ✓ Executed: {opp.get('ticker')} (EV: {opp.get('expected_value'):.1%})")
        
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
