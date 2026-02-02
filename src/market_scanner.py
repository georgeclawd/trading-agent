"""
Market Scanner - Finds +EV trading opportunities
Focus on markets with predictable data (weather, sports, etc.)
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional
from datetime import datetime, timedelta


class MarketScanner:
    """
    Scans Polymarket and other markets for +EV opportunities
    Inspired by the weather bot making $10k/month
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Data sources for different markets
        self.data_sources = {
            'weather': {
                'api': 'https://api.open-meteo.com/v1/forecast',
                'reliability': 0.95,  # Weather is very predictable
            },
            'sports': {
                'api': None,  # Will use external APIs
                'reliability': 0.75,
            },
            'crypto': {
                'api': 'https://api.coingecko.com/api/v3',
                'reliability': 0.60,  # More volatile
            }
        }
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def find_opportunities(self) -> List[Dict]:
        """Scan all markets for +EV opportunities"""
        opportunities = []
        
        # Real weather-based opportunities
        weather_opps = await self._analyze_weather_markets()
        opportunities.extend(weather_opps)
        
        # Kalshi markets
        kalshi_opps = await self._scan_kalshi()
        opportunities.extend(kalshi_opps)
        
        # Sort by expected value
        opportunities.sort(key=lambda x: x.get('expected_value', 0), reverse=True)
        
        return opportunities
    
    async def _scan_kalshi(self) -> List[Dict]:
        """
        Scan Kalshi for +EV opportunities
        
        High-value categories:
        - Weather markets (predictable with meteorological data)
        - Sports (with good data sources)
        - Finance/Economic events
        """
        opportunities = []
        
        try:
            # Import Kalshi client
            from kalshi_client import KalshiClient
            import subprocess
            
            # Load credentials
            api_key_id = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], 
                                       capture_output=True, text=True).stdout.strip().split('\n')[0]
            api_key = subprocess.run(['pass', 'show', 'kalshi/api_key'], 
                                    capture_output=True, text=True).stdout.strip()
            
            client = KalshiClient(api_key_id=api_key_id, api_key=api_key)
            
            # Get active markets
            markets = client.get_markets(limit=100, status='active')
            
            for market in markets:
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                
                # Check for weather markets
                if any(word in title.lower() for word in ['rain', 'temperature', 'snow', 'weather']):
                    opp = await self._analyze_kalshi_weather(client, market)
                    if opp:
                        opportunities.append(opp)
                        
        except Exception as e:
            print(f"Kalshi scan error: {e}")
        
        return opportunities
    
    async def _analyze_kalshi_weather(self, client, market: Dict) -> Optional[Dict]:
        """Analyze a Kalshi weather market with real weather data"""
        ticker = market.get('ticker', '')
        title = market.get('title', '')
        
        # Parse location from title (basic parsing)
        cities = {
            'new york': (40.7128, -74.0060),
            'nyc': (40.7128, -74.0060),
            'los angeles': (34.0522, -118.2437),
            'la': (34.0522, -118.2437),
            'chicago': (41.8781, -87.6298),
            'london': (51.5074, -0.1278),
            'tokyo': (35.6762, 139.6503),
        }
        
        # Find city in title
        city_name = None
        city_coords = None
        title_lower = title.lower()
        
        for city, coords in cities.items():
            if city in title_lower:
                city_name = city.title()
                city_coords = coords
                break
        
        if not city_coords:
            return None
        
        # Fetch real weather data
        weather_data = await self._fetch_weather(city_coords[0], city_coords[1])
        
        if not weather_data:
            return None
        
        # Calculate our probability from weather data
        daily = weather_data.get('daily', {})
        weather_codes = daily.get('weathercode', [])
        precipitation = daily.get('precipitation_sum', [])
        
        if not weather_codes or len(weather_codes) < 2:
            return None
        
        # Tomorrow's weather (index 1)
        tomorrow_code = weather_codes[1]
        tomorrow_rain = precipitation[1] if len(precipitation) > 1 else 0
        
        our_probability = self._weather_code_to_rain_prob(tomorrow_code, tomorrow_rain)
        
        # Get actual market price from Kalshi
        try:
            orderbook = client.get_orderbook(ticker)
            
            if orderbook:
                yes_bids = orderbook.get('yes', [])
                yes_asks = orderbook.get('no', [])
                
                # Get best bid and ask
                best_bid = yes_bids[0].get('price', 0) / 100 if yes_bids else 0
                # Convert NO ask to YES price
                no_ask = yes_asks[0].get('price', 0) if yes_asks else 0
                best_ask = (100 - no_ask) / 100 if no_ask > 0 else 0
                
                # Use midpoint as market probability
                if best_bid > 0 and best_ask > 0:
                    market_probability = (best_bid + best_ask) / 2
                elif best_bid > 0:
                    market_probability = best_bid
                elif best_ask > 0:
                    market_probability = best_ask
                else:
                    market_probability = market.get('last_price', 50) / 100
            else:
                market_probability = market.get('last_price', 50) / 100
                
        except Exception as e:
            market_probability = market.get('last_price', 50) / 100
        
        # Calculate expected value
        expected_value = our_probability - market_probability
        
        return {
            'market': title,
            'ticker': ticker,
            'platform': 'kalshi',
            'our_probability': our_probability,
            'market_probability': market_probability,
            'expected_value': expected_value,
            'odds': 1 / market_probability if market_probability > 0 else 0,
            'data_source': 'open-meteo',
            'confidence': 0.90,
            'category': 'weather',
            'city': city_name,
            'weather_code': tomorrow_code,
            'precipitation_mm': tomorrow_rain,
        }
    
    async def _analyze_weather_markets(self) -> List[Dict]:
        """
        Analyze weather prediction markets on Kalshi
        These are goldmines - weather is highly predictable 24-48h out
        """
        opportunities = []
        
        # Get weather data for major cities that have Kalshi markets
        cities = [
            {'name': 'New York', 'lat': 40.7128, 'lon': -74.0060},
            {'name': 'Los Angeles', 'lat': 34.0522, 'lon': -118.2437},
            {'name': 'Chicago', 'lat': 41.8781, 'lon': -87.6298},
        ]
        
        # Fetch fresh weather data for each city
        for city in cities:
            weather_data = await self._fetch_weather(city['lat'], city['lon'])
            
            if weather_data:
                # Log the fresh data for debugging
                daily = weather_data.get('daily', {})
                weather_codes = daily.get('weathercode', [])
                precipitation = daily.get('precipitation_sum', [])
                
                if weather_codes and len(weather_codes) > 1:
                    tomorrow_code = weather_codes[1]
                    tomorrow_rain = precipitation[1] if len(precipitation) > 1 else 0
                    rain_prob = self._weather_code_to_rain_prob(tomorrow_code, tomorrow_rain)
                    
                    print(f"[SCANNER] Weather for {city['name']}: code={tomorrow_code}, "
                          f"rain={tomorrow_rain}mm, prob={rain_prob:.1%}")
                
                # The actual market matching happens in _scan_kalshi
                # which looks for these cities in market titles
        
        return opportunities
    
    async def _fetch_weather(self, lat: float, lon: float) -> Optional[Dict]:
        """Fetch weather forecast from Open-Meteo"""
        if not self.session:
            return None
        
        try:
            url = (
                f"https://api.open-meteo.com/v1/forecast?"
                f"latitude={lat}&longitude={lon}"
                f"&daily=precipitation_sum,weathercode"
                f"&timezone=auto"
            )
            
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            print(f"Weather fetch error: {e}")
        
        return None
    
    def _create_weather_opportunity(self, city: Dict, weather_data: Dict) -> Optional[Dict]:
        """Create trading opportunity from weather data"""
        # Parse weather code to probability
        # Weather codes: https://open-meteo.com/en/docs
        
        daily = weather_data.get('daily', {})
        weather_codes = daily.get('weathercode', [])
        precipitation = daily.get('precipitation_sum', [])
        
        if not weather_codes:
            return None
        
        # Tomorrow's weather
        tomorrow_code = weather_codes[1] if len(weather_codes) > 1 else weather_codes[0]
        tomorrow_rain = precipitation[1] if len(precipitation) > 1 else precipitation[0]
        
        # Map weather code to rain probability
        rain_probability = self._weather_code_to_rain_prob(tomorrow_code, tomorrow_rain)
        
        return {
            'market': f"Weather - Rain in {city['name']} Tomorrow",
            'platform': 'polymarket',
            'category': 'weather',
            'our_probability': rain_probability,
            'data_source': 'open-meteo',
            'confidence': 0.90,
            'raw_data': weather_data,
        }
    
    def _weather_code_to_rain_prob(self, code: int, precipitation: float) -> float:
        """Convert WMO weather code to rain probability"""
        # WMO Weather interpretation codes
        # 0: Clear sky
        # 1-3: Mainly clear, partly cloudy, overcast
        # 45, 48: Fog
        # 51-55: Drizzle
        # 61-65: Rain
        # 71-77: Snow
        # 80-82: Rain showers
        # 95-99: Thunderstorm
        
        if code == 0:
            return 0.05
        elif code <= 3:
            return 0.10 if precipitation < 1 else 0.20
        elif code in [45, 48]:
            return 0.15
        elif 51 <= code <= 55:
            return 0.60
        elif 61 <= code <= 65:
            return 0.85
        elif 71 <= code <= 77:
            return 0.70
        elif 80 <= code <= 82:
            return 0.75
        elif 95 <= code <= 99:
            return 0.90
        
        return 0.50  # Unknown
    
    def _validate_opportunity(self, opp: Dict) -> bool:
        """Validate opportunity meets minimum criteria"""
        # Check EV threshold
        if opp.get('expected_value', 0) < self.config.get('min_ev_threshold', 0.05):
            return False
        
        # Check confidence
        if opp.get('confidence', 0) < 0.70:
            return False
        
        # Check data source reliability
        category = opp.get('category', '')
        reliability = self.data_sources.get(category, {}).get('reliability', 0.5)
        
        if reliability < 0.70:
            return False
        
        return True
    
    async def _scan_sports_markets(self) -> List[Dict]:
        """Scan sports betting markets"""
        # TODO: Integrate with sports APIs
        return []
    
    async def _scan_crypto_markets(self) -> List[Dict]:
        """Scan crypto price prediction markets"""
        # TODO: Integrate with CoinGecko/CoinMarketCap
        return []
