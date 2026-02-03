"""
Crypto Momentum Strategy - FIXED VERSION
Exact port of PolymarketBTC15mAssistant algorithm with all corrections
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
from position_monitor import PositionMonitor
from consensus_tracker import ConsensusTracker

def clamp(value, min_val, max_val):
    """Clamp value between min and max"""
    return max(min_val, min(max_val, value))

class CryptoMomentumStrategy(BaseStrategy):
    """
    EXACT port of PolymarketBTC15mAssistant algorithm - FIXED
    """
    
    def __init__(self, config: Dict, client, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "CryptoMomentum"
        
        if position_manager:
            self.position_monitor = PositionMonitor(position_manager, kalshi_client=client)
        else:
            self.position_monitor = None
        
        # Initialize consensus tracker
        self.consensus_tracker = ConsensusTracker()
        logger.info("✅ Consensus tracking enabled - comparing with competitor bots")
        
        # Assets
        self.assets = {
            'BTC': {
                'series': 'KXBTC15M',
                'candles': [],
                'price_history': [],
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
        
        # Data storage
        self.data_file = '/root/clawd/trading-agent/data/crypto_candles.json'
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        self._load_candles()
        
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    def _load_candles(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                for asset in self.assets:
                    if asset in data:
                        self.assets[asset]['candles'] = data[asset].get('candles', [])
                        self.assets[asset]['price_history'] = data[asset].get('price_history', [])
            except Exception as e:
                logger.warning(f"Failed to load candles: {e}")
    
    def _save_candles(self):
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
            logger.warning(f"Failed to save candles: {e}")
    
    async def fetch_1m_candles(self):
        """Fetch 1-minute candles for BTC"""
        try:
            session = await self._get_session()
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
            
            async with asyncio.timeout(10):
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        now = datetime.now()
                        price = data['bitcoin']['usd']
                        self.assets['BTC']['last_price'] = price
                        self._update_asset_candles('BTC', price, now)
                        self._save_candles()
        except Exception as e:
            logger.warning(f"Failed to fetch prices: {e}")
    
    def _update_asset_candles(self, asset: str, price: float, now: datetime):
        info = self.assets[asset]
        candles = info['candles']
        current_minute = now.replace(second=0, microsecond=0)
        
        if not candles:
            candles.append({
                'openTime': current_minute.timestamp() * 1000,
                'open': price, 'high': price, 'low': price, 'close': price,
                'volume': 1.0, 'closeTime': current_minute.timestamp() * 1000
            })
        else:
            last_candle = candles[-1]
            last_minute = datetime.fromtimestamp(last_candle['closeTime'] / 1000).replace(second=0, microsecond=0)
            
            if current_minute > last_minute:
                candles.append({
                    'openTime': current_minute.timestamp() * 1000,
                    'open': price, 'high': price, 'low': price, 'close': price,
                    'volume': 1.0, 'closeTime': current_minute.timestamp() * 1000
                })
                if len(candles) > 240:
                    candles = candles[-240:]
                    info['candles'] = candles
            else:
                last_candle['high'] = max(last_candle['high'], price)
                last_candle['low'] = min(last_candle['low'], price)
                last_candle['close'] = price
                last_candle['volume'] += 1.0
        
        info['price_history'].append(price)
        if len(info['price_history']) > 240:
            info['price_history'] = info['price_history'][-240:]
    
    def compute_vwap(self, candles: List[Dict]) -> float:
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
        if len(candles) < minutes + 1:
            return 0.0
        start_candles = candles[-(minutes+1):-minutes]
        end_candles = candles[-minutes:]
        vwap_start = self.compute_vwap(start_candles)
        vwap_end = self.compute_vwap(end_candles)
        return vwap_end - vwap_start
    
    def compute_rsi(self, prices: List[float], period: int = 14) -> float:
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
    
    def compute_macd(self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
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
        hist_delta = 0
        if len(macd_series) >= 2:
            prev_macd = macd_series[-2]
            prev_signal = ema(macd_series[:-1], signal)
            if prev_signal is not None:
                prev_hist = prev_macd - prev_signal
                hist_delta = histogram - prev_hist
        
        return {'macd': macd_line, 'signal': signal_line, 'histogram': histogram, 'hist_delta': hist_delta}
    
    def compute_heiken_ashi(self, candles: List[Dict]) -> List[Dict]:
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
                'open': ha_open, 'high': ha_high, 'low': ha_low, 'close': ha_close,
                'color': 'green' if ha_close > ha_open else 'red'
            })
        return ha_candles
    
    def score_direction(self, ha_candles: List[Dict], candles: List[Dict], vwap: float, current_price: float) -> float:
        """EXACT port from probability.js"""
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
        
        # RSI
        rsi_now = self.compute_rsi(self.assets['BTC']['price_history'], self.rsi_period)
        rsi_slope = 0
        if len(self.assets['BTC']['price_history']) >= 17:
            rsi_series = []
            for i in range(self.rsi_period, len(self.assets['BTC']['price_history'])):
                sub = self.assets['BTC']['price_history'][:i+1]
                r = self.compute_rsi(sub, self.rsi_period)
                if r is not None:
                    rsi_series.append(r)
            if len(rsi_series) >= 3:
                rsi_slope = rsi_series[-1] - rsi_series[-3]
        
        if rsi_now > 55 and rsi_slope > 0:
            up += 2.0
        if rsi_now < 45 and rsi_slope < 0:
            down += 2.0
        
        # MACD
        macd = self.compute_macd(self.assets['BTC']['price_history'], self.macd_fast, self.macd_slow, self.macd_signal)
        if macd.get('histogram') is not None and macd['hist_delta'] is not None:
            expanding_green = macd.get('histogram') > 0 and macd['hist_delta'] > 0
            expanding_red = macd.get('histogram') < 0 and macd['hist_delta'] < 0
            if expanding_green:
                up += 2.0
            if expanding_red:
                down += 2.0
            if macd.get('macd') > 0:
                up += 1.0
            if macd.get('macd') < 0:
                down += 1.0
        
        total = up + down
        raw_score = (up - down) / total if total > 0 else 0
        return clamp(raw_score, -1.0, 1.0)
    
    def apply_time_awareness(self, raw_score: float, minutes: int) -> Dict:
        """FIXED: Returns dict like original"""
        time_decay = clamp(minutes / self.candle_window_minutes, 0, 1)
        adjusted_up = clamp(0.5 + (raw_score - 0.5) * time_decay, 0, 1)
        return {
            'time_decay': time_decay,
            'adjusted_up': adjusted_up,
            'adjusted_down': 1 - adjusted_up
        }
    
    def get_minutes_into_interval(self) -> int:
        now = datetime.now()
        return now.minute % 15
    
    def get_remaining_minutes(self) -> int:
        """Get minutes remaining in current window"""
        now = datetime.now()
        minutes_into = now.minute % 15
        return 15 - minutes_into
    
    async def analyze(self):
        logger.info("🔍 CryptoMomentum: Starting analysis...")
        """FIXED: Proper edge calculation comparing BOTH sides"""
        """FIXED: Proper edge calculation comparing BOTH sides"""
        opportunities = []
        
        if self.position_monitor:
            await self._monitor_positions()
        
        await self.fetch_1m_candles()
        minutes = self.get_minutes_into_interval()
        remaining_minutes = self.get_remaining_minutes()
        
        for asset, info in self.assets.items():
            candles = info['candles']
            price_history = info['price_history']
            
            if len(candles) < 30:
                logger.info(f"⏳ {asset}: Building data ({len(candles)}/30 candles)")
                continue
            
            current_price = candles[-1]['close']
            vwap = self.compute_vwap(candles)
            ha_candles = self.compute_heiken_ashi(candles)
            
            # Score direction
            direction_score = self.score_direction(ha_candles, candles, vwap, current_price)
            
            # Time awareness - returns dict
            time_aware = self.apply_time_awareness(direction_score, remaining_minutes)
            model_up = time_aware['adjusted_up']
            model_down = time_aware['adjusted_down']
            
            # Log algorithm thinking
            logger.info("=" * 60)
            logger.info(f"🔍 {asset} ANALYSIS - {minutes}m into 15-min window")
            logger.info("=" * 60)
            logger.info(f"📊 PRICE DATA:")
            logger.info(f"   • Current price: ${current_price:,.2f}")
            logger.info(f"   • VWAP: ${vwap:,.2f}")
            logger.info(f"   • Price vs VWAP: {'ABOVE' if current_price > vwap else 'BELOW'}")
            logger.info(f"📊 MODEL CALCULATIONS:")
            logger.info(f"   • Raw direction score: {direction_score:+.2f} (-1=bearish, +1=bullish)")
            logger.info(f"   • After time adjustment: UP={model_up:.1%}, DOWN={model_down:.1%}")
            logger.info(f"   • Remaining time: {remaining_minutes} minutes")
            logger.info(f"   • Model prediction: {'BULLISH' if model_up > model_down else 'BEARISH' if model_down > model_up else 'NEUTRAL'}")
            
            # Get market data
            try:
                response = self.client._request("GET", f"/markets?series_ticker={info['series']}&status=open")
                markets = response.json().get('markets', [])
            except Exception as e:
                continue
            
            for market in markets:
                ticker = market['ticker']
                
                try:
                    orderbook = self.client.get_orderbook(ticker)
                    if not orderbook or 'orderbook' not in orderbook:
                        continue
                    
                    yes_bids = orderbook['orderbook'].get('yes', [])
                    no_bids = orderbook['orderbook'].get('no', [])
                    
                    if not yes_bids or not no_bids:
                        continue
                    
                    # Get prices
                    yes_price = yes_bids[0][0] / 100  # Bid price for YES
                    no_price = no_bids[0][0] / 100    # Bid price for NO
                    
                    # Calculate market probabilities (normalize)
                    total = yes_price + no_price
                    if total <= 0:
                        continue
                    
                    market_up = yes_price / total
                    market_down = no_price / total
                    
                    # FIXED: Calculate edge for BOTH sides
                    edge_up = model_up - market_up
                    edge_down = model_down - market_down
                    
                    # Determine phase and thresholds
                    phase = "EARLY" if remaining_minutes > 10 else "MID" if remaining_minutes > 5 else "LATE"
                    threshold = 0.05 if phase == "EARLY" else 0.10 if phase == "MID" else 0.20
                    min_prob = 0.55 if phase == "EARLY" else 0.60 if phase == "MID" else 0.65
                    
                    # Pick best side
                    if edge_up > edge_down:
                        best_side = 'YES'
                        best_edge = edge_up
                        best_model = model_up
                        entry_price = yes_price
                    else:
                        best_side = 'NO'
                        best_edge = edge_down
                        best_model = model_down
                        entry_price = no_price
                    
                    # FIXED: Check threshold AND min probability
                    if best_edge < threshold:
                        logger.debug(f"{ticker}: Edge {best_edge:.2%} below threshold {threshold}")
                        continue
                    
                    if best_model < min_prob:
                        logger.debug(f"{ticker}: Model prob {best_model:.2%} below min {min_prob}")
                        continue
                    
                    # Don't buy if price is too high (>60c)
                    if entry_price > 0.60:
                        logger.debug(f"{ticker}: Entry price {entry_price:.0%} too high")
                        continue
                    
                    opportunities.append({
                        'ticker': ticker,
                        'side': best_side,
                        'market_up': market_up,
                        'market_down': market_down,
                        'model_up': model_up,
                        'model_down': model_down,
                        'edge_up': edge_up,
                        'edge_down': edge_down,
                        'best_edge': best_edge,
                        'entry_price': entry_price,
                        'phase': phase,
                        'threshold': threshold,
                        'remaining_minutes': remaining_minutes
                    })
                    
                    logger.info(f"✅ OPPORTUNITY FOUND: {ticker}")
                    logger.info(f"   • Our recommendation: {best_side}")
                    logger.info(f"   • Edge: {best_edge:.2%} (threshold: {threshold:.0%})")
                    logger.info(f"   • Market price: {entry_price:.0%}")
                    logger.info(f"   • Phase: {phase} ({remaining_minutes} min left)")
                    
                except Exception as e:
                    continue
        
        return opportunities
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute trades with consensus validation - DETAILED LOGGING"""
        executed = 0
        
        # Get competitor consensus
        logger.info("=" * 60)
        logger.info("🤝 CHECKING COMPETITOR CONSENSUS")
        logger.info("=" * 60)
        
        consensus = None
        try:
            consensus = self.consensus_tracker.get_competitor_consensus()
            logger.info(f"📊 COMPETITOR VOTES:")
            logger.info(f"   • Bullish (YES): {consensus['bullish_count']} traders")
            logger.info(f"   • Bearish (NO):  {consensus['bearish_count']} traders")  
            logger.info(f"   • Neutral:       {consensus['neutral_count']} traders")
            logger.info(f"📊 COMPETITOR CONSENSUS: {consensus['consensus_side']} ({consensus['agreement_ratio']:.0%} agreement)")
            if consensus.get('details'):
                logger.info(f"📊 INDIVIDUAL VOTES:")
                for vote in consensus['details']:
                    logger.info(f"   • {vote['name']}: {vote['side']}")
        except Exception as e:
            logger.warning(f"⚠️  Could not get consensus: {e}")
        
        for opp in opportunities:
            ticker = opp['ticker']
            side = opp['side']
            entry_price_cents = int(opp['entry_price'] * 100)
            
            logger.info("-" * 60)
            logger.info(f"🎯 EVALUATING: {ticker}")
            logger.info("-" * 60)
            logger.info(f"📈 OUR ALGORITHM DECISION:")
            logger.info(f"   • Signal: {side}")
            logger.info(f"   • Edge: {opp['best_edge']:.2%}")
            logger.info(f"   • Model UP: {opp['model_up']:.1%} | Model DOWN: {opp['model_down']:.1%}")
            logger.info(f"   • Market UP: {opp['market_up']:.1%} | Market DOWN: {opp['market_down']:.1%}")
            logger.info(f"   • Phase: {opp['phase']} (threshold: {opp['threshold']:.0%})")
            logger.info(f"   • Entry price: {opp['entry_price']:.0%}")
            
            # Check duplicate
            if self.position_manager and self.position_manager.has_open_position(ticker, self.dry_run):
                logger.info(f"   ⏸️  SKIPPED: Already have position in {ticker}")
                continue
            
            # Compare with consensus
            our_signal = side
            competitor_signal = consensus['consensus_side'] if consensus else 'UNKNOWN'
            agreement = consensus['agreement_ratio'] if consensus else 0.0
            
            logger.info(f"📊 COMPARISON:")
            logger.info(f"   • Our signal:      {our_signal}")
            logger.info(f"   • Competitors:     {competitor_signal}")
            logger.info(f"   • Agreement:       {agreement:.0%}")
            
            # Position sizing
            edge = opp['best_edge']
            if edge >= 0.20:
                base_contracts = 5
            elif edge >= 0.10:
                base_contracts = 3
            else:
                base_contracts = 1
            
            # Apply consensus modifier
            final_signal = our_signal
            final_confidence = edge
            
            if consensus and competitor_signal != 'UNKNOWN':
                if competitor_signal == our_signal:
                    # Agreement - boost confidence
                    final_confidence = edge * 1.2
                    logger.info(f"   ✅ COMPETITORS AGREE - Boosting confidence to {final_confidence:.2%}")
                elif competitor_signal == 'NEUTRAL':
                    # Neutral - proceed normally
                    logger.info(f"   ⚪ COMPETITORS NEUTRAL - Using our signal")
                else:
                    # Disagreement - be cautious
                    if agreement >= 0.6:
                        # Strong disagreement - skip
                        logger.info(f"   ❌ SKIP: Strong competitor consensus ({agreement:.0%}) disagrees with our signal!")
                        logger.info(f"   📝 Decision: NO TRADE - Competitors say {competitor_signal}, we say {our_signal}")
                        continue
                    else:
                        # Weak disagreement - reduce size
                        base_contracts = max(1, base_contracts // 2)
                        final_confidence = edge * 0.7
                        logger.info(f"   ⚠️  DISAGREEMENT - Reducing position size to {base_contracts}, confidence {final_confidence:.2%}")
            
            contracts = base_contracts
            
            logger.info(f"   📋 FINAL DECISION:")
            logger.info(f"   • Signal:     {final_signal}")
            logger.info(f"   • Contracts:  {contracts}")
            logger.info(f"   • Confidence: {final_confidence:.2%}")
            logger.info(f"   • Reason:     {our_signal} (our algo) + {competitor_signal} (competitors)")
            
            if self.dry_run:
                self.record_position(ticker, side, contracts, entry_price_cents, ticker)
                logger.info(f"   📝 [SIMULATION] Would trade: {ticker} {side} x{contracts} @ {entry_price_cents}c")
                executed += 1
            else:
                result = self.client.place_order(ticker, side.lower(), entry_price_cents, contracts)
                if result.get('order_id'):
                    logger.info(f"   💰 [REAL TRADE] {ticker} {side} x{contracts} @ {entry_price_cents}c - Order: {result['order_id']}")
                    self.record_position(ticker, side, contracts, entry_price_cents, ticker)
                    executed += 1
                else:
                    logger.error(f"   ❌ [TRADE FAILED] {ticker} {side} - Error: {result}")
        
        return executed
    
    async def scan(self) -> List[Dict]:
        return await self.analyze()
    
    def get_performance(self) -> Dict:
        return {'name': self.name, 'trades': len(self.trades)}

    async def continuous_trade_loop(self):
        """Continuous trading loop - check for entry/exit every minute"""
        logger.info("🔄 CryptoMomentum: Starting continuous trade loop")
        logger.info("=" * 60)
        
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
                
                logger.info("")
                logger.info("=" * 60)
                logger.info(f"⏰ TRADING CYCLE - {now.strftime('%H:%M:%S')} EST | Window: {phase.upper()} ({minutes_into}/15 min)")
                logger.info("=" * 60)
                
                # Only trade if we have enough candles
                if len(self.assets['BTC']['candles']) >= 30:
                    # Check for entry opportunities
                    opportunities = await self.analyze()
                    
                    if opportunities:
                        logger.info(f"🎯 Found {len(opportunities)} trading opportunity/ies")
                        executed = await self.execute(opportunities)
                        if executed:
                            logger.info(f"✅ EXECUTED {executed} trade(s) this cycle")
                        else:
                            logger.info(f"⏸️  No trades executed (filtered by consensus or duplicates)")
                    else:
                        logger.info(f"📊 No opportunities found this cycle")
                else:
                    logger.info(f"⏳ Building data ({len(self.assets['BTC']['candles'])}/30 candles)...")
                
                logger.info("=" * 60)
                logger.info(f"⏱️  Next check in 60 seconds...")
                
                # Wait 60 seconds before next check
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                logger.info("🛑 CryptoMomentum: Continuous trade loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ CryptoMomentum: Trade loop error: {e}")
                await asyncio.sleep(60)

    async def _monitor_positions(self):
        """Monitor existing positions - simplified for demo"""
        if not self.position_monitor:
            return
        # Basic monitoring - can be expanded later
        pass
