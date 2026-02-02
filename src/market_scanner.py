"""
Market Scanner - Finds +EV trading opportunities
Focus on markets with predictable data (weather, sports, etc.)
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


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
        
        # Ensure session exists
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        logger.info("🔍 STARTING MARKET SCAN")
        logger.info("="*60)
        
        # Real weather-based opportunities
        logger.info("📡 Fetching fresh weather data for major cities...")
        weather_opps = await self._analyze_weather_markets()
        opportunities.extend(weather_opps)
        
        # Kalshi markets
        logger.info("🏦 Scanning Kalshi for opportunities...")
        kalshi_opps, kalshi_details = await self._scan_kalshi()
        opportunities.extend(kalshi_opps)
        
        # If no weather markets, scan sports/finance for other opportunities
        if kalshi_details.get('weather_markets_found', 0) == 0:
            logger.info("   📝 No weather markets found, checking sports/finance...")
            other_opps = await self._scan_kalshi_other_markets()
            opportunities.extend(other_opps)
        
        # Log summary
        logger.info("="*60)
        logger.info(f"📊 SCAN SUMMARY:")
        logger.info(f"   Cities checked: {kalshi_details.get('cities_checked', 0)}")
        logger.info(f"   Weather markets found: {kalshi_details.get('weather_markets_found', 0)}")
        logger.info(f"   Markets with data: {kalshi_details.get('markets_with_data', 0)}")
        logger.info(f"   Opportunities passing EV filter: {len(opportunities)}")
        
        if opportunities:
            logger.info(f"   Best EV: {opportunities[0].get('expected_value', 0):.2%}")
        else:
            if kalshi_details.get('weather_markets_found', 0) == 0:
                logger.info(f"   Reason: No weather markets available on Kalshi right now")
                logger.info(f"   Note: Weather markets are seasonal. Try again during storm/winter season.")
            else:
                logger.info(f"   Reason: Found markets but none met +EV threshold ({self.config.get('min_ev_threshold', 0.05):.1%})")
        logger.info("="*60)
        
        # Sort by expected value
        opportunities.sort(key=lambda x: x.get('expected_value', 0), reverse=True)
        
        return opportunities
    
    async def _scan_kalshi(self) -> tuple:
        """
        Scan Kalshi for +EV opportunities
        Returns: (opportunities_list, details_dict)
        """
        opportunities = []
        details = {
            'cities_checked': 0,
            'weather_markets_found': 0,
            'markets_with_data': 0,
            'rejected_low_ev': 0,
            'rejected_no_data': 0,
        }
        
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
            
            # Cities we monitor
            cities = ['new york', 'nyc', 'los angeles', 'la', 'chicago', 'london', 'tokyo']
            details['cities_checked'] = len(cities)
            
            # Get open markets (status='active' returns 400 on new API)
            logger.info("   📥 Fetching open markets from Kalshi...")
            markets = client.get_markets(limit=100, status='open')
            logger.info(f"   📊 Retrieved {len(markets)} active markets")
            
            # Filter for weather markets
            weather_keywords = ['rain', 'temperature', 'snow', 'weather']
            weather_markets = []
            
            for market in markets:
                title = market.get('title', '').lower()
                if any(word in title for word in weather_keywords):
                    # Check if it's for one of our monitored cities
                    if any(city in title for city in cities):
                        weather_markets.append(market)
            
            details['weather_markets_found'] = len(weather_markets)
            logger.info(f"   🌦️  Found {len(weather_markets)} weather markets for monitored cities")
            
            # Analyze each weather market
            for i, market in enumerate(weather_markets, 1):
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                
                logger.info(f"   [{i}/{len(weather_markets)}] Analyzing: {ticker}")
                
                opp = await self._analyze_kalshi_weather(client, market, details)
                
                if opp:
                    opportunities.append(opp)
                    details['markets_with_data'] += 1
                    
                    # Log the analysis
                    ev = opp.get('expected_value', 0)
                    our_prob = opp.get('our_probability', 0)
                    market_prob = opp.get('market_probability', 0)
                    
                    logger.info(f"      ✅ Data fetched: Weather code={opp.get('weather_code')}, "
                              f"Rain prob={our_prob:.1%}")
                    logger.info(f"      💰 Market price: {market_prob:.1%} | Our model: {our_prob:.1%} | "
                              f"EV: {ev:+.1%}")
                    
                    if ev < self.config.get('min_ev_threshold', 0.05):
                        logger.info(f"      ❌ REJECTED: EV {ev:.1%} below threshold "
                                  f"({self.config.get('min_ev_threshold', 0.05):.1%})")
                        details['rejected_low_ev'] += 1
                    else:
                        logger.info(f"      ✓ PASSED: EV {ev:.1%} meets threshold")
                else:
                    details['rejected_no_data'] += 1
                    logger.info(f"      ⚠️  Could not fetch weather data or no matching city")
                        
        except Exception as e:
            logger.error(f"Kalshi scan error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        return opportunities, details
    
    async def _analyze_kalshi_weather(self, client, market: Dict, details: Dict = None) -> Optional[Dict]:
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
        market_probability = None
        price_source = "unknown"
        
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
                    price_source = f"orderbook (bid={best_bid:.2f}, ask={best_ask:.2f})"
                elif best_bid > 0:
                    market_probability = best_bid
                    price_source = f"bid_only ({best_bid:.2f})"
                elif best_ask > 0:
                    market_probability = best_ask
                    price_source = f"ask_only ({best_ask:.2f})"
                else:
                    market_probability = market.get('last_price', 50) / 100
                    price_source = f"last_price ({market.get('last_price', 50)}¢)"
            else:
                market_probability = market.get('last_price', 50) / 100
                price_source = f"last_price ({market.get('last_price', 50)}¢)"
                
        except Exception as e:
            market_probability = market.get('last_price', 50) / 100
            price_source = f"last_price_fallback ({market.get('last_price', 50)}¢)"
        
        # Calculate expected value
        expected_value = our_probability - market_probability
        
        # Only return if it passes validation
        opp = {
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
            'price_source': price_source,
        }
        
        return opp
    
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
        
        logger.info("   🌍 Fetching weather forecasts:")
        
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
                    
                    logger.info(f"      📍 {city['name']}: Weather code={tomorrow_code}, "
                              f"Rain={tomorrow_rain}mm → Our prob={rain_prob:.1%}")
                else:
                    logger.warning(f"      ⚠️  {city['name']}: Incomplete weather data")
            else:
                logger.error(f"      ❌ {city['name']}: Failed to fetch weather data")
        
        return opportunities
    
    async def _fetch_weather(self, lat: float, lon: float) -> Optional[Dict]:
        """Fetch weather forecast from Open-Meteo"""
        # Create session if not exists
        if not self.session:
            self.session = aiohttp.ClientSession()
        
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
                else:
                    logger.error(f"Weather API returned {response.status}")
        except Exception as e:
            logger.error(f"Weather fetch error: {e}")
        
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
    
    async def _scan_kalshi_other_markets(self) -> List[Dict]:
        """Scan sports/finance markets on Kalshi for value"""
        opportunities = []
        
        try:
            from kalshi_client import KalshiClient
            import subprocess
            
            api_key_id = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], 
                                       capture_output=True, text=True).stdout.strip().split('\n')[0]
            api_key = subprocess.run(['pass', 'show', 'kalshi/api_key'], 
                                    capture_output=True, text=True).stdout.strip()
            
            client = KalshiClient(api_key_id=api_key_id, api_key=api_key)
            
            # Get finance markets (more predictable than sports)
            logger.info("   💰 Checking finance markets...")
            markets = client.get_markets(limit=50, status='open')
            
            finance_keywords = ['spx', 'nasdaq', 'bitcoin', 'btc', 'eth', 'fed', 'rate']
            
            for m in markets:
                title = m.get('title', '').lower()
                ticker = m.get('ticker', '')
                
                # Look for finance markets we might have an edge on
                if any(k in title for k in finance_keywords):
                    last_price = m.get('last_price', 50)
                    volume = m.get('volume', 0)
                    
                    # Log what we find
                    logger.info(f"      📈 {ticker[:40]}...")
                    logger.info(f"         Price: {last_price}¢ | Volume: ${volume:,.0f}")
                    logger.info(f"         Title: {title[:50]}...")
                    
                    # For now just log - would need external data source for +EV calc
                    # opportunities.append({...})
                    
            logger.info(f"   📊 Checked {len(markets)} markets, found {len(opportunities)} opportunities")
            
        except Exception as e:
            logger.error(f"   Error scanning other markets: {e}")
        
        return opportunities
    
    async def _scan_sports_markets(self) -> List[Dict]:
        """Scan sports betting markets"""
        # TODO: Integrate with sports APIs (would need odds APIs like Odds API)
        return []
    
    async def _scan_crypto_markets(self) -> List[Dict]:
        """Scan crypto price prediction markets"""
        # TODO: Integrate with CoinGecko/CoinMarketCap
        return []
