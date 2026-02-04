"""
Pure Copy Trading Strategy - With Trade Queue

Queues trades that fail due to closed markets and retries them.
"""

import asyncio
import logging
from typing import Dict, Optional, List
from datetime import datetime, timezone, timedelta
from collections import deque
from strategy_framework import BaseStrategy

logger = logging.getLogger('PureCopyTrading')


class QueuedTrade:
    """Represents a trade waiting to be executed"""
    def __init__(self, competitor: str, trade: Dict, crypto: str, 
                 kalshi_side: str, price: int, size: int, 
                 queued_at: datetime, retry_count: int = 0):
        self.competitor = competitor
        self.trade = trade
        self.crypto = crypto
        self.kalshi_side = kalshi_side
        self.price = price
        self.size = size
        self.queued_at = queued_at
        self.retry_count = retry_count
        self.ticker = None  # Set when market is found
    
    def __repr__(self):
        return f"QueuedTrade({self.crypto} {self.kalshi_side} @ {self.price}c, retries={self.retry_count})"


class PureCopyStrategy(BaseStrategy):
    """Pure copy trading - copy competitor trades to Kalshi with retry queue"""
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "PureCopy"
        
        # FOCUS ONLY ON distinct-baguette - proven profitable with exits
        self.competitors = {
            'distinct-baguette': '0xe00740bce98a594e26861838885ab310ec3b548c',
            # REMOVED: '0x8dxd' - accumulator strategy (needs big bankroll)
            # REMOVED: 'k9Q2mX4L8A7ZP3R' - accumulator strategy (needs big bankroll)
        }
        
        self.competitor_bankrolls = {
            'distinct-baguette': 6800,
        }
        
        self.seen_trades = set()
        self.our_bankroll = 57.0
        self._running = False
        self.kalshi_markets = {}  # crypto -> ticker mapping
        
        # Trade queue for failed trades
        self.trade_queue = deque()
        self.max_retries = 10
        self.max_queue_age_seconds = 600  # 10 minutes max in queue
        
        # Bankroll management - CONSERVATIVE with 20% safety margin
        # Based on observation: $3-11 per cycle, using 20% max for safety
        self.max_exposure_pct = 0.20  # Max 20% of bankroll (very conservative)
        self.min_trade_size = 1
        self.max_trade_size = 3  # Cap at 3 to prevent over-trading
        self.open_exposure = 0.0  # Track current exposure in USD
        self.our_bankroll = 21.70  # Current actual bankroll
        
        # LIVE TRADING MODE
        self.observation_mode = False  # LIVE TRADING ENABLED
        self.cycle_stats = {}  # Track trades per cycle
        
        # TRADER PERFORMANCE TRACKING
        self.trader_performance = {
            name: {
                'trades_count': 0,
                'total_cost': 0.0,      # Total USD spent on contracts
                'total_contracts': 0,   # Total contracts held
                'avg_price': 0.0,       # Weighted average entry price
                'realized_pnl': 0.0,    # Closed trade P&L
                'unrealized_pnl': 0.0,  # Current open position value
                'wins': 0,
                'losses': 0,
                'trades': []            # List of individual trades
            }
            for name in self.competitors.keys()
        }
        
        # OPEN POSITIONS TRACKING - for exit logic
        self.open_positions = {}  # Key: (trader, crypto, side) -> {size, entry_price, ticker}
    
    def _log_cycle_stats(self):
        """Log statistics for the current cycle"""
        if not self.cycle_stats:
            return
        
        logger.info("=" * 70)
        logger.info("📊 CYCLE OBSERVATION STATS")
        logger.info("=" * 70)
        
        total_would_spend = 0
        for competitor, stats in self.cycle_stats.items():
            count = stats['count']
            total_usd = stats['total_usd']
            avg_usd = total_usd / count if count > 0 else 0
            
            logger.info(f"\n👤 {competitor}:")
            logger.info(f"   Trades: {count}")
            logger.info(f"   Total USD: ${total_usd:.2f}")
            logger.info(f"   Avg per trade: ${avg_usd:.2f}")
            
            # Calculate what WE would spend
            their_bankroll = self.competitor_bankrolls.get(competitor, 50000)
            our_bankroll = 21.70  # Current bankroll
            ratio = our_bankroll / their_bankroll
            our_spend = total_usd * ratio
            total_would_spend += our_spend
            
            logger.info(f"   Their bankroll: ${their_bankroll:,.0f}")
            logger.info(f"   Our bankroll: ${our_bankroll:.2f}")
            logger.info(f"   Ratio: {ratio:.4f}")
            logger.info(f"   We would spend: ${our_spend:.2f}")
        
        logger.info(f"\n💰 TOTAL WE WOULD NEED PER CYCLE: ${total_would_spend:.2f}")
        logger.info(f"   Current bankroll: ${our_bankroll:.2f}")
        
        if total_would_spend > our_bankroll * 0.5:
            logger.warning(f"   ⚠️  INSUFFICIENT FUNDS! Need ${total_would_spend:.2f}, have ${our_bankroll:.2f}")
            logger.warning(f"   Recommend: Wait for settlement or add funds")
    
    def _track_trader_performance(self, trader: str, ticker: str, side: str, price: int, size: int):
        """Track performance metrics for each trader"""
        if trader not in self.trader_performance:
            return
        
        perf = self.trader_performance[trader]
        cost = size * price * 0.01  # Cost in USD
        
        perf['trades_count'] += 1
        perf['total_cost'] += cost
        perf['total_contracts'] += size
        
        # Update weighted average price
        if perf['total_contracts'] > 0:
            perf['avg_price'] = (perf['avg_price'] * (perf['total_contracts'] - size) + price * size) / perf['total_contracts']
        
        # Store trade details
        perf['trades'].append({
            'ticker': ticker,
            'side': side,
            'price': price,
            'size': size,
            'cost': cost,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        logger.info(f"   📊 Tracked: {trader} now has {perf['trades_count']} trades, ${perf['total_cost']:.2f} invested")
    
    def _log_trader_performance(self):
        """Log performance summary for all traders"""
        logger.info("=" * 70)
        logger.info("📈 TRADER PERFORMANCE REPORT")
        logger.info("=" * 70)
        
        # Sort by total cost (activity level)
        sorted_traders = sorted(
            self.trader_performance.items(),
            key=lambda x: x[1]['total_cost'],
            reverse=True
        )
        
        total_pnl = 0
        for trader, perf in sorted_traders:
            if perf['trades_count'] == 0:
                continue
            
            total_trades = perf['wins'] + perf['losses']
            win_rate = (perf['wins'] / total_trades * 100) if total_trades > 0 else 0
            total_pnl += perf['realized_pnl']
            
            pnl_emoji = "🟢" if perf['realized_pnl'] > 0 else "🔴" if perf['realized_pnl'] < 0 else "⚪"
            
            logger.info(f"\n👤 {trader}:")
            logger.info(f"   Trades: {perf['trades_count']} | Exits: {total_trades}")
            logger.info(f"   Win Rate: {win_rate:.0f}% ({perf['wins']}W/{perf['losses']}L)")
            logger.info(f"   Total Invested: ${perf['total_cost']:.2f}")
            logger.info(f"   {pnl_emoji} Realized P&L: ${perf['realized_pnl']:+.2f}")
        
        logger.info(f"\n💰 COMBINED P&L: ${total_pnl:+.2f}")
        logger.info("=" * 70)
    
    async def _exit_position(self, competitor: str, crypto: str, side: str):
        """Sell our position when competitor exits"""
        position_key = (competitor, crypto, side)
        
        if position_key not in self.open_positions:
            logger.debug(f"   No position to exit for {position_key}")
            return
        
        pos = self.open_positions[position_key]
        ticker = pos['ticker']
        size = pos['size']
        entry_price = pos['entry_price']
        
        logger.info(f"   🔄 Exiting {ticker} {side} x{size} @ entry {entry_price}c")
        
        if not ticker:
            logger.warning(f"   No ticker for {crypto}, can't exit")
            return
        
        # Get current market price
        orderbook = self.client.get_orderbook(ticker)
        if not orderbook:
            logger.warning(f"   Can't get orderbook for {ticker}")
            return
        
        # Determine sell price (bid side)
        if side == 'YES':
            book_side = orderbook.get('orderbook', {}).get('yes', [])
        else:
            book_side = orderbook.get('orderbook', {}).get('no', [])
        
        if not book_side:
            logger.warning(f"   No liquidity for {ticker} {side}")
            return
        
        # Use best bid
        exit_price = int(book_side[0].get('price', entry_price))
        logger.info(f"   📊 Best bid: {exit_price}c, Entry: {entry_price}c")
        
        # Place sell order
        sell_side = side.lower()
        result = self.client.place_order(ticker, sell_side, exit_price, size)
        logger.info(f"   📤 Sell order result: {result}")
        
        if result.get('success') or result.get('order_id'):
            # Calculate P&L
            entry_cost = size * entry_price * 0.01
            exit_value = size * exit_price * 0.01
            pnl = exit_value - entry_cost
            pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price > 0 else 0
            
            # Update trader performance
            if competitor in self.trader_performance:
                self.trader_performance[competitor]['realized_pnl'] += pnl
                if pnl > 0:
                    self.trader_performance[competitor]['wins'] += 1
                else:
                    self.trader_performance[competitor]['losses'] += 1
            
            # Remove from open positions
            del self.open_positions[position_key]
            
            # Reduce exposure tracking
            self.open_exposure -= size * entry_price * 0.01
            if self.open_exposure < 0:
                self.open_exposure = 0
            
            emoji = "🟢" if pnl > 0 else "🔴"
            logger.info(f"   {emoji} EXITED: {competitor} {crypto} {side} x{size}")
            logger.info(f"      Entry: {entry_price}c | Exit: {exit_price}c | P&L: ${pnl:.2f} ({pnl_pct:+.1f}%)")
        else:
            logger.warning(f"   ❌ Failed to exit: {result}")
    
    def _update_bankroll(self):
        """Update our bankroll from Kalshi"""
        try:
            balance_data = self.client.get_balance()
            if balance_data and 'balance' in balance_data:
                self.our_bankroll = balance_data['balance'] / 100.0
        except Exception as e:
            logger.debug(f"Could not update bankroll: {e}")
    
    def _recalculate_exposure(self):
        """Recalculate exposure from actual open positions - fixes tracking drift"""
        total = 0.0
        for key, pos in self.open_positions.items():
            total += pos['size'] * pos['entry_price'] * 0.01
        self.open_exposure = total
    
    def _get_position_size(self, competitor: str, trade_size_usd: float, price: float) -> int:
        """Calculate position size based on competitor's trade relative to their bankroll"""
        competitor_bankroll = self.competitor_bankrolls.get(competitor, 50000)
        
        # What % of their bankroll did they trade?
        their_trade_pct = trade_size_usd / competitor_bankroll
        
        # Apply same % to our bankroll
        our_trade_usd = self.our_bankroll * their_trade_pct
        
        # Convert to contracts (size / price)
        if price > 0:
            contracts = int(our_trade_usd / (price * 10))  # price is in cents (0-99)
        else:
            contracts = 1
        
        # Apply limits
        contracts = max(self.min_trade_size, min(contracts, self.max_trade_size))
        
        # Check if we'd exceed max exposure
        max_allowed_exposure = self.our_bankroll * self.max_exposure_pct
        if self.open_exposure + (contracts * price * 0.1) > max_allowed_exposure:
            # Reduce size to stay under limit
            remaining = max_allowed_exposure - self.open_exposure
            if remaining > 0:
                contracts = int(remaining / (price * 0.1))
                contracts = max(0, contracts)
            else:
                contracts = 0
        
        if contracts == 0:
            logger.warning(f"   ⚠️  Skipping: max exposure reached (${self.open_exposure:.2f} / ${max_allowed_exposure:.2f})")
        
        return contracts
    
    def _update_exposure(self, contracts: int, price: float):
        """Update tracked exposure when trade is executed"""
        self.open_exposure += contracts * price * 0.1  # Approximate USD value
    
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
    
    async def _execute_trade(self, qt: QueuedTrade) -> bool:
        """Execute a queued trade. Returns True if successful."""
        ticker = self.kalshi_markets.get(qt.crypto)
        if not ticker:
            logger.debug(f"   No market for {qt.crypto}")
            return False
        
        qt.ticker = ticker
        
        # Check market has liquidity
        orderbook = self.client.get_orderbook(ticker)
        if not orderbook:
            logger.debug(f"   Market {ticker} not found")
            return False
        
        yes = orderbook.get('orderbook', {}).get('yes')
        no = orderbook.get('orderbook', {}).get('no')
        if not yes and not no:
            logger.debug(f"   Market {ticker} closed (no liquidity)")
            return False
        
        logger.info(f"   💰 Executing: {ticker} {qt.kalshi_side} x{qt.size} @ {qt.price}c (retry #{qt.retry_count})")
        
        # Place order
        result = self.client.place_order(ticker, qt.kalshi_side.lower(), qt.price, qt.size)
        
        if result.get('success'):
            logger.info(f"   ✅ Copied! Order: {result.get('order_id')}")
            self.trades.append({
                'ticker': ticker,
                'side': qt.kalshi_side,
                'size': qt.size,
                'price': qt.price,
                'order_id': result.get('order_id'),
                'competitor': qt.competitor,
                'retries': qt.retry_count
            })
            self._update_exposure(qt.size, qt.price)
            
            # TRACK TRADER PERFORMANCE
            self._track_trader_performance(qt.competitor, ticker, qt.kalshi_side, qt.price, qt.size)
            
            return True
        else:
            error = result.get('error', '')
            if 'market_closed' in error.lower() or 'not found' in error.lower():
                logger.debug(f"   Market still closed")
                return False
            else:
                # Other error, log it but don't retry indefinitely
                logger.warning(f"   Failed with error: {error}")
                return False  # Don't retry on other errors
    
    async def _process_queue(self):
        """Process queued trades. Returns number of successful trades."""
        if not self.trade_queue:
            return 0
        
        logger.info(f"📋 Processing {len(self.trade_queue)} queued trades...")
        
        successful = 0
        failed_trades = []
        now = datetime.now(timezone.utc)
        
        while self.trade_queue:
            qt = self.trade_queue.popleft()
            
            # Check if trade is too old
            age = (now - qt.queued_at).total_seconds()
            if age > self.max_queue_age_seconds:
                logger.info(f"   Dropping stale trade ({age:.0f}s old): {qt}")
                continue
            
            # Check max retries
            if qt.retry_count >= self.max_retries:
                logger.info(f"   Max retries reached for: {qt}")
                continue
            
            # Try to execute
            qt.retry_count += 1
            if await self._execute_trade(qt):
                successful += 1
            else:
                # Put back in queue for next retry
                failed_trades.append(qt)
        
        # Put failed trades back in queue
        for qt in failed_trades:
            self.trade_queue.append(qt)
        
        if successful > 0:
            logger.info(f"✅ Successfully executed {successful} queued trades, {len(self.trade_queue)} remaining")
        
        return successful
    
    async def _copy_trade(self, competitor: str, trade: Dict):
        """Copy a single trade to Kalshi. Queues if market closed."""
        # Skip non-15m markets
        slug = trade.get('slug', '')
        if '-updown-15m-' not in slug:
            return
        
        # Get crypto
        crypto = self._get_crypto(slug)
        if not crypto:
            logger.debug(f"   Unknown crypto in {slug}")
            return
        
        # Calculate trade params
        side = trade.get('side', 'BUY')
        kalshi_side = 'YES' if side == 'BUY' else 'NO'
        price = int(float(trade.get('price', 0.5)) * 100)
        
        # Get competitor's trade size
        trade_size_usd = float(trade.get('usdcSize', 0))
        if trade_size_usd == 0:
            trade_size_usd = float(trade.get('size', 0))
        
        # OBSERVATION MODE: Just log stats, don't trade
        if self.observation_mode:
            if competitor not in self.cycle_stats:
                self.cycle_stats[competitor] = {'count': 0, 'total_usd': 0, 'trades': []}
            
            self.cycle_stats[competitor]['count'] += 1
            self.cycle_stats[competitor]['total_usd'] += trade_size_usd
            self.cycle_stats[competitor]['trades'].append({
                'crypto': crypto,
                'side': kalshi_side,
                'usd': trade_size_usd,
                'price': price
            })
            
            logger.info(f"   👁️  OBSERVED: {competitor} {crypto} {kalshi_side} ${trade_size_usd:.2f} @ {price}c")
            return
        
        # LIVE TRADING MODE
        position_key = (competitor, crypto, kalshi_side)
        opposite_key = (competitor, crypto, 'NO' if kalshi_side == 'YES' else 'YES')
        
        # CASE 1: Competitor is BUYING - we BUY too (allow doubling down)
        if side == 'BUY':
            # Check if we have opposite position - should we flip?
            if opposite_key in self.open_positions:
                logger.info(f"   🔄 Competitor flipped! Selling our {crypto} {'NO' if kalshi_side == 'YES' else 'YES'} position")
                await self._exit_position(competitor, crypto, 'NO' if kalshi_side == 'YES' else 'YES')
                # Don't immediately buy - wait for next signal
                return
            
            # Buy (even if already long - allows doubling down)
            size = self._get_position_size(competitor, trade_size_usd, price)
            if size == 0:
                return  # Max exposure reached
            
            qt = QueuedTrade(
                competitor=competitor,
                trade=trade,
                crypto=crypto,
                kalshi_side=kalshi_side,
                price=price,
                size=size,
                queued_at=datetime.now(timezone.utc)
            )
            
            if await self._execute_trade(qt):
                # Track/add to open position
                if position_key in self.open_positions:
                    # Doubling down - update average price
                    old = self.open_positions[position_key]
                    total_size = old['size'] + size
                    avg_price = (old['entry_price'] * old['size'] + price * size) / total_size
                    old['size'] = total_size
                    old['entry_price'] = avg_price
                    logger.info(f"   📈 DOUBLED DOWN: {competitor} {crypto} {kalshi_side} now x{total_size} @ {avg_price:.0f}c avg")
                else:
                    self.open_positions[position_key] = {
                        'size': size,
                        'entry_price': price,
                        'ticker': self.kalshi_markets.get(crypto),
                        'timestamp': datetime.now(timezone.utc)
                    }
                    logger.info(f"   📈 Opened position: {competitor} {crypto} {kalshi_side} x{size} @ {price}c")
                return
            
            self.trade_queue.append(qt)
            logger.info(f"   📥 Queued: {qt}")
        
        # CASE 2: Competitor is SELLING - we SELL our position
        else:  # side == 'SELL'
            # When competitor sells, we don't know which side they sold (YES or NO)
            # Check if we have ANY position in this crypto for this competitor
            yes_key = (competitor, crypto, 'YES')
            no_key = (competitor, crypto, 'NO')
            
            if yes_key in self.open_positions:
                logger.info(f"   💸 Competitor selling - exiting our {crypto} YES position!")
                await self._exit_position(competitor, crypto, 'YES')
            elif no_key in self.open_positions:
                logger.info(f"   💸 Competitor selling - exiting our {crypto} NO position!")
                await self._exit_position(competitor, crypto, 'NO')
            else:
                logger.info(f"   ⚠️ Competitor sold {crypto} but we have no position to exit")
    
    async def _poll_once(self):
        """Poll competitors once and process queue"""
        from competitor_tracker import PolymarketTracker
        
        # Process any queued trades first
        await self._process_queue()
        
        # Poll for new trades
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
        logger.info("🚀 PureCopy started with trade queue")
        
        # Refresh markets initially
        logger.info("📊 Discovering Kalshi markets...")
        self._refresh_kalshi_markets()
        
        poll_count = 0
        last_window = None
        
        while self._running:
            try:
                # Detect cycle changes for observation stats
                now_utc = datetime.now(timezone.utc)
                now_est = now_utc - timedelta(hours=5)
                current_minute = now_est.minute
                current_window = current_minute // 15  # 0, 1, 2, or 3
                
                if last_window is not None and current_window != last_window:
                    # Window changed - log cycle stats and reset exposure
                    if self.observation_mode and self.cycle_stats:
                        self._log_cycle_stats()
                    # Reset exposure tracking for new cycle and log trader performance
                    if not self.observation_mode:
                        logger.info(f"🔄 New cycle starting - resetting exposure (was ${self.open_exposure:.2f})")
                        self._log_trader_performance()
                        self.open_exposure = 0.0
                last_window = current_window
                
                # Refresh markets and bankroll every 10 polls
                if poll_count % 10 == 0:
                    self._refresh_kalshi_markets()
                    if not self.observation_mode:
                        self._update_bankroll()
                        # Recalculate exposure from actual open positions (fixes drift)
                        self._recalculate_exposure()
                        logger.info(f"💰 Bankroll: ${self.our_bankroll:.2f}, Exposure: ${self.open_exposure:.2f} ({self.open_exposure/self.our_bankroll*100:.1f}%)")
                        logger.info(f"   Open positions: {len(self.open_positions)}")
                    else:
                        logger.info(f"👁️  OBSERVATION MODE - Watching competitors (bankroll: $21.70)")
                
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
        return {'name': self.name, 'trades': len(self.trades), 'queued': len(self.trade_queue)}
