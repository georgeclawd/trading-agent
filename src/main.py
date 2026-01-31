"""
Trading Agent - Autonomous Trading System
Main orchestrator for market scanning, risk management, and trade execution
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

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
    Autonomous trading agent for Polymarket and crypto markets
    Runs 24/7, finds +EV opportunities, manages risk dynamically
    """
    
    def __init__(self):
        self.config = self._load_config()
        self.risk_manager = RiskManager(self.config)
        self.market_scanner = MarketScanner(self.config)
        self.whale_watcher = WhaleWatcher(self.config)
        self.trade_executor = TradeExecutor(self.config)
        self.portfolio = PortfolioTracker(self.config)
        self.alerts = AlertSystem(self.config)
        
        self.running = False
        self.trade_history: List[Dict] = []
        
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
            'max_position_size': 0.05,  # 5% max per trade
            'daily_loss_limit': 0.20,   # 20% daily stop
            'kelly_fraction': 0.25,     # Conservative Kelly
            'min_ev_threshold': 0.05,   # 5% +EV minimum
            'scan_interval': 300,       # 5 minutes between scans
            'markets': {
                'polymarket': True,
                'crypto': False,  # Enable later
            }
        }
    
    async def run(self):
        """Main trading loop - runs 24/7"""
        logger.info("🚀 Trading Agent starting...")
        logger.info(f"💰 Initial bankroll: ${self.config['initial_bankroll']}")
        
        self.running = True
        await self.alerts.send_alert("🚀 Trading Agent started", f"Bankroll: ${self.config['initial_bankroll']}")
        
        while self.running:
            try:
                await self._trading_cycle()
                await asyncio.sleep(self.config['scan_interval'])
                
            except Exception as e:
                logger.error(f"Error in trading cycle: {e}")
                await self.alerts.send_alert("❌ Trading Error", str(e))
                await asyncio.sleep(60)  # Wait before retry
    
    async def _trading_cycle(self):
        """Single trading cycle: scan → analyze → execute"""
        
        # 1. Update portfolio status
        current_bankroll = await self.portfolio.get_current_bankroll()
        win_rate = self.portfolio.get_win_rate(days=7)
        
        logger.info(f"📊 Bankroll: ${current_bankroll:.2f} | Win Rate (7d): {win_rate:.1f}%")
        
        # 2. Check risk limits
        if not self.risk_manager.can_trade(current_bankroll):
            logger.warning("⛔ Risk limits hit - skipping trades")
            return
        
        # 3. Scan for opportunities
        opportunities = await self.market_scanner.find_opportunities()
        
        # 3b. Check for whale trades (insider signals)
        whale_opps = await self.whale_watcher.get_all_opportunities(current_bankroll)
        if whale_opps:
            logger.info(f"🐋 Found {len(whale_opps)} whale copy opportunities")
            opportunities.extend(whale_opps)
        
        if not opportunities:
            logger.info("🔍 No +EV opportunities found")
            return
        
        logger.info(f"🔍 Found {len(opportunities)} potential trades")
        
        # 4. Filter and rank by EV
        valid_trades = []
        for opp in opportunities:
            ev = self.risk_manager.calculate_ev(opp)
            if ev > self.config['min_ev_threshold']:
                opp['expected_value'] = ev
                valid_trades.append(opp)
        
        valid_trades.sort(key=lambda x: x['expected_value'], reverse=True)
        
        # 5. Execute best trades
        for trade in valid_trades[:3]:  # Max 3 trades per cycle
            position_size = self.risk_manager.calculate_position_size(
                bankroll=current_bankroll,
                win_rate=win_rate,
                ev=trade['expected_value'],
                odds=trade['odds']
            )
            
            if position_size < 1.0:  # Minimum $1
                continue
            
            # Execute trade
            result = await self.trade_executor.execute_trade(trade, position_size)
            
            if result['success']:
                await self.portfolio.record_trade(result)
                await self.alerts.send_trade_notification(result)
                logger.info(f"✅ Executed: {trade['market']} | Size: ${position_size:.2f}")
                
                # Update bankroll for next calculation
                current_bankroll = await self.portfolio.get_current_bankroll()
            else:
                logger.error(f"❌ Trade failed: {result.get('error', 'Unknown')}")
    
    async def stop(self):
        """Graceful shutdown"""
        logger.info("🛑 Stopping Trading Agent...")
        self.running = False
        await self.alerts.send_alert("🛑 Trading Agent stopped", "All positions closed")


async def main():
    """Entry point"""
    agent = TradingAgent()
    
    try:
        await agent.run()
    except KeyboardInterrupt:
        await agent.stop()


if __name__ == '__main__':
    asyncio.run(main())
