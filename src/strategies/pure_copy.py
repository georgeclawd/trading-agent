"""
Pure Copy Trading Strategy - Simplified

Watch competitors on Polymarket, copy trades to Kalshi.
"""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from strategy_framework import BaseStrategy

logger = logging.getLogger('PureCopyTrading')


class PureCopyStrategy(BaseStrategy):
    """Pure copy trading - copy competitor trades to Kalshi"""
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "PureCopy"
        
        # Competitors
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
    
    def _get_kalshi_ticker(self, crypto: str) -> Optional[str]:
        """Generate Kalshi ticker for current window"""
        if not crypto:
            return None
        
        # Get current EST time
        now_utc = datetime.now(timezone.utc)
        now_est = now_utc - timedelta(hours=5)
        
        # Find window close time (next 15-min boundary)
        minute = now_est.minute
        if minute < 15:
            close_min = 15
        elif minute < 30:
            close_min = 30
        elif minute < 45:
            close_min = 45
        else:
            close_min = 0
            now_est = now_est + timedelta(hours=1)
        
        # Build ticker
        series_map = {'BTC': 'KXBTC15M', 'ETH': 'KXETH15M', 'SOL': 'KSOL15M'}
        series = series_map.get(crypto)
        if not series:
            return None
        
        month_map = {1:'JAN', 2:'FEB', 3:'MAR', 4:'APR', 5:'MAY', 6:'JUN',
                    7:'JUL', 8:'AUG', 9:'SEP', 10:'OCT', 11:'NOV', 12:'DEC'}
        
        year = str(now_est.year)[2:]
        month = month_map.get(now_est.month, 'XXX')
        day = f"{now_est.day:02d}"
        hour = f"{now_est.hour:02d}"
        minute_str = f"{close_min:02d}"
        
        return f"{series}-{year}{month}{day}{hour}{minute_str}-00"
    
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
        ticker = self._get_kalshi_ticker(crypto)
        if not ticker:
            return
        
        # Check market has liquidity
        orderbook = self.client.get_orderbook(ticker)
        if not orderbook:
            logger.info(f"   Market {ticker} not found")
            return
        
        yes = orderbook.get('orderbook', {}).get('yes')
        no = orderbook.get('orderbook', {}).get('no')
        if not yes and not no:
            logger.info(f"   Market {ticker} closed (no liquidity)")
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
        
        while self._running:
            try:
                await self._poll_once()
                await asyncio.sleep(5)  # Poll every 5 seconds
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
