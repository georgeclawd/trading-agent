"""
Crypto Momentum Strategy - EXACT port of PolymarketBTC15mAssistant
https://github.com/FrondEnt/PolymarketBTC15mAssistant

Now supports BTC, ETH, and SOL 15M markets for maximum edge.
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

# Import position monitor
import sys
sys.path.insert(0, '/root/clawd/trading-agent/src')
from position_monitor import PositionMonitor


def clamp(value, min_val, max_val):
    """Clamp value between min and max"""
    return max(min_val, min(max_val, value))


class CryptoMomentumStrategy(BaseStrategy):
    """
    EXACT port of PolymarketBTC15mAssistant algorithm
    
    Uses 1-minute candles, computes VWAP, RSI, MACD, Heiken Ashi
    Scores direction, applies time awareness, computes edge, decides trade
    
    Now supports BTC, ETH, and SOL markets simultaneously.
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "CryptoMomentum"
        
        # Initialize position monitor for hedge tracking
        if position_manager:
            self.position_monitor = PositionMonitor(position_manager, kalshi_client=client)
        else:
            self.position_monitor = None
        
        # Market series for all three assets
        self.assets = {
            'BTC': {
                'series': 'KXBTC15M',
                'candles': [],
                'price_history': [],
                'coingecko_id': 'bitcoin',
                'last_price': None
            },
            'ETH': {
                'series': 'KXETH15M', 
                'candles': [],
                'price_history': [],
                'coingecko_id': 'ethereum',
                'last_price': None
            },
            'SOL': {
                'series': 'KXSOL15M',
                'candles': [],
                'price_history': [],
                'coingecko_id': 'solana',
                'last_price': None
            }
        }
        
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
        
        # Persistence
        self.data_file = '/root/clawd/trading-agent/data/crypto_candles.json'
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        self._load_candles()  # Load saved data on init
        
        # API
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _load_candles(self):
        """Load saved candle data from disk"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                for asset in self.assets:
                    if asset in data:
                        self.assets[asset]['candles'] = data[asset].get('candles', [])
                        self.assets[asset]['price_history'] = data[asset].get('price_history', [])
                logger.info(f"CryptoMomentum: Loaded candle data for {', '.join(self.assets.keys())}")
            except Exception as e:
                logger.warning(f"CryptoMomentum: Failed to load candles: {e}")
    
    def _save_candles(self):
        """Save candle data to disk"""
        try:
            data = {}
            for asset, info in self.assets.items():
                data[asset] = {
                    'candles': info['candles'],
                    'price_history': info['price_history']
                }
            with open(self.data_file, 'w') as f:
                json.dump(data, f, default=str)
        except Exception as e:
            logger.warning(f"CryptoMomentum: Failed to save candles: {e}")
    
    async def fetch_1m_candles(self):
        """Fetch 1-minute candles for all assets"""
        try:
            session = await self._get_session()
            
            # CoinGecko API for all assets
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd"
            
            async with asyncio.timeout(10):
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        
                        now = datetime.now()
                        for asset, info in self.assets.items():
                            coingecko_id = info['coingecko_id']
                            if coingecko_id in data:
                                price = data[coingecko_id]['usd']
                                info['last_price'] = price
                                
                                # Update candles for this asset
                                self._update_asset_candles(asset, price, now)
                        
                        # Save periodically
                        self._save_candles()
                        
                    elif resp.status == 429:
                        logger.warning("CryptoMomentum: CoinGecko RATE LIMITED (429)")
                    else:
                        logger.debug(f"CryptoMomentum: CoinGecko HTTP {resp.status}")
                        
        except asyncio.TimeoutError:
            logger.warning("CryptoMomentum: CoinGecko TIMEOUT")
        except Exception as e:
            logger.warning(f"CryptoMomentum: Failed to fetch prices: {type(e).__name__}: {e}")
    
    def _update_asset_candles(self, asset: str, price: float, now: datetime):
        """Update 1-minute candles for a specific asset"""
        info = self.assets[asset]
        candles = info['candles']
        
        # Get current minute
        current_minute = now.replace(second=0, microsecond=0)
        
        if not candles:
            # First candle
            candles.append({
                'openTime': current_minute.timestamp() * 1000,
                'open': price,
                'high': price,
                'low': price,
                'close': price,
                'volume': 1.0,
                'closeTime': current_minute.timestamp() * 1000
            })
        else:
            last_candle = candles[-1]
            last_minute = datetime.fromtimestamp(last_candle['closeTime'] / 1000).replace(second=0, microsecond=0)
            
            if current_minute > last_minute:
                # New minute - start new candle
                candles.append({
                    'openTime': current_minute.timestamp() * 1000,
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 1.0,
                    'closeTime': current_minute.timestamp() * 1000
                })
                
                # Keep last 240 candles (4 hours)
                if len(candles) > 240:
                    candles = candles[-240:]
                    info['candles'] = candles
            else:
                # Update current candle
                last_candle['high'] = max(last_candle['high'], price)
                last_candle['low'] = min(last_candle['low'], price)
                last_candle['close'] = price
                last_candle['volume'] += 1.0
        
        # Update price history
        info['price_history'].append(price)
        if len(info['price_history']) > 240:
            info['price_history'] = info['price_history'][-240:]
    
    # ==================== EXACT PORTS FROM JS ====================
    
    def compute_vwap(self, candles: List[Dict]) -> float:
        """EXACT port from vwap.js"""
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
        """EXACT port from vwap.js"""
        if len(candles) < minutes + 1:
            return 0.0
        
        start_candles = candles[-(minutes+1):-minutes]
        end_candles = candles[-minutes:]
        
        vwap_start = self.compute_vwap(start_candles)
        vwap_end = self.compute_vwap(end_candles)
        
        return vwap_end - vwap_start
    
    def compute_rsi(self, prices: List[float], period: int = 14) -> float:
        """EXACT port from rsi.js"""
        if len(prices) < period + 1:
            return 50.0
        
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
        
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def compute_rsi_ma(self, prices: List[float], period: int = 14) -> float:
        """Simple moving average of RSI"""
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
        """EXACT port from macd.js"""
        def ema(values, period):
            if len(values) < period:
                return None
            k = 2 / (period + 1)
            ema_val = values[0]
            for price in values[1:]:
                ema_val = price * k + ema_val * (1 - k)
            return ema_val
        
        if len(prices) < slow + signal:
            return {'macd': 0, 'signal': 0, 'histogram': 0, 'hist_delta': 0}
        
        fast_ema = ema(prices, fast)
        slow_ema = ema(prices, slow)
        
        if fast_ema is None or slow_ema is None:
            return {'macd': 0, 'signal': 0, 'histogram': 0, 'hist_delta': 0}
        
        macd_line = fast_ema - slow_ema
        
        # Build MACD series for signal calculation
        macd_series = []
        for i in range(slow, len(prices)):
            f = ema(prices[:i+1], fast)
            s = ema(prices[:i+1], slow)
            if f is not None and s is not None:
                macd_series.append(f - s)
        
        signal_line = ema(macd_series, signal) if len(macd_series) >= signal else 0
        
        if signal_line is None:
            signal_line = 0
        
        histogram = macd_line - signal_line
        
        # Compute hist_delta (change in histogram)
        hist_delta = 0
        if len(macd_series) >= 2:
            prev_macd = macd_series[-2]
            prev_signal = ema(macd_series[:-1], signal)
            if prev_signal is not None:
                prev_hist = prev_macd - prev_signal
                hist_delta = histogram - prev_hist
        
        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram,
            'hist_delta': hist_delta
        }
    
    def compute_heiken_ashi(self, candles: List[Dict]) -> List[Dict]:
        """EXACT port from heikenAshi.js"""
        if not candles:
            return []
        
        ha_candles = []
        
        for i, c in enumerate(candles):
            if i == 0:
                ha_close = (c['open'] + c['high'] + c['low'] + c['close']) / 4
                ha_open = (c['open'] + c['close']) / 2
            else:
                ha_close = (c['open'] + c['high'] + c['low'] + c['close']) / 4
                ha_open = (ha_candles[-1]['open'] + ha_candles[-1]['close']) / 2
            
            ha_high = max(c['high'], ha_open, ha_close)
            ha_low = min(c['low'], ha_open, ha_close)
            
            ha_candles.append({
                'open': ha_open,
                'high': ha_high,
                'low': ha_low,
                'close': ha_close,
                'color': 'green' if ha_close > ha_open else 'red'
            })
        
        return ha_candles
    
    def score_direction(self, ha_candles: List[Dict], candles: List[Dict], 
                        vwap: float, current_price: float) -> float:
        """EXACT port from probability.js - scoreDirection"""
        if not ha_candles or not candles:
            return 0.0
        
        up = 1.0
        down = 1.0
        
        # VWAP position
        if current_price > vwap:
            up += 2.0
        elif current_price < vwap:
            down += 2.0
        
        # VWAP slope
        vwap_slope = self.compute_vwap_slope(candles, self.vwap_slope_lookback_minutes)
        if vwap_slope > 0:
            up += 2.0
        elif vwap_slope < 0:
            down += 2.0
        
        # Heiken Ashi
        if ha_candles:
            last_ha = ha_candles[-1]
            color = last_ha['color']
            
            # Count consecutive candles
            consecutive = 0
            for c in reversed(ha_candles):
                if c['color'] == color:
                    consecutive += 1
                else:
                    break
            
            if color == 'green' and consecutive >= 2:
                up += 1.0
            elif color == 'red' and consecutive >= 2:
                down += 1.0
        
        # Convert to score (-1 to 1)
        total = up + down
        raw_score = (up - down) / total if total > 0 else 0
        
        return clamp(raw_score, -1.0, 1.0)
    
    def apply_time_awareness(self, raw_score: float, minutes: int) -> float:
        """EXACT port from probability.js - applyTimeAwareness"""
        # Linear decay: full strength at start, 0 at 15 minutes
        time_decay = clamp((15 - minutes) / 15, 0, 1)
        
        # Apply decay to deviation from neutral
        adjusted_score = raw_score * time_decay
        
        return adjusted_score
    
    def compute_edge(self, model_prob: float, market_price: float, minutes: int) -> float:
        """EXACT port from edge.js - computeEdge"""
        # Edge = (b * p - q) / b where b = (1-m)/m, q = 1-p
        if market_price <= 0 or market_price >= 1:
            return 0.0
        
        b = (1 - market_price) / market_price
        q = 1 - model_prob
        
        edge = (b * model_prob - q) / b
        
        return edge
    
    def get_minutes_into_interval(self) -> int:
        """Get minutes into current 15-minute interval"""
        now = datetime.now()
        return now.minute % 15
    
    async def _monitor_positions(self):
        """Monitor existing positions for hedge/exit opportunities and settlement"""
        try:
            async def get_market_data(ticker):
                """Fetch current market data for a ticker - includes settlement detection"""
                try:
                    # First check if market is settled via Kalshi API
                    import requests
                    import time
                    import base64
                    from cryptography.hazmat.primitives import hashes, padding as crypto_padding
                    
                    api_key_id = self.client.api_key_id
                    api_key = self.client.api_key
                    
                    # Create signature for market lookup
                    def create_sig(ts, method, path):
                        msg = f"{ts}{method}{path}"
                        sig = self.client._private_key.sign(
                            msg.encode(),
                            crypto_padding.PSS(mgf=crypto_padding.MGF1(hashes.SHA256()), salt_length=crypto_padding.PSS.DIGEST_LENGTH),
                            hashes.SHA256()
                        )
                        return base64.b64encode(sig).decode()
                    
                    ts = str(int(time.time() * 1000))
                    sig = create_sig(ts, "GET", f"/trade-api/v2/markets/{ticker}")
                    
                    headers = {
                        "KALSHI-ACCESS-KEY": api_key_id,
                        "KALSHI-ACCESS-SIGNATURE": sig,
                        "KALSHI-ACCESS-TIMESTAMP": ts
                    }
                    
                    resp = requests.get(
                        f"https://api.elections.kalshi.com/trade-api/v2/markets/{ticker}",
                        headers=headers,
                        timeout=10
                    )
                    
                    if resp.status_code == 200:
                        market = resp.json().get('market', {})
                        status = market.get('status', 'open')
                        
                        if status == 'settled':
                            # Market settled - return settlement price
                            yes_result = market.get('yes_result', 0)  # 0 or 100
                            return {
                                'is_settled': True,
                                'settlement_price': yes_result,  # 0 or 100 cents
                                'price': yes_result,
                                'edge': 0
                            }
                    
                    # Market still open - get orderbook
                    orderbook = self.client.get_orderbook(ticker)
                    if orderbook and 'orderbook' in orderbook:
                        yes_bids = orderbook['orderbook'].get('yes', [])
                        if yes_bids and len(yes_bids) > 0:
                            # Get best bid price
                            price = yes_bids[0][0] / 100  # Convert cents to decimal
                            return {'price': price, 'edge': 0, 'is_settled': False}
                            
                except Exception as e:
                    logger.debug(f"get_market_data error for {ticker}: {e}")
                    pass
                return None
            
            # Check for early exit opportunities (take profit / stop loss)
            if self.position_monitor:
                exits = await self.position_monitor.check_and_exit_positions(
                    self, 
                    auto_exit=True,  # Automatically execute exits
                    simulated=self.dry_run
                )
                if exits > 0:
                    logger.info(f"🔄 CryptoMomentum: Executed {exits} early exits")
            
            # Regular position monitoring
            alerts = await self.position_monitor.check_all_positions(self, get_market_data)
            
            if alerts:
                # Log settled positions
                settled = [a for a in alerts if a.is_settled]
                for s in settled:
                    if s.pnl_dollars >= 0:
                        logger.info(f"💰 SETTLED WIN: {s.ticker} {s.side} | P&L: ${s.pnl_dollars:+.2f}")
                    else:
                        logger.warning(f"💸 SETTLED LOSS: {s.ticker} {s.side} | P&L: ${s.pnl_dollars:+.2f}")
                
                # Generate hedge recommendations for non-settled
                hedges = self.position_monitor.generate_hedge_recommendations(alerts)
                for hedge in hedges:
                    logger.warning(f"🔄 HEDGE RECOMMENDED: {hedge['ticker']} - "
                                   f"Buy {hedge['hedge_side']} x{hedge['hedge_size']} | {hedge['reason']}")
                    
        except Exception as e:
            logger.debug(f"CryptoMomentum: Position monitoring error: {e}")
    
    async def continuous_trade_loop(self):
        """Continuous trading loop - check for entry/exit every minute"""
        logger.info("🔄 CryptoMomentum: Starting continuous trade loop (1-min checks) - BTC, ETH, SOL")
        
        while True:
            try:
                now = datetime.now()
                minutes_into = now.minute % 15
                
                # Log which phase of 15-min window we're in
                if minutes_into < 5:
                    phase = "early"
                elif minutes_into < 10:
                    phase = "mid"
                else:
                    phase = "late"
                
                # Only trade if we have enough candles for at least one asset
                ready_assets = [a for a, info in self.assets.items() if len(info['candles']) >= 30]
                
                if ready_assets:
                    # Check for entry opportunities
                    opportunities = await self.analyze()
                    
                    if opportunities:
                        logger.info(f"🎯 CryptoMomentum: Found {len(opportunities)} opportunities ({phase} phase)")
                        executed = await self.execute(opportunities)
                        if executed:
                            logger.info(f"✅ CryptoMomentum: Executed {executed} trades")
                    else:
                        logger.debug(f"📊 CryptoMomentum: No opportunities ({phase} phase, {minutes_into}m into window)")
                else:
                    logger.debug(f"📊 CryptoMomentum: Building data (assets ready: {ready_assets})")
                
                # Wait 60 seconds before next check
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                logger.info("🛑 CryptoMomentum: Continuous trade loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ CryptoMomentum: Trade loop error: {e}")
                await asyncio.sleep(60)
    
    # ==================== STRATEGY INTERFACE ====================
    
    async def analyze(self) -> List[Dict]:
        """Main analysis - compute indicators and find opportunities for all assets"""
        opportunities = []
        
        # Monitor existing positions for hedge/exit opportunities
        if self.position_monitor:
            await self._monitor_positions()
        
        # Fetch/build candles for all assets
        await self.fetch_1m_candles()
        
        # Get current time info
        minutes = self.get_minutes_into_interval()
        
        # Analyze each asset
        for asset, info in self.assets.items():
            candles = info['candles']
            price_history = info['price_history']
            
            if len(candles) < 30:
                logger.debug(f"CryptoMomentum: {asset} - Building data ({len(candles)}/30 candles)")
                continue
            
            # Get current price
            current_price = candles[-1]['close']
            
            # Compute indicators
            vwap = self.compute_vwap(candles)
            vwap_slope = self.compute_vwap_slope(candles, self.vwap_slope_lookback_minutes)
            rsi = self.compute_rsi(price_history, self.rsi_period)
            rsi_ma = self.compute_rsi_ma(price_history, self.rsi_ma_period)
            macd = self.compute_macd(price_history, self.macd_fast, self.macd_slow, self.macd_signal)
            ha_candles = self.compute_heiken_ashi(candles)
            
            logger.info(f"CryptoMomentum: {asset} - VWAP: ${vwap:.2f}, RSI: {rsi:.1f}, MACD: {macd['histogram']:.4f}")
            
            # Get Kalshi markets for this asset
            try:
                response = self.client._request("GET", f"/markets?series_ticker={info['series']}&status=open")
                markets = response.json().get('markets', [])
            except Exception as e:
                logger.error(f"CryptoMomentum: Failed to fetch {asset} markets: {e}")
                continue
            
            if not markets:
                logger.debug(f"CryptoMomentum: No {asset} markets available")
                continue
            
            # Score direction
            direction_score = self.score_direction(ha_candles, candles, vwap, current_price)
            
            # Time awareness
            adjusted_score = self.apply_time_awareness(direction_score, minutes)
            
            # Convert score to probability
            raw_prob = (adjusted_score + 1) / 2
            
            logger.info(f"CryptoMomentum: {asset} - Direction={direction_score:+.2f}, Prob={raw_prob:.2%}, Min={minutes}")
            
            # Find opportunities for this asset
            for market in markets:
                ticker = market['ticker']
                title = market.get('title', '')
                
                try:
                    orderbook_response = self.client.get_orderbook(ticker)
                    orderbook = orderbook_response.get('orderbook', {})
                    yes_bids = orderbook.get('yes', [])
                    no_bids = orderbook.get('no', [])
                    
                    if not yes_bids or not no_bids:
                        continue
                    
                    # Get best YES and NO prices
                    yes_price = yes_bids[0][0] / 100
                    no_price = no_bids[0][0] / 100
                    
                    # Determine which side to bet based on probability
                    if raw_prob > 0.5:
                        side = 'YES'
                        market_price = yes_price
                        fair_prob = raw_prob
                    else:
                        side = 'NO'
                        market_price = no_price
                        fair_prob = 1 - raw_prob
                    
                    # Compute edge
                    edge = self.compute_edge(fair_prob, market_price, minutes)
                    
                    if edge > 0.1:  # 10% edge threshold
                        opportunities.append({
                            'ticker': ticker,
                            'market': title,
                            'asset': asset,
                            'side': side,
                            'market_price': market_price,
                            'fair_probability': fair_prob,
                            'edge': edge,
                            'direction_score': direction_score,
                            'rsi': rsi,
                            'macd_hist': macd['histogram']
                        })
                        
                        logger.info(f"CryptoMomentum: OPPORTUNITY {asset} {ticker} {side} - Edge={edge:.2%}, Price={market_price:.2%}")
                        
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
        
        # Count by asset
        asset_counts = {}
        for t in self.trades:
            asset = t.get('asset', 'UNKNOWN')
            asset_counts[asset] = asset_counts.get(asset, 0) + 1
        
        return {
            'name': self.name,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'win_rate': winning_trades / total_trades if total_trades > 0 else 0,
            'total_pnl': total_pnl,
            'trades_by_asset': asset_counts,
            'candles_collected': {a: len(i['candles']) for a, i in self.assets.items()}
        }
    
    def get_current_exposure(self) -> float:
        """Calculate total exposure from open positions"""
        if not self.position_manager:
            return 0.0
        
        open_positions = self.position_manager.get_open_positions(
            strategy=self.name,
            simulated=self.dry_run
        )
        
        total_exposure = 0.0
        for pos in open_positions:
            exposure = pos.contracts * pos.entry_price / 100
            total_exposure += exposure
        
        return total_exposure
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute trades based on opportunities"""
        executed_count = 0
        
        # Risk management: Check total exposure
        current_exposure = self.get_current_exposure()
        max_exposure = self.config.get('max_bankroll_exposure', 0.3) * self.config.get('initial_bankroll', 100)
        
        if current_exposure >= max_exposure:
            logger.warning(f"🛑 CryptoMomentum: Max exposure reached (${current_exposure:.2f}/${max_exposure:.2f}). Skipping new trades.")
            return 0
        
        remaining_exposure_budget = max_exposure - current_exposure
        logger.info(f"💰 CryptoMomentum: Current exposure ${current_exposure:.2f}, budget ${remaining_exposure_budget:.2f}")
        
        for opp in opportunities:
            ticker = opp['ticker']
            edge = opp['edge']
            asset = opp.get('asset', 'UNKNOWN')
            
            # Position sizing based on edge (Kelly-ish)
            if edge > 0.3:
                contracts = self.max_position
            elif edge > 0.2:
                contracts = max(1, self.max_position // 2)
            else:
                contracts = 1
            
            # Limit order at fair price
            limit_price = int(opp['fair_probability'] * 100)
            limit_price = max(1, min(99, limit_price))
            
            # Calculate trade cost
            trade_cost = contracts * limit_price / 100
            
            # Check exposure budget
            if trade_cost > remaining_exposure_budget:
                logger.warning(f"🛑 CryptoMomentum: Trade ${trade_cost:.2f} exceeds remaining budget ${remaining_exposure_budget:.2f}. Skipping.")
                continue
            
            # Check for duplicate BEFORE executing
            if self.position_manager and self.position_manager.has_open_position(ticker, simulated=self.dry_run):
                logger.debug(f"CryptoMomentum: Skipping {ticker} - already have open position")
                continue
            
            if self.dry_run:
                # SIMULATED
                success = self.record_position(
                    ticker=ticker,
                    side=opp['side'],
                    contracts=contracts,
                    entry_price=limit_price,
                    market_title=opp['market']
                )
                if success:
                    logger.info(f"CryptoMomentum: [SIMULATED] {asset} - Would execute {ticker} {opp['side']} x{contracts}")
                    executed_count += 1
            else:
                # REAL
                logger.info(f"CryptoMomentum: [REAL] EXECUTING {asset} - {ticker} {opp['side']} x{contracts} @ {limit_price}c")
                
                try:
                    result = self.client.place_order(
                        market_id=ticker,
                        side=opp['side'].lower(),
                        price=limit_price,
                        count=contracts
                    )
                    
                    if result.get('order_id'):
                        logger.info(f"CryptoMomentum: [REAL] Executed {asset} - {ticker} Order: {result['order_id']}")
                        executed_count += 1
                        
                        # Deduct from exposure budget
                        remaining_exposure_budget -= trade_cost
                        
                        self.record_position(
                            ticker=ticker,
                            side=opp['side'],
                            contracts=contracts,
                            entry_price=limit_price,
                            market_title=opp['market']
                        )
                        
                        self.record_trade({
                            'ticker': ticker,
                            'asset': asset,
                            'side': opp['side'],
                            'contracts': contracts,
                            'price': limit_price,
                            'edge': edge,
                            'pnl': 0,
                            'order_id': result['order_id']
                        })
                    else:
                        logger.error(f"CryptoMomentum: [REAL] Order failed for {ticker}: {result}")
                        
                except Exception as e:
                    logger.error(f"CryptoMomentum: [REAL] Failed to execute {ticker}: {e}")
        
        return executed_count
