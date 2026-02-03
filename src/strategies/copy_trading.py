"""
Copy Trading Strategy - Copy successful competitor bets

When competitors trade on Polymarket, we copy them on Kalshi
"""

import asyncio
import json
import logging
from typing import Dict, Optional
from datetime import datetime
from strategy_framework import BaseStrategy
from competitor_websocket import PolymarketWebSocketTracker
import aiohttp

logger = logging.getLogger('CopyTrading')


class CopyTradingStrategy(BaseStrategy):
    """
    Copy successful competitors' trades from Polymarket to Kalshi
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "CopyTrading"
        self.ws_tracker = PolymarketWebSocketTracker()
        self.ws_tracker.on_trade(self._on_competitor_trade)
        self.recent_trades = []
        
        # Market mapping cache
        self.market_cache = {}
        
        logger.info("✅ Copy Trading strategy initialized")
        logger.info("   Will copy trades from: distinct-baguette, 0x8dxd, k9Q2mX4L8A7ZP3R")
    
    async def _on_competitor_trade(self, notification: Dict):
        """Called when a competitor makes a trade"""
        logger.info("=" * 60)
        logger.info("🚨 COMPETITOR TRADE DETECTED - COPY TRADING!")
        logger.info("=" * 60)
        
        competitor = notification['competitor']
        asset_id = notification.get('asset_id', '')
        side = notification['side']  # 'BUY' or 'SELL'
        size = notification['size']
        price = notification['price']
        
        logger.info(f"👤 Trader: {competitor}")
        logger.info(f"📊 Polymarket Asset: {asset_id[:30]}...")
        logger.info(f"📈 Side: {side}")
        logger.info(f"💰 Size: {size} @ {price}")
        
        # 1. Look up what market this is
        market_info = await self._lookup_polymarket_market(asset_id)
        
        if not market_info:
            logger.warning("⚠️  Could not identify Polymarket market")
            return
        
        logger.info(f"🎯 Market: {market_info.get('question', 'Unknown')}")
        logger.info(f"   Slug: {market_info.get('marketSlug', 'Unknown')}")
        
        # 2. Find equivalent Kalshi market
        kalshi_ticker = await self._find_kalshi_equivalent(market_info)
        
        if not kalshi_ticker:
            logger.warning("⚠️  No Kalshi equivalent found")
            return
        
        logger.info(f"✅ Kalshi equivalent: {kalshi_ticker}")
        
        # 3. Determine Kalshi side
        # Polymarket side: BUY = buying YES, SELL = selling YES (buying NO)
        # Kalshi side: YES or NO
        pm_outcome = market_info.get('outcome', 'Unknown')
        
        if side == 'BUY':
            # They're buying YES on Polymarket
            kalshi_side = 'YES'
        else:
            # They're selling YES (effectively buying NO)
            kalshi_side = 'NO'
        
        logger.info(f"📊 Copying trade: {kalshi_side} on {kalshi_ticker}")
        
        # 4. Execute copy trade
        await self._execute_copy_trade(kalshi_ticker, kalshi_side, size, price)
    
    async def _lookup_polymarket_market(self, asset_id: str) -> Optional[Dict]:
        """Look up Polymarket market details from asset ID"""
        try:
            # Check cache first
            if asset_id in self.market_cache:
                return self.market_cache[asset_id]
            
            # Query Gamma API
            async with aiohttp.ClientSession() as session:
                url = f"https://gamma-api.polymarket.com/markets"
                params = {"assetId": asset_id}
                
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            market = data[0]
                            self.market_cache[asset_id] = market
                            return market
                        elif isinstance(data, dict) and 'markets' in data:
                            markets = data['markets']
                            if markets:
                                market = markets[0]
                                self.market_cache[asset_id] = market
                                return market
        except Exception as e:
            logger.error(f"Error looking up market: {e}")
        
        return None
    
    async def _find_kalshi_equivalent(self, pm_market: Dict) -> Optional[str]:
        """
        Find equivalent Kalshi market
        
        This is the key mapping function:
        - Polymarket weather markets -> Kalshi weather markets
        - Based on location, date, and metric
        """
        try:
            slug = pm_market.get('marketSlug', '').lower()
            question = pm_market.get('question', '').lower()
            
            # Extract key info from Polymarket market
            # Example: "nyc-weather-feb-3-2025-high-temp"
            # Or: "Will NYC have a high temp above 45°F on Feb 3?"
            
            # Parse location
            location = None
            for loc in ['nyc', 'new york', 'chicago', 'boston', 'miami', 'la', 'los angeles']:
                if loc in slug or loc in question:
                    location = loc
                    break
            
            # Parse date
            import re
            date_match = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})', question)
            
            # Parse metric (temp, rain, snow)
            metric = None
            if 'temp' in question or 'high' in question or 'low' in question:
                metric = 'TEMP'
            elif 'rain' in question:
                metric = 'RAIN'
            elif 'snow' in question:
                metric = 'SNOW'
            
            logger.info(f"   Parsed: location={location}, metric={metric}")
            
            # Now find matching Kalshi market
            # This would query Kalshi API for markets matching these criteria
            # For now, return a placeholder
            
            # Example mapping
            if location == 'nyc' and metric == 'TEMP':
                return "KXWEATHER-NYC-TEMP-20250203"  # Placeholder
            
            return None
            
        except Exception as e:
            logger.error(f"Error finding Kalshi equivalent: {e}")
            return None
    
    async def _execute_copy_trade(self, ticker: str, side: str, size: float, price: float):
        """Execute the copy trade on Kalshi"""
        try:
            # Check if we already have a position
            if self.position_manager and self.position_manager.has_open_position(ticker, self.dry_run):
                logger.info(f"⏸️  Already have position in {ticker}, skipping")
                return
            
            # Size adjustment - copy proportional size
            # But cap at max position size
            contracts = min(int(size), 10)  # Max 10 contracts
            if contracts < 1:
                contracts = 1
            
            entry_price_cents = int(price * 100)
            
            if self.dry_run:
                self.record_position(ticker, side, contracts, entry_price_cents, ticker)
                logger.info(f"📝 [SIM] Copy trade: {ticker} {side} x{contracts} @ {entry_price_cents}c")
            else:
                result = self.client.place_order(ticker, side.lower(), entry_price_cents, contracts)
                if result.get('order_id'):
                    logger.info(f"💰 [REAL COPY] {ticker} {side} x{contracts} @ {entry_price_cents}c")
                    self.record_position(ticker, side, contracts, entry_price_cents, ticker)
                else:
                    logger.error(f"❌ Copy trade failed: {result}")
                    
        except Exception as e:
            logger.error(f"Error executing copy trade: {e}")
    
    async def continuous_trade_loop(self):
        """Run the WebSocket listener in background"""
        logger.info("🔄 Copy Trading: Starting WebSocket listener...")
        
        # Start WebSocket in background
        ws_task = asyncio.create_task(self.ws_tracker.run_forever())
        
        # Keep running
        while True:
            try:
                await asyncio.sleep(60)
                logger.debug("Copy trading listening...")
            except asyncio.CancelledError:
                ws_task.cancel()
                break
            except Exception as e:
                logger.error(f"Copy trading loop error: {e}")
                await asyncio.sleep(60)
    
    async def scan(self):
        """Scan is handled by WebSocket callbacks"""
        return []
    
    async def execute(self, opportunities):
        """Execute is handled by WebSocket callbacks"""
        return 0
    
    def get_performance(self):
        return {'name': self.name, 'trades': len(self.trades)}


# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("Copy Trading Strategy Test")
    print("=" * 60)
    print("This strategy will:")
    print("1. Monitor competitor trades on Polymarket via WebSocket")
    print("2. Identify the market they're trading")
    print("3. Find equivalent market on Kalshi")
    print("4. Copy their trade (same side, proportional size)")
    print("=" * 60)
