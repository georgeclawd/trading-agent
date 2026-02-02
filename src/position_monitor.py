"""
Position Monitor - Tracks open positions and syncs with Kalshi
Monitors positions for exit opportunities and settlement
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
    pnl_dollars: float
    recommendation: str  # 'HOLD', 'HEDGE', 'EXIT', 'SETTLED'
    is_settled: bool
    settlement_price: Optional[float] = None


class PositionMonitor:
    """
    Monitors open positions for:
    1. Edge deterioration (hedge opportunity)
    2. Market settlement (position closes)
    3. Profit taking levels
    4. Stop loss triggers
    """
    
    def __init__(self, position_manager, kalshi_client=None):
        self.position_manager = position_manager
        self.kalshi_client = kalshi_client
        self.edge_threshold = 0.05  # Warn if edge < 5%
        self.take_profit_pct = 0.50  # 50% gain = take profit
        self.stop_loss_pct = -0.30  # 30% loss = stop out
    
    async def sync_with_kalshi(self, strategy_name: str, simulated: bool = False):
        """
        Sync local positions with Kalshi's actual positions
        Marks positions as closed if Kalshi shows them settled
        """
        if not self.kalshi_client or simulated:
            return []
        
        open_positions = self.position_manager.get_open_positions(
            strategy=strategy_name,
            simulated=False
        )
        
        if not open_positions:
            return []
        
        # Get current positions from Kalshi
        kalshi_positions = self.kalshi_client.get_positions()
        kalshi_tickers = {p.get('ticker') for p in kalshi_positions}
        
        closed_positions = []
        
        for local_pos in open_positions:
            ticker = local_pos.ticker
            
            # Check if position still exists on Kalshi
            if ticker not in kalshi_tickers:
                # Position was closed on Kalshi - check settlement status
                market_data = await self._get_market_settlement(ticker)
                
                if market_data and market_data.get('is_settled'):
                    # Full settlement data available
                    settlement_price = market_data.get('settlement_price', 0)
                    
                    # Calculate actual P&L
                    if local_pos.side == 'YES':
                        pnl_dollars = (settlement_price - local_pos.entry_price) * local_pos.contracts / 100
                    else:  # NO
                        pnl_dollars = (local_pos.entry_price - settlement_price) * local_pos.contracts / 100
                    
                    # Close the position
                    self.position_manager.close_position(
                        ticker=ticker,
                        exit_price=settlement_price,
                        pnl=pnl_dollars,
                        simulated=False
                    )
                    
                    closed_positions.append({
                        'ticker': ticker,
                        'side': local_pos.side,
                        'contracts': local_pos.contracts,
                        'entry_price': local_pos.entry_price,
                        'settlement_price': settlement_price,
                        'pnl': pnl_dollars,
                        'reason': 'market_settled'
                    })
                    
                    if pnl_dollars >= 0:
                        logger.info(f"💰 Position settled WIN: {ticker} {local_pos.side} x{local_pos.contracts} "
                                   f"@ {settlement_price}c | P&L: ${pnl_dollars:+.2f}")
                    else:
                        logger.warning(f"💸 Position settled LOSS: {ticker} {local_pos.side} x{local_pos.contracts} "
                                      f"@ {settlement_price}c | P&L: ${pnl_dollars:+.2f}")
                
                elif market_data and market_data.get('is_finalized'):
                    # Market finalized but settlement pending
                    logger.info(f"⏳ Position finalized (settlement pending): {ticker} - "
                               f"waiting for result publication")
                    # Don't close position yet - keep monitoring
                
                else:
                    # Position gone but can't determine status - assume settled at entry
                    logger.warning(f"⚠️ Position disappeared from Kalshi: {ticker} - "
                                  f"manual review recommended")
        
        return closed_positions
    
    async def _get_market_settlement(self, ticker: str) -> Optional[Dict]:
        """Get settlement info for a market"""
        try:
            if not self.kalshi_client:
                return None
            
            # Get market details from Kalshi
            import requests
            import time
            import base64
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            
            api_key_id = self.kalshi_client.api_key_id
            api_key = self.kalshi_client.api_key
            
            def create_sig(ts, method, path):
                msg = f"{ts}{method}{path}"
                # Use the client's loaded key
                pk = self.kalshi_client._private_key
                sig = pk.sign(
                    msg.encode(),
                    padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                    hashes.SHA256()
                )
                return base64.b64encode(sig).decode()
            
            ts = str(int(time.time() * 1000))
            sig = create_sig(ts, "GET", f"/trade-api/v2/markets/{ticker}")
            
            headers = {
                "KALSHI-ACCESS-KEY": api_key_id,
                "KALSHI-ACCESS-SIGNATURE": sig,
                "KALSHI-ACCESS-TIMESTAMP": ts
            }
            
            resp = requests.get(
                f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                headers=headers,
                timeout=10
            )
            
            if resp.status_code == 200:
                market = resp.json().get('market', {})
                status = market.get('status', 'open')
                
                if status == 'settled':
                    # Get settlement price - YES side pays 100 if YES won, 0 if NO won
                    yes_result = market.get('yes_result', 0)  # 0 or 100
                    settlement_price = 100 if yes_result else 0
                    return {
                        'is_settled': True,
                        'settlement_price': settlement_price,  # 0 or 100 cents
                        'result': 'YES' if yes_result else 'NO'
                    }
                elif status == 'finalized':
                    # Market is finalized but not yet settled
                    # Position was closed but result pending
                    return {
                        'is_settled': False,
                        'is_finalized': True,
                        'status': 'finalized',
                        'message': 'Market closed, settlement pending'
                    }
                else:
                    return {'is_settled': False}
                    
            return None
        except Exception as e:
            logger.debug(f"Could not fetch settlement for {ticker}: {e}")
            return None
    
    async def check_all_positions(self, strategy, market_data_fn):
        """
        Check all open positions for a strategy
        
        Args:
            strategy: Strategy instance
            market_data_fn: Async function to fetch current market data
        """
        # First sync with Kalshi to catch settled positions
        await self.sync_with_kalshi(strategy.name, strategy.dry_run)
        
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
            
            # Check if market is settled
            if market_data and market_data.get('is_settled'):
                settlement_price = market_data.get('settlement_price', 0)
                
                # Calculate actual P&L
                if position.side == 'YES':
                    pnl_dollars = (settlement_price - position.entry_price) * position.contracts / 100
                    pnl_pct = (settlement_price - position.entry_price) / position.entry_price
                else:  # NO
                    pnl_dollars = (position.entry_price - settlement_price) * position.contracts / 100
                    pnl_pct = (position.entry_price - settlement_price) / position.entry_price
                
                return PositionState(
                    ticker=position.ticker,
                    side=position.side,
                    entry_price=position.entry_price,
                    current_price=settlement_price,
                    current_edge=0,
                    original_edge=getattr(position, 'edge', 0),
                    pnl_pct=pnl_pct,
                    pnl_dollars=pnl_dollars,
                    recommendation='SETTLED',
                    is_settled=True,
                    settlement_price=settlement_price
                )
            
            # Regular open position analysis
            if not market_data:
                return None
            
            current_price = market_data.get('price', position.entry_price)
            current_edge = market_data.get('edge', 0)
            
            # Calculate P&L for open position
            if position.side == 'YES':
                pnl_pct = (current_price - position.entry_price) / position.entry_price
                pnl_dollars = (current_price - position.entry_price) * position.contracts / 100
            else:  # NO
                pnl_pct = (position.entry_price - current_price) / position.entry_price
                pnl_dollars = (position.entry_price - current_price) * position.contracts / 100
            
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
                pnl_dollars=pnl_dollars,
                recommendation=recommendation,
                is_settled=False
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
            'WATCH': '👀',
            'SETTLED': '💰'
        }.get(state.recommendation, '❓')
        
        pnl_str = f"${state.pnl_dollars:+.2f} ({state.pnl_pct:+.1%})"
        edge_str = f"{state.current_edge:.1%}" if not state.is_settled else "SETTLED"
        
        msg = f"{state.ticker}: {state.side} | P&L: {pnl_str} | Edge: {edge_str} | {state.recommendation}"
        
        if state.recommendation == 'HEDGE':
            logger.warning(f"⚠️ HEDGE: {msg}")
        elif state.recommendation == 'EXIT':
            if state.pnl_dollars > 0:
                logger.info(f"🎯 TAKE PROFIT: {msg}")
            else:
                logger.warning(f"🛑 STOP LOSS: {msg}")
        elif state.recommendation == 'SETTLED':
            if state.pnl_dollars >= 0:
                logger.info(f"💰 SETTLED WIN: {msg}")
            else:
                logger.warning(f"💸 SETTLED LOSS: {msg}")
        else:
            logger.info(f"📊 {emoji} {msg}")
    
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
