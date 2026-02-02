"""
Strategy Framework - Multi-strategy trading system
Runs multiple strategies and optimizes for most profitable
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class StrategyResult:
    """Result from a strategy execution"""
    strategy_name: str
    opportunities_found: int
    trades_executed: int
    profit_loss: float
    win_rate: float
    runtime_seconds: float
    errors: List[str]


class BaseStrategy(ABC):
    """Base class for all trading strategies"""
    
    def __init__(self, config: Dict, client):
        self.config = config
        self.client = client
        self.name = self.__class__.__name__
        self.trades = []
        self.errors = []
    
    @abstractmethod
    async def scan(self) -> List[Dict]:
        """Scan for opportunities. Returns list of opportunities."""
        pass
    
    @abstractmethod
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute trades. Returns number of trades executed."""
        pass
    
    @abstractmethod
    def get_performance(self) -> Dict:
        """Get strategy performance metrics"""
        pass
    
    def record_trade(self, trade: Dict):
        """Record a trade for performance tracking"""
        self.trades.append({
            **trade,
            'timestamp': datetime.now().isoformat(),
            'strategy': self.name
        })
    
    def record_error(self, error: str):
        """Record an error"""
        self.errors.append({
            'error': error,
            'timestamp': datetime.now().isoformat()
        })


class StrategyManager:
    """
    Manages multiple trading strategies
    - Runs all strategies in parallel
    - Tracks performance of each
    - Optimizes allocation based on profitability
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.strategies: List[BaseStrategy] = []
        self.performance_history: Dict[str, List[StrategyResult]] = {}
        self.allocations: Dict[str, float] = {}  # Capital allocation per strategy
    
    def register_strategy(self, strategy: BaseStrategy, allocation: float = 0.5):
        """
        Register a strategy with initial capital allocation
        
        Args:
            strategy: Strategy instance
            allocation: Fraction of capital (0.0-1.0)
        """
        self.strategies.append(strategy)
        self.performance_history[strategy.name] = []
        self.allocations[strategy.name] = allocation
        print(f"✅ Registered strategy: {strategy.name} (allocation: {allocation:.0%})")
    
    async def run_all(self) -> Dict[str, StrategyResult]:
        """
        Run all registered strategies
        
        Returns:
            Dict mapping strategy name to result
        """
        import asyncio
        import time
        
        results = {}
        
        print(f"\n🚀 Running {len(self.strategies)} strategies...")
        print("="*60)
        
        for strategy in self.strategies:
            start_time = time.time()
            
            try:
                # Run strategy
                opportunities = await strategy.scan()
                trades_executed = await strategy.execute(opportunities)
                
                # Get performance
                perf = strategy.get_performance()
                
                result = StrategyResult(
                    strategy_name=strategy.name,
                    opportunities_found=len(opportunities),
                    trades_executed=trades_executed,
                    profit_loss=perf.get('total_pnl', 0),
                    win_rate=perf.get('win_rate', 0),
                    runtime_seconds=time.time() - start_time,
                    errors=[e['error'] for e in strategy.errors[-5:]]  # Last 5 errors
                )
                
            except Exception as e:
                result = StrategyResult(
                    strategy_name=strategy.name,
                    opportunities_found=0,
                    trades_executed=0,
                    profit_loss=0,
                    win_rate=0,
                    runtime_seconds=time.time() - start_time,
                    errors=[str(e)]
                )
            
            results[strategy.name] = result
            self.performance_history[strategy.name].append(result)
        
        # Print summary
        self._print_summary(results)
        
        return results
    
    def _print_summary(self, results: Dict[str, StrategyResult]):
        """Print summary of all strategy results"""
        print("\n📊 STRATEGY PERFORMANCE SUMMARY")
        print("="*60)
        
        for name, result in results.items():
            print(f"\n{name}:")
            print(f"  Opportunities: {result.opportunities_found}")
            print(f"  Trades: {result.trades_executed}")
            print(f"  P&L: ${result.profit_loss:+.2f}")
            print(f"  Win Rate: {result.win_rate:.1%}")
            print(f"  Runtime: {result.runtime_seconds:.1f}s")
            if result.errors:
                print(f"  ⚠️  Recent errors: {len(result.errors)}")
        
        print("\n" + "="*60)
    
    def optimize_allocations(self):
        """
        Optimize capital allocations based on performance
        Shifts capital toward more profitable strategies
        """
        if not self.performance_history:
            return
        
        # Calculate recent performance (last 10 runs)
        recent_performance = {}
        
        for name, history in self.performance_history.items():
            if len(history) < 3:  # Need minimum data
                continue
            
            recent = history[-10:]  # Last 10 runs
            avg_pnl = sum(r.profit_loss for r in recent) / len(recent)
            win_rate = sum(r.win_rate for r in recent) / len(recent)
            
            # Score = weighted combination
            score = (avg_pnl * 0.7) + (win_rate * 100 * 0.3)
            recent_performance[name] = score
        
        if not recent_performance:
            return
        
        # Calculate new allocations
        total_score = sum(abs(s) for s in recent_performance.values()) or 1
        
        for name, score in recent_performance.items():
            # Normalize to positive weights
            weight = (score + abs(min(recent_performance.values()))) / total_score
            # Smooth transition (don't change too fast)
            old_alloc = self.allocations[name]
            new_alloc = old_alloc * 0.7 + weight * 0.3
            self.allocations[name] = max(0.1, min(0.9, new_alloc))  # Keep 10-90% bounds
        
        # Normalize to sum to 1.0
        total = sum(self.allocations.values())
        for name in self.allocations:
            self.allocations[name] /= total
        
        print("\n🎯 OPTIMIZED ALLOCATIONS:")
        for name, alloc in self.allocations.items():
            print(f"  {name}: {alloc:.1%}")
    
    def get_best_strategy(self) -> Optional[str]:
        """Get the name of the best performing strategy"""
        if not self.performance_history:
            return None
        
        # Calculate total P&L for each strategy
        total_pnl = {}
        for name, history in self.performance_history.items():
            total_pnl[name] = sum(r.profit_loss for r in history)
        
        if not total_pnl:
            return None
        
        return max(total_pnl, key=total_pnl.get)
    
    def export_results(self) -> Dict:
        """Export all results for analysis"""
        return {
            'allocations': self.allocations,
            'performance_history': {
                name: [
                    {
                        'timestamp': datetime.now().isoformat(),
                        'opportunities': r.opportunities_found,
                        'trades': r.trades_executed,
                        'pnl': r.profit_loss,
                        'win_rate': r.win_rate
                    }
                    for r in history
                ]
                for name, history in self.performance_history.items()
            },
            'best_strategy': self.get_best_strategy()
        }
