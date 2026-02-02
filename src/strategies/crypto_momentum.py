"""
Crypto Momentum Strategy - 15 Minute Trading
Based on PolymarketBTC15mAssistant algorithm

Strategy:
- Monitor BTC price in real-time
- Calculate momentum indicators (RSI, MACD, price delta)
- Predict probability of UP/DOWN in next 15 min
- Trade when market price differs from prediction
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
    15-minute crypto momentum trading strategy
    
    Monitors BTC price and trades on momentum signals.
    Works with Kalshi KXBTC15M markets.
    """
    
    def __init__(self, config: Dict, client):
        super().__init__(config, client)
        self.name = "CryptoMomentum"
        
        # Price tracking
        self.price_history: List[Dict] = []
        self.max_history = 100  # Keep last 100 price points
        
        # Market series to trade
        self.series_ticker = "KXBTC15M"
        
        # Trading parameters
        self.min_edge = 0.05  # Minimum 5% edge
        self.max_position = config.get('max_position_size', 5)
        
        # Price sources
        self.price_sources = [
            'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT',
            'https://api.coinbase.com/v2/exchange-rates?currency=BTC',
        ]
        
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def fetch_btc_price(self) -> Optional[float]:
        """
        Fetch current BTC price from multiple sources
        Returns average price or None if all fail
        """
        prices = []
        session = await self._get_session()
        
        # Try Binance
        try:
            async with session.get(self.price_sources[0], timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = float(data.get('price', 0))
                    if price > 0:
                        prices.append(price)
                        logger.debug(f"Binance BTC price: ${price:,.2f}")
        except Exception as e:
            logger.debug(f"Binance price fetch failed: {e}")
        
        # Try Coinbase
        try:
            async with session.get(self.price_sources[1], timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    rate = data.get('data', {}).get('rates', {}).get('USD', 0)
                    if rate:
                        price = 1.0 / float(rate)  # Convert from BTC/USD to USD/BTC
                        prices.append(price)
                        logger.debug(f"Coinbase BTC price: ${price:,.2f}")
        except Exception as e:
            logger.debug(f"Coinbase price fetch failed: {e}")
        
        if not prices:
            return None
        
        avg_price = sum(prices) / len(prices)
        logger.info(f"BTC price: ${avg_price:,.2f} (from {len(prices)} sources)")
        
        # Store in history
        self.price_history.append({
            'timestamp': datetime.now(),
            'price': avg_price
        })
        
        # Trim history
        if len(self.price_history) > self.max_history:
            self.price_history = self.price_history[-self.max_history:]
        
        return avg_price
    
    def calculate_indicators(self) -> Dict:
        """
        Calculate technical indicators from price history
        
        Returns:
            Dict with rsi, macd, vwap, delta_1m, delta_5m, trend
        """
        if len(self.price_history) < 20:
            return {'error': 'Insufficient price history'}
        
        prices = [p['price'] for p in self.price_history]
        
        # Calculate RSI (Relative Strength Index)
        rsi = self._calculate_rsi(prices, period=14)
        
        # Calculate MACD
        macd, signal, histogram = self._calculate_macd(prices)
        
        # Calculate VWAP (Volume Weighted Average Price)
        # Simplified - using regular average since we don't have volume
        vwap = sum(prices[-20:]) / 20
        
        # Calculate price deltas
        current_price = prices[-1]
        delta_1m = (current_price - prices[-2]) / prices[-2] if len(prices) >= 2 else 0
        delta_5m = (current_price - prices[-6]) / prices[-6] if len(prices) >= 6 else 0
        delta_15m = (current_price - prices[-16]) / prices[-16] if len(prices) >= 16 else 0
        
        # Determine trend
        trend = 'neutral'
        if delta_5m > 0.001 and rsi > 50:
            trend = 'up'
        elif delta_5m < -0.001 and rsi < 50:
            trend = 'down'
        
        return {
            'rsi': rsi,
            'macd': macd,
            'macd_signal': signal,
            'macd_histogram': histogram,
            'vwap': vwap,
            'delta_1m': delta_1m,
            'delta_5m': delta_5m,
            'delta_15m': delta_15m,
            'trend': trend,
            'current_price': current_price
        }
    
    def _calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Calculate RSI (Relative Strength Index)"""
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
        
        # Use only last 'period' values
        gains = gains[-period:]
        losses = losses[-period:]
        
        avg_gain = sum(gains) / period if gains else 0
        avg_loss = sum(losses) / period if losses else 0
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def _calculate_macd(self, prices: List[float]) -> Tuple[float, float, float]:
        """Calculate MACD (Moving Average Convergence Divergence)"""
        if len(prices) < 26:
            return 0, 0, 0
        
        # Calculate EMAs
        ema_12 = self._calculate_ema(prices, 12)
        ema_26 = self._calculate_ema(prices, 26)
        
        # MACD line
        macd_line = ema_12 - ema_26
        
        # Signal line (9-period EMA of MACD)
        # Simplified - just use recent MACD values
        signal_line = macd_line * 0.9  # Approximation
        
        # Histogram
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _calculate_ema(self, prices: List[float], period: int) -> float:
        """Calculate Exponential Moving Average"""
        if len(prices) < period:
            return sum(prices) / len(prices)
        
        multiplier = 2 / (period + 1)
        ema = sum(prices[:period]) / period
        
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        
        return ema
    
    def predict_direction(self, indicators: Dict) -> Tuple[str, float]:
        """
        Predict UP or DOWN direction and confidence
        
        Returns:
            (direction, confidence) where direction is 'up' or 'down'
        """
        score = 0
        
        # RSI factor
        rsi = indicators.get('rsi', 50)
        if rsi > 60:
            score += 1
        elif rsi < 40:
            score -= 1
        
        # MACD factor
        macd_hist = indicators.get('macd_histogram', 0)
        if macd_hist > 0:
            score += 1
        elif macd_hist < 0:
            score -= 1
        
        # Price vs VWAP
        price = indicators.get('current_price', 0)
        vwap = indicators.get('vwap', price)
        if price > vwap * 1.001:
            score += 1
        elif price < vwap * 0.999:
            score -= 1
        
        # Recent momentum
        delta_5m = indicators.get('delta_5m', 0)
        if delta_5m > 0.0005:
            score += 1
        elif delta_5m < -0.0005:
            score -= 1
        
        # Convert score to prediction
        if score >= 2:
            return 'up', min(0.5 + score * 0.1, 0.9)
        elif score <= -2:
            return 'down', min(0.5 + abs(score) * 0.1, 0.9)
        else:
            return 'neutral', 0.5
    
    async def scan(self) -> List[Dict]:
        """Scan for crypto momentum opportunities"""
        opportunities = []
        
        logger.info("  CryptoMomentum: Scanning for opportunities...")
        
        # Fetch current BTC price
        current_price = await self.fetch_btc_price()
        if not current_price:
            logger.warning("  CryptoMomentum: Could not fetch BTC price")
            return opportunities
        
        # Need enough history for indicators
        if len(self.price_history) < 20:
            logger.info(f"  CryptoMomentum: Building price history ({len(self.price_history)}/20)")
            return opportunities
        
        # Calculate indicators
        indicators = self.calculate_indicators()
        if 'error' in indicators:
            logger.warning(f"  CryptoMomentum: {indicators['error']}")
            return opportunities
        
        # Log indicators
        logger.info(f"  CryptoMomentum: RSI={indicators['rsi']:.1f}, "
                   f"MACD={indicators['macd_histogram']:.2f}, "
                   f"Trend={indicators['trend']}")
        
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
            
            # Get prediction
            direction, confidence = self.predict_direction(indicators)
            
            if direction == 'neutral':
                logger.info(f"  CryptoMomentum: {ticker} - No clear signal (confidence too low)")
                continue
            
            # Get market orderbook
            try:
                orderbook = self.client.get_orderbook(ticker)
                yes_bids = orderbook.get('yes', [])
                
                if not yes_bids:
                    logger.debug(f"  CryptoMomentum: {ticker} - No orderbook liquidity")
                    continue
                
                market_price = yes_bids[0].get('price', 50) / 100
                
            except Exception as e:
                logger.debug(f"  CryptoMomentum: Error fetching orderbook for {ticker}: {e}")
                continue
            
            # Calculate edge
            if direction == 'up':
                our_prob = confidence
                edge = our_prob - market_price
            else:  # down
                our_prob = 1 - confidence
                edge = market_price - our_prob
            
            logger.info(f"  CryptoMomentum: {ticker} - {direction.upper()}, "
                       f"our_prob={our_prob:.1%}, market={market_price:.1%}, edge={edge:.1%}")
            
            if edge > self.min_edge:
                opp = {
                    'ticker': ticker,
                    'market': market.get('title', 'BTC 15m'),
                    'direction': direction,
                    'our_probability': our_prob,
                    'market_probability': market_price,
                    'expected_value': edge,
                    'confidence': confidence,
                    'indicators': indicators,
                    'strategy': 'crypto_momentum'
                }
                opportunities.append(opp)
                logger.info(f"  CryptoMomentum: ✅ FOUND OPPORTUNITY - {ticker}, edge={edge:.1%}")
        
        return opportunities
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute crypto momentum trades"""
        executed = 0
        
        for opp in opportunities:
            trade = {
                'ticker': opp['ticker'],
                'market': opp['market'],
                'direction': opp['direction'],
                'our_probability': opp['our_probability'],
                'market_probability': opp['market_probability'],
                'expected_value': opp['expected_value'],
                'size': min(self.max_position, 5),
                'timestamp': datetime.now().isoformat(),
                'status': 'open',
                'simulated': True
            }
            
            self.record_trade(trade)
            executed += 1
            
            logger.info(f"    ✓ Executed: {opp['ticker']} - {opp['direction'].upper()} "
                       f"(edge: {opp['expected_value']:.1%})")
        
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
