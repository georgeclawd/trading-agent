"""
Fixed Trade Executor - Simulated mode with proper safeguards
"""

import asyncio
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class TradeResult:
    success: bool
    trade_id: Optional[str]
    market: str
    position_size: float
    price: float
    error: Optional[str] = None


class TradeExecutor:
    """
    Executes trades on Kalshi (SIMULATION MODE)
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.simulation_mode = True  # ALWAYS simulation until explicitly disabled
        self.executed_trades = []  # Track all simulated trades
        
    async def execute_trade(self, opportunity: Dict, position_size: float) -> Dict:
        """
        Execute a trade (SIMULATION)
        """
        market = opportunity.get('market', 'Unknown')
        ticker = opportunity.get('ticker', 'Unknown')
        
        try:
            # In simulation mode, just log the trade
            trade_record = {
                'timestamp': datetime.now().isoformat(),
                'ticker': ticker,
                'market': market,
                'side': 'buy' if opportunity.get('our_probability', 0.5) > opportunity.get('market_probability', 0.5) else 'sell',
                'size': position_size,
                'price': opportunity.get('market_probability', 0.5),
                'expected_value': opportunity.get('expected_value', 0),
                'simulated': True
            }
            self.executed_trades.append(trade_record)
            
            return {
                'success': True,
                'trade_id': f'SIM-{ticker}-{int(datetime.now().timestamp())}',
                'market': market,
                'position_size': position_size,
                'price': opportunity.get('market_probability', 0.5),
                'side': 'buy',
                'expected_value': opportunity.get('expected_value', 0),
                'timestamp': datetime.now().isoformat(),
                'simulated': True,
                'warning': 'THIS IS A SIMULATED TRADE - NO REAL MONEY WAS SPENT'
            }
                
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'market': market
            }
    
    async def _check_balance(self) -> float:
        """Check balance"""
        return self.config.get('initial_bankroll', 100.0)
    
    async def _get_market_data(self, market_id: str) -> Optional[Dict]:
        """Fetch market data"""
        return {
            'id': market_id,
            'status': 'open',
            'best_bid': 0.65,
            'best_ask': 0.67,
        }
    
    def _calculate_order_price(self, opportunity: Dict) -> float:
        """Calculate optimal order price"""
        market_prob = opportunity.get('market_probability', 0.5)
        return market_prob
    
    async def _place_order(self, market_id: str, side: str, 
                          size: float, price: float) -> Dict:
        """Place order - SIMULATION ONLY"""
        return {
            'success': True,
            'order_id': f'SIM-{market_id}-{int(datetime.now().timestamp())}',
            'filled_size': size,
            'filled_price': price,
            'warning': 'SIMULATED - NOT A REAL TRADE'
        }
    
    async def close_position(self, trade_id: str) -> Dict:
        """Close a position"""
        return {'success': False, 'error': 'Not implemented'}
    
    def get_simulated_trades(self) -> list:
        """Get all simulated trades"""
        return self.executed_trades
    
    def clear_simulated_trades(self):
        """Clear simulated trades history"""
        self.executed_trades = []
