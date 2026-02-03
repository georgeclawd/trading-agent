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
import threading

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
        
        # Get actual bankroll from Kalshi
        self.our_bankroll = 100.0  # Default
        try:
            if client and hasattr(client, 'get_balance'):
                balance_data = client.get_balance()
                if balance_data and 'balance' in balance_data:
                    # Balance comes in cents from Kalshi
                    balance_cents = balance_data.get('balance', 10000)
                    self.our_bankroll = balance_cents / 100.0
                    logger.info(f"   Kalshi balance: ${self.our_bankroll:,.2f}")
                else:
                    logger.warning("   Could not get balance from Kalshi, using config")
                    self.our_bankroll = config.get('initial_bankroll', 100.0)
            else:
                logger.warning("   No client or get_balance method, using config")
                self.our_bankroll = config.get('initial_bankroll', 100.0)
        except Exception as e:
            logger.warning(f"   Error getting balance: {e}, using config")
            self.our_bankroll = config.get('initial_bankroll', 100.0)
        
        # Start background polling task
        self.polling_task = None
        self._running = False
        
        logger.info("✅ Pure Copy Strategy initialized")
        logger.info(f"   Tracking {len(self.competitors)} competitors")
        logger.info(f"   Our bankroll: ${self.our_bankroll:,.2f}")
    
    def _get_est_time(self, utc_dt: datetime) -> str:
        """Convert UTC to EST for display"""
        est = utc_dt - timedelta(hours=5)  # UTC-5 for EST
        return est.strftime('%I:%M %p EST')
    
    def _get_current_15m_window(self) -> tuple:
        """Get the current 15-minute window"""
        now = datetime.now(timezone.utc)
        minute = now.minute
        window_start_minute = (minute // 15) * 15
        window_start = now.replace(minute=window_start_minute, second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=15)
        return window_start, window_end
    
    def _generate_kalshi_ticker(self, crypto: str, timestamp: int = None) -> str:
        """Generate Kalshi ticker for CURRENT 15-min window"""
        if timestamp:
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            window_start, _ = self._get_current_15m_window()
            dt = window_start
        
        series_map = {'BTC': 'KXBTC15M', 'ETH': 'KXETH15M', 'SOL': 'KSOL15M'}
        if crypto not in series_map:
            return None
        
        series = series_map[crypto]
        month_map = {1:'JAN', 2:'FEB', 3:'MAR', 4:'APR', 5:'MAY', 6:'JUN',
                     7:'JUL', 8:'AUG', 9:'SEP', 10:'OCT', 11:'NOV', 12:'DEC'}
        
        year_str = str(dt.year)[2:]
        month_str = month_map.get(dt.month, 'XXX')
        day_str = f"{dt.day:02d}"
        hour_str = f"{dt.hour:02d}"
        min_str = f"{dt.minute:02d}"
        
        return f"{series}-{year_str}{month_str}{day_str}{hour_str}{min_str}-00"
    
    async def poll_competitors(self):
        """Poll Polymarket for competitor trades"""
        try:
            from competitor_tracker import PolymarketTracker
            tracker = PolymarketTracker()
            
            for name, address in self.competitors.items():
                try:
                    activity = tracker.get_user_activity(address, limit=5)
                    
                    for trade in activity:
                        tx_hash = trade.get('transaction_hash', '')
                        if tx_hash in self.seen_trades:
                            continue
                        
                        self.seen_trades.add(tx_hash)
                        await self._process_competitor_trade(name, trade)
                        
                except Exception as e:
                    logger.debug(f"Error polling {name}: {e}")
        except Exception as e:
            logger.error(f"Poll error: {e}")
    
    async def _process_competitor_trade(self, competitor: str, trade: Dict):
        """Process a competitor trade and copy it"""
        side = trade.get('side', 'UNKNOWN')
        size = float(trade.get('size', 0))
        price = float(trade.get('price', 0))
        asset_id = trade.get('asset', '')
        timestamp = trade.get('timestamp', 0)
        
        if isinstance(timestamp, (int, float)):
            trade_time = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            trade_time = datetime.now(timezone.utc)
        
        utc_str = trade_time.strftime('%H:%M UTC')
        est_str = self._get_est_time(trade_time)
        window_start, window_end = self._get_current_15m_window()
        
        logger.info("=" * 70)
        logger.info(f"🚨 {competitor} TRADED! ({utc_str} / {est_str})")
        logger.info(f"   Current window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')} UTC")
        logger.info("=" * 70)
        logger.info(f"   Side: {side}")
        logger.info(f"   Size: ${size:.2f}")
        logger.info(f"   Price: {price:.0%}")
        
        # Extract market info from trade data
        pm_slug = trade.get('slug', '')  # e.g., "btc-updown-15m-1770158700"
        pm_title = trade.get('title', '')
        
        logger.info(f"   Polymarket Slug: {pm_slug or 'Unknown'}")
        logger.info(f"   Title: {pm_title[:60] if pm_title else 'Unknown'}...")
        
        # Parse the Polymarket slug to get crypto and timestamp
        # Format: {crypto}-updown-15m-{unix_timestamp}
        
        # FILTER: Only copy 15-minute markets (not hourly/daily)
        if '-updown-15m-' not in pm_slug:
            return
        
        # Get the current ACTIVE Kalshi market for this crypto
        # (Not the historical market from the trade timestamp)
        crypto = self._detect_crypto_from_slug(pm_slug)
        if not crypto:
            logger.warning(f"   Could not detect crypto from slug '{pm_slug}'")
            return
        
        kalshi_ticker = self._get_current_kalshi_ticker(crypto)
        if not kalshi_ticker:
            logger.warning(f"   No active Kalshi market for {crypto}")
            return
        
        logger.info(f"   Kalshi Ticker: {kalshi_ticker}")
        
        # Check if market is still open and has liquidity
        orderbook = self.client.get_orderbook(kalshi_ticker)
        if not orderbook:
            logger.info(f"   Market {kalshi_ticker} not found, skipping")
            return
        
        # Check if orderbook has actual bids/offers (not null)
        yes_bids = orderbook.get('orderbook', {}).get('yes')
        no_bids = orderbook.get('orderbook', {}).get('no')
        if yes_bids is None and no_bids is None:
            logger.info(f"   Market {kalshi_ticker} has no liquidity (closed), skipping")
            return
        
        # Determine side - for BUY/SELL
        # On Polymarket: BUY = buy YES contracts, SELL = sell YES (or buy NO)
        # On Kalshi: YES contracts for buy side, NO contracts for sell side
        kalshi_side = 'YES' if side == 'BUY' else 'NO'
        
        # Size based on bankroll ratio
        competitor_bankroll = self.competitor_bankrolls.get(competitor, 50000)
        bankroll_ratio = self.our_bankroll / competitor_bankroll
        their_contracts = max(1, int(size / price / 10))
        copy_contracts = max(1, int(their_contracts * bankroll_ratio))
        copy_contracts = min(copy_contracts, 10)
        
        logger.info(f"   Sizing: They have ${competitor_bankroll:,.0f}, we have ${self.our_bankroll:,.0f}")
        logger.info(f"   Ratio: {bankroll_ratio:.1%}")
        logger.info(f"   Copying: {kalshi_side} x{copy_contracts}")
        
        await self._execute_copy(kalshi_ticker, kalshi_side, copy_contracts, price)
    
    async def _try_copy_trade(self, competitor: str, ticker: str, side: str, size: float, price: float):
        """Try to copy trade on a specific ticker"""
        try:
            orderbook = self.client.get_orderbook(ticker)
            if not orderbook or 'orderbook' not in orderbook:
                return False
            
            yes_bids = orderbook['orderbook'].get('yes', [])
            no_bids = orderbook['orderbook'].get('no', [])
            
            if not yes_bids or not no_bids:
                return False
            
            kalshi_side = 'YES' if side == 'BUY' else 'NO'
            
            # Size based on bankroll ratio
            competitor_bankroll = self.competitor_bankrolls.get(competitor, 50000)
            bankroll_ratio = self.our_bankroll / competitor_bankroll
            contracts = max(1, int((size / 10) * bankroll_ratio))
            contracts = min(contracts, 5)
            
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
    
    def _detect_crypto_from_asset(self, asset_id: str) -> Optional[str]:
        """Try to detect crypto type from asset ID patterns"""
        # This is a fallback when slug/title aren't available
        # Asset IDs are long strings, we can't reliably detect from them
        # Return None to trigger the brute force approach
        return None
    
    def _map_pm_slug_to_kalshi(self, pm_slug: str, trade: Dict = None) -> Optional[str]:
        """
        Map Polymarket slug to Kalshi ticker
        
        Polymarket: btc-updown-15m-1770158700 (crypto-updown-15m-{unix_timestamp})
        Kalshi:     KXBTC15M-26FEB031800-00    (KX{CRYPTO}15M-YY{MON}{DD}{HH}{MM}-00)
        """
        if not pm_slug:
            return None
        
        try:
            # Check for standard format: btc-updown-15m-1770158700
            parts = pm_slug.split('-')
            
            # Format 1: {crypto}-updown-15m-{timestamp} (e.g., btc-updown-15m-1770158700)
            if len(parts) >= 4 and parts[1] == 'updown' and parts[2] == '15m':
                return self._map_standard_slug(pm_slug, parts)
            
            # Format 2: {crypto}-up-or-down-{month}-{day}-{time} (e.g., bitcoin-up-or-down-february-3-6pm-et)
            # These use the trade timestamp instead
            if trade and 'timestamp' in trade:
                return self._map_from_trade_timestamp(trade, pm_slug)
            
            logger.debug(f"   Unknown slug format: {pm_slug}")
            return None
            
        except Exception as e:
            logger.warning(f"   Error mapping slug '{pm_slug}': {e}")
            return None
    
    def _map_standard_slug(self, pm_slug: str, parts: list) -> Optional[str]:
        """Map standard format: btc-updown-15m-1770158700"""
        # Extract crypto type (only BTC, ETH, SOL supported on Kalshi)
        crypto_map = {'btc': 'BTC', 'eth': 'ETH', 'sol': 'SOL'}
        crypto = crypto_map.get(parts[0].lower())
        if not crypto:
            logger.info(f"   Skipping unsupported crypto: {parts[0]} (Kalshi only supports BTC, ETH, SOL)")
            return None
        
        # Extract timestamp (last part)
        try:
            timestamp = int(parts[-1])
        except ValueError:
            logger.debug(f"   Invalid timestamp in slug: {parts[-1]}")
            return None
        
        return self._build_kalshi_ticker(crypto, timestamp, pm_slug)
    
    def _map_from_trade_timestamp(self, trade: Dict, pm_slug: str) -> Optional[str]:
        """Map using trade timestamp for non-standard slugs"""
        # Try to detect crypto from title
        title = trade.get('title', '').lower()
        crypto = None
        if 'bitcoin' in title or 'btc' in title:
            crypto = 'BTC'
        elif 'ethereum' in title or 'eth' in title:
            crypto = 'ETH'
        elif 'solana' in title or 'sol' in title:
            crypto = 'SOL'
        
        if not crypto:
            logger.info(f"   Could not detect crypto from title: {title[:50]}")
            return None
        
        # Use trade timestamp
        timestamp = trade.get('timestamp', 0)
        if not timestamp:
            return None
        
        return self._build_kalshi_ticker(crypto, timestamp, pm_slug)
    
    def _build_kalshi_ticker(self, crypto: str, timestamp: int, pm_slug: str) -> str:
        """Build Kalshi ticker from crypto and timestamp"""
        from datetime import timedelta
        
        # Convert timestamp to datetime (UTC)
        dt_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        
        # Kalshi uses EST (UTC-5) for market times
        dt_est = dt_utc - timedelta(hours=5)
        
        # Build Kalshi ticker using EST time
        series_map = {'BTC': 'KXBTC15M', 'ETH': 'KXETH15M', 'SOL': 'KSOL15M'}
        series = series_map[crypto]
        
        month_map = {1:'JAN', 2:'FEB', 3:'MAR', 4:'APR', 5:'MAY', 6:'JUN',
                    7:'JUL', 8:'AUG', 9:'SEP', 10:'OCT', 11:'NOV', 12:'DEC'}
        
        year_str = str(dt_est.year)[2:]
        month_str = month_map.get(dt_est.month, 'XXX')
        day_str = f"{dt_est.day:02d}"
        hour_str = f"{dt_est.hour:02d}"
        min_str = f"{dt_est.minute:02d}"
        
        kalshi_ticker = f"{series}-{year_str}{month_str}{day_str}{hour_str}{min_str}"
        logger.info(f"   Mapped: {pm_slug} ({dt_utc.strftime('%H:%M')} UTC / {dt_est.strftime('%H:%M')} EST) -> {kalshi_ticker}")
        return kalshi_ticker
    
    def _detect_crypto_from_slug(self, pm_slug: str) -> Optional[str]:
        """Detect crypto type from Polymarket slug"""
        if not pm_slug:
            return None
        
        parts = pm_slug.split('-')
        if len(parts) < 1:
            return None
        
        crypto_map = {'btc': 'BTC', 'eth': 'ETH', 'sol': 'SOL', 'bitcoin': 'BTC', 'ethereum': 'ETH', 'solana': 'SOL'}
        return crypto_map.get(parts[0].lower())
    
    def _get_current_kalshi_ticker(self, crypto: str) -> Optional[str]:
        """Get the currently active Kalshi ticker for this crypto"""
        # Kalshi 15M markets are 15-minute windows
        # Ticker uses the CLOSE time (end of window), not start
        from datetime import timedelta
        
        now_utc = datetime.now(timezone.utc)
        now_est = now_utc - timedelta(hours=5)
        
        # 15-minute windows: :00, :15, :30, :45
        # Round UP to nearest 15 min to get window CLOSE time for ticker
        current_minute = now_est.minute
        if current_minute < 15:
            window_close_minute = 15
        elif current_minute < 30:
            window_close_minute = 30
        elif current_minute < 45:
            window_close_minute = 45
        else:
            window_close_minute = 0
            now_est = now_est + timedelta(hours=1)
        
        window_close = now_est.replace(minute=window_close_minute, second=0, microsecond=0)
        
        # Calculate how far into the window we are
        window_start_minute = window_close_minute - 15
        if window_start_minute < 0:
            window_start_minute = 45
        seconds_into_window = (current_minute - window_start_minute) * 60 + now_est.second
        
        # Markets close ~10-12 min before window end for settlement
        # Window is 15 min, so tradeable for ~3-5 min
        if seconds_into_window > 300:  # 5 minutes = 300 seconds
            logger.info(f"   Market likely closed (window started {seconds_into_window}s ago), skipping")
            return None
        
        # Build ticker using WINDOW CLOSE time (not start)
        series_map = {'BTC': 'KXBTC15M', 'ETH': 'KXETH15M', 'SOL': 'KSOL15M'}
        series = series_map.get(crypto)
        if not series:
            return None
        
        month_map = {1:'JAN', 2:'FEB', 3:'MAR', 4:'APR', 5:'MAY', 6:'JUN',
                    7:'JUL', 8:'AUG', 9:'SEP', 10:'OCT', 11:'NOV', 12:'DEC'}
        
        year_str = str(window_close.year)[2:]
        month_str = month_map.get(window_close.month, 'XXX')
        day_str = f"{window_close.day:02d}"
        hour_str = f"{window_close.hour:02d}"
        min_str = f"{window_close.minute:02d}"
        
        return f"{series}-{year_str}{month_str}{day_str}{hour_str}{min_str}-45"
    
    async def _lookup_pm_market(self, asset_id: str) -> Optional[Dict]:
        """Look up Polymarket market from asset ID"""
        if asset_id in self.pm_market_cache:
            return self.pm_market_cache[asset_id]
        
        try:
            async with aiohttp.ClientSession() as session:
                url = "https://gamma-api.polymarket.com/markets"
                params = {"assetId": asset_id}
                
                logger.debug(f"   Looking up market for asset: {asset_id[:30]}...")
                async with session.get(url, params=params, timeout=10) as resp:
                    logger.debug(f"   API response status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        
                        if isinstance(data, list) and data:
                            market = data[0]
                            self.pm_market_cache[asset_id] = market
                            logger.debug(f"   Found market: {market.get('marketSlug', 'N/A')}")
                            return market
                        elif isinstance(data, dict) and data.get('markets'):
                            market = data['markets'][0]
                            self.pm_market_cache[asset_id] = market
                            logger.debug(f"   Found market: {market.get('marketSlug', 'N/A')}")
                            return market
                        else:
                            logger.debug(f"   API returned empty or unexpected format: {type(data)}")
        except Exception as e:
            logger.warning(f"   Error looking up market: {e}")
        
        return None
    
    async def _execute_copy(self, ticker: str, side: str, size: int, price: float):
        """Execute the copy trade on Kalshi"""
        try:
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
    
    async def scan(self) -> List[Dict]:
        """Called by StrategyManager - start polling"""
        # Start background polling if not already running
        if not self._running:
            self._running = True
            window_start, window_end = self._get_current_15m_window()
            
            logger.info("=" * 70)
            logger.info("🔄 PURE COPY STRATEGY STARTED")
            logger.info("=" * 70)
            logger.info(f"Current window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')} UTC")
            logger.info(f"EST: {self._get_est_time(window_start)} - {self._get_est_time(window_end)}")
            logger.info(f"Competitors: {', '.join(self.competitors.keys())}")
            logger.info(f"Poll interval: 10 seconds")
            logger.info(f"Status: WAITING for competitor trades...")
            logger.info("=" * 70)
            
            # Start background polling
            asyncio.create_task(self._polling_loop())
        else:
            logger.debug("PureCopy polling already running")
        
        return []  # No immediate opportunities
    
    async def _polling_loop(self):
        """Background polling loop"""
        poll_count = 0
        while self._running:
            try:
                poll_count += 1
                window_start, window_end = self._get_current_15m_window()
                
                # Log every 6 polls (every minute) to show we're alive
                if poll_count % 6 == 0:
                    logger.info(f"📊 PureCopy polling... (cycle #{poll_count})")
                    logger.info(f"   Current window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')} UTC")
                    logger.info(f"   EST: {self._get_est_time(window_start)} - {self._get_est_time(window_end)}")
                
                # Poll competitors
                for name, address in self.competitors.items():
                    try:
                        from competitor_tracker import PolymarketTracker
                        tracker = PolymarketTracker()
                        activity = tracker.get_user_activity(address, limit=5)
                        
                        if activity:
                            logger.info(f"   👤 {name}: {len(activity)} activities fetched")
                            
                            for trade in activity:
                                # Polymarket uses 'transactionHash' not 'transaction_hash'
                                tx_hash = trade.get('transactionHash') or trade.get('transaction_hash', '')
                                trade_type = trade.get('type', 'UNKNOWN')
                                
                                # Log what we see
                                if tx_hash:
                                    if tx_hash in self.seen_trades:
                                        logger.debug(f"      Skipping seen trade: {tx_hash[:20]}...")
                                    else:
                                        logger.info(f"🚨 NEW {trade_type} from {name}!")
                                        logger.info(f"      Tx: {tx_hash[:30]}...")
                                        self.seen_trades.add(tx_hash)
                                        await self._process_competitor_trade(name, trade)
                                else:
                                    logger.warning(f"      Activity has no tx_hash: {list(trade.keys())}")
                        else:
                            logger.info(f"   👤 {name}: No activity")
                                
                    except Exception as e:
                        logger.error(f"   💥 Error polling {name}: {e}", exc_info=True)
                
                await asyncio.sleep(10)  # Poll every 10 seconds
                
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(10)
    
    async def execute(self, opportunities):
        """Execute is handled by polling"""
        return 0
    
    async def continuous_trade_loop(self):
        """Alternative entry point"""
        logger.info(" continuous_trade_loop() called - starting scan...")
        await self.scan()
        logger.info(" scan() completed - entering keep-alive loop")
        # Keep running
        while self._running:
            await asyncio.sleep(1)
        logger.info(" Keep-alive loop exited")
    
    def get_performance(self):
        return {'name': self.name, 'trades': len(self.trades)}
