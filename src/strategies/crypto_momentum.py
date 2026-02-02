"""
Crypto Momentum Strategy - 15 Minute Trading
Based on PolymarketBTC15mAssistant algorithm

Strategy:
- Monitor BTC price in real-time
- Calculate VWAP, RSI, MACD, Heiken Ashi
- Score direction (UP/DOWN) based on indicators
- Apply time decay as market approaches close
- Trade when model probability differs from market by threshold
"""

from typing import Dict, List, Optional, Tuple
from strategy_framework import BaseStrategy
from datetime import datetime, timedelta
import logging
import aiohttp
import asyncio

logger = logging.getLogger('CryptoMomentum')


class CryptoMomentumStrategy(BaseStrategy):
    """
    15-minute crypto momentum trading strategy based on PolymarketBTC15mAssistant
    
    Monitors BTC price and trades on momentum signals with time-aware probabilities.
    Works with Kalshi KXBTC15M markets.
    """
    
    def __init__(self, config: Dict, client):
        super().__init__(config, client)
        self.name = "CryptoMomentum"
        
        # Price tracking with OHLCV data
        self.price_history: List[Dict] = []  # OHLCV candles
        self.max_history = 50  # Keep last 50 candles
        
        # Market series to trade
        self.series_ticker = "KXBTC15M"
        
        # Trading parameters (from edge.js)
        self.early_threshold = 0.05   # 5% edge early (>10 min)
        self.mid_threshold = 0.10     # 10% edge mid (5-10 min)
        self.late_threshold = 0.20    # 20% edge late (<5 min)
        
        self.early_min_prob = 0.55    # 55% min prob early
        self.mid_min_prob = 0.60      # 60% min prob mid
        self.late_min_prob = 0.65     # 65% min prob late
        
        self.max_position = config.get('max_position_size', 5)
        
        # Price sources
        self.price_sources = [
            'https://api.coinbase.com/v2/exchange-rates?currency=BTC',
            'https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd',
        ]
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_price: Optional[float] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def fetch_btc_price(self) -> Optional[float]:
        """
        Fetch current BTC price from multiple sources
        """
        prices = []
        session = await self._get_session()
        
        # Try Coinbase
        try:
            async with session.get(self.price_sources[0], timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = data.get('data', {}).get('rates', {}).get('USD')
                    if rate:
                        price = float(rate)
                        prices.append(price)
                        logger.debug(f"Coinbase BTC price: ${price:,.2f}")
        except Exception as e:
            logger.debug(f"Coinbase price fetch failed: {e}")
        
        # Try CoinGecko
        try:
            async with session.get(self.price_sources[1], timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = data.get('bitcoin', {}).get('usd', 0)
                    if price > 0:
                        prices.append(float(price))
                        logger.debug(f"CoinGecko BTC price: ${price:,.2f}")
        except Exception as e:
            logger.debug(f"CoinGecko price fetch failed: {e}")
        
        if not prices:
            return None
        
        avg_price = sum(prices) / len(prices)
        logger.info(f"BTC price: ${avg_price:,.2f} (from {len(prices)} sources)")
        
        self.last_price = avg_price
        return avg_price
    
    def add_price_point(self, price: float):
        """Add price point and create OHLCV candles"""
        now = datetime.now()
        
        # Create 1-minute OHLCV candle
        if not self.price_history:
            # First candle
            self.price_history.append({
                'timestamp': now,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 1.0
            })
        else:
            last_candle = self.price_history[-1]
            time_diff = (now - last_candle['timestamp']).total_seconds()
            
            if time_diff >= 60:  # New minute
                # Close previous candle
                last_candle['close'] = price
                
                # Start new candle
                self.price_history.append({
                    'timestamp': now,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 1.0
                })
                
                # Trim history
                if len(self.price_history) > self.max_history:
                    self.price_history = self.price_history[-self.max_history:]
            else:
                # Update current candle
                last_candle['high'] = max(last_candle['high'], price)
                last_candle['low'] = min(last_candle['low'], price)
                last_candle['close'] = price
                last_candle['volume'] += 1.0
    
    def compute_vwap(self, candles: List[Dict]) -> Optional[float]:
        """Compute Volume Weighted Average Price"""
        if not candles:
            return None
        
        pv = 0  # Price * Volume sum
        v = 0   # Volume sum
        
        for c in candles:
            tp = (c['high'] + c['low'] + c['close']) / 3  # Typical price
            pv += tp * c['volume']
            v += c['volume']
        
        if v == 0:
            return None
        
        return pv / v
    
    def compute_rsi(self, candles: List[Dict], period: int = 14) -> Tuple[Optional[float], Optional[float]]:
        """Compute RSI and RSI slope"""
        if len(candles) < period + 2:
            return None, None
        
        closes = [c['close'] for c in candles]
        
        gains = []
        losses = []
        
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        # Use last 'period' values
        gains = gains[-period:]
        losses = losses[-period:]
        
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0
        
        if avg_loss == 0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        # Calculate RSI slope (change over last 3 periods)
        rsi_slope = None
        if len(closes) >= period + 3:
            # Simplified slope calculation
            rsi_slope = (closes[-1] - closes[-3]) / closes[-3] * 100
        
        return rsi, rsi_slope
    
    def compute_macd(self, candles: List[Dict]) -> Dict:
        """Compute MACD with histogram delta"""
        if len(candles) < 26:
            return {'macd': None, 'signal': None, 'hist': None, 'histDelta': None}
        
        closes = [c['close'] for c in candles]
        
        # Calculate EMAs
        ema_12 = self._calculate_ema(closes, 12)
        ema_26 = self._calculate_ema(closes, 26)
        
        if ema_12 is None or ema_26 is None:
            return {'macd': None, 'signal': None, 'hist': None, 'histDelta': None}
        
        # MACD line
        macd_line = ema_12 - ema_26
        
        # Signal line (9-period EMA of MACD)
        # We need historical MACD values - simplified approach
        macd_series = []
        for i in range(26, len(closes)):
            e12 = self._calculate_ema(closes[:i], 12)
            e26 = self._calculate_ema(closes[:i], 26)
            if e12 and e26:
                macd_series.append(e12 - e26)
        
        signal_line = self._calculate_ema(macd_series, 9) if len(macd_series) >= 9 else macd_line * 0.9
        
        # Histogram
        hist = macd_line - signal_line
        
        # Histogram delta (change from previous)
        hist_delta = None
        if len(macd_series) >= 2:
            prev_hist = macd_series[-2] - signal_line
            hist_delta = hist - prev_hist
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'hist': hist,
            'histDelta': hist_delta
        }
    
    def _calculate_ema(self, values: List[float], period: int) -> Optional[float]:
        """Calculate Exponential Moving Average"""
        if not values or len(values) < period:
            return None
        
        multiplier = 2 / (period + 1)
        ema = sum(values[:period]) / period
        
        for val in values[period:]:
            ema = (val - ema) * multiplier + ema
        
        return ema
    
    def compute_heiken_ashi(self, candles: List[Dict]) -> List[Dict]:
        """Compute Heiken Ashi candles"""
        if not candles:
            return []
        
        ha = []
        for i, c in enumerate(candles):
            ha_close = (c['open'] + c['high'] + c['low'] + c['close']) / 4
            
            if i > 0:
                ha_open = (ha[i-1]['open'] + ha[i-1]['close']) / 2
            else:
                ha_open = (c['open'] + c['close']) / 2
            
            ha_high = max(c['high'], ha_open, ha_close)
            ha_low = min(c['low'], ha_open, ha_close)
            
            ha.append({
                'open': ha_open,
                'high': ha_high,
                'low': ha_low,
                'close': ha_close,
                'isGreen': ha_close >= ha_open
            })
        
        return ha
    
    def count_consecutive_heiken(self, ha_candles: List[Dict]) -> Tuple[Optional[str], int]:
        """Count consecutive Heiken Ashi candles of same color"""
        if not ha_candles:
            return None, 0
        
        last = ha_candles[-1]
        color = "green" if last['isGreen'] else "red"
        
        count = 0
        for i in range(len(ha_candles) - 1, -1, -1):
            c = ha_candles[i]
            c_color = "green" if c['isGreen'] else "red"
            if c_color != color:
                break
            count += 1
        
        return color, count
    
    def score_direction(self, inputs: Dict) -> Dict:
        """
        Score UP vs DOWN direction based on indicators
        Based on PolymarketBTC15mAssistant probability.js
        """
        price = inputs.get('price')
        vwap = inputs.get('vwap')
        vwap_slope = inputs.get('vwap_slope')
        rsi = inputs.get('rsi')
        rsi_slope = inputs.get('rsi_slope')
        macd = inputs.get('macd', {})
        heiken_color = inputs.get('heiken_color')
        heiken_count = inputs.get('heiken_count', 0)
        
        up = 1
        down = 1
        
        # Price vs VWAP
        if price is not None and vwap is not None:
            if price > vwap:
                up += 2
            if price < vwap:
                down += 2
        
        # VWAP slope
        if vwap_slope is not None:
            if vwap_slope > 0:
                up += 2
            if vwap_slope < 0:
                down += 2
        
        # RSI with slope
        if rsi is not None and rsi_slope is not None:
            if rsi > 55 and rsi_slope > 0:
                up += 2
            if rsi < 45 and rsi_slope < 0:
                down += 2
        
        # MACD histogram
        macd_hist = macd.get('hist')
        macd_hist_delta = macd.get('histDelta')
        macd_line = macd.get('macd')
        
        if macd_hist is not None and macd_hist_delta is not None:
            expanding_green = macd_hist > 0 and macd_hist_delta > 0
            expanding_red = macd_hist < 0 and macd_hist_delta < 0
            
            if expanding_green:
                up += 2
            if expanding_red:
                down += 2
            
            if macd_line is not None:
                if macd_line > 0:
                    up += 1
                if macd_line < 0:
                    down += 1
        
        # Heiken Ashi
        if heiken_color:
            if heiken_color == "green" and heiken_count >= 2:
                up += 1
            if heiken_color == "red" and heiken_count >= 2:
                down += 1
        
        raw_up = up / (up + down)
        
        return {
            'upScore': up,
            'downScore': down,
            'rawUp': raw_up,
            'rawDown': 1 - raw_up
        }
    
    def apply_time_awareness(self, raw_up: float, remaining_minutes: float, window_minutes: float = 15) -> Dict:
        """
        Apply time decay to probability
        As time runs out, confidence decays toward 50%
        """
        time_decay = min(remaining_minutes / window_minutes, 1.0)
        adjusted_up = max(0, min(1, 0.5 + (raw_up - 0.5) * time_decay))
        
        return {
            'timeDecay': time_decay,
            'adjustedUp': adjusted_up,
            'adjustedDown': 1 - adjusted_up
        }
    
    def compute_edge(self, model_up: float, model_down: float, market_yes: float, market_no: float) -> Dict:
        """
        Compute edge between model prediction and market prices
        """
        if market_yes is None or market_no is None:
            return {'marketUp': None, 'marketDown': None, 'edgeUp': None, 'edgeDown': None}
        
        total = market_yes + market_no
        if total == 0:
            return {'marketUp': None, 'marketDown': None, 'edgeUp': None, 'edgeDown': None}
        
        market_up = market_yes / total
        market_down = market_no / total
        
        edge_up = model_up - market_up
        edge_down = model_down - market_down
        
        return {
            'marketUp': max(0, min(1, market_up)),
            'marketDown': max(0, min(1, market_down)),
            'edgeUp': edge_up,
            'edgeDown': edge_down
        }
    
    def decide(self, remaining_minutes: float, edge_up: float, edge_down: float, 
               model_up: float, model_down: float) -> Dict:
        """
        Decide whether to trade based on edge and time remaining
        """
        if remaining_minutes > 10:
            phase = "EARLY"
            threshold = self.early_threshold
            min_prob = self.early_min_prob
        elif remaining_minutes > 5:
            phase = "MID"
            threshold = self.mid_threshold
            min_prob = self.mid_min_prob
        else:
            phase = "LATE"
            threshold = self.late_threshold
            min_prob = self.late_min_prob
        
        if edge_up is None or edge_down is None:
            return {'action': 'NO_TRADE', 'side': None, 'phase': phase, 'reason': 'missing_market_data'}
        
        # Determine best side
        if edge_up > edge_down:
            best_side = "UP"
            best_edge = edge_up
            best_model = model_up
        else:
            best_side = "DOWN"
            best_edge = edge_down
            best_model = model_down
        
        # Check threshold
        if best_edge < threshold:
            return {'action': 'NO_TRADE', 'side': None, 'phase': phase, 
                   'reason': f'edge_below_{threshold}', 'edge': best_edge}
        
        # Check minimum probability
        if best_model < min_prob:
            return {'action': 'NO_TRADE', 'side': None, 'phase': phase,
                   'reason': f'prob_below_{min_prob}', 'model': best_model}
        
        # Determine strength
        if best_edge >= 0.20:
            strength = "STRONG"
        elif best_edge >= 0.10:
            strength = "GOOD"
        else:
            strength = "OPTIONAL"
        
        return {
            'action': 'ENTER',
            'side': best_side,
            'phase': phase,
            'strength': strength,
            'edge': best_edge,
            'model': best_model
        }
    
    async def scan(self) -> List[Dict]:
        """Scan for crypto momentum opportunities"""
        opportunities = []
        
        logger.info("  CryptoMomentum: Scanning for opportunities...")
        
        # Fetch current BTC price
        current_price = await self.fetch_btc_price()
        if not current_price:
            logger.warning("  CryptoMomentum: Could not fetch BTC price")
            return opportunities
        
        # Add to price history
        self.add_price_point(current_price)
        
        # Need enough candles for indicators
        if len(self.price_history) < 20:
            logger.info(f"  CryptoMomentum: Building price history ({len(self.price_history)}/20 candles)")
            return opportunities
        
        # Calculate indicators
        vwap = self.compute_vwap(self.price_history)
        vwap_prev = self.compute_vwap(self.price_history[:-5])  # VWAP 5 candles ago
        vwap_slope = (vwap - vwap_prev) / vwap_prev if vwap and vwap_prev else None
        
        rsi, rsi_slope = self.compute_rsi(self.price_history)
        macd = self.compute_macd(self.price_history)
        
        ha_candles = self.compute_heiken_ashi(self.price_history)
        heiken_color, heiken_count = self.count_consecutive_heiken(ha_candles)
        
        # Log indicators
        logger.info(f"  CryptoMomentum: VWAP=${vwap:,.2f}, RSI={rsi:.1f}, MACD_hist={macd.get('hist', 0):.2f}, Heiken={heiken_color}({heiken_count})")
        
        # Score direction
        score_inputs = {
            'price': current_price,
            'vwap': vwap,
            'vwap_slope': vwap_slope,
            'rsi': rsi,
            'rsi_slope': rsi_slope,
            'macd': macd,
            'heiken_color': heiken_color,
            'heiken_count': heiken_count
        }
        
        direction_score = self.score_direction(score_inputs)
        raw_up = direction_score['rawUp']
        
        # Get active markets
        try:
            response = self.client._request("GET", 
                f"/markets?series_ticker={self.series_ticker}&status=open&limit=5")
            markets = response.json().get('markets', [])
        except Exception as e:
            logger.error(f"  CryptoMomentum: Error fetching markets: {e}")
            return opportunities
        
        if not markets:
            logger.info("  CryptoMomentum: No active markets found")
            return opportunities
        
        logger.info(f"  CryptoMomentum: Found {len(markets)} active markets")
        
        # Analyze each market
        for market in markets:
            ticker = market.get('ticker', '')
            close_time_str = market.get('close_time', '')
            
            # Calculate remaining time
            try:
                close_time = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
                remaining = (close_time - datetime.now(close_time.tzinfo)).total_seconds() / 60
            except:
                remaining = 15  # Default to 15 minutes
            
            if remaining <= 0:
                continue
            
            # Apply time awareness
            time_adj = self.apply_time_awareness(raw_up, remaining)
            model_up = time_adj['adjustedUp']
            model_down = time_adj['adjustedDown']
            
            # Get market orderbook
            try:
                orderbook = self.client.get_orderbook(ticker)
                yes_bids = orderbook.get('yes', [])
                no_bids = orderbook.get('no', [])
                
                if not yes_bids or not no_bids:
                    logger.debug(f"  CryptoMomentum: {ticker} - No orderbook liquidity")
                    continue
                
                market_yes = yes_bids[0].get('price', 50) / 100
                market_no = no_bids[0].get('price', 50) / 100
                
            except Exception as e:
                logger.debug(f"  CryptoMomentum: Error fetching orderbook for {ticker}: {e}")
                continue
            
            # Compute edge
            edge = self.compute_edge(model_up, model_down, market_yes, market_no)
            
            logger.info(f"  CryptoMomentum: {ticker} - Model: UP={model_up:.1%}, DOWN={model_down:.1%} | "
                       f"Market: YES={market_yes:.1%}, NO={market_no:.1%} | "
                       f"Edge: UP={edge.get('edgeUp', 0):.1%}, DOWN={edge.get('edgeDown', 0):.1%}")
            
            # Decide whether to trade
            decision = self.decide(
                remaining,
                edge.get('edgeUp'),
                edge.get('edgeDown'),
                model_up,
                model_down
            )
            
            if decision['action'] == 'ENTER':
                opp = {
                    'ticker': ticker,
                    'market': market.get('title', 'BTC 15m'),
                    'direction': 'UP' if decision['side'] == 'UP' else 'DOWN',
                    'side': 'yes' if decision['side'] == 'UP' else 'no',
                    'model_probability': model_up if decision['side'] == 'UP' else model_down,
                    'market_probability': edge.get('marketUp') if decision['side'] == 'UP' else edge.get('marketDown'),
                    'expected_value': decision['edge'],
                    'strength': decision['strength'],
                    'phase': decision['phase'],
                    'remaining_minutes': remaining,
                    'indicators': {
                        'vwap': vwap,
                        'rsi': rsi,
                        'macd_hist': macd.get('hist'),
                        'heiken': f"{heiken_color}({heiken_count})"
                    },
                    'strategy': 'crypto_momentum'
                }
                opportunities.append(opp)
                logger.info(f"  CryptoMomentum: ✅ FOUND OPPORTUNITY - {ticker}, "
                           f"{decision['side']}, edge={decision['edge']:.1%}, "
                           f"strength={decision['strength']}, phase={decision['phase']}")
            else:
                logger.info(f"  CryptoMomentum: No trade - {decision.get('reason', 'unknown')}")
        
        return opportunities
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute crypto momentum trades"""
        executed = 0
        
        for opp in opportunities:
            trade = {
                'ticker': opp['ticker'],
                'market': opp['market'],
                'direction': opp['direction'],
                'side': opp['side'],
                'model_probability': opp['model_probability'],
                'market_probability': opp['market_probability'],
                'expected_value': opp['expected_value'],
                'strength': opp['strength'],
                'phase': opp['phase'],
                'size': min(self.max_position, 5),
                'timestamp': datetime.now().isoformat(),
                'status': 'open',
                'simulated': True
            }
            
            self.record_trade(trade)
            executed += 1
            
            logger.info(f"    ✓ Executed: {opp['ticker']} - {opp['direction']} "
                       f"(edge: {opp['expected_value']:.1%}, strength: {opp['strength']})")
        
        return executed
    
    def get_performance(self) -> Dict:
        """Get performance metrics"""
        if not self.trades:
            return {'total_pnl': 0, 'win_rate': 0, 'trades': 0}
        
        total_pnl = sum(t.get('expected_value', 0) * t.get('size', 0) for t in self.trades)
        win_rate = sum(1 for t in self.trades if t.get('expected_value', 0) > 0) / len(self.trades)
        
        return {
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'trades': len(self.trades)
        }
    
    async def close(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()
