"""
Pure Copy Trading Strategy - SIMULATION MODE

4-hour simulation with $1000 starting balance.
Logs all trades that WOULD have been made and calculates P&L.
"""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone, timedelta
from strategy_framework import BaseStrategy

logger = logging.getLogger('PureCopyTrading')


class PureCopyStrategy(BaseStrategy):
    """
    SIMULATION: Copy distinct-baguette trades, track hypothetical P&L
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "PureCopy-SIMULATION"
        
        # Only copy distinct-baguette
        self.competitor_address = '0xe00740bce98a594e26861838885ab310ec3b548c'
        self.competitor_bankroll = 6800
        
        self.seen_trades = set()
        self._running = False
        
        # SIMULATION PARAMETERS
        self.simulation_start_balance = 1000.00  # Starting with $1000
        self.simulated_balance = 1000.00
        self.simulated_exposure = 0.0
        
        # Current window tracking
        self.current_window_end = None
        self.active_markets = {}  # crypto -> kalshi_ticker for current window
        
        # Track simulated positions
        self.simulated_positions = {}  # crypto -> {size, side, entry_price, ticker}
        
        # Trade log for analysis
        self.simulated_trades = []  # List of all simulated trades
        
        # Track baguette's trades for comparison
        self.baguette_trades = []
        
        logger.info("🎮 SIMULATION MODE ACTIVE")
        logger.info(f"   Starting balance: ${self.simulation_start_balance:.2f}")
        logger.info("   No real trades will be executed")
        logger.info("=" * 70)
    
    def _get_current_window_times(self):
        """Get start and end of current 15-min window"""
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        window_start_minute = (current_minute // 15) * 15
        
        window_start = now.replace(minute=window_start_minute, second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=15)
        
        return window_start, window_end
    
    def _get_window_timestamp(self, dt: datetime):
        """Convert datetime to window timestamp string"""
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
                markets = self.client.get_markets(series_ticker=series, limit=20)
                
                for m in markets:
                    ticker = m.get('ticker', '')
                    status = m.get('status', '')
                    close_time = m.get('close_time', '')
                    
                    if status != 'active':
                        continue
                    
                    if close_time:
                        close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                        if close_dt == window_end or close_dt.strftime('%H%M') == window_ts:
                            self.active_markets[crypto] = ticker
                            logger.info(f"  ✅ {crypto}: {ticker}")
                            break
                            
            except Exception as e:
                logger.error(f"  ❌ Error finding {crypto} market: {e}")
        
        return len(self.active_markets) > 0
    
    def _check_window_change(self):
        """Check if we've moved to a new window"""
        now = datetime.now(timezone.utc)
        
        if self.current_window_end and now >= self.current_window_end:
            logger.info(f"🔄 Window expired - settling positions")
            self._settle_window_positions()
            logger.info("   Finding markets for NEW window...")
            self.seen_trades.clear()
            return self._find_current_window_markets()
        
        return False
    
    def _settle_window_positions(self):
        """Settle all positions at window end (0 or 100 based on market outcome)"""
        logger.info("📊 SETTLING WINDOW POSITIONS:")
        
        for crypto, pos in list(self.simulated_positions.items()):
            size = pos['size']
            side = pos['side']
            entry_price = pos['entry_price']
            
            # SIMULATION: Assume 50/50 outcome for now
            # In reality, we'd check actual market settlement
            settle_price = 50  # 50 cents = breakeven expectation
            
            if side == 'YES':
                pnl = (settle_price - entry_price) * size * 0.01
            else:
                pnl = (entry_price - settle_price) * size * 0.01
            
            self.simulated_balance += pnl
            
            logger.info(f"   {crypto}: {side} x{size} @ {entry_price}c -> settle @ {settle_price}c = ${pnl:+.2f}")
            
            self.simulated_trades.append({
                'type': 'SETTLE',
                'crypto': crypto,
                'side': side,
                'size': size,
                'entry_price': entry_price,
                'exit_price': settle_price,
                'pnl': pnl,
                'time': datetime.now(timezone.utc).isoformat()
            })
        
        self.simulated_positions.clear()
        logger.info(f"   New balance: ${self.simulated_balance:.2f}")
    
    def _get_position_size(self, trade_size_usd: float) -> int:
        """Calculate position size based on competitor's trade relative to their bankroll"""
        their_pct = trade_size_usd / self.competitor_bankroll
        our_trade_usd = self.simulated_balance * their_pct
        
        # Max 10% per trade
        our_trade_usd = min(our_trade_usd, self.simulated_balance * 0.10)
        
        if our_trade_usd < 0.50:
            return 1
        elif our_trade_usd < 1.50:
            return 2
        else:
            return 3
    
    def _log_market_prices(self):
        """Log current market prices for all active markets"""
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
    
    def _simulate_buy(self, crypto: str, price_cents: int, size: int, baguette_price: float) -> bool:
        """Simulate a buy - track but don't execute"""
        ticker = self.active_markets.get(crypto)
        if not ticker:
            return False
        
        cost = size * price_cents * 0.01
        
        if cost > self.simulated_balance:
            logger.warning(f"  ❌ INSUFFICIENT FUNDS: Need ${cost:.2f}, have ${self.simulated_balance:.2f}")
            return False
        
        self.simulated_balance -= cost
        
        # Track position
        if crypto in self.simulated_positions:
            old = self.simulated_positions[crypto]
            old['size'] += size
            old['entry_price'] = (old['entry_price'] + price_cents) / 2
        else:
            self.simulated_positions[crypto] = {
                'size': size,
                'side': 'YES',
                'entry_price': price_cents,
                'ticker': ticker
            }
        
        logger.info(f"  💰 SIM BUY: {crypto} YES x{size} @ {price_cents}c = ${cost:.2f}")
        logger.info(f"     Simulated balance: ${self.simulated_balance:.2f}")
        
        self.simulated_trades.append({
            'type': 'BUY',
            'crypto': crypto,
            'side': 'YES',
            'size': size,
            'price': price_cents,
            'cost': cost,
            'time': datetime.now(timezone.utc).isoformat()
        })
        
        return True
    
    def _simulate_sell(self, crypto: str, size: int, baguette_price: float) -> bool:
        """Simulate a sell - track but don't execute"""
        if crypto not in self.simulated_positions:
            logger.warning(f"  ⚠️ No position to sell for {crypto}")
            return False
        
        pos = self.simulated_positions[crypto]
        ticker = pos['ticker']
        
        # Get current market price
        try:
            r = self.client._request("GET", f"/markets/{ticker}")
            if r.status_code == 200:
                m = r.json().get('market', {})
                exit_price = m.get('yes_bid', 0)  # What we can sell at
            else:
                exit_price = 50  # Fallback
        except:
            exit_price = 50
        
        entry_price = pos['entry_price']
        pnl = (exit_price - entry_price) * size * 0.01
        revenue = size * exit_price * 0.01
        
        self.simulated_balance += revenue
        pos['size'] -= size
        
        if pos['size'] <= 0:
            del self.simulated_positions[crypto]
        
        logger.info(f"  💸 SIM SELL: {crypto} YES x{size} @ {exit_price}c = ${revenue:.2f} (PnL: ${pnl:+.2f})")
        logger.info(f"     Simulated balance: ${self.simulated_balance:.2f}")
        
        self.simulated_trades.append({
            'type': 'SELL',
            'crypto': crypto,
            'side': 'YES',
            'size': size,
            'price': exit_price,
            'revenue': revenue,
            'pnl': pnl,
            'time': datetime.now(timezone.utc).isoformat()
        })
        
        return True
    
    async def scan(self):
        """Main loop - poll and simulate trades"""
        from competitor_tracker import PolymarketTracker
        
        self._running = True
        logger.info("🎮 SIMULATION STARTED")
        logger.info(f"   Start: ${self.simulation_start_balance:.2f}")
        logger.info("   Duration: 4 hours")
        logger.info("=" * 70)
        
        # Find initial markets
        self._find_current_window_markets()
        
        tracker = PolymarketTracker()
        start_time = datetime.now(timezone.utc)
        
        while self._running:
            try:
                # Check for 4-hour limit
                elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
                if elapsed > 14400:  # 4 hours
                    logger.info("=" * 70)
                    logger.info("⏰ 4-HOUR SIMULATION COMPLETE")
                    await self._print_final_report()
                    break
                
                # Check for window change
                self._check_window_change()
                
                # Log status
                now = datetime.now(timezone.utc)
                time_to_close = (self.current_window_end - now).total_seconds() if self.current_window_end else 0
                
                # Log prices every minute
                if int(elapsed) % 60 == 0:
                    self._log_market_prices()
                
                logger.info(f"💰 Sim Balance: ${self.simulated_balance:.2f} | Window: {int(time_to_close/60)}m | Pos: {list(self.simulated_positions.keys())}")
                
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
                    side = trade.get('side', '')
                    size_usd = float(trade.get('size', 0))
                    price = float(trade.get('price', 0.5))
                    
                    # Extract crypto and EXACT expiration from slug
                    # Format: eth-updown-15m-1234567890 (Unix timestamp)
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
                    
                    # Get Polymarket OPEN timestamp (when window starts)
                    try:
                        pm_timestamp = int(parts[3])
                        pm_open_dt = datetime.fromtimestamp(pm_timestamp, tz=timezone.utc)
                        pm_open_str = pm_open_dt.strftime('%H:%M UTC')
                    except:
                        logger.debug(f"Could not parse timestamp from {slug}")
                        continue
                    
                    if crypto not in self.active_markets:
                        continue
                    
                    # Verify Kalshi market matches Polymarket OPEN time
                    kalshi_ticker = self.active_markets[crypto]
                    try:
                        r = self.client._request("GET", f"/markets/{kalshi_ticker}")
                        if r.status_code == 200:
                            kalshi_open = r.json().get('market', {}).get('open_time', '')
                            if kalshi_open:
                                kalshi_dt = datetime.fromisoformat(kalshi_open.replace('Z', '+00:00'))
                                # Check if they match (within 1 minute)
                                time_diff = abs((kalshi_dt - pm_open_dt).total_seconds())
                                if time_diff > 60:  # More than 1 minute difference
                                    logger.info(f"⏭️  Skipping {crypto} - window mismatch")
                                    logger.info(f"   PM open: {pm_open_str} | Kalshi open: {kalshi_dt.strftime('%H:%M UTC')} | Diff: {int(time_diff/60)}m")
                                    continue
                                else:
                                    logger.info(f"✅ {crypto} window MATCH: {pm_open_str}")
                            else:
                                continue
                        else:
                            continue
                    except Exception as e:
                        logger.debug(f"Error checking Kalshi open time: {e}")
                        continue
                    
                    logger.info(f"🚨 distinct-baguette: {side} {crypto} ${size_usd:.2f} @ {price:.2f}")
                    
                    # Record baguette's trade
                    self.baguette_trades.append({
                        'side': side,
                        'crypto': crypto,
                        'size': size_usd,
                        'price': price,
                        'time': datetime.now(timezone.utc).isoformat()
                    })
                    
                    # Simulate
                    if side == 'BUY':
                        price_cents = int(price * 100)
                        position_size = self._get_position_size(size_usd)
                        self._simulate_buy(crypto, price_cents, position_size, price)
                    else:  # SELL
                        position_size = self._get_position_size(size_usd)
                        self._simulate_sell(crypto, position_size, price)
                
                await asyncio.sleep(5)
                
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(5)
    
    async def _print_final_report(self):
        """Print final simulation report"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 SIMULATION FINAL REPORT")
        logger.info("=" * 70)
        
        # Settle any remaining positions at current market price
        logger.info("\nSettling remaining positions at current prices:")
        for crypto, pos in list(self.simulated_positions.items()):
            ticker = pos['ticker']
            try:
                r = self.client._request("GET", f"/markets/{ticker}")
                if r.status_code == 200:
                    m = r.json().get('market', {})
                    settle_price = m.get('yes_bid', 50)
                else:
                    settle_price = 50
            except:
                settle_price = 50
            
            entry = pos['entry_price']
            size = pos['size']
            pnl = (settle_price - entry) * size * 0.01
            self.simulated_balance += pnl + (size * settle_price * 0.01)
            
            logger.info(f"   {crypto}: {pos['side']} x{size} @ {entry}c -> settle @ {settle_price}c = ${pnl:+.2f}")
        
        self.simulated_positions.clear()
        
        # Calculate results
        total_pnl = self.simulated_balance - self.simulation_start_balance
        pnl_pct = (total_pnl / self.simulation_start_balance) * 100
        
        logger.info("\n" + "=" * 70)
        logger.info("💰 RESULTS:")
        logger.info("=" * 70)
        logger.info(f"   Start Balance: ${self.simulation_start_balance:.2f}")
        logger.info(f"   End Balance:   ${self.simulated_balance:.2f}")
        logger.info(f"   Total P&L:     ${total_pnl:+.2f} ({pnl_pct:+.2f}%)")
        logger.info(f"   Total Trades:  {len(self.simulated_trades)}")
        
        # Count baguette trades
        baguette_buys = sum(1 for t in self.baguette_trades if t['side'] == 'BUY')
        baguette_sells = sum(1 for t in self.baguette_trades if t['side'] == 'SELL')
        
        logger.info("\n👤 BAGUETTE COMPARISON:")
        logger.info(f"   Baguette trades copied: {len(self.baguette_trades)}")
        logger.info(f"   (Buys: {baguette_buys}, Sells: {baguette_sells})")
        
        logger.info("\n" + "=" * 70)
        logger.info("Trade log saved to: logs/simulation_trades.json")
        logger.info("=" * 70)
        
        # Save detailed trade log
        import json
        with open('logs/simulation_trades.json', 'w') as f:
            json.dump({
                'start_balance': self.simulation_start_balance,
                'end_balance': self.simulated_balance,
                'pnl': total_pnl,
                'pnl_pct': pnl_pct,
                'our_trades': self.simulated_trades,
                'baguette_trades': self.baguette_trades
            }, f, indent=2)
    
    async def continuous_trade_loop(self):
        """Entry point for continuous trading"""
        await self.scan()
    
    async def execute(self, opportunities):
        """Execute trades - not used in simulation"""
        return 0
    
    def get_performance(self):
        """Get performance metrics"""
        return {
            'simulated_balance': self.simulated_balance,
            'pnl': self.simulated_balance - self.simulation_start_balance,
            'trades': len(self.simulated_trades)
        }
