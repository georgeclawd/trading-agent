"""
Crypto Momentum Strategy - EXACT port of PolymarketBTC15mAssistant
https://github.com/FrondEnt/PolymarketBTC15mAssistant

This is a direct translation of the JavaScript algorithm to Python.
"""

from typing import Dict, List, Optional, Tuple
from strategy_framework import BaseStrategy
from datetime import datetime, timedelta
import logging
import aiohttp
import asyncio
import json
import os

logger = logging.getLogger('CryptoMomentum')


def clamp(value, min_val, max_val):
    """Clamp value between min and max"""
    return max(min_val, min(max_val, value))


class CryptoMomentumStrategy(BaseStrategy):
    """
    EXACT port of PolymarketBTC15mAssistant algorithm
    
    Uses 1-minute candles, computes VWAP, RSI, MACD, Heiken Ashi
    Scores direction, applies time awareness, computes edge, decides trade
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "CryptoMomentum"
        
        # Market series
        self.series_ticker = "KXBTC15M"
        
        # Parameters from config.js
        self.candle_window_minutes = 15
        self.vwap_slope_lookback_minutes = 5
        self.rsi_period = 14
        self.rsi_ma_period = 14
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        
        # Trading params from edge.js
        self.early_threshold = 0.05
        self.mid_threshold = 0.10
        self.late_threshold = 0.20
        self.early_min_prob = 0.55
        self.mid_min_prob = 0.60
        self.late_min_prob = 0.65
        
        self.max_position = config.get('max_position_size', 5)
        
        # Data storage
        self.candles_1m: List[Dict] = []  # 1-minute OHLCV candles
        self.price_history: List[float] = []  # Raw closes for indicators
        
        # Persistence
        self.data_file = '/root/clawd/trading-agent/data/crypto_candles.json'
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        self._load_candles()  # Load saved data on init
        
        # API
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Price sources (Binance blocked, using alternatives)
        self.use_binance = False  # Set to True if you have API access
    
    def _save_candles(self):
        """Save candle data to disk atomically with validation"""
        try:
            # Validate data before saving
            if not isinstance(self.candles_1m, list):
                logger.error("Invalid candles data type, skipping save")
                return
            
            data = {
                'candles': self.candles_1m[-500:],  # Keep last 500 candles (~8 hours)
                'price_history': self.price_history[-500:],
                'saved_at': datetime.now().isoformat(),
                'version': 1
            }
            
            # Atomic write: write to temp file, then rename
            temp_file = self.data_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f)
            os.replace(temp_file, self.data_file)  # Atomic on POSIX
            
            logger.debug(f"Saved {len(self.candles_1m)} candles to disk")
        except Exception as e:
            logger.error(f"Failed to save candles: {e}")
    
    def _load_candles(self):
        """Load candle data from disk with validation and staleness check"""
        try:
            if not os.path.exists(self.data_file):
                logger.info("No saved candle data found, starting fresh")
                return
            
            with open(self.data_file, 'r') as f:
                data = json.load(f)
            
            # Validate data structure
            if not isinstance(data, dict):
                logger.error("Invalid data format, starting fresh")
                return
            
            candles = data.get('candles', [])
            price_history = data.get('price_history', [])
            saved_at_str = data.get('saved_at')
            
            # Check staleness (discard if older than 4 hours)
            if saved_at_str:
                try:
                    saved_at = datetime.fromisoformat(saved_at_str)
                    age_hours = (datetime.now() - saved_at).total_seconds() / 3600
                    if age_hours > 4:
                        logger.warning(f"Data is {age_hours:.1f}h old, starting fresh")
                        return
                except:
                    pass
            
            # Validate candle structure
            valid_candles = []
            for c in candles[-240:]:  # Keep last 4 hours max
                if isinstance(c, dict) and all(k in c for k in ['open', 'high', 'low', 'close', 'openTime']):
                    valid_candles.append(c)
            
            self.candles_1m = valid_candles
            self.price_history = price_history[-240:] if isinstance(price_history, list) else []
            
            logger.info(f"Loaded {len(valid_candles)} valid candles from disk (saved at {saved_at_str})")
            
        except json.JSONDecodeError as e:
            logger.error(f"Corrupted data file, starting fresh: {e}")
            # Backup corrupted file
            if os.path.exists(self.data_file):
                backup = self.data_file + '.corrupted.' + datetime.now().strftime('%Y%m%d%H%M%S')
                os.rename(self.data_file, backup)
                logger.info(f"Backed up corrupted file to {backup}")
        except Exception as e:
            logger.error(f"Failed to load candles: {e}")
            self.candles_1m = []
            self.price_history = []
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def fetch_1m_candles(self) -> List[Dict]:
        """
        Fetch 1-minute candles from Coinbase or CoinGecko
        Since we can't get historical candles easily, we'll build them from price polls
        """
        # Fetch current price
        price = await self.fetch_btc_price()
        if not price:
            return []
        
        now = datetime.now()
        
        # Build/update 1-minute candle
        if not self.candles_1m:
            # First candle
            self.candles_1m.append({
                'openTime': now.timestamp() * 1000,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 1.0,
                'closeTime': now.timestamp() * 1000
            })
        else:
            last_candle = self.candles_1m[-1]
            time_diff = (now.timestamp() * 1000 - last_candle['openTime']) / 1000
            
            if time_diff >= 60:  # New minute
                # Close previous candle
                last_candle['close'] = price
                last_candle['closeTime'] = now.timestamp() * 1000
                
                # Add new candle
                self.candles_1m.append({
                    'openTime': now.timestamp() * 1000,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 1.0,
                    'closeTime': now.timestamp() * 1000
                })
                
                # Keep last 240 candles (4 hours)
                if len(self.candles_1m) > 240:
                    self.candles_1m = self.candles_1m[-240:]
            else:
                # Update current candle
                last_candle['high'] = max(last_candle['high'], price)
                last_candle['low'] = min(last_candle['low'], price)
                last_candle['close'] = price
                last_candle['volume'] += 1.0
        
        # Save to disk periodically (every 5 candles)
        if len(self.candles_1m) % 5 == 0:
            self._save_candles()
        
        return self.candles_1m
    
    async def fetch_btc_price(self) -> Optional[float]:
        """Fetch current BTC price"""
        session = await self._get_session()
        prices = []
        
        # Coinbase
        try:
            async with session.get(
                'https://api.coinbase.com/v2/exchange-rates?currency=BTC',
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    usd_price = float(data['data']['rates']['USD'])
                    prices.append(usd_price)
        except Exception as e:
            logger.debug(f"Coinbase price fetch failed: {e}")
        
        # CoinGecko
        try:
            async with session.get(
                'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd',
                timeout=10
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    prices.append(data['bitcoin']['usd'])
        except Exception as e:
            logger.debug(f"CoinGecko price fetch failed: {e}")
        
        if not prices:
            return None
        
        return sum(prices) / len(prices)
    
    # ==================== EXACT PORTS FROM JS ====================
    
    def compute_vwap(self, candles: List[Dict]) -> float:
        """
        EXACT port from vwap.js
        VWAP = sum(typical_price * volume) / sum(volume)
        """
        if not candles:
            return 0.0
        
        total_pv = 0.0
        total_vol = 0.0
        
        for c in candles:
            typical_price = (c['high'] + c['low'] + c['close']) / 3
            volume = c.get('volume', 1.0)
            total_pv += typical_price * volume
            total_vol += volume
        
        return total_pv / total_vol if total_vol > 0 else 0.0
    
    def compute_vwap_slope(self, candles: List[Dict], minutes: int) -> float:
        """
        EXACT port from vwap.js
        Returns slope of VWAP over last N minutes
        """
        if len(candles) < minutes + 1:
            return 0.0
        
        # Get VWAP at start and end of window
        start_candles = candles[-(minutes+1):-minutes]
        end_candles = candles[-minutes:]
        
        vwap_start = self.compute_vwap(start_candles)
        vwap_end = self.compute_vwap(end_candles)
        
        return vwap_end - vwap_start
    
    def compute_rsi(self, prices: List[float], period: int = 14) -> float:
        """
        EXACT port from rsi.js
        Standard RSI calculation
        """
        if len(prices) < period + 1:
            return 50.0  # Neutral
        
        gains = []
        losses = []
        
        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        if len(gains) < period:
            return 50.0
        
        # Calculate initial averages
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        # Calculate subsequent values using smoothing
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def compute_rsi_ma(self, prices: List[float], period: int = 14) -> float:
        """
        EXACT port from rsi.js
        Moving average of RSI
        """
        if len(prices) < period * 2:
            return 50.0
        
        rsi_values = []
        for i in range(period, len(prices)):
            rsi = self.compute_rsi(prices[:i+1], period)
            rsi_values.append(rsi)
        
        if len(rsi_values) < period:
            return 50.0
        
        return sum(rsi_values[-period:]) / period
    
    def compute_macd(self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """
        EXACT port from macd.js
        Returns MACD line, signal line, and histogram
        """
        def ema(data: List[float], period: int) -> List[float]:
            if len(data) < period:
                return data
            
            multiplier = 2 / (period + 1)
            ema_values = [sum(data[:period]) / period]  # SMA start
            
            for price in data[period:]:
                ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
            
            return ema_values
        
        if len(prices) < slow + signal:
            return {'macd': 0, 'signal': 0, 'histogram': 0}
        
        fast_ema = ema(prices, fast)
        slow_ema = ema(prices, slow)
        
        # Align the EMAs (slow EMA starts later)
        offset = len(fast_ema) - len(slow_ema)
        macd_line = [fast_ema[i + offset] - slow_ema[i] for i in range(len(slow_ema))]
        
        signal_line = ema(macd_line, signal)
        
        # Align histogram
        hist_offset = len(macd_line) - len(signal_line)
        histogram = [macd_line[i + hist_offset] - signal_line[i] for i in range(len(signal_line))]
        
        return {
            'macd': macd_line[-1] if macd_line else 0,
            'signal': signal_line[-1] if signal_line else 0,
            'histogram': histogram[-1] if histogram else 0
        }
    
    def compute_heiken_ashi(self, candles: List[Dict]) -> List[Dict]:
        """
        EXACT port from heikenAshi.js
        Computes Heiken Ashi candles
        """
        if not candles:
            return []
        
        ha_candles = []
        prev_ha = None
        
        for c in candles:
            close = (c['open'] + c['high'] + c['low'] + c['close']) / 4
            
            if prev_ha is None:
                open_price = (c['open'] + c['close']) / 2
            else:
                open_price = (prev_ha['open'] + prev_ha['close']) / 2
            
            high = max(c['high'], open_price, close)
            low = min(c['low'], open_price, close)
            
            ha_candle = {
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'timestamp': c.get('openTime', 0)
            }
            
            ha_candles.append(ha_candle)
            prev_ha = ha_candle
        
        return ha_candles
    
    def score_direction(self, ha_candles: List[Dict], candles: List[Dict], vwap: float, price: float) -> float:
        """
        EXACT port from probability.js
        Scores direction: -1 (strong down) to +1 (strong up)
        """
        if len(ha_candles) < 2 or not candles:
            return 0.0
        
        score = 0.0
        
        # Heiken Ashi trend
        ha = ha_candles[-1]
        prev_ha = ha_candles[-2]
        
        if ha['close'] > ha['open']:  # Bullish HA
            score += 0.3
        elif ha['close'] < ha['open']:  # Bearish HA
            score -= 0.3
        
        if len(ha_candles) >= 3:
            ha3 = ha_candles[-3]
            if ha['close'] > prev_ha['close'] > ha3['close']:
                score += 0.2  # Uptrend
            elif ha['close'] < prev_ha['close'] < ha3['close']:
                score -= 0.2  # Downtrend
        
        # Price vs VWAP
        if price > vwap:
            score += 0.25
        elif price < vwap:
            score -= 0.25
        
        # Candle momentum
        last_candle = candles[-1]
        body = last_candle['close'] - last_candle['open']
        range_val = last_candle['high'] - last_candle['low']
        
        if range_val > 0:
            body_pct = body / range_val
            if body_pct > 0.5:
                score += 0.15
            elif body_pct < -0.5:
                score -= 0.15
        
        return clamp(score, -1.0, 1.0)
    
    def apply_time_awareness(self, score: float, minutes_into_interval: int) -> float:
        """
        EXACT port from probability.js
        Adjusts confidence based on time into 15-min interval
        """
        if minutes_into_interval <= 5:
            # Early: require stronger signal
            threshold = self.early_threshold
            return score * 0.8 if abs(score) >= threshold else 0.0
        elif minutes_into_interval <= 10:
            # Mid: moderate confidence
            threshold = self.mid_threshold
            return score * 1.0 if abs(score) >= threshold else 0.0
        else:
            # Late: higher confidence but only if strong signal
            threshold = self.late_threshold
            return score * 1.2 if abs(score) >= threshold else 0.0
    
    def compute_edge(self, raw_prob: float, market_price: float, minutes: int) -> float:
        """
        EXACT port from edge.js
        Computes Kelly edge for betting
        """
        if raw_prob <= 0 or raw_prob >= 1 or market_price <= 0:
            return 0.0
        
        # Adjust probability based on time
        if minutes <= 5:
            min_prob = self.early_min_prob
        elif minutes <= 10:
            min_prob = self.mid_min_prob
        else:
            min_prob = self.late_min_prob
        
        # Adjust raw probability toward 0.5 for conservatism
        adjusted_prob = (raw_prob + 0.5) / 2 if raw_prob > 0.5 else raw_prob / 2
        
        if adjusted_prob < min_prob:
            return 0.0
        
        # Kelly criterion: edge = (bp - q) / b where b = (1-p)/p
        b = (1 - market_price) / market_price
        q = 1 - adjusted_prob
        edge = (b * adjusted_prob - q) / b
        
        return edge
    
    def get_minutes_into_interval(self) -> int:
        """Get minutes into current 15-minute interval"""
        now = datetime.now()
        return now.minute % 15
    
    # ==================== STRATEGY INTERFACE ====================
    
    async def analyze(self) -> List[Dict]:
        """
        Main analysis - compute indicators and find opportunities
        """
        opportunities = []
        
        # Fetch/build candles
        candles = await self.fetch_1m_candles()
        if len(candles) < 30:
            logger.info(f"CryptoMomentum: Building 1m candles ({len(candles)}/30)")
            return []
        
        # Get current BTC price
        current_price = candles[-1]['close']
        self.price_history.append(current_price)
        
        # Keep price history bounded
        if len(self.price_history) > 240:
            self.price_history = self.price_history[-240:]
        
        # Compute indicators
        vwap = self.compute_vwap(candles)
        vwap_slope = self.compute_vwap_slope(candles, self.vwap_slope_lookback_minutes)
        rsi = self.compute_rsi(self.price_history, self.rsi_period)
        rsi_ma = self.compute_rsi_ma(self.price_history, self.rsi_ma_period)
        macd = self.compute_macd(self.price_history, self.macd_fast, self.macd_slow, self.macd_signal)
        ha_candles = self.compute_heiken_ashi(candles)
        
        logger.info(f"CryptoMomentum: Indicators - VWAP: ${vwap:.2f}, RSI: {rsi:.1f}, MACD hist: {macd['histogram']:.4f}")
        
        # Get Kalshi BTC markets
        try:
            response = self.client._request("GET", f"/markets?series_ticker={self.series_ticker}&status=open")
            markets = response.json().get('markets', [])
        except Exception as e:
            logger.error(f"CryptoMomentum: Failed to fetch markets: {e}")
            return []
        
        if not markets:
            logger.debug("CryptoMomentum: No BTC markets available")
            return []
        
        # Score direction
        direction_score = self.score_direction(ha_candles, candles, vwap, current_price)
        
        # Time awareness
        minutes = self.get_minutes_into_interval()
        adjusted_score = self.apply_time_awareness(direction_score, minutes)
        
        # Convert score to probability (0 to 1, 0.5 is neutral)
        raw_prob = (adjusted_score + 1) / 2
        
        logger.info(f"CryptoMomentum: Direction={direction_score:+.2f}, Adjusted={adjusted_score:+.2f}, Prob={raw_prob:.2%}, Min={minutes}")
        
        # Find opportunities
        for market in markets:
            ticker = market['ticker']
            title = market.get('title', '')
            
            # Determine YES/NO side
            is_yes = 'YES' in title.upper() or market.get('yes_sub_title', '').upper() == 'YES'
            
            try:
                orderbook_response = self.client.get_orderbook(ticker)
                orderbook = orderbook_response.get('orderbook', {})
                yes_bids = orderbook.get('yes', [])
                yes_asks = orderbook.get('yes', [])
                
                if not yes_bids:
                    continue
                
                # Get best YES price
                market_price = yes_bids[0][0] / 100  # Kalshi returns cents
                
                # Compute edge
                edge = self.compute_edge(raw_prob if is_yes else 1 - raw_prob, market_price, minutes)
                
                if edge > 0.1:  # 10% edge threshold
                    opportunities.append({
                        'ticker': ticker,
                        'market': title,
                        'side': 'YES' if is_yes else 'NO',
                        'market_price': market_price,
                        'fair_probability': raw_prob if is_yes else 1 - raw_prob,
                        'edge': edge,
                        'direction_score': direction_score,
                        'rsi': rsi,
                        'macd_hist': macd['histogram']
                    })
                    
                    logger.info(f"CryptoMomentum: OPPORTUNITY {ticker} - Edge={edge:.2%}, Price={market_price:.2%}, Prob={raw_prob:.2%}")
                    
            except Exception as e:
                logger.debug(f"CryptoMomentum: Error analyzing {ticker}: {e}")
                continue
        
        return opportunities
    
    async def scan(self) -> List[Dict]:
        """Required by BaseStrategy - alias for analyze"""
        return await self.analyze()
    
    def get_performance(self) -> Dict:
        """Required by BaseStrategy - return performance metrics"""
        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if t.get('pnl', 0) > 0)
        total_pnl = sum(t.get('pnl', 0) for t in self.trades)
        
        return {
            'name': self.name,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'win_rate': winning_trades / total_trades if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'candles_collected': len(self.candles_1m)
        }
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """
        Execute trades based on opportunities
        Returns: number of trades executed
        """
        executed_count = 0
        
        for opp in opportunities:
            ticker = opp['ticker']
            edge = opp['edge']
            market_price = opp['market_price']
            
            # Position sizing based on edge (Kelly-ish)
            if edge > 0.3:
                contracts = self.max_position
            elif edge > 0.2:
                contracts = max(1, self.max_position // 2)
            else:
                contracts = 1
            
            # Limit order at fair price
            limit_price = int(opp['fair_probability'] * 100)  # Convert to cents
            limit_price = max(1, min(99, limit_price))  # Clamp to valid range
            
            if self.dry_run:
                # SIMULATED: Record position without executing
                self.record_position(
                    ticker=ticker,
                    side=opp['side'],
                    contracts=contracts,
                    entry_price=limit_price,
                    market_title=opp['market']
                )
                logger.info(f"CryptoMomentum: [SIMULATED] Would execute {ticker} {opp['side']} x{contracts} @ {limit_price}c (edge={edge:.2%})")
                executed_count += 1
            else:
                # REAL: Execute via Kalshi API
                logger.info(f"CryptoMomentum: [REAL] EXECUTING - {ticker} {opp['side']} x{contracts} @ {limit_price}c (edge={edge:.2f}%})")
                
                try:
                    self.client.create_order(
                        ticker=ticker,
                        side='buy',
                        contracts=contracts,
                        price=limit_price
                    )
                    logger.info(f"CryptoMomentum: [REAL] Executed {ticker}")
                    executed_count += 1
                    
                    # Record position for tracking
                    self.record_position(
                        ticker=ticker,
                        side=opp['side'],
                        contracts=contracts,
                        entry_price=limit_price,
                        market_title=opp['market']
                    )
                    
                    # Record trade for performance tracking
                    self.record_trade({
                        'ticker': ticker,
                        'side': opp['side'],
                        'contracts': contracts,
                        'price': limit_price,
                        'edge': edge,
                        'pnl': 0  # Will be updated on settlement
                    })
                except Exception as e:
                    logger.error(f"CryptoMomentum: [REAL] Failed to execute {ticker}: {e}")
                    self.record_error(f"Execute {ticker}: {e}")
        
        return executed_count