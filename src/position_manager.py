"""
Position Manager - Handles persistence and tracking of all positions
Supports both real trading and dry-run (simulated) modes
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path
import logging

logger = logging.getLogger('PositionManager')


@dataclass
class Position:
    """Represents a trading position"""
    ticker: str
    side: str  # 'YES' or 'NO'
    contracts: int
    entry_price: float  # In cents (1-99)
    entry_time: str  # ISO format
    strategy: str
    simulated: bool
    market_title: str
    status: str = 'open'  # 'open', 'closed', 'cancelled'
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    pnl: Optional[float] = None
    expected_settlement: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Position':
        # Filter to only valid fields
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


class PositionManager:
    """
    Manages all trading positions with persistence
    Supports both real and simulated (dry-run) trading
    """
    
    def __init__(self, data_dir: str = '/root/clawd/trading-agent/data'):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.positions_file = self.data_dir / 'positions.json'
        self.simulated_file = self.data_dir / 'simulated_positions.json'
        
        # In-memory state
        self.positions: Dict[str, Position] = {}  # ticker -> Position
        self.simulated_positions: Dict[str, Position] = {}
        
        self._load_all()
    
    def _atomic_save(self, filepath: Path, data: Dict):
        """Atomically save data to file"""
        temp_file = filepath.with_suffix('.tmp')
        try:
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            os.replace(temp_file, filepath)
        except Exception as e:
            logger.error(f"Failed to save {filepath}: {e}")
            if temp_file.exists():
                temp_file.unlink()
            raise
    
    def _load_all(self):
        """Load all positions from disk"""
        # Load real positions
        if self.positions_file.exists():
            try:
                with open(self.positions_file, 'r') as f:
                    data = json.load(f)
                for ticker, pos_data in data.items():
                    self.positions[ticker] = Position.from_dict(pos_data)
                logger.info(f"Loaded {len(self.positions)} real positions")
            except Exception as e:
                logger.error(f"Failed to load positions: {e}")
                self._backup_corrupted(self.positions_file)
        
        # Load simulated positions
        if self.simulated_file.exists():
            try:
                with open(self.simulated_file, 'r') as f:
                    data = json.load(f)
                for ticker, pos_data in data.items():
                    self.simulated_positions[ticker] = Position.from_dict(pos_data)
                logger.info(f"Loaded {len(self.simulated_positions)} simulated positions")
            except Exception as e:
                logger.error(f"Failed to load simulated positions: {e}")
                self._backup_corrupted(self.simulated_file)
    
    def _backup_corrupted(self, filepath: Path):
        """Backup a corrupted file and start fresh"""
        if filepath.exists():
            backup = filepath.with_suffix(f'.corrupted.{datetime.now().strftime("%Y%m%d%H%M%S")}')
            os.rename(filepath, backup)
            logger.warning(f"Backed up corrupted file to {backup}")
    
    def clear_simulated_positions(self, backup: bool = True):
        """Clear all simulated positions (for weekly competition reset)"""
        if backup and self.simulated_positions:
            backup_file = self.data_dir / f'simulated_positions.backup.{datetime.now().strftime("%Y%m%d")}.json'
            try:
                data = {ticker: pos.to_dict() for ticker, pos in self.simulated_positions.items()}
                with open(backup_file, 'w') as f:
                    json.dump(data, f, indent=2, default=str)
                logger.info(f"Backed up {len(self.simulated_positions)} simulated positions to {backup_file}")
            except Exception as e:
                logger.error(f"Failed to backup simulated positions: {e}")
        
        count = len(self.simulated_positions)
        self.simulated_positions = {}
        self._save_simulated()
        logger.info(f"Cleared {count} simulated positions")
    
    def get_daily_performance(self, strategy: str = None, simulated: bool = False, date=None) -> Dict:
        """Get performance for a specific date (defaults to today)"""
        if date is None:
            date = datetime.now().date()
        
        positions_dict = self.simulated_positions if simulated else self.positions
        
        daily_positions = []
        unique_tickers = set()
        
        for pos in positions_dict.values():
            try:
                pos_date = datetime.fromisoformat(pos.entry_time).date()
                if pos_date == date:
                    if strategy is None or pos.strategy == strategy:
                        daily_positions.append(pos)
                        unique_tickers.add(pos.ticker)
            except:
                continue
        
        closed = [p for p in daily_positions if p.status == 'closed' and p.pnl is not None]
        total_pnl = sum(p.pnl for p in closed)
        
        return {
            'date': date.isoformat(),
            'strategy': strategy or 'all',
            'total_trades': len(daily_positions),
            'unique_markets': len(unique_tickers),
            'closed_trades': len(closed),
            'total_pnl': total_pnl,
            'tickers': list(unique_tickers)[:10]  # First 10 tickers
        }
    
    def _save_positions(self):
        """Save real positions to disk"""
        data = {ticker: pos.to_dict() for ticker, pos in self.positions.items()}
        self._atomic_save(self.positions_file, data)
    
    def _save_simulated(self):
        """Save simulated positions to disk"""
        data = {ticker: pos.to_dict() for ticker, pos in self.simulated_positions.items()}
        self._atomic_save(self.simulated_file, data)
    
    def has_open_position(self, ticker: str, simulated: bool = False) -> bool:
        """Check if we already have an OPEN position for this ticker"""
        positions_dict = self.simulated_positions if simulated else self.positions
        
        if ticker not in positions_dict:
            return False
        
        pos = positions_dict[ticker]
        # Only check if position is still open (not closed)
        return pos.status == 'open'
    
    def open_position(self, ticker: str, side: str, contracts: int, 
                      entry_price: float, strategy: str, simulated: bool,
                      market_title: str = '', expected_settlement: str = None,
                      check_duplicate: bool = True) -> Optional[Position]:
        """
        Record a new position
        
        Args:
            ticker: Market ticker
            side: 'YES' or 'NO'
            contracts: Number of contracts
            entry_price: Entry price in cents (1-99)
            strategy: Strategy name
            simulated: True for dry-run, False for real
            market_title: Human-readable market description
            expected_settlement: ISO datetime when market settles
            check_duplicate: If True, skip if position already exists today
        """
        # Check for duplicate (already have open position)
        if check_duplicate and self.has_open_position(ticker, simulated):
            logger.debug(f"PositionManager: Skipping {ticker} - already have open position")
            return None
        
        position = Position(
            ticker=ticker,
            side=side,
            contracts=contracts,
            entry_price=entry_price,
            entry_time=datetime.now().isoformat(),
            strategy=strategy,
            simulated=simulated,
            market_title=market_title,
            expected_settlement=expected_settlement
        )
        
        if simulated:
            self.simulated_positions[ticker] = position
            self._save_simulated()
            logger.info(f"[SIMULATED] Opened {ticker} {side} x{contracts} @ {entry_price}c")
        else:
            self.positions[ticker] = position
            self._save_positions()
            logger.info(f"[REAL] Opened {ticker} {side} x{contracts} @ {entry_price}c")
        
        return position
    
    def close_position(self, ticker: str, exit_price: float, 
                       pnl: float, simulated: bool) -> Optional[Position]:
        """
        Close a position and record P&L
        
        Args:
            ticker: Market ticker
            exit_price: Exit/settlement price in cents
            pnl: Profit/loss in dollars
            simulated: Whether this is a simulated position
        """
        positions_dict = self.simulated_positions if simulated else self.positions
        
        if ticker not in positions_dict:
            logger.warning(f"Cannot close {ticker}: position not found")
            return None
        
        position = positions_dict[ticker]
        position.status = 'closed'
        position.exit_price = exit_price
        position.exit_time = datetime.now().isoformat()
        position.pnl = pnl
        
        if simulated:
            self._save_simulated()
            logger.info(f"[SIMULATED] Closed {ticker} @ {exit_price}c, P&L: ${pnl:+.2f}")
        else:
            self._save_positions()
            logger.info(f"[REAL] Closed {ticker} @ {exit_price}c, P&L: ${pnl:+.2f}")
        
        return position
    
    def get_open_positions(self, strategy: str = None, simulated: bool = False) -> List[Position]:
        """Get all open positions, optionally filtered by strategy"""
        positions_dict = self.simulated_positions if simulated else self.positions
        
        open_pos = [p for p in positions_dict.values() if p.status == 'open']
        
        if strategy:
            open_pos = [p for p in open_pos if p.strategy == strategy]
        
        return open_pos
    
    def get_position(self, ticker: str, simulated: bool = False) -> Optional[Position]:
        """Get a specific position by ticker"""
        positions_dict = self.simulated_positions if simulated else self.positions
        return positions_dict.get(ticker)
    
    def get_performance(self, strategy: str = None, simulated: bool = False) -> Dict:
        """
        Get performance metrics
        
        Returns:
            Dict with trades, win_rate, total_pnl, open_positions
        """
        positions_dict = self.simulated_positions if simulated else self.positions
        
        if strategy:
            positions = [p for p in positions_dict.values() if p.strategy == strategy]
        else:
            positions = list(positions_dict.values())
        
        closed = [p for p in positions if p.status == 'closed' and p.pnl is not None]
        open_pos = [p for p in positions if p.status == 'open']
        
        total_trades = len(closed)
        winning_trades = sum(1 for p in closed if p.pnl > 0)
        total_pnl = sum(p.pnl for p in closed)
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'win_rate': winning_trades / total_trades if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'open_positions': len(open_pos),
            'avg_pnl_per_trade': total_pnl / total_trades if total_trades > 0 else 0
        }
    
    def get_all_performance(self) -> Dict[str, Dict]:
        """Get performance for all strategies (real and simulated)"""
        result = {}
        
        # Get all unique strategies
        all_strategies = set()
        for p in list(self.positions.values()) + list(self.simulated_positions.values()):
            all_strategies.add(p.strategy)
        
        for strategy in all_strategies:
            real_perf = self.get_performance(strategy, simulated=False)
            sim_perf = self.get_performance(strategy, simulated=True)
            
            result[strategy] = {
                'real': real_perf,
                'simulated': sim_perf,
                'combined_trades': real_perf['total_trades'] + sim_perf['total_trades'],
                'combined_pnl': real_perf['total_pnl'] + sim_perf['total_pnl']
            }
        
        return result
    
    def print_weekly_report(self):
        """Print a formatted weekly performance report"""
        all_perf = self.get_all_performance()
        
        logger.info("=" * 70)
        logger.info("📊 WEEKLY STRATEGY COMPETITION RESULTS")
        logger.info("=" * 70)
        logger.info(f"{'Strategy':<20} {'Type':<10} {'Trades':<8} {'Win%':<8} {'P&L':<12}")
        logger.info("-" * 70)
        
        for strategy, perf in sorted(all_perf.items(), 
                                      key=lambda x: x[1]['combined_pnl'], 
                                      reverse=True):
            real = perf['real']
            sim = perf['simulated']
            
            if real['total_trades'] > 0:
                logger.info(f"{strategy:<20} {'REAL':<10} {real['total_trades']:<8} "
                           f"{real['win_rate']*100:>6.1f}%  ${real['total_pnl']:>+8.2f}")
            
            if sim['total_trades'] > 0:
                logger.info(f"{'':<20} {'SIM':<10} {sim['total_trades']:<8} "
                           f"{sim['win_rate']*100:>6.1f}%  ${sim['total_pnl']:>+8.2f}")
            
            logger.info("-" * 70)
        
        # Determine winner (only real money counts for winner)
        real_performances = {s: p['real'] for s, p in all_perf.items() if p['real']['total_trades'] > 0}
        if real_performances:
            winner = max(real_performances.items(), key=lambda x: x[1]['total_pnl'])
            logger.info(f"🏆 WINNER (Real Money): {winner[0]} with ${winner[1]['total_pnl']:+.2f}")
        
        # Best simulated
        sim_performances = {s: p['simulated'] for s, p in all_perf.items() if p['simulated']['total_trades'] > 0}
        if sim_performances:
            best_sim = max(sim_performances.items(), key=lambda x: x[1]['total_pnl'])
            logger.info(f"🥈 BEST SIMULATED: {best_sim[0]} with ${best_sim[1]['total_pnl']:+.2f}")
        
        logger.info("=" * 70)

    def print_daily_summary(self, simulated: bool = True):
        """Print a nice summary of today's trading activity"""
        perf = self.get_daily_performance(simulated=simulated)
        
        logger.info("=" * 60)
        logger.info(f"📊 DAILY SUMMARY - {perf['date']}")
        logger.info("=" * 60)
        logger.info(f"Strategy: {perf['strategy']}")
        logger.info(f"Total Trades: {perf['total_trades']}")
        logger.info(f"Unique Markets: {perf['unique_markets']}")
        logger.info(f"Closed Trades: {perf['closed_trades']}")
        logger.info(f"Total P&L: ${perf['total_pnl']:+.2f}")
        
        if perf['tickers']:
            logger.info(f"Markets: {', '.join(perf['tickers'][:5])}")
            if len(perf['tickers']) > 5:
                logger.info(f"        ... and {len(perf['tickers']) - 5} more")
        
        logger.info("=" * 60)
