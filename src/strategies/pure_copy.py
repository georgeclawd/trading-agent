"""
Pure Copy Trading Strategy - Copy competitor trades exactly

Translates Polymarket trades to Kalshi equivalents in real-time
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from strategy_framework import BaseStrategy
import aiohttp
import subprocess

logger = logging.getLogger('PureCopyTrading')


class PureCopyStrategy(BaseStrategy):
    """
    Pure copy trading - When competitors trade on Polymarket,
    we copy immediately on Kalshi
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "PureCopy"
        
        # Competitor addresses to track
        self.competitors = {
            'distinct-baguette': '0xe00740bce98a594e26861838885ab310ec3b548c',
            '0x8dxd': '0x63ce342161250d705dc0b16df89036c8e5f9ba9a',
            'k9Q2mX4L8A7ZP3R': '0xd0d6053c3c37e727402d84c14069780d360993aa',
        }
        
        # Track last seen trades to avoid duplicates
        self.seen_trades = set()
        
        # Market cache
        self.pm_market_cache = {}
        self.kalshi_market_cache = {}
        
        logger.info("✅ Pure Copy Strategy initialized")
        logger.info(f"   Tracking {len(self.competitors)} competitors")
    
    def _get_est_time(self, utc_dt: datetime) -> str:
        """Convert UTC to EST for display"""
        from datetime import timedelta
        est = utc_dt - timedelta(hours=5)  # UTC-5 for EST
        return est.strftime('%I:%M %p EST')
    
    async def poll_competitors(self):
        """Poll Polymarket for competitor trades"""
        try:
            from competitor_tracker import PolymarketTracker
            tracker = PolymarketTracker()
            
            for name, address in self.competitors.items():
                try:
                    # Get recent activity
                    activity = tracker.get_user_activity(address, limit=5)
                    
                    for trade in activity:
                        tx_hash = trade.get('transaction_hash', '')
                        
                        # Skip if already processed
                        if tx_hash in self.seen_trades:
                            continue
                        
                        self.seen_trades.add(tx_hash)
                        
                        # Process new trade
                        await self._process_competitor_trade(name, trade)
                        
                except Exception as e:
                    logger.debug(f"Error polling {name}: {e}")
                    
        except Exception as e:
            logger.error(f"Poll error: {e}")
    
    async def _process_competitor_trade(self, competitor: str, trade: Dict):
        """Process a competitor trade and copy it"""
        side = trade.get('side', 'UNKNOWN')  # BUY or SELL
        size = float(trade.get('size', 0))
        price = float(trade.get('price', 0))
        asset_id = trade.get('asset', '')
        timestamp = trade.get('timestamp', 0)
        
        # Convert timestamp
        if isinstance(timestamp, (int, float)):
            trade_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            trade_time = datetime.now(timezone.utc)
        
        utc_str = trade_time.strftime('%H:%M UTC')
        est_str = self._get_est_time(trade_time)
        
        logger.info("=" * 70)
        logger.info(f"🚨 {competitor} TRADED! ({utc_str} / {est_str})")
        logger.info("=" * 70)
        logger.info(f"   Side: {side}")
        logger.info(f"   Size: ${size:.2f}")
        logger.info(f"   Price: {price:.0%}")
        logger.info(f"   Asset: {asset_id[:40]}...")
        
        # Look up Polymarket market
        pm_market = await self._lookup_pm_market(asset_id)
        
        if not pm_market:
            logger.warning("   Could not identify Polymarket market")
            return
        
        pm_slug = pm_market.get('marketSlug', 'Unknown')
        pm_question = pm_market.get('question', 'Unknown')
        
        logger.info(f"   Market: {pm_slug}")
        logger.info(f"   Question: {pm_question[:60]}...")
        
        # Find Kalshi equivalent
        kalshi_ticker = self._find_kalshi_equivalent(pm_slug, pm_question)
        
        if not kalshi_ticker:
            logger.warning("   No Kalshi equivalent found")
            return
        
        logger.info(f"   Kalshi: {kalshi_ticker}")
        
        # Determine side for Kalshi
        # Polymarket: BUY = buying YES, SELL = selling YES (buying NO)
        if side == 'BUY':
            kalshi_side = 'YES'
        else:
            kalshi_side = 'NO'
        
        # Calculate copy size (proportional)
        # Base: $10 per $100 they trade
        copy_size = max(1, int(size / 10))
        copy_size = min(copy_size, 10)  # Max 10 contracts
        
        logger.info(f"   Copying: {kalshi_side} x{copy_size} contracts")
        
        # Execute copy trade
        await self._execute_copy(kalshi_ticker, kalshi_side, copy_size, price)
    
    async def _lookup_pm_market(self, asset_id: str) -> Optional[Dict]:
        """Look up Polymarket market from asset ID"""
        if asset_id in self.pm_market_cache:
            return self.pm_market_cache[asset_id]
        
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://gamma-api.polymarket.com/markets"
                params = {"assetId": asset_id}
                
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        if isinstance(data, list) and data:
                            market = data[0]
                            self.pm_market_cache[asset_id] = market
                            return market
                        elif isinstance(data, dict) and data.get('markets'):
                            market = data['markets'][0]
                            self.pm_market_cache[asset_id] = market
                            return market
        except Exception as e:
            logger.debug(f"Error looking up market: {e}")
        
        return None
    
    def _find_kalshi_equivalent(self, pm_slug: str, pm_question: str) -> Optional[str]:
        """
        Map Polymarket market to Kalshi ticker
        
        Examples:
        - btc-updown-15m-1770147900 -> KXBTC15M-YYMMDDHHMM-XX
        - eth-updown-15m-1770147900 -> KXETH15M-YYMMDDHHMM-XX
        """
        import re
        from datetime import datetime
        
        slug_lower = pm_slug.lower()
        
        # Extract crypto type and timestamp
        # Format: btc-updown-15m-1770147900
        match = re.search(r'(btc|eth|sol)-updown-15m-(\d+)', slug_lower)
        
        if not match:
            logger.debug(f"Could not parse slug: {pm_slug}")
            return None
        
        crypto = match.group(1).upper()
        timestamp = int(match.group(2))
        
        # Convert timestamp to datetime
        dt = datetime.fromtimestamp(timestamp)
        
        # Map to Kalshi format
        crypto_map = {
            'BTC': 'KXBTC15M',
            'ETH': 'KXETH15M', 
            'SOL': 'KSOL15M',
        }
        
        if crypto not in crypto_map:
            return None
        
        series = crypto_map[crypto]
        
        # Format: YY MMM DD HHMM
        # Example: 26FEB031500
        month_map = {
            1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR',
            5: 'MAY', 6: 'JUN', 7: 'JUL', 8: 'AUG',
            9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
        }
        
        year_str = str(dt.year)[2:]  # Last 2 digits
        month_str = month_map.get(dt.month, 'XXX')
        day_str = f"{dt.day:02d}"
        hour_str = f"{dt.hour:02d}"
        min_str = f"{dt.minute:02d}"
        
        # For up/down markets, the strike is typically 00
        strike = "00"
        
        kalshi_ticker = f"{series}-{year_str}{month_str}{day_str}{hour_str}{min_str}-{strike}"
        
        return kalshi_ticker
    
    async def _execute_copy(self, ticker: str, side: str, size: int, price: float):
        """Execute the copy trade on Kalshi"""
        try:
            # Check if we already have position
            if self.position_manager and self.position_manager.has_open_position(ticker, self.dry_run):
                logger.info(f"   ⏸️  Already have position in {ticker}, skipping")
                return
            
            entry_price = int(price * 100)
            
            if self.dry_run:
                self.record_position(ticker, side, size, entry_price, ticker)
                logger.info(f"   📝 [SIM] Copied: {ticker} {side} x{size}")
            else:
                result = self.client.place_order(ticker, side.lower(), entry_price, size)
                
                if result.get('order_id'):
                    logger.info(f"   💰 [REAL] Copied: {ticker} {side} x{size} @ {entry_price}c - {result['order_id']}")
                    self.record_position(ticker, side, size, entry_price, ticker)
                else:
                    logger.error(f"   ❌ Copy failed: {result}")
                    
        except Exception as e:
            logger.error(f"   Error executing copy: {e}")
    
    async def continuous_trade_loop(self):
        """Main loop - poll competitors frequently"""
        logger.info("🔄 Pure Copy Strategy: Starting")
        logger.info(f"   Poll interval: 10 seconds")
        logger.info(f"   Competitors: {', '.join(self.competitors.keys())}")
        logger.info(f"   Display: EST (UTC-5)")
        
        while True:
            try:
                await self.poll_competitors()
                await asyncio.sleep(10)  # Poll every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(10)
    
    async def scan(self):
        """Scan is handled by polling"""
        return []
    
    async def execute(self, opportunities):
        """Execute is handled by polling"""
        return 0
    
    def get_performance(self):
        return {'name': self.name, 'trades': len(self.trades)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Pure Copy Trading Strategy")
    print("=" * 70)
    print("Copies competitor trades from Polymarket to Kalshi")
    print("Times displayed in EST (UTC-5)")
    print("=" * 70)
