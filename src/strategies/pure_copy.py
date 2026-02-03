"""
Pure Copy Trading Strategy - Copy competitor trades exactly

Translates Polymarket trades to Kalshi equivalents in real-time
Uses CURRENT 15-minute markets based on time
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from strategy_framework import BaseStrategy
import aiohttp

logger = logging.getLogger('PureCopyTrading')


class PureCopyStrategy(BaseStrategy):
    """
    Pure copy trading - When competitors trade on Polymarket,
    we copy immediately on Kalshi using CURRENT markets
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
        
        # Get competitor bankroll estimates (from observed profits)
        self.competitor_bankrolls = {
            'distinct-baguette': 6800,   # $6.8k profit today
            '0x8dxd': 47000,             # $47k profit today
            'k9Q2mX4L8A7ZP3R': 51000,    # $51k profit today
        }
        
        # Track last seen trades to avoid duplicates
        self.seen_trades = set()
        
        # Market cache
        self.pm_market_cache = {}
        
        # Our bankroll
        self.our_bankroll = config.get('initial_bankroll', 100.0)
        
        logger.info("✅ Pure Copy Strategy initialized")
        logger.info(f"   Tracking {len(self.competitors)} competitors")
        logger.info(f"   Our bankroll: ${self.our_bankroll:,.2f}")
    
    def _get_est_time(self, utc_dt: datetime) -> str:
        """Convert UTC to EST for display"""
        est = utc_dt - timedelta(hours=5)  # UTC-5 for EST
        return est.strftime('%I:%M %p EST')
    
    def _get_current_15m_window(self) -> tuple:
        """
        Get the current 15-minute window
        Returns: (window_start, window_end) as UTC datetimes
        """
        now = datetime.now(timezone.utc)
        
        # Find the start of current 15-min window
        # Windows start at :00, :15, :30, :45
        minute = now.minute
        window_start_minute = (minute // 15) * 15
        
        window_start = now.replace(minute=window_start_minute, second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=15)
        
        return window_start, window_end
    
    def _generate_kalshi_ticker(self, crypto: str, timestamp: int = None) -> str:
        """
        Generate Kalshi ticker for CURRENT 15-min window
        
        Args:
            crypto: 'BTC', 'ETH', or 'SOL'
            timestamp: Optional specific timestamp (if not provided, uses current time)
        """
        if timestamp:
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            # Use current 15-min window
            window_start, _ = self._get_current_15m_window()
            dt = window_start
        
        # Map to series
        series_map = {
            'BTC': 'KXBTC15M',
            'ETH': 'KXETH15M',
            'SOL': 'KSOL15M',
        }
        
        if crypto not in series_map:
            return None
        
        series = series_map[crypto]
        
        # Format: YY MMM DD HHMM
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
        
        # Strike is 00 for up/down markets
        strike = "00"
        
        return f"{series}-{year_str}{month_str}{day_str}{hour_str}{min_str}-{strike}"
    
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
        
        # Get current 15-min window
        window_start, window_end = self._get_current_15m_window()
        
        logger.info("=" * 70)
        logger.info(f"🚨 {competitor} TRADED! ({utc_str} / {est_str})")
        logger.info(f"   Current 15-min window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')} UTC")
        logger.info("=" * 70)
        logger.info(f"   Side: {side}")
        logger.info(f"   Size: ${size:.2f}")
        logger.info(f"   Price: {price:.0%}")
        
        # Look up Polymarket market to identify crypto type
        pm_market = await self._lookup_pm_market(asset_id)
        
        if not pm_market:
            # Try to infer from asset_id or use current time
            logger.warning("   Could not identify market, trying BTC/ETH/SOL current windows")
            # Try all three and see which has liquidity
            for crypto in ['BTC', 'ETH', 'SOL']:
                kalshi_ticker = self._generate_kalshi_ticker(crypto)
                if kalshi_ticker:
                    await self._try_copy_trade(competitor, kalshi_ticker, side, size, price)
            return
        
        pm_slug = pm_market.get('marketSlug', 'Unknown')
        pm_question = pm_market.get('question', 'Unknown')
        
        logger.info(f"   Market: {pm_slug}")
        
        # Determine crypto type from market
        crypto = self._detect_crypto_type(pm_slug, pm_question)
        
        if not crypto:
            logger.warning(f"   Could not detect crypto type from: {pm_slug}")
            return
        
        logger.info(f"   Crypto: {crypto}")
        
        # Generate Kalshi ticker for CURRENT 15-min window
        kalshi_ticker = self._generate_kalshi_ticker(crypto)
        
        if not kalshi_ticker:
            logger.error("   Could not generate Kalshi ticker")
            return
        
        logger.info(f"   Kalshi (current window): {kalshi_ticker}")
        
        # Determine side for Kalshi
        if side == 'BUY':
            kalshi_side = 'YES'
        else:
            kalshi_side = 'NO'
        
        # Calculate copy size based on bankroll ratio
        competitor_bankroll = self.competitor_bankrolls.get(competitor, 50000)  # Default $50k
        bankroll_ratio = self.our_bankroll / competitor_bankroll
        
        # Their size in contracts (approximate)
        their_contracts = max(1, int(size / price / 10))  # Rough estimate
        
        # Our copy size
        copy_contracts = max(1, int(their_contracts * bankroll_ratio))
        copy_contracts = min(copy_contracts, 10)  # Cap at 10
        
        logger.info(f"   Sizing: They have ${competitor_bankroll:,.0f}, we have ${self.our_bankroll:,.0f}")
        logger.info(f"   Ratio: {bankroll_ratio:.1%}")
        logger.info(f"   They traded ~{their_contracts} contracts")
        logger.info(f"   We copy: {copy_contracts} contracts")
        logger.info(f"   Copying: {kalshi_side} x{copy_contracts}")
        
        # Execute copy trade
        await self._execute_copy(kalshi_ticker, kalshi_side, copy_contracts, price)
    
    async def _try_copy_trade(self, ticker: str, side: str, size: float, price: float):
        """Try to copy trade on a specific ticker"""
        try:
            # Check if market exists and has liquidity
            orderbook = self.client.get_orderbook(ticker)
            if not orderbook or 'orderbook' not in orderbook:
                return False
            
            yes_bids = orderbook['orderbook'].get('yes', [])
            no_bids = orderbook['orderbook'].get('no', [])
            
            if not yes_bids or not no_bids:
                return False
            
            # Market exists, execute trade
            kalshi_side = 'YES' if side == 'BUY' else 'NO'
            contracts = min(max(1, int(size / 10)), 5)  # Conservative sizing
            
            await self._execute_copy(ticker, kalshi_side, contracts, price)
            return True
            
        except Exception as e:
            logger.debug(f"Could not trade {ticker}: {e}")
            return False
    
    def _detect_crypto_type(self, slug: str, question: str) -> Optional[str]:
        """Detect if market is BTC, ETH, or SOL"""
        text = (slug + " " + question).lower()
        
        if 'btc' in text or 'bitcoin' in text:
            return 'BTC'
        elif 'eth' in text or 'ethereum' in text:
            return 'ETH'
        elif 'sol' in text or 'solana' in text:
            return 'SOL'
        
        return None
    
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
        window_start, window_end = self._get_current_15m_window()
        
        logger.info("=" * 70)
        logger.info("🔄 PURE COPY STRATEGY STARTED")
        logger.info("=" * 70)
        logger.info(f"Current 15-min window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')} UTC")
        logger.info(f"EST time: {self._get_est_time(window_start)} - {self._get_est_time(window_end)}")
        logger.info(f"Poll interval: 10 seconds")
        logger.info(f"Competitors: {', '.join(self.competitors.keys())}")
        logger.info(f"Our bankroll: ${self.our_bankroll:,.2f}")
        logger.info("=" * 70)
        
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
    print("Uses CURRENT 15-minute markets based on time")
    print("Sizes relative to bankroll, not their bet size")
    print("Times displayed in EST (UTC-5)")
    print("=" * 70)
    
    # Test current window
    strategy = PureCopyStrategy({'initial_bankroll': 100}, None)
    start, end = strategy._get_current_15m_window()
    print(f"\nCurrent 15-min window:")
    print(f"  UTC: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}")
    print(f"  EST: {strategy._get_est_time(start)} - {strategy._get_est_time(end)}")
    
    # Test ticker generation
    for crypto in ['BTC', 'ETH', 'SOL']:
        ticker = strategy._generate_kalshi_ticker(crypto)
        print(f"  {crypto}: {ticker}")
