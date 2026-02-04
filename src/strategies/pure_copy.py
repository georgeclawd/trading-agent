"""
Pure Copy Trading Strategy - SIMPLIFIED VERSION

Only trades CURRENT WINDOW markets.
When window expires, moves to next window.
No position tracking - just immediate trade copying.
"""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from strategy_framework import BaseStrategy

logger = logging.getLogger('PureCopyTrading')


class PureCopyStrategy(BaseStrategy):
    """
    Copy distinct-baguette trades on CURRENT WINDOW only.
    When window expires, move to next window.
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "PureCopy"
        
        # Only copy distinct-baguette
        self.competitor_address = '0xe00740bce98a594e26861838885ab310ec3b548c'
        self.competitor_bankroll = 6800
        
        self.seen_trades = set()
        self._running = False
        
        # Current window tracking
        self.current_window_end = None
        self.active_markets = {}  # crypto -> kalshi_ticker for current window
        
        # Simple position sizing
        self.our_bankroll = 21.70  # Will update dynamically
        self.max_position_pct = 0.10  # Max 10% per trade
        
        # Track open positions for exit-at-5-min logic
        self.open_positions = {}  # crypto -> {size, side, entry_price}
        
        logger.info("🚀 PureCopy initialized - CURRENT WINDOW ONLY mode")
        logger.info("   Strategy: Exit all positions 5 min before window close")
    
    def _get_current_window_times(self):
        """Get start and end of current 15-min window"""
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        window_start_minute = (current_minute // 15) * 15
        
        window_start = now.replace(minute=window_start_minute, second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=15)
        
        return window_start, window_end
    
    def _get_window_timestamp(self, dt: datetime):
        """Convert datetime to window timestamp string (for market matching)"""
        # Format: HHMM (e.g., 1045 for 10:45)
        return dt.strftime('%H%M')
    
    def _find_current_window_markets(self):
        """Find ACTIVE markets for current 15-min window only"""
        window_start, window_end = self._get_current_window_times()
        self.current_window_end = window_end
        
        window_ts = self._get_window_timestamp(window_end)
        logger.info(f"🔍 Looking for markets ending at {window_ts} ({window_end.strftime('%H:%M UTC')})")
        
        self.active_markets = {}
        
        for crypto, series in [('BTC', 'KXBTC15M'), ('ETH', 'KXETH15M'), ('SOL', 'KXSOL15M')]:
            try:
                # Look for market matching current window
                markets = self.client.get_markets(series_ticker=series, limit=20)
                
                for m in markets:
                    ticker = m.get('ticker', '')
                    status = m.get('status', '')
                    close_time = m.get('close_time', '')
                    
                    if status != 'active':
                        continue
                    
                    # Check if this market closes at our window end
                    if close_time:
                        close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                        if close_dt == window_end or close_dt.strftime('%H%M') == window_ts:
                            self.active_markets[crypto] = ticker
                            logger.info(f"  ✅ {crypto}: {ticker} (closes {close_time})")
                            break
                            
            except Exception as e:
                logger.error(f"  ❌ Error finding {crypto} market: {e}")
        
        if not self.active_markets:
            logger.warning("  ⚠️ No active markets found for current window!")
        
        return len(self.active_markets) > 0
    
    def _check_window_change(self):
        """Check if we've moved to a new window"""
        now = datetime.now(timezone.utc)
        
        if self.current_window_end and now >= self.current_window_end:
            logger.info(f"🔄 Window expired at {self.current_window_end.strftime('%H:%M UTC')}")
            logger.info("   Finding markets for NEW window...")
            self.seen_trades.clear()  # Clear seen trades for new window
            return self._find_current_window_markets()
        
        return False
    
    def _get_position_size(self, trade_size_usd: float) -> int:
        """Simple position sizing based on bankroll ratio"""
        # What % of their bankroll did they trade?
        their_pct = trade_size_usd / self.competitor_bankroll
        
        # Apply same % to our bankroll (max 10%)
        our_trade_usd = min(self.our_bankroll * their_pct, 
                           self.our_bankroll * self.max_position_pct)
        
        # Return 1-3 contracts
        if our_trade_usd < 0.50:
            return 1
        elif our_trade_usd < 1.50:
            return 2
        else:
            return 3
    
    def _log_market_prices(self):
        """Log current market prices for all active markets (for proof)"""
        logger.info("📊 MARKET PRICE CHECK:")
        for crypto, ticker in self.active_markets.items():
            try:
                r = self.client._request("GET", f"/markets/{ticker}")
                if r.status_code == 200:
                    m = r.json().get('market', {})
                    yes_bid = m.get('yes_bid', 0)
                    yes_ask = m.get('yes_ask', 0)
                    last = m.get('last_price', 0)
                    logger.info(f"   {crypto}: yes_bid={yes_bid}c, yes_ask={yes_ask}c, last={last}c")
                else:
                    logger.info(f"   {crypto}: Error {r.status_code}")
            except Exception as e:
                logger.info(f"   {crypto}: Error {e}")
    
    async def _exit_all_positions(self):
        """Exit all open positions at current market price"""
        logger.info(f"   Exiting {len(self.open_positions)} positions...")
        for crypto, pos in list(self.open_positions.items()):
            size = pos['size']
            side = pos['side']
            logger.info(f"   Selling {crypto} {side} x{size}")
            success = self._execute_exit(crypto, side, size)
            if success:
                del self.open_positions[crypto]
                logger.info(f"   ✅ Exited {crypto}")
            else:
                logger.warning(f"   ❌ Failed to exit {crypto}")
    
    def _execute_trade(self, crypto: str, side: str, price_cents: int, size: int) -> bool:
        """Execute a single trade immediately"""
        ticker = self.active_markets.get(crypto)
        if not ticker:
            logger.debug(f"  No active market for {crypto}")
            return False
        
        # Verify market still active
        try:
            response = self.client._request("GET", f"/markets/{ticker}")
            if response.status_code == 200:
                status = response.json().get('market', {}).get('status', '')
                if status != 'active':
                    logger.warning(f"  Market {ticker} is {status}, skipping")
                    return False
        except Exception as e:
            logger.debug(f"  Could not verify market status: {e}")
            return False
        
        # Execute
        logger.info(f"  💰 BUY: {ticker} {side} x{size} @ {price_cents}c")
        try:
            result = self.client.place_order(ticker, side.lower(), price_cents, size)
            if result.get('success') or result.get('order_id'):
                logger.info(f"  ✅ Executed! Order: {result.get('order_id', 'N/A')[:16]}...")
                # Track position for exit logic
                if crypto in self.open_positions:
                    # Add to existing position
                    old = self.open_positions[crypto]
                    old['size'] += size
                    old['entry_price'] = (old['entry_price'] + price_cents) / 2  # Avg
                else:
                    self.open_positions[crypto] = {
                        'size': size,
                        'side': side,
                        'entry_price': price_cents,
                        'ticker': ticker
                    }
                return True
            else:
                logger.warning(f"  ❌ Failed: {result}")
                return False
        except Exception as e:
            logger.error(f"  ❌ Error: {e}")
            return False
    
    def _execute_exit(self, crypto: str, side: str, size: int) -> bool:
        """Execute exit (sell) immediately at current market price"""
        logger.info(f"  _execute_exit called: {crypto} {side} x{size}")
        ticker = self.active_markets.get(crypto)
        if not ticker:
            logger.warning(f"  No active market for {crypto}")
            return False
        
        # Get current market price from /markets/{ticker}
        try:
            response = self.client._request("GET", f"/markets/{ticker}")
            if response.status_code != 200:
                logger.warning(f"  Could not get market data for {ticker}")
                return False
            
            market = response.json().get('market', {})
            
            # Get yes_bid or no_bid (for selling)
            # API returns these as cents directly
            if side == 'YES':
                # We're selling YES, use yes_bid (what buyers will pay)
                exit_price = market.get('yes_bid', 0)
            else:
                exit_price = market.get('no_bid', 0)
            
            if exit_price <= 0:
                logger.warning(f"  Invalid price for {ticker}: {exit_price}c")
                return False
            
            logger.info(f"  💸 SELL: {ticker} {side} x{size} @ {exit_price}c (market price: yes={market.get('yes_price')}, no={market.get('no_price')})")
            result = self.client.place_order(ticker, side.lower(), exit_price, size)
            
            if result.get('success') or result.get('order_id'):
                logger.info(f"  ✅ Exited! Order: {result.get('order_id', 'N/A')[:16]}...")
                # Remove from tracking
                if crypto in self.open_positions:
                    del self.open_positions[crypto]
                return True
            else:
                logger.warning(f"  ❌ Exit failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"  ❌ Error exiting: {e}")
            return False
    
    async def scan(self):
        """Main loop - continuously poll and copy trades for current window only"""
        from competitor_tracker import PolymarketTracker
        
        self._running = True
        logger.info("🚀 PureCopy started - CURRENT WINDOW ONLY MODE")
        
        # Find initial markets
        self._find_current_window_markets()
        
        tracker = PolymarketTracker()
        
        while self._running:
            try:
                # Check for window change
                self._check_window_change()
                
                # Update bankroll
                try:
                    balance_data = self.client.get_balance()
                    if balance_data:
                        self.our_bankroll = balance_data['balance'] / 100.0
                except:
                    pass
                
                # Log status periodically
                now = datetime.now(timezone.utc)
                time_to_close = (self.current_window_end - now).total_seconds() if self.current_window_end else 0
                time_to_close_min = int(time_to_close/60)
                
                # LOG MARKET PRICES every minute (for proof of price action)
                if int(time_to_close) % 60 == 0:  # Once per minute
                    self._log_market_prices()
                
                # EXIT ALL at 5 minutes before close
                if 240 < time_to_close <= 300 and self.open_positions:  # Between 4-5 min left
                    logger.info(f"⏰ 5 MIN WARNING - EXITING ALL POSITIONS")
                    await self._exit_all_positions()
                    await asyncio.sleep(5)
                    continue
                
                # STOP NEW TRADES 3 minutes before window close
                if time_to_close < 180:  # 3 minutes
                    if time_to_close > 0:
                        logger.info(f"⏰ Window closing in {time_to_close_min}m - LIQUIDITY LOCKDOWN - No new trades")
                        await asyncio.sleep(10)
                        continue
                
                logger.info(f"💰 Bankroll: ${self.our_bankroll:.2f} | Window closes in {time_to_close_min}m | Positions: {list(self.open_positions.keys())}")
                
                # Poll for trades
                activity = tracker.get_user_activity(self.competitor_address, limit=10)
                
                for trade in activity:
                    tx_hash = trade.get('transactionHash') or trade.get('transaction_hash', '')
                    if not tx_hash or tx_hash in self.seen_trades:
                        continue
                    
                    self.seen_trades.add(tx_hash)
                    
                    if trade.get('type') != 'TRADE':
                        continue
                    
                    # Parse trade
                    slug = trade.get('slug', '')
                    side = trade.get('side', '')  # BUY or SELL
                    size_usd = float(trade.get('size', 0))
                    price = float(trade.get('price', 0.5))
                    
                    # Extract crypto and window from slug
                    # Format: eth-updown-15m-1234567890
                    parts = slug.split('-')
                    if len(parts) < 4:
                        continue
                    
                    crypto = parts[0].upper()
                    if crypto == 'BITCOIN':
                        crypto = 'BTC'
                    elif crypto == 'ETHEREUM':
                        crypto = 'ETH'
                    elif crypto == 'SOLANA':
                        crypto = 'SOL'
                    
                    # Check if this is for current window
                    if crypto not in self.active_markets:
                        logger.debug(f"⏭️  Skipping {crypto} - not in current window")
                        continue
                    
                    logger.info(f"🚨 distinct-baguette: {side} {crypto} ${size_usd:.2f} @ {price:.2f}")
                    
                    # Execute (these are synchronous, don't use await)
                    if side == 'BUY':
                        # Convert price (0.0-1.0) to cents (0-100)
                        price_cents = int(price * 100)
                        position_size = self._get_position_size(size_usd)
                        
                        # Map Polymarket side to Kalshi
                        kalshi_side = 'YES'
                        
                        self._execute_trade(crypto, kalshi_side, price_cents, position_size)
                        
                    else:  # SELL
                        position_size = self._get_position_size(size_usd)
                        kalshi_side = 'YES'
                        
                        logger.info(f"  🔄 Executing SELL for {crypto}...")
                        result = self._execute_exit(crypto, kalshi_side, position_size)
                        if not result:
                            logger.warning(f"  ⚠️ SELL failed for {crypto}")
                
                # Wait before next poll
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(5)
    
    async def continuous_trade_loop(self):
        """Entry point for continuous trading"""
        await self.scan()
    
    async def execute(self, opportunities):
        """Execute trades - not used in this simplified version"""
        return 0
    
    def get_performance(self):
        """Get performance metrics"""
        return {'trades': len(self.seen_trades), 'pnl': 0}
