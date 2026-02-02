"""
Trading Agent v2 - Multi-Strategy Trading System
Runs multiple strategies in parallel, optimizes for best performance
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Strategy framework
from strategy_framework import StrategyManager
from strategies import WeatherPredictionStrategy, SpreadTradingStrategy, CryptoMomentumStrategy

# Legacy components
from risk_manager import RiskManager
from market_scanner import MarketScanner
from trade_executor import TradeExecutor
from portfolio_tracker import PortfolioTracker
from alert_system import AlertSystem
from whale_watcher import WhaleWatcher

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/trading.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TradingAgent')


class TradingAgent:
    """
    Multi-strategy trading agent
    Runs WeatherPrediction + SpreadTrading in parallel
    Optimizes capital allocation based on performance
    """
    
    def __init__(self):
        self.config = self._load_config()
        self.strategy_manager = None
        self.kalshi_client = None
        
        # Legacy components (for WeatherPrediction strategy)
        self.risk_manager = RiskManager(self.config)
        self.market_scanner = MarketScanner(self.config)
        self.trade_executor = TradeExecutor(self.config)
        self.portfolio = PortfolioTracker(self.config)
        self.alerts = AlertSystem(self.config)
        
        self.running = False
        self.cycle_count = 0
        
    def _load_config(self) -> Dict:
        """Load trading configuration"""
        config_path = Path(__file__).parent.parent / 'config' / 'trading_config.yaml'
        if config_path.exists():
            import yaml
            with open(config_path) as f:
                return yaml.safe_load(f)
        return self._default_config()
    
    def _default_config(self) -> Dict:
        """Default configuration"""
        return {
            'initial_bankroll': 100.0,  # $100 starting
            'currency': 'USDC',
            'max_position_size': 5.0,   # $5 max per trade for testing
            'daily_loss_limit': 0.20,   # 20% daily stop
            'kelly_fraction': 0.25,     # Conservative Kelly
            'min_ev_threshold': 0.05,   # 5% +EV minimum
            'scan_interval': 300,       # 5 minutes between scans
            'simulation_mode': True,    # Default to simulation
            'strategies': {
                'weather_prediction': {
                    'enabled': True,
                    'allocation': 0.5,  # 50% capital
                },
                'spread_trading': {
                    'enabled': True,
                    'allocation': 0.5,  # 50% capital
                }
            }
        }
    
    async def _init_strategies(self):
        """Initialize strategy manager and register strategies"""
        logger.info("🎯 Initializing Strategy Manager...")
        
        self.strategy_manager = StrategyManager(self.config)
        
        # Create Kalshi client
        import subprocess
        from kalshi_client import KalshiClient
        
        api_key_id = subprocess.run(
            ['pass', 'show', 'kalshi/api_key_id'],
            capture_output=True, text=True
        ).stdout.strip().splitlines()[0]
        
        api_key = subprocess.run(
            ['pass', 'show', 'kalshi/api_key'],
            capture_output=True, text=True
        ).stdout.strip()
        
        self.kalshi_client = KalshiClient(api_key_id=api_key_id, api_key=api_key)
        
        # Register Weather Prediction Strategy
        if self.config.get('strategies', {}).get('weather_prediction', {}).get('enabled', True):
            weather_strategy = WeatherPredictionStrategy(
                config=self.config,
                client=self.kalshi_client,
                market_scanner=self.market_scanner
            )
            allocation = self.config['strategies']['weather_prediction'].get('allocation', 0.5)
            self.strategy_manager.register_strategy(weather_strategy, allocation)
        
        # Register Spread Trading Strategy
        if self.config.get('strategies', {}).get('spread_trading', {}).get('enabled', True):
            spread_strategy = SpreadTradingStrategy(
                config=self.config,
                client=self.kalshi_client
            )
            allocation = self.config['strategies']['spread_trading'].get('allocation', 0.33)
            self.strategy_manager.register_strategy(spread_strategy, allocation)
        
        # Register Crypto Momentum Strategy
        if self.config.get('strategies', {}).get('crypto_momentum', {}).get('enabled', True):
            crypto_strategy = CryptoMomentumStrategy(
                config=self.config,
                client=self.kalshi_client
            )
            allocation = self.config['strategies']['crypto_momentum'].get('allocation', 0.33)
            self.strategy_manager.register_strategy(crypto_strategy, allocation)
        
        logger.info(f"✅ Registered {len(self.strategy_manager.strategies)} strategies")
    
    async def run(self):
        """Main trading loop - runs 24/7 with multiple strategies"""
        logger.info("🚀 Trading Agent v2 starting...")
        logger.info(f"💰 Initial bankroll: ${self.config['initial_bankroll']}")
        logger.info(f"🎲 SIMULATION MODE: {'ENABLED' if self.config.get('simulation_mode', True) else 'DISABLED'}")
        
        # Initialize strategies
        await self._init_strategies()
        
        self.running = True
        await self.alerts.send_alert(
            "🚀 Trading Agent v2 Started", 
            f"Bankroll: ${self.config['initial_bankroll']}\nStrategies: {len(self.strategy_manager.strategies)}"
        )
        
        while self.running:
            try:
                self.cycle_count += 1
                logger.info(f"\n{'='*60}")
                logger.info(f"🔄 TRADING CYCLE #{self.cycle_count}")
                logger.info(f"{'='*60}")
                
                await self._trading_cycle()
                
                # Optimize allocations every 10 cycles
                if self.cycle_count % 10 == 0:
                    logger.info("🎯 Optimizing strategy allocations...")
                    self.strategy_manager.optimize_allocations()
                
                await asyncio.sleep(self.config['scan_interval'])
                
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}", exc_info=True)
                await self.alerts.send_alert("❌ Trading Error", str(e))
                await asyncio.sleep(60)
    
    async def _trading_cycle(self):
        """Execute all strategies"""
        
        # Get current portfolio status
        current_bankroll = await self.portfolio.get_current_bankroll()
        win_rate = self.portfolio.get_win_rate(days=7)
        
        logger.info(f"📊 Portfolio: ${current_bankroll:.2f} | Win Rate: {win_rate:.1f}%")
        
        # Check risk limits
        if not self.risk_manager.can_trade(current_bankroll):
            logger.warning("⛔ Risk limits hit - skipping cycle")
            return
        
        # Run all strategies
        results = await self.strategy_manager.run_all()
        
        # Log summary
        total_opportunities = sum(r.opportunities_found for r in results.values())
        total_trades = sum(r.trades_executed for r in results.values())
        
        logger.info(f"\n📈 CYCLE SUMMARY:")
        logger.info(f"   Total opportunities: {total_opportunities}")
        logger.info(f"   Total trades: {total_trades}")
        logger.info(f"   Simulation mode: {'YES' if self.config.get('simulation_mode', True) else 'NO'}")
        
        # Execute legacy trade flow for WeatherPrediction results
        # (This maintains backward compatibility)
        await self._execute_legacy_trades(results, current_bankroll, win_rate)
    
    async def _execute_legacy_trades(self, results: Dict, bankroll: float, win_rate: float):
        """Execute trades using legacy flow for WeatherPrediction strategy"""
        
        # Get WeatherPrediction results
        weather_result = results.get('WeatherPrediction')
        if not weather_result or weather_result.opportunities_found == 0:
            return
        
        # This maintains the old execution flow
        # In future, move this into the strategy itself
        logger.info(f"   (Legacy execution for {weather_result.opportunities_found} weather opportunities)")
    
    async def stop(self):
        """Graceful shutdown"""
        logger.info("🛑 Stopping Trading Agent...")
        self.running = False
        
        # Export final results
        if self.strategy_manager:
            results = self.strategy_manager.export_results()
            logger.info(f"📊 Final performance: {json.dumps(results, indent=2)}")
        
        await self.alerts.send_alert("🛑 Trading Agent stopped", "All strategies halted")


async def main():
    """Entry point"""
    agent = TradingAgent()
    
    try:
        await agent.run()
    except KeyboardInterrupt:
        await agent.stop()


if __name__ == '__main__':
    asyncio.run(main())
