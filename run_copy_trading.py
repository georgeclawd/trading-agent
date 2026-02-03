#!/usr/bin/env python3
"""
Simple Copy Trading Bot

Monitors Polymarket competitors and copies their trades on Kalshi
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('CopyTradingBot')

# Import our modules
import sys
sys.path.insert(0, 'src')
from competitor_tracker import PolymarketTracker
from kalshi_client import KalshiClient
import subprocess


class CopyTradingBot:
    def __init__(self):
        self.pm_tracker = PolymarketTracker()
        self.kalshi_client = self._init_kalshi()
        self.competitors = self._load_competitors()
        self.last_trades = {}
        
    def _init_kalshi(self):
        """Initialize Kalshi client with LIVE credentials"""
        try:
            api_key_id = subprocess.run(['pass', 'show', 'kalshi/api-key-id'], capture_output=True, text=True).stdout.strip().split('\n')[0]
            api_key = subprocess.run(['pass', 'show', 'kalshi/api-key'], capture_output=True, text=True).stdout.strip().split('\n')[0]
            
            return KalshiClient(api_key_id=api_key_id, api_key=api_key, demo=False)
        except Exception as e:
            logger.error(f"Failed to init Kalshi: {e}")
            return None
    
    def _load_competitors(self):
        """Load competitor list"""
        return [
            {"name": "distinct-baguette", "address": "0xe00740bce98a594e26861838885ab310ec3b548c"},
            {"name": "0x8dxd", "address": "0x63ce342161250d705dc0b16df89036c8e5f9ba9a"},
            {"name": "k9Q2mX4L8A7ZP3R", "address": "0xd0d6053c3c37e727402d84c14069780d360993aa"},
        ]
    
    async def poll_competitors(self):
        """Poll competitor activity and copy trades"""
        logger.info("🔍 Polling competitors for new trades...")
        
        for competitor in self.competitors:
            name = competitor['name']
            address = competitor['address']
            
            try:
                # Get recent activity
                activity = self.pm_tracker.get_user_activity(address, limit=5)
                
                for trade in activity:
                    trade_id = trade.get('transaction_hash', '')
                    
                    # Skip if we've already processed this trade
                    if trade_id in self.last_trades:
                        continue
                    
                    self.last_trades[trade_id] = trade
                    
                    # Process new trade
                    await self._process_trade(name, trade)
                    
            except Exception as e:
                logger.error(f"Error polling {name}: {e}")
    
    async def _process_trade(self, competitor_name: str, trade: Dict):
        """Process a competitor trade and copy it"""
        side = trade.get('side', 'UNKNOWN')
        size = trade.get('size', 0)
        price = trade.get('price', 0)
        asset_id = trade.get('asset', '')
        
        logger.info("=" * 60)
        logger.info(f"🚨 {competitor_name} TRADED!")
        logger.info("=" * 60)
        logger.info(f"   Side: {side}")
        logger.info(f"   Size: {size}")
        logger.info(f"   Price: {price:.2%}")
        logger.info(f"   Asset: {asset_id[:30]}...")
        
        # Look up the market
        market_info = await self._lookup_market(asset_id)
        
        if market_info:
            logger.info(f"   Market: {market_info.get('question', 'Unknown')}")
            
            # Find Kalshi equivalent
            kalshi_ticker = self._find_kalshi_market(market_info)
            
            if kalshi_ticker:
                logger.info(f"   Kalshi: {kalshi_ticker}")
                await self._copy_trade(kalshi_ticker, side, size, price)
            else:
                logger.warning("   No Kalshi equivalent found")
        else:
            logger.warning("   Could not identify market")
    
    async def _lookup_market(self, asset_id: str) -> Optional[Dict]:
        """Look up market info from asset ID"""
        # This would query Gamma API
        # For now, return None
        return None
    
    def _find_kalshi_market(self, pm_market: Dict) -> Optional[str]:
        """Find equivalent Kalshi market"""
        # This would implement the mapping logic
        # For now, return None
        return None
    
    async def _copy_trade(self, ticker: str, side: str, size: float, price: float):
        """Execute copy trade on Kalshi"""
        if not self.kalshi_client:
            logger.error("Kalshi client not initialized")
            return
        
        # Convert side
        kalshi_side = 'YES' if side == 'BUY' else 'NO'
        contracts = min(int(size), 10)
        entry_price = int(price * 100)
        
        logger.info(f"💰 COPYING: {ticker} {kalshi_side} x{contracts} @ {entry_price}c")
        
        # Place order
        try:
            result = self.kalshi_client.place_order(ticker, kalshi_side.lower(), entry_price, contracts)
            if result.get('order_id'):
                logger.info(f"✅ COPY SUCCESS: {result['order_id']}")
            else:
                logger.error(f"❌ COPY FAILED: {result}")
        except Exception as e:
            logger.error(f"Error copying: {e}")
    
    async def run(self):
        """Main loop"""
        logger.info("=" * 60)
        logger.info("🚀 COPY TRADING BOT STARTING")
        logger.info("=" * 60)
        logger.info("Monitoring competitors:")
        for c in self.competitors:
            logger.info(f"  • {c['name']}")
        logger.info("=" * 60)
        
        while True:
            try:
                await self.poll_competitors()
                await asyncio.sleep(30)  # Poll every 30 seconds
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(30)


if __name__ == "__main__":
    bot = CopyTradingBot()
    asyncio.run(bot.run())
