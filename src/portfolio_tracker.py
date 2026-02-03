"""
Portfolio Tracker - Tracks PNL, bankroll, and performance metrics
"""

import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime, timedelta


class PortfolioTracker:
    """Tracks trading performance and bankroll"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.data_dir.mkdir(exist_ok=True)
        
        self.trades_file = self.data_dir / 'trades.json'
        self.bankroll_file = self.data_dir / 'bankroll.json'
        
        self.trades: List[Dict] = self._load_trades()
        self.current_bankroll = self._load_bankroll()
    
    def _load_trades(self) -> List[Dict]:
        """Load trade history"""
        if self.trades_file.exists():
            with open(self.trades_file) as f:
                return json.load(f)
        return []
    
    def _save_trades(self):
        """Save trade history"""
        with open(self.trades_file, 'w') as f:
            json.dump(self.trades, f, indent=2)
    
    def _load_bankroll(self) -> float:
        """Load current bankroll"""
        # Get initial bankroll from config (top level or bot section)
        initial = self.config.get('initial_bankroll', 
                                  self.config.get('bot', {}).get('initial_bankroll', 100.0))
        
        if self.bankroll_file.exists():
            with open(self.bankroll_file) as f:
                data = json.load(f)
                return data.get('current', initial)
        return initial
    
    def _save_bankroll(self):
        """Save bankroll"""
        with open(self.bankroll_file, 'w') as f:
            json.dump({
                'current': self.current_bankroll,
                'initial': self.config['initial_bankroll'],
                'peak': self._get_peak_bankroll(),
                'updated': datetime.now().isoformat()
            }, f, indent=2)
    
    async def get_current_bankroll(self) -> float:
        """Get current bankroll"""
        return self.current_bankroll
    
    async def record_trade(self, trade: Dict):
        """Record a completed trade"""
        trade['recorded_at'] = datetime.now().isoformat()
        self.trades.append(trade)
        self._save_trades()
        
        # Update bankroll
        # In real implementation, query actual balance
        # For now, simulate
        pass
    
    def get_win_rate(self, days: int = 7) -> float:
        """Calculate win rate over last N days"""
        cutoff = datetime.now() - timedelta(days=days)
        
        recent_trades = [
            t for t in self.trades 
            if datetime.fromisoformat(t.get('recorded_at', '2000-01-01')) > cutoff
        ]
        
        if not recent_trades:
            return 0.5  # Default
        
        wins = sum(1 for t in recent_trades if t.get('pnl', 0) > 0)
        return wins / len(recent_trades)
    
    def get_pnl(self, days: int = None) -> float:
        """Calculate PNL over period"""
        if days:
            cutoff = datetime.now() - timedelta(days=days)
            trades = [
                t for t in self.trades 
                if datetime.fromisoformat(t.get('recorded_at', '2000-01-01')) > cutoff
            ]
        else:
            trades = self.trades
        
        return sum(t.get('pnl', 0) for t in trades)
    
    def get_stats(self) -> Dict:
        """Get comprehensive portfolio stats"""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0,
                'pnl': 0,
                'bankroll': self.current_bankroll
            }
        
        total_pnl = self.get_pnl()
        win_rate = self.get_win_rate(days=30)
        
        return {
            'total_trades': len(self.trades),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'current_bankroll': self.current_bankroll,
            'roi': (total_pnl / self.config['initial_bankroll']) * 100
        }
    
    def _get_peak_bankroll(self) -> float:
        """Get peak bankroll reached"""
        # Simplified - in reality would track over time
        return max(self.current_bankroll, self.config['initial_bankroll'])
