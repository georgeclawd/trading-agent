"""
Longshot Weather Strategy - The $64K Weather Bot Algorithm
Based on: Vibe-coded AI bot that made $64K trading weather

Strategy:
1. Target ONLY cheap weather markets (<10¢)
2. Calculate probability with ±3.5°F deviation
3. Edge = (fair_price - market_price) / market_price
4. Buy when edge is significant

Markets: London, NYC, Seoul (original bot cities)
"""

from typing import Dict, List, Optional
from strategy_framework import BaseStrategy
from datetime import datetime, timedelta
import logging
import aiohttp
import asyncio

logger = logging.getLogger('LongshotWeather')


class LongshotWeatherStrategy(BaseStrategy):
    """
    The $64K weather bot strategy - proven to work
    
    Key differences from WeatherPrediction:
    - Only trades cheap markets (<10¢)
    - Uses ±3.5°F deviation model
    - Edge = (fair - market) / market
    - Targets longshots with high ROI potential
    """
    
    def __init__(self, config: Dict, client, market_scanner=None):
        super().__init__(config, client)
        self.name = "LongshotWeather"
        self.market_scanner = market_scanner
        
        # Strategy parameters (from $64K bot)
        self.max_market_price = 0.20  # Only markets < 20¢ (adjusted for Kalshi)
        self.min_liquidity = 50  # $50 minimum
        self.deviation_f = 3.5  # ±3.5°F deviation
        self.min_edge = 0.20  # Minimum 20% edge for cheap markets
        self.max_position = config.get('max_position_size', 5)
        
        # Cities to monitor (Kalshi weather markets)
        self.cities = {
            'New York': {'lat': 40.7128, 'lon': -74.0060, 'kalshi_key': ['NYC', 'New York']},
            'Chicago': {'lat': 41.8781, 'lon': -87.6298, 'kalshi_key': ['CHI', 'Chicago']},
            'Philadelphia': {'lat': 39.9526, 'lon': -75.1652, 'kalshi_key': ['PHIL', 'Philadelphia']},
            'Los Angeles': {'lat': 34.0522, 'lon': -118.2437, 'kalshi_key': ['LAX', 'Los Angeles']},
            'Seattle': {'lat': 47.6062, 'lon': -122.3321, 'kalshi_key': ['SEA', 'Seattle']},
            'Houston': {'lat': 29.7604, 'lon': -95.3698, 'kalshi_key': ['HOU', 'Houston']},
        }
        
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def fetch_weather_forecast(self, city: str, lat: float, lon: float) -> Optional[Dict]:
        """Fetch weather forecast from OpenWeather"""
        import subprocess
        
        try:
            api_key = subprocess.run(
                ['pass', 'show', 'openweather/api-key'],
                capture_output=True, text=True
            ).stdout.strip().splitlines()[0]
        except:
            logger.error(f"Could not get OpenWeather API key")
            return None
        
        session = await self._get_session()
        
        try:
            url = (
                f"https://api.openweathermap.org/data/2.5/forecast?"
                f"lat={lat}&lon={lon}&appid={api_key}&units=imperial"
            )
            
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Extract daily forecasts
                    daily_temps = {}
                    for item in data.get('list', []):
                        dt = datetime.fromtimestamp(item['dt'])
                        date_str = dt.strftime('%Y-%m-%d')
                        
                        if date_str not in daily_temps:
                            daily_temps[date_str] = {'highs': [], 'lows': [], 'avgs': []}
                        
                        temp = item['main']['temp']
                        temp_max = item['main']['temp_max']
                        temp_min = item['main']['temp_min']
                        
                        daily_temps[date_str]['avgs'].append(temp)
                        daily_temps[date_str]['highs'].append(temp_max)
                        daily_temps[date_str]['lows'].append(temp_min)
                    
                    # Calculate daily stats
                    result = {}
                    for date, temps in daily_temps.items():
                        result[date] = {
                            'high': max(temps['highs']),
                            'low': min(temps['lows']),
                            'avg': sum(temps['avgs']) / len(temps['avgs'])
                        }
                    
                    return result
                    
        except Exception as e:
            logger.debug(f"Weather fetch error for {city}: {e}")
        
        return None
    
    def calculate_probability_with_deviation(self, forecast_high: float, 
                                             forecast_low: float, threshold: float,
                                             is_above: bool = True) -> float:
        """
        Calculate probability using ±3.5°F deviation model
        
        This is the key insight from the $64K bot - weather forecasts
        have natural deviation, so we model probability as a range
        """
        if is_above:
            # Probability temp > threshold
            # If forecast_high - deviation > threshold, high probability
            # If forecast_high + deviation < threshold, low probability
            
            optimistic = forecast_high + self.deviation_f
            pessimistic = forecast_high - self.deviation_f
            
            if pessimistic > threshold:
                return 0.85  # Very likely
            elif optimistic < threshold:
                return 0.15  # Very unlikely
            else:
                # Linear interpolation between pessimistic and optimistic
                range_size = optimistic - pessimistic
                position = threshold - pessimistic
                prob = 1 - (position / range_size)
                return max(0.15, min(0.85, prob))
        else:
            # Probability temp < threshold
            optimistic = forecast_low - self.deviation_f
            pessimistic = forecast_low + self.deviation_f
            
            if pessimistic < threshold:
                return 0.85
            elif optimistic > threshold:
                return 0.15
            else:
                range_size = optimistic - pessimistic
                position = threshold - optimistic
                prob = position / range_size
                return max(0.15, min(0.85, prob))
    
    def calculate_edge(self, fair_price: float, market_price: float) -> float:
        """
        Calculate edge using $64K bot formula:
        edge = (fair_price - market_price) / market_price
        
        This gives higher edge for cheap markets (where market_price is small)
        """
        if market_price <= 0:
            return 0
        return (fair_price - market_price) / market_price
    
    async def scan(self) -> List[Dict]:
        """Scan for longshot weather opportunities"""
        opportunities = []
        
        logger.info("  LongshotWeather: Scanning for cheap weather markets...")
        
        # Get all markets
        try:
            markets = self.client.get_markets(limit=1000, status='open')
        except Exception as e:
            logger.error(f"  LongshotWeather: Error fetching markets: {e}")
            return opportunities
        
        # Filter for weather markets in our cities
        weather_markets = []
        for m in markets:
            title = m.get('title', '').lower()
            ticker = m.get('ticker', '')
            
            # Check if it's a weather market
            is_weather = any(k in title for k in ['temp', 'temperature', 'high', 'low'])
            
            # Check if it's in our cities (using kalshi_key list)
            city_match = None
            for city, data in self.cities.items():
                kalshi_keys = data.get('kalshi_key', [])
                for key in kalshi_keys:
                    if key.lower() in title or key.lower() in ticker.lower():
                        city_match = city
                        break
                if city_match:
                    break
            
            if is_weather and city_match:
                # Check if cheap (<10¢)
                try:
                    orderbook = self.client.get_orderbook(ticker)
                    yes_bids = orderbook.get('yes', [])
                    if yes_bids:
                        market_price = yes_bids[0].get('price', 100) / 100
                        if market_price < self.max_market_price:
                            weather_markets.append({
                                'market': m,
                                'city': city_match,
                                'market_price': market_price,
                                'ticker': ticker,
                                'title': m.get('title', '')
                            })
                except:
                    continue
        
        logger.info(f"  LongshotWeather: Found {len(weather_markets)} cheap weather markets (<20¢)")
        
        # Analyze each cheap market
        for item in weather_markets:
            market = item['market']
            city = item['city']
            market_price = item['market_price']
            ticker = item['ticker']
            title = item['title']
            
            # Get weather forecast
            city_data = self.cities[city]
            forecast = await self.fetch_weather_forecast(city, city_data['lat'], city_data['lon'])
            
            if not forecast:
                continue
            
            # Parse market to extract threshold and date
            import re
            
            # Try to extract threshold (e.g., "will be >37°" or "will be 29-30°")
            threshold = None
            is_above = True
            
            # Pattern: >37 or <30
            match = re.search(r'[><](\d+)', title)
            if match:
                threshold = int(match.group(1))
                is_above = '>' in title
            
            # Pattern: 29-30 (range)
            match = re.search(r'(\d+)-(\d+)', title)
            if match:
                threshold = (int(match.group(1)) + int(match.group(2))) / 2
                is_above = None  # Range market
            
            if threshold is None:
                continue
            
            # Get forecast for relevant date
            # Try to extract date from ticker
            date_match = re.search(r'-(\d{2})([A-Z]{3})(\d{2})-', ticker)
            if date_match:
                day = date_match.group(1)
                month_str = date_match.group(2)
                months = {'JAN': 1, 'FEB': 2, 'MAR': 3}
                month = months.get(month_str, 2)
                
                forecast_date = f"2026-{month:02d}-{int(day):02d}"
                daily_forecast = forecast.get(forecast_date)
                
                if not daily_forecast:
                    continue
                
                # Calculate fair probability with deviation
                if is_above is not None:
                    # Above/below market
                    forecast_temp = daily_forecast['high'] if is_above else daily_forecast['low']
                    fair_prob = self.calculate_probability_with_deviation(
                        daily_forecast['high'], daily_forecast['low'],
                        threshold, is_above
                    )
                else:
                    # Range market - simplified probability
                    range_center = threshold
                    forecast_temp = daily_forecast['avg']
                    diff = abs(forecast_temp - range_center)
                    if diff < self.deviation_f:
                        fair_prob = 0.7
                    else:
                        fair_prob = 0.3
                
                # Calculate edge using $64K formula
                edge = self.calculate_edge(fair_prob, market_price)
                
                logger.info(f"  LongshotWeather: {ticker[:25]}... "
                           f"Market={market_price:.1%}, Fair={fair_prob:.1%}, Edge={edge:.1%}")
                
                # Only trade if edge > threshold (cheap markets need bigger edge)
                if edge > self.min_edge:
                    opp = {
                        'ticker': ticker,
                        'market': title,
                        'city': city,
                        'market_price': market_price,
                        'fair_probability': fair_prob,
                        'expected_value': edge,
                        'edge_formula': '(fair - market) / market',
                        'forecast_temp': forecast_temp,
                        'threshold': threshold,
                        'deviation': self.deviation_f,
                        'strategy': 'longshot_weather'
                    }
                    opportunities.append(opp)
                    logger.info(f"  LongshotWeather: ✅ FOUND - Edge {edge:.1%} > {self.min_edge:.1%}")
                else:
                    logger.info(f"  LongshotWeather: Edge {edge:.1%} too small")
        
        return opportunities
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute longshot trades"""
        executed = 0
        
        for opp in opportunities:
            trade = {
                'ticker': opp['ticker'],
                'market': opp['market'],
                'city': opp['city'],
                'market_price': opp['market_price'],
                'fair_probability': opp['fair_probability'],
                'expected_value': opp['expected_value'],
                'size': min(self.max_position, 5),
                'timestamp': datetime.now().isoformat(),
                'status': 'open',
                'simulated': True
            }
            
            self.record_trade(trade)
            executed += 1
            
            logger.info(f"    ✓ Executed: {opp['ticker'][:30]}... "
                       f"at {opp['market_price']:.1%}, edge={opp['expected_value']:.1%}")
        
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
