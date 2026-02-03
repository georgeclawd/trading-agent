"""
Pure Copy Trading Strategy - Dynamic market discovery

Watch competitors on Polymarket, copy trades to Kalshi.
Pulls available markets dynamically instead of hardcoding.
"""

import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone, timedelta
from strategy_framework import BaseStrategy

logger = logging.getLogger('PureCopyTrading')


class PureCopyStrategy(BaseStrategy):
    """Pure copy trading - copy competitor trades to Kalshi"""
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "PureCopy"
        
        self.competitors = {
            'distinct-baguette': '0xe00740bce98a594e26861838885ab310ec3b548c',
            '0x8dxd': '0x63ce342161250d705dc0b16df89036c8e5f9ba9a',
            'k9Q2mX4L8A7ZP3R': '0xd0d6053c3c37e727402d84c14069780d360993aa',
        }
        
        self.competitor_bankrolls = {
            'distinct-baguette': 6800,
            '0x8dxd': 47000,
            'k9Q2mX4L8A7ZP3R': 51000,
        }
        
        self.seen_trades = set()
        self.our_bankroll = 57.0
        self._running = False
        self.kalshi_markets = {}  # crypto -> ticker mapping
    
    def _get_crypto(self, slug: str) -> Optional[str]:
        """Detect crypto from Polymarket slug"""
        if not slug:
            return None
        parts = slug.split('-')
        if not parts:
            return None
        
        crypto_map = {
            'btc': 'BTC', 'bitcoin': 'BTC',
            'eth': 'ETH', 'ethereum': 'ETH',
            'sol': 'SOL', 'solana': 'SOL'
        }
        return crypto_map.get(parts[0].lower())
    
    def _refresh_kalshi_markets(self):
        """Pull available 15M markets from Kalshi"""
        try:
            self.kalshi_markets = {}
            
            # Check each crypto series individually
            for series in ['KXBTC15M', 'KXETH15M', 'KXSOL15M']:
                try:
                    markets = self.client.get_markets(series_ticker=series, limit=5)
                    if not markets:
                        continue
                    
                    # markets is a list
                    for m in markets:
                        ticker = m.get('ticker', '')
                        status = m.get('status', '')
                        
                        if status != 'active':
                            continue
                        
                        # Determine crypto
                        crypto = None
                        if 'BTC' in ticker:
                            crypto = 'BTC'
                        elif 'ETH' in ticker:
                            crypto = 'ETH'
                        elif 'SOL' in ticker:
                            crypto = 'SOL'
                        
                        if crypto:
                            # Check liquidity
                            ob = self.client.get_orderbook(ticker)
                            if ob:
                                yes = ob.get('orderbook', {}).get('yes')
                                no = ob.get('orderbook', {}).get('no')
                                if yes or no:
                                    self.kalshi_markets[crypto] = ticker
                                    logger.info(f"  Found market: {crypto} -> {ticker}")
                                    break  # Use first valid market per crypto
                except Exception as e:
                    logger.debug(f"Error fetching {series}: {e}")
            
        except Exception as e:
            logger.error(f"Error refreshing markets: {e}")
    
    async def _copy_trade(self, competitor: str, trade: Dict):
        """Copy a single trade to Kalshi"""
        # Skip non-15m markets
        slug = trade.get('slug', '')
        if '-updown-15m-' not in slug:
            return
        
        # Get crypto
        crypto = self._get_crypto(slug)
        if not crypto:
            logger.debug(f"   Unknown crypto in {slug}")
            return
        
        # Get Kalshi ticker
        ticker = self.kalshi_markets.get(crypto)
        if not ticker:
            logger.info(f"   No Kalshi market for {crypto}")
            return
        
        # Calculate trade params
        side = trade.get('side', 'BUY')
        kalshi_side = 'YES' if side == 'BUY' else 'NO'
        price = int(float(trade.get('price', 0.5)) * 100)
        size = 1  # Fixed size for now
        
        logger.info(f"   💰 Copying: {ticker} {kalshi_side} x{size} @ {price}c")
        
        # Place order
        result = self.client.place_order(ticker, kalshi_side.lower(), price, size)
        
        if result.get('success'):
            logger.info(f"   ✅ Copied! Order: {result.get('order_id')}")
            self.trades.append({
                'ticker': ticker,
                'side': kalshi_side,
                'size': size,
                'price': price,
                'order_id': result.get('order_id')
            })
        else:
            logger.warning(f"   ❌ Failed: {result.get('error', 'Unknown error')}")
    
    async def _poll_once(self):
        """Poll competitors once"""
        from competitor_tracker import PolymarketTracker
        
        for name, address in self.competitors.items():
            try:
                tracker = PolymarketTracker()
                activity = tracker.get_user_activity(address, limit=10)
                
                for trade in activity:
                    tx_hash = trade.get('transactionHash') or trade.get('transaction_hash', '')
                    if not tx_hash or tx_hash in self.seen_trades:
                        continue
                    
                    self.seen_trades.add(tx_hash)
                    
                    trade_type = trade.get('type', '')
                    if trade_type != 'TRADE':
                        continue  # Skip REDEEM, etc
                    
                    logger.info(f"🚨 {name} traded!")
                    await self._copy_trade(name, trade)
                    
            except Exception as e:
                logger.debug(f"Error polling {name}: {e}")
    
    async def scan(self):
        """Main loop - poll continuously"""
        self._running = True
        logger.info("🚀 PureCopy started")
        
        # Refresh markets initially
        logger.info("📊 Discovering Kalshi markets...")
        self._refresh_kalshi_markets()
        
        poll_count = 0
        while self._running:
            try:
                # Refresh markets every 10 polls (every ~50 seconds)
                if poll_count % 10 == 0:
                    self._refresh_kalshi_markets()
                
                await self._poll_once()
                poll_count += 1
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Poll error: {e}")
                await asyncio.sleep(5)
        
        return []
    
    async def continuous_trade_loop(self):
        """Entry point"""
        await self.scan()
    
    async def execute(self, opportunities):
        """Execute is handled by polling loop"""
        return 0
    
    def get_performance(self):
        return {'name': self.name, 'trades': len(self.trades)}
