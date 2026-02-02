"""
Position Monitor - Tracks open positions and alerts when edge changes
Monitors positions for exit opportunities (hedging)
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger('PositionMonitor')


@dataclass
class PositionState:
    """Current state of a position"""
    ticker: str
    side: str
    entry_price: float
    current_price: Optional[float]
    current_edge: float
    original_edge: float
    pnl_pct: float
    recommendation: str  # 'HOLD', 'HEDGE', 'EXIT'


class PositionMonitor:
    """
    Monitors open positions for:
    1. Edge deterioration (hedge opportunity)
    2. Profit taking levels
    3. Stop loss triggers
    """
    
    def __init__(self, position_manager):
        self.position_manager = position_manager
        self.edge_threshold = 0.05  # Warn if edge < 5%
        self.take_profit_pct = 0.50  # 50% gain = take profit
        self.stop_loss_pct = -0.30  # 30% loss = stop out
    
    async def check_all_positions(self, strategy, market_data_fn):
        """
        Check all open positions for a strategy
        
        Args:
            strategy: Strategy instance
            market_data_fn: Async function to fetch current market data
        """
        open_positions = self.position_manager.get_open_positions(
            strategy=strategy.name,
            simulated=strategy.dry_run
        )
        
        if not open_positions:
            return []
        
        logger.info(f"📊 PositionMonitor: Checking {len(open_positions)} open positions for {strategy.name}")
        
        alerts = []
        for position in open_positions:
            state = await self._analyze_position(position, market_data_fn)
            if state:
                alerts.append(state)
                self._log_recommendation(state)
        
        return alerts
    
    async def _analyze_position(self, position, market_data_fn) -> Optional[PositionState]:
        """Analyze a single position"""
        try:
            # Get current market data
            market_data = await market_data_fn(position.ticker)
            if not market_data:
                return None
            
            current_price = market_data.get('price', position.entry_price)
            current_edge = market_data.get('edge', 0)
            
            # Calculate P&L
            if position.side == 'YES':
                pnl_pct = (current_price - position.entry_price) / position.entry_price
            else:  # NO
                pnl_pct = (position.entry_price - current_price) / position.entry_price
            
            # Determine recommendation
            recommendation = self._get_recommendation(
                current_edge, pnl_pct, position.entry_price, current_price
            )
            
            return PositionState(
                ticker=position.ticker,
                side=position.side,
                entry_price=position.entry_price,
                current_price=current_price,
                current_edge=current_edge,
                original_edge=getattr(position, 'edge', 0),
                pnl_pct=pnl_pct,
                recommendation=recommendation
            )
            
        except Exception as e:
            logger.error(f"PositionMonitor: Error analyzing {position.ticker}: {e}")
            return None
    
    def _get_recommendation(self, edge: float, pnl_pct: float, 
                           entry_price: float, current_price: float) -> str:
        """Get trading recommendation based on position state"""
        
        # Stop loss
        if pnl_pct < self.stop_loss_pct:
            return 'EXIT'  # Cut losses
        
        # Take profit
        if pnl_pct > self.take_profit_pct:
            return 'EXIT'  # Take profit
        
        # Edge disappeared - consider hedge
        if edge < self.edge_threshold:
            # Check if hedge makes sense (significant position)
            if abs(pnl_pct) > 0.10:  # 10% move
                return 'HEDGE'  # Hedge the position
            else:
                return 'HOLD'  # Too small to hedge
        
        # Good edge, hold
        if edge > 0.15:  # Still >15% edge
            return 'HOLD'
        
        # Edge diminishing
        return 'WATCH'
    
    def _log_recommendation(self, state: PositionState):
        """Log position state and recommendation"""
        emoji = {
            'HOLD': '✅',
            'HEDGE': '⚠️',
            'EXIT': '🚨',
            'WATCH': '👀'
        }.get(state.recommendation, '❓')
        
        pnl_str = f"{state.pnl_pct:+.1%}"
        edge_str = f"{state.current_edge:.1%}"
        
        msg = f"{emoji} {state.ticker}: {state.side} | P&L: {pnl_str} | Edge: {edge_str} | {state.recommendation}"
        
        if state.recommendation == 'HEDGE':
            logger.warning(f"HEDGE OPPORTUNITY: {msg}")
        elif state.recommendation == 'EXIT':
            logger.error(f"EXIT SIGNAL: {msg}")
        else:
            logger.info(f"PositionMonitor: {msg}")
    
    def generate_hedge_recommendations(self, alerts: List[PositionState]) -> List[Dict]:
        """Generate specific hedge recommendations"""
        hedges = []
        
        for alert in alerts:
            if alert.recommendation == 'HEDGE':
                hedge_side = 'NO' if alert.side == 'YES' else 'YES'
                hedge_size = self._calculate_hedge_size(alert)
                
                hedges.append({
                    'ticker': alert.ticker,
                    'original_side': alert.side,
                    'hedge_side': hedge_side,
                    'hedge_size': hedge_size,
                    'reason': f"Edge dropped to {alert.current_edge:.1%}, P&L at {alert.pnl_pct:+.1%}"
                })
        
        return hedges
    
    def _calculate_hedge_size(self, state: PositionState) -> int:
        """Calculate appropriate hedge size"""
        # Hedge 50% of position when edge disappears
        # This locks in some profit while keeping upside
        base_size = 5  # Default
        
        # Adjust based on P&L
        if state.pnl_pct > 0.30:  # Up 30%+
            return base_size  # Full hedge
        elif state.pnl_pct > 0.10:  # Up 10-30%
            return max(1, base_size // 2)  # Half hedge
        else:
            return 1  # Minimal hedge
    
    def get_position_summary(self, strategy_name: str, simulated: bool = False) -> Dict:
        """Get summary of all positions for a strategy"""
        positions = self.position_manager.get_open_positions(strategy_name, simulated)
        
        if not positions:
            return {'count': 0, 'total_pnl': 0, 'avg_edge': 0}
        
        total_pnl = sum(getattr(p, 'pnl', 0) or 0 for p in positions)
        avg_entry = sum(p.entry_price for p in positions) / len(positions)
        
        return {
            'count': len(positions),
            'total_pnl': total_pnl,
            'avg_entry_price': avg_entry,
            'positions': [p.ticker for p in positions]
        }
