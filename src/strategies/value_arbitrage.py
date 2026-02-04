"""
Value Arbitrage Strategy

Uses Polymarket as a leading indicator + real-time price data
to find mispriced opportunities on Kalshi.

Logic:
1. Get real-time crypto price from CoinGecko
2. Get Polymarket implied probability (leading indicator)
3. Get Kalshi odds
4. If Kalshi odds diverge significantly from "true" probability,
   bet on the value side

Example:
- BTC price: $97,000
- Strike: $97,500 (needs to go up)
- Polymarket says 65% chance UP (leading indicator)
- Kalshi says 40% chance UP (mispriced!)
- Bet YES on Kalshi at 40¢ (true value ~65¢)
"""

import asyncio
import logging
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional
from strategy_framework import BaseStrategy

logger = logging.getLogger('ValueArbitrage')


class ValueArbitrageStrategy(BaseStrategy):
    """
    Find value bets by comparing Kalshi odds to:
    - Real-time crypto prices
    - Polymarket implied probabilities (leading indicator)
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "ValueArbitrage"
        
        # Thresholds
        self.min_edge = 0.10  # Minimum 10% edge required
        self.max_position = 3  # Max contracts per bet
        
        # Track current window
        self.current_window_end = None
        self.active_markets = {}  # crypto -> {ticker, strike}
        
        logger.info("📊 Value Arbitrage Strategy initialized")
        logger.info(f"   Min edge: {self.min_edge*100:.0f}%")
        logger.info("=" * 70)
    
    def _get_current_window_times(self):
        """Get start and end of current 15-min window"""
        now = datetime.now(timezone.utc)
        current_minute = now.minute
        window_start_minute = (current_minute // 15) * 15
        
        window_start = now.replace(minute=window_start_minute, second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=15)
        
        return window_start, window_end
    
    def _get_crypto_price(self, crypto: str) -> Optional[float]:
        """Get real-time price from CoinGecko"""
        coin_map = {
            'BTC': 'bitcoin',
            'ETH': 'ethereum',
            'SOL': 'solana'
        }
        
        coin_id = coin_map.get(crypto)
        if not coin_id:
            return None
        
        try:
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                return data.get(coin_id, {}).get('usd')
        except Exception as e:
            logger.error(f"Error getting {crypto} price: {e}")
        
        return None
    
    def _get_polymarket_odds(self, crypto: str, window_ts: int) -> Optional[float]:
        """
        Get implied probability from Polymarket for this window.
        Returns probability as decimal (0.0-1.0)
        """
        from competitor_tracker import PolymarketTracker
        
        tracker = PolymarketTracker()
        
        # Map crypto to Polymarket slug format
        slug_crypto = crypto.lower()
        if crypto == 'BTC':
            slug_crypto = 'btc'
        elif crypto == 'ETH':
            slug_crypto = 'eth'
        elif crypto == 'SOL':
            slug_crypto = 'sol'
        
        try:
            # Build slug pattern: {crypto}-updown-15m-{timestamp}
            slug = f"{slug_crypto}-updown-15m-{window_ts}"
            
            # Fetch market directly by slug
            market = tracker.get_market_by_slug(slug)
            
            if market:
                best_ask = market.get('bestAsk', 0)  # Price to buy YES
                best_bid = market.get('bestBid', 0)  # Price to sell YES
                
                if best_ask > 0 and best_bid > 0:
                    # Mid price as implied probability
                    mid = (best_ask + best_bid) / 2
                    return mid
                elif best_ask > 0:
                    return best_ask
                elif best_bid > 0:
                    return best_bid
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting Polymarket odds: {e}")
            return None
    
    def _get_kalshi_odds(self, ticker: str) -> Optional[Dict]:
        """Get current odds from Kalshi market"""
        try:
            r = self.client._request("GET", f"/markets/{ticker}")
            if r.status_code == 200:
                m = r.json().get('market', {})
                yes_bid = m.get('yes_bid', 0) / 100  # Convert cents to decimal
                yes_ask = m.get('yes_ask', 0) / 100
                
                if yes_bid > 0 and yes_ask > 0:
                    return {
                        'yes_bid': yes_bid,
                        'yes_ask': yes_ask,
                        'mid': (yes_bid + yes_ask) / 2
                    }
            return None
        except Exception as e:
            logger.error(f"Error getting Kalshi odds: {e}")
            return None
    
    def _calculate_true_probability(self, crypto: str, strike: float, current_price: float) -> float:
        """
        Calculate "true" probability based on:
        - Distance to strike
        - Historical volatility
        - Time remaining
        
        Simplified: Linear probability based on distance
        """
        if strike == 0:
            return 0.5
        
        pct_change_needed = (strike - current_price) / current_price
        
        # Rough heuristic:
        # +2% needed = ~35% chance
        # +1% needed = ~45% chance  
        # 0% needed = ~50% chance
        # -1% needed = ~55% chance
        # -2% needed = ~65% chance
        
        # Base probability
        base_prob = 0.50
        
        # Adjust for distance (roughly 10% per 1% price move)
        adjustment = -pct_change_needed * 10  # Negative because up = harder
        
        prob = base_prob + adjustment
        return max(0.05, min(0.95, prob))  # Clamp 5%-95%
    
    def _find_value_bets(self) -> list:
        """Find all value bets in current window"""
        value_bets = []
        window_start, window_end = self._get_current_window_times()
        window_ts = int(window_start.timestamp())
        
        logger.info(f"\n🔍 Scanning for value bets (window: {window_start.strftime('%H:%M')}-{window_end.strftime('%H:%M')})")
        
        for crypto in ['BTC', 'ETH', 'SOL']:
            if crypto not in self.active_markets:
                continue
            
            market_info = self.active_markets[crypto]
            ticker = market_info['ticker']
            
            # Get current price
            current_price = self._get_crypto_price(crypto)
            if not current_price:
                logger.warning(f"  {crypto}: Could not get current price")
                continue
            
            # Get Kalshi odds
            kalshi = self._get_kalshi_odds(ticker)
            if not kalshi:
                logger.warning(f"  {crypto}: Could not get Kalshi odds")
                continue
            
            # Get Polymarket odds (leading indicator)
            pm_prob = self._get_polymarket_odds(crypto, window_ts)
            
            # Calculate true probability based on price + distance
            # Note: Need to extract strike from market title
            # For now, assume strike is close to current price
            strike = current_price * 1.001  # Rough estimate
            true_prob = self._calculate_true_probability(crypto, strike, current_price)
            
            # Use Polymarket if available, otherwise use calculated
            if pm_prob:
                # Weighted average: 60% Polymarket (leading), 40% calculated
                estimated_prob = (pm_prob * 0.6) + (true_prob * 0.4)
                pm_str = f"PM:{pm_prob:.0%}"
            else:
                estimated_prob = true_prob
                pm_str = "PM:N/A"
            
            kalshi_mid = kalshi['mid']
            
            # Calculate edge
            edge = estimated_prob - kalshi_mid
            
            logger.info(f"\n  {crypto} @ ${current_price:,.0f}")
            logger.info(f"    Kalshi:  {kalshi['yes_bid']:.0%} - {kalshi['yes_ask']:.0%} (mid: {kalshi_mid:.0%})")
            logger.info(f"    Est prob: {estimated_prob:.0%} ({pm_str}, calc:{true_prob:.0%})")
            logger.info(f"    Edge: {edge:+.0%}")
            
            # Check for value
            if edge > self.min_edge:
                value_bets.append({
                    'crypto': crypto,
                    'ticker': ticker,
                    'side': 'YES',
                    'kalshi_ask': kalshi['yes_ask'],
                    'edge': edge,
                    'estimated_prob': estimated_prob,
                    'current_price': current_price
                })
                logger.info(f"    ✅ VALUE BET: YES at {kalshi['yes_ask']:.0%} (edge: {edge:.0%})")
            
            elif edge < -self.min_edge:
                # Edge negative = NO has value
                no_prob = 1 - estimated_prob
                no_edge = no_prob - (1 - kalshi_mid)
                if no_edge > self.min_edge:
                    value_bets.append({
                        'crypto': crypto,
                        'ticker': ticker,
                        'side': 'NO',
                        'kalshi_ask': 1 - kalshi['yes_bid'],
                        'edge': no_edge,
                        'estimated_prob': no_prob,
                        'current_price': current_price
                    })
                    logger.info(f"    ✅ VALUE BET: NO at {1-kalshi['yes_bid']:.0%} (edge: {no_edge:.0%})")
        
        return value_bets
    
    def _find_current_window_markets(self):
        """Find ACTIVE markets for current 15-min window"""
        window_start, window_end = self._get_current_window_times()
        self.current_window_end = window_end
        
        window_ts = window_end.strftime('%H%M')
        logger.info(f"🔍 Finding markets for window ending {window_ts}")
        
        self.active_markets = {}
        
        for crypto, series in [('BTC', 'KXBTC15M'), ('ETH', 'KXETH15M'), ('SOL', 'KXSOL15M')]:
            try:
                markets = self.client.get_markets(series_ticker=series, limit=20)
                
                for m in markets:
                    if m.get('status') != 'active':
                        continue
                    
                    close_time = m.get('close_time', '')
                    if close_time:
                        close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                        if close_dt == window_end:
                            self.active_markets[crypto] = {
                                'ticker': m['ticker'],
                                'title': m.get('title', '')
                            }
                            logger.info(f"  ✅ {crypto}: {m['ticker']}")
                            break
                            
            except Exception as e:
                logger.error(f"  ❌ Error finding {crypto} market: {e}")
        
        return len(self.active_markets) > 0
    
    async def scan(self):
        """Main loop - find and execute value bets"""
        self._running = True
        
        # Find initial markets
        self._find_current_window_markets()
        
        start_time = datetime.now(timezone.utc)
        
        while self._running:
            try:
                # Check for window change
                now = datetime.now(timezone.utc)
                if self.current_window_end and now >= self.current_window_end:
                    logger.info("🔄 Window expired - finding new markets")
                    self._find_current_window_markets()
                
                # Find value bets
                value_bets = self._find_value_bets()
                
                if value_bets:
                    logger.info(f"\n🎯 Found {len(value_bets)} value bets:")
                    for bet in value_bets:
                        logger.info(f"   {bet['crypto']} {bet['side']} @ {bet['kalshi_ask']:.0%} (edge: {bet['edge']:.0%})")
                    
                    # Execute bets
                    for bet in value_bets:
                        await self._execute_bet(bet)
                else:
                    logger.info("\n  No value bets found this cycle")
                
                # Wait before next scan
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error in scan loop: {e}")
                await asyncio.sleep(30)
    
    async def _execute_bet(self, bet: Dict):
        """Execute a value bet"""
        crypto = bet['crypto']
        ticker = bet['ticker']
        side = bet['side']
        edge = bet['edge']
        
        # Calculate position size based on edge
        # More edge = bigger position (up to max)
        size = min(self.max_position, max(1, int(edge * 10)))
        
        logger.info(f"\n🚀 EXECUTING: {crypto} {side} x{size}")
        logger.info(f"   Edge: {edge:.0%} | Est prob: {bet['estimated_prob']:.0%}")
        
        try:
            # Get current price for order
            r = self.client._request("GET", f"/markets/{ticker}")
            if r.status_code != 200:
                logger.error(f"   Failed to get market data")
                return
            
            market = r.json().get('market', {})
            
            if side == 'YES':
                price = market.get('yes_ask', 0)
            else:
                price = market.get('no_ask', 0)
            
            if price == 0:
                logger.warning(f"   No ask price available")
                return
            
            # Execute order using KalshiClient's place_order method
            # Convert YES/NO to side ('buy') and determine which side of market
            if side == 'YES':
                order_side = 'yes'
            else:
                order_side = 'no'
            
            order = self.client.place_order(
                market_id=ticker,
                side=order_side,
                price=price,
                count=size
            )
            
            if order:
                logger.info(f"   ✅ Order placed: {side} x{size} @ {price}c")
            else:
                logger.error(f"   ❌ Order failed")
                
        except Exception as e:
            logger.error(f"   ❌ Error executing bet: {e}")
    
    async def continuous_trade_loop(self):
        """Entry point"""
        await self.scan()
    
    async def execute(self, opportunities):
        """Execute trades - not used in this strategy"""
        return 0
    
    def get_performance(self):
        """Get performance metrics"""
        return {
            'trades_executed': 0,
            'total_pnl': 0.0,
            'win_rate': 0.0
        }
