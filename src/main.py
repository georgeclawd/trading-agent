"""
Trading Agent v2 - Multi-Strategy Trading System
Runs multiple strategies in parallel, optimizes for best performance
"""

import asyncio
import json
import logging
import pytz
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Strategy framework
from strategy_framework import StrategyManager
from strategies import WeatherPredictionStrategy, SpreadTradingStrategy, CryptoMomentumStrategy, LongshotWeatherStrategy
try:
    from strategies.pure_copy import PureCopyStrategy
    PURE_COPY_AVAILABLE = True
except ImportError:
    PURE_COPY_AVAILABLE = False
from position_manager import PositionManager

# Legacy components
from risk_manager import RiskManager
from market_scanner import MarketScanner
from trade_executor import TradeExecutor
from portfolio_tracker import PortfolioTracker
from alert_system import AlertSystem
from whale_watcher import WhaleWatcher

# Timezone setup
EST = pytz.timezone('America/New_York')

def now_est() -> datetime:
    """Get current time in EST"""
    return datetime.now(EST)

def format_est(dt: datetime = None) -> str:
    """Format datetime as EST string"""
    if dt is None:
        dt = now_est()
    return dt.strftime('%Y-%m-%d %H:%M:%S EST')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/trading.log')
        # Note: StreamHandler removed to avoid duplicate logs when using shell redirect
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
        self.position_manager = None
        
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
                    'allocation': 0.25,
                    'dry_run': True,     # Simulated trading
                },
                'spread_trading': {
                    'enabled': True,
                    'allocation': 0.25,
                    'dry_run': True,     # Simulated trading
                },
                'crypto_momentum': {
                    'enabled': True,
                    'allocation': 0.25,
                    'dry_run': False,    # REAL MONEY - Crypto trades live
                },
                'longshot_weather': {
                    'enabled': True,
                    'allocation': 0.25,
                    'dry_run': True,     # Simulated trading
                }
            }
        }
    
    async def _init_strategies(self):
        """Initialize strategy manager and register strategies"""
        logger.info("🎯 Initializing Strategy Manager...")
        
        self.strategy_manager = StrategyManager(self.config)
        
        # Initialize Position Manager for tracking all positions
        self.position_manager = PositionManager()
        
        # Create Kalshi client
        import subprocess
        from kalshi_client import KalshiClient
        
        # Check if demo mode is enabled
        demo_mode = self.config.get('demo_mode', False)
        
        if demo_mode:
            logger.info("🎮 DEMO MODE: Using paper trading environment")
            api_key_id = subprocess.run(
                ['pass', 'show', 'kalshi/demo_api_key_id'],
                capture_output=True, text=True
            ).stdout.strip().splitlines()[0]
            
            api_key = subprocess.run(
                ['pass', 'show', 'kalshi/demo_api_key'],
                capture_output=True, text=True
            ).stdout.strip()
            
            self.kalshi_client = KalshiClient(api_key_id=api_key_id, api_key=api_key, demo=True)
        else:
            logger.info("💰 LIVE MODE: Using real money!")
            api_key_id = subprocess.run(
                ['pass', 'show', 'kalshi/api_key_id'],
                capture_output=True, text=True
            ).stdout.strip().splitlines()[0]
            
            api_key = subprocess.run(
                ['pass', 'show', 'kalshi/api_key'],
                capture_output=True, text=True
            ).stdout.strip()
            
            self.kalshi_client = KalshiClient(api_key_id=api_key_id, api_key=api_key, demo=False)
        
        # Test connection to verify API keys work
        logger.info("🔐 Testing Kalshi connection...")
        if not self.kalshi_client.test_connection():
            logger.error("❌ Kalshi connection failed - check API keys")
            raise Exception("Kalshi API connection failed")
        logger.info("✅ Kalshi connected successfully")
        
        # Register Weather Prediction Strategy (DRY RUN)
        weather_cfg = self.config.get('strategies', {}).get('weather_prediction', {})
        if weather_cfg.get('enabled', True):
            weather_strategy = WeatherPredictionStrategy(
                config={**self.config, 'dry_run': weather_cfg.get('dry_run', True)},
                client=self.kalshi_client,
                market_scanner=self.market_scanner,
                position_manager=self.position_manager
            )
            allocation = weather_cfg.get('allocation', 0.25)
            self.strategy_manager.register_strategy(weather_strategy, allocation)
        
        # Register Spread Trading Strategy (DRY RUN)
        spread_cfg = self.config.get('strategies', {}).get('spread_trading', {})
        if spread_cfg.get('enabled', True):
            spread_strategy = SpreadTradingStrategy(
                config={**self.config, 'dry_run': spread_cfg.get('dry_run', True)},
                client=self.kalshi_client,
                position_manager=self.position_manager
            )
            allocation = spread_cfg.get('allocation', 0.25)
            self.strategy_manager.register_strategy(spread_strategy, allocation)
        
        # Register Crypto Momentum Strategy (REAL MONEY!)
        crypto_cfg = self.config.get('strategies', {}).get('crypto_momentum', {})
        if crypto_cfg.get('enabled', True):
            crypto_strategy = CryptoMomentumStrategy(
                config={**self.config, 'dry_run': crypto_cfg.get('dry_run', False)},
                client=self.kalshi_client,
                position_manager=self.position_manager
            )
            allocation = crypto_cfg.get('allocation', 0.25)
            self.strategy_manager.register_strategy(crypto_strategy, allocation)
        
        # Register Longshot Weather Strategy ($64K bot algorithm) (DRY RUN)
        longshot_cfg = self.config.get('strategies', {}).get('longshot_weather', {})
        if longshot_cfg.get('enabled', True):
            longshot_strategy = LongshotWeatherStrategy(
                config={**self.config, 'dry_run': longshot_cfg.get('dry_run', True)},
                client=self.kalshi_client,
                market_scanner=self.market_scanner,
                position_manager=self.position_manager
            )
            allocation = longshot_cfg.get('allocation', 0.25)
            self.strategy_manager.register_strategy(longshot_strategy, allocation)
        
        # Register Pure Copy Strategy (LIVE - Copy competitors)
        if PURE_COPY_AVAILABLE:
            pure_copy_cfg = self.config.get('strategies', {}).get('PureCopy', {})
            if pure_copy_cfg.get('enabled', False):
                pure_copy_strategy = PureCopyStrategy(
                    config={**self.config, 'dry_run': pure_copy_cfg.get('dry_run', False)},
                    client=self.kalshi_client,
                    position_manager=self.position_manager
                )
                allocation = pure_copy_cfg.get('allocation', 0.50)
                # Ensure allocation is a fraction (0.0-1.0), not percentage
                if allocation > 1.0:
                    allocation = allocation / 100.0
                self.strategy_manager.register_strategy(pure_copy_strategy, allocation)
                logger.info("✅ Pure Copy strategy registered - copying competitor trades")
        
        logger.info(f"✅ Registered {len(self.strategy_manager.strategies)} strategies")
        
        # Print active strategies
        logger.info("🏆 ACTIVE STRATEGIES:")
        for strategy in self.strategy_manager.strategies:
            mode = "LIVE" if not getattr(strategy, 'dry_run', True) else "DRY RUN"
            logger.info(f"   {strategy.name}: {mode}")
    
    async def _price_fetcher_loop(self):
        """
        Background task to fetch prices every minute for CryptoMomentum strategy
        """
        logger.info("📈 Starting multi-asset price fetcher (1-minute intervals)")
        
        # Get crypto strategy
        crypto_strategy = None
        for strategy in self.strategy_manager.strategies:
            if strategy.name == "CryptoMomentum":
                crypto_strategy = strategy
                break
        
        if not crypto_strategy:
            logger.warning("CryptoMomentum strategy not found, price fetcher stopping")
            return
        
        cycle_count = 0
        while self.running:
            cycle_count += 1
            try:
                logger.debug(f"Price fetcher cycle #{cycle_count}")
                
                # Fetch 1m candles for all assets (this updates the price history)
                await crypto_strategy.fetch_1m_candles()
                
                # Check candle counts for all assets
                assets_ready = 0
                total_candles = 0
                for asset, info in crypto_strategy.assets.items():
                    num_candles = len(info.get('candles', []))
                    total_candles += num_candles
                    if num_candles >= 30:
                        assets_ready += 1
                
                # Log progress periodically
                if total_candles > 0:
                    if assets_ready < len(crypto_strategy.assets):
                        # Log every minute until all assets have 30 candles
                        asset_status = ', '.join([f"{a}:{len(i.get('candles', []))}" for a, i in crypto_strategy.assets.items()])
                        logger.info(f"📊 Candles - {asset_status} - {format_est()}")
                    else:
                        # All assets ready
                        if cycle_count % 60 == 0:  # Log every hour
                            logger.info(f"✅ All assets ready! Trading BTC, ETH, SOL - {format_est()}")
                else:
                    logger.warning(f"Price fetcher: No candles yet - {format_est()}")
                
                # Wait 60 seconds
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                logger.info("Price fetcher cancelled")
                break
            except Exception as e:
                logger.error(f"Price fetcher error: {e}", exc_info=True)
                await asyncio.sleep(60)
    
    async def run(self):
        """Main trading loop - runs 24/7 with multiple strategies"""
        logger.info(f"🚀 Trading Agent v2 starting... - {format_est()}")
        logger.info(f"💰 Initial bankroll: ${self.config['initial_bankroll']}")
        logger.info(f"🎲 SIMULATION MODE: {'ENABLED' if self.config.get('simulation_mode', True) else 'DISABLED'}")
        logger.info(f"🕐 All times shown in EST (Eastern)")
        
        # Initialize strategies
        await self._init_strategies()
        
        self.running = True
        await self.alerts.send_alert(
            "🚀 Trading Agent v2 Started", 
            f"Bankroll: ${self.config['initial_bankroll']}\nStrategies: {len(self.strategy_manager.strategies)}"
        )
        
        # Start background price fetcher
        price_fetcher_task = asyncio.create_task(self._price_fetcher_loop())
        
        # Start independent strategy loops with different intervals
        strategy_tasks = []
        for strategy in self.strategy_manager.strategies:
            logger.info(f"🔄 Starting loop for {strategy.name}...")
            try:
                task = asyncio.create_task(self._run_strategy_with_error_handling(strategy))
                strategy_tasks.append(task)
                logger.info(f"✅ Created task for {strategy.name}")
            except Exception as e:
                logger.error(f"❌ Failed to create task for {strategy.name}: {e}", exc_info=True)
        
        # Keep main loop alive
        while self.running:
            try:
                await asyncio.sleep(60)  # Just keep alive, strategies run independently
                
                # Optimize allocations every hour
                if self.cycle_count > 0 and self.cycle_count % 12 == 0:
                    logger.info("🎯 Optimizing strategy allocations...")
                    self.strategy_manager.optimize_allocations()
                    
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(60)
        
        # Clean up
        price_fetcher_task.cancel()
        for task in strategy_tasks:
            task.cancel()
    
    async def _run_strategy_with_error_handling(self, strategy):
        """Wrapper to catch errors in strategy loops"""
        try:
            logger.info(f"🛡️ Error handler started for {strategy.name}")
            await self._strategy_loop(strategy)
            logger.info(f"🛡️ Error handler completed for {strategy.name}")
        except Exception as e:
            logger.error(f"💥 CRITICAL ERROR in {strategy.name} loop: {e}", exc_info=True)
    
    async def _strategy_loop(self, strategy):
        """Run a single strategy in its own loop with its own interval"""
        logger.info(f"📍 _strategy_loop() entered for {strategy.name}")
        
        # Map strategy names to config keys
        name_to_key = {
            'WeatherPrediction': 'weather_prediction',
            'SpreadTrading': 'spread_trading',
            'CryptoMomentum': 'crypto_momentum',
            'LongshotWeather': 'longshot_weather',
            'PureCopy': 'pure_copy'
        }
        config_key = name_to_key.get(strategy.name, strategy.name.lower())
        strategy_config = self.config.get('strategies', {}).get(config_key, {})
        # Use 300 seconds (5 min) as default if not specified
        interval = strategy_config.get('scan_interval', self.config.get('scan_interval', 300))
        
        # Convert interval to minutes for display
        interval_min = interval // 60
        
        logger.info(f"📍 Checking if {strategy.name} uses continuous loop...")
        # For strategies with continuous loops, use their own loop
        if strategy.name in ["CryptoMomentum", "PureCopy"]:
            logger.info(f"📍 {strategy.name} matches continuous loop list, calling _run_crypto_momentum_loop")
            await self._run_crypto_momentum_loop(strategy)
        else:
            logger.info(f"📍 {strategy.name} using regular loop")
            await self._run_strategy_loop(strategy, interval, interval_min)
        
        logger.info(f"📍 _strategy_loop() completed for {strategy.name}")
    
    async def _run_crypto_momentum_loop(self, strategy):
        """Run strategy in continuous trading mode"""
        logger.info(f"🚀 _run_crypto_momentum_loop() called for {strategy.name}")
        logger.info(f"🚀 Starting {strategy.name} continuous trading - {format_est()}")
        if strategy.name == "CryptoMomentum":
            logger.info("📈 Trading every minute within 15-min windows")
        elif strategy.name == "PureCopy":
            logger.info("👥 Copying competitor trades in real-time")
        
        # Run the strategy's continuous loop
        logger.info(f"📍 About to call {strategy.name}.continuous_trade_loop()")
        try:
            await strategy.continuous_trade_loop()
            logger.info(f"📍 {strategy.name}.continuous_trade_loop() returned")
        except Exception as e:
            logger.error(f"❌ Error in {strategy.name} continuous loop: {e}", exc_info=True)
        logger.info(f"📍 _run_crypto_momentum_loop() completed for {strategy.name}")
    
    async def _run_strategy_loop(self, strategy, interval, interval_min, aligned=False):
        """Run strategy in regular loop"""
        if aligned:
            logger.info(f"🔄 {strategy.name} STARTING at 15-min boundary - {format_est()}")
        else:
            logger.info(f"🔄 Starting {strategy.name} loop (every {interval_min} min) - {format_est()}")
        
        while self.running:
            try:
                import time
                start_time = time.time()
                
                # Run strategy
                opportunities = await strategy.scan()
                trades_executed = await strategy.execute(opportunities)
                
                runtime = time.time() - start_time
                
                if opportunities or trades_executed:
                    logger.info(f"📊 {strategy.name}: {len(opportunities)} opportunities, {trades_executed} trades ({runtime:.1f}s) - {format_est()}")
                else:
                    logger.debug(f"📊 {strategy.name}: No opportunities ({runtime:.1f}s) - {format_est()}")
                
                self.cycle_count += 1
                
                # Calculate and log next run time
                next_run = now_est() + timedelta(seconds=interval)
                logger.info(f"⏰ {strategy.name}: Next run at {next_run.strftime('%H:%M:%S EST')}")
                
                # Sleep until next cycle
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"❌ {strategy.name} error: {e} - {format_est()}")
                await asyncio.sleep(interval)
    
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
