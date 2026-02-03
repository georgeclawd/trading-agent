"""
Crypto Momentum Strategy - FOCUSED ON BTC/ETH/SOL 15M

Tracks and copies successful competitor trades on 15-min crypto markets
"""

from typing import Dict, List, Optional, Tuple
from strategy_framework import BaseStrategy
from datetime import datetime, timedelta, timezone
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
    Focused on BTC/ETH/SOL 15M markets with competitor copying
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
        
        # Assets - FOCUS ON BTC, ETH, SOL
        self.assets = {
            'BTC': {'series': 'KXBTC15M', 'candles': [], 'price_history': []},
            'ETH': {'series': 'KXETH15M', 'candles': [], 'price_history': []},
            'SOL': {'series': 'KSOL15M', 'candles': [], 'price_history': []},
        }
        
        # Parameters
        self.candle_window_minutes = 15
        self.vwap_slope_lookback_minutes = 5
        self.rsi_period = 14
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
        """Fetch 1-minute candles for all crypto assets"""
        try:
            session = await self._get_session()
            
            # Fetch BTC
            url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd"
            
            async with asyncio.timeout(10):
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        now = datetime.now()
                        
                        for asset, key in [('BTC', 'bitcoin'), ('ETH', 'ethereum'), ('SOL', 'solana')]:
                            if key in data:
                                price = data[key]['usd']
                                self._update_asset_candles(asset, price, now)
                        
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
    
    def score_direction(self, candles: List[Dict], vwap: float, current_price: float) -> float:
        """Simple direction scoring"""
        if not candles:
            return 0.0
        
        up = 1.0
        down = 1.0
        
        # VWAP position
        if current_price > vwap:
            up += 2.0
        else:
            down += 2.0
        
        # Price momentum
        if len(candles) >= 5:
            recent_change = (candles[-1]['close'] - candles[-5]['close']) / candles[-5]['close']
            if recent_change > 0.001:
                up += 1.5
            elif recent_change < -0.001:
                down += 1.5
        
        total = up + down
        return (up - down) / total if total > 0 else 0.0
    
    async def analyze(self) -> List[Dict]:
        """Analyze all crypto assets for opportunities"""
        opportunities = []
        
        if self.position_monitor:
            await self._monitor_positions()
        
        await self.fetch_1m_candles()
        
        for asset, info in self.assets.items():
            candles = info['candles']
            
            if len(candles) < 10:
                continue
            
            current_price = candles[-1]['close']
            vwap = self.compute_vwap(candles)
            
            # Score direction
            direction_score = self.score_direction(candles, vwap, current_price)
            
            # Convert to probabilities
            model_up = clamp(0.5 + direction_score * 0.3, 0.1, 0.9)
            model_down = 1 - model_up
            
            # Get markets for this asset
            try:
                response = self.client._request("GET", f"/markets?series_ticker={info['series']}&status=open")
                all_markets = response.json().get('markets', [])
                
                # Filter to only currently open markets
                now = datetime.now(timezone.utc)
                markets = []
                
                for m in all_markets:
                    open_str = m.get('open_time', '')
                    close_str = m.get('close_time', '')
                    
                    if open_str and close_str:
                        try:
                            open_time = datetime.fromisoformat(open_str.replace('Z', '+00:00'))
                            close_time = datetime.fromisoformat(close_str.replace('Z', '+00:00'))
                            
                            if open_time <= now < close_time:
                                markets.append(m)
                        except:
                            pass
                
                if markets:
                    logger.info(f"📊 {asset}: Found {len(markets)} open markets (model: {model_up:.0%} up)")
                
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
                        
                        yes_price = yes_bids[0][0] / 100
                        no_price = no_bids[0][0] / 100
                        
                        total = yes_price + no_price
                        if total <= 0:
                            continue
                        
                        market_up = yes_price / total
                        market_down = no_price / total
                        
                        edge_up = model_up - market_up
                        edge_down = model_down - market_down
                        
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
                        
                        # Threshold check
                        if best_edge < 0.05:
                            continue
                        if best_model < 0.55:
                            continue
                        if entry_price > 0.60:
                            continue
                        
                        opportunities.append({
                            'ticker': ticker,
                            'side': best_side,
                            'market_up': market_up,
                            'market_down': market_down,
                            'model_up': model_up,
                            'model_down': model_down,
                            'best_edge': best_edge,
                            'entry_price': entry_price,
                            'asset': asset
                        })
                        
                        logger.info(f"✅ {asset} OPPORTUNITY: {ticker} {best_side} | Edge={best_edge:.1%}")
                        
                    except Exception as e:
                        continue
                        
            except Exception as e:
                logger.error(f"Error fetching {asset} markets: {e}")
        
        return opportunities
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute trades with consensus"""
        executed = 0
        
        # Get competitor consensus
        logger.info("🤝 Checking competitor consensus...")
        try:
            consensus = self.consensus_tracker.get_competitor_consensus()
            logger.info(f"📊 Competitors: {consensus['consensus_side']} ({consensus['agreement_ratio']:.0%} agreement)")
        except Exception as e:
            logger.warning(f"Could not get consensus: {e}")
            consensus = None
        
        for opp in opportunities:
            ticker = opp['ticker']
            side = opp['side']
            entry_price_cents = int(opp['entry_price'] * 100)
            
            # Check for existing position
            if self.position_manager and self.position_manager.has_open_position(ticker, self.dry_run):
                continue
            
            # Position sizing based on edge
            edge = opp['best_edge']
            if edge >= 0.20:
                contracts = 5
            elif edge >= 0.10:
                contracts = 3
            else:
                contracts = 1
            
            # Execute
            if self.dry_run:
                self.record_position(ticker, side, contracts, entry_price_cents, ticker)
                logger.info(f"[SIM] {ticker} {side} x{contracts}")
                executed += 1
            else:
                result = self.client.place_order(ticker, side.lower(), entry_price_cents, contracts)
                if result.get('order_id'):
                    logger.info(f"[REAL] {ticker} {side} x{contracts} @ {entry_price_cents}c")
                    self.record_position(ticker, side, contracts, entry_price_cents, ticker)
                    executed += 1
        
        return executed
    
    async def _monitor_positions(self):
        """Monitor existing positions"""
        pass
    
    async def continuous_trade_loop(self):
        """Continuous trading loop"""
        logger.info("🔄 Starting CryptoMomentum loop (BTC/ETH/SOL 15M)")
        
        while True:
            try:
                opportunities = await self.analyze()
                
                if opportunities:
                    logger.info(f"🎯 Found {len(opportunities)} opportunities")
                    executed = await self.execute(opportunities)
                    if executed:
                        logger.info(f"✅ Executed {executed} trades")
                
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                await asyncio.sleep(60)
    
    async def scan(self):
        return await self.analyze()
    
    def get_performance(self):
        return {'name': self.name, 'trades': len(self.trades)}
