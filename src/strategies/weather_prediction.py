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
                
                # Handle market_price - could be decimal (0.50) or already cents (50)
                raw_price = opp.get('market_price', 50)
                if raw_price < 1:  # Decimal format (0.50)
                    market_price = int(raw_price * 100)
                else:  # Already cents (50)
                    market_price = int(raw_price)
                
                contracts = int(position_size)
                logger.info(f"WeatherPrediction: Executing {ticker} - size={position_size}, contracts={contracts}, price={market_price}")
                
                if self.dry_run:
                    # SIMULATED: Record position without executing
                    self.record_position(
                        ticker=ticker,
                        side='YES',
                        contracts=contracts,
                        entry_price=market_price,
                        market_title=opp.get('market', ''),
                        expected_settlement=opp.get('settlement_time')
                    )
                    logger.info(f"    [SIMULATED] ✓ Would execute: {ticker} (EV: {opp.get('expected_value'):.1%})")
                else:
                    # REAL: Execute via Kalshi API
                    try:
                        result = self.client.place_order(
                            market_id=ticker,
                            side='yes',
                            price=market_price,
                            count=contracts
                        )
                        if result.get('order_id'):
                            self.record_position(
                                ticker=ticker,
                                side='YES',
                                contracts=contracts,
                                entry_price=market_price,
                                market_title=opp.get('market', '')
                            )
                            logger.info(f"    [REAL] ✓ Executed: {ticker} (EV: {opp.get('expected_value'):.1%}) Order: {result['order_id']}")
                        else:
                            logger.error(f"    [REAL] ✗ Order failed: {result}")
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
    
    def _calculate_position_size(self, opportunity: Dict) -> int:
        """Calculate position size based on EV and bankroll"""
        ev = opportunity.get('expected_value', 0)
        
        # EV might be stored as decimal (0.05 = 5%) or already as percentage (5.0 = 5%)
        # Normalize to percentage points
        if ev < 1.0:  # Assume decimal format (0.05 = 5%)
            ev_percent = ev * 100
        else:  # Already percentage (5.0 = 5%)
            ev_percent = ev
        
        # min_ev is stored as decimal (0.05), so compare with raw ev
        if ev < self.min_ev:
            logger.info(f"WeatherPrediction: SKIPPING - EV {ev:.4f} < min_ev {self.min_ev}")
            return 0
        
        # Simple sizing: $1 per 1% EV, max $5
        max_position = self.config.get('max_position_size', 5)
        size = int(min(max_position, max(1, ev_percent)))
        
        logger.info(f"WeatherPrediction: SIZING - EV={ev:.4f}, ev_percent={ev_percent:.2f}, max_pos={max_position}, size={size}")
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
