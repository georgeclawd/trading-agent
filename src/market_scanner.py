"""
Market Scanner - Finds +EV trading opportunities
Focus on markets with predictable data (weather, sports, etc.)
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging
from weather_cache import WeatherCache
from weather_api import WeatherAPI

logger = logging.getLogger(__name__)


class MarketScanner:
    """
    Scans Polymarket and other markets for +EV opportunities
    Inspired by the weather bot making $10k/month
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.weather_cache = WeatherCache()
        
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
        
        # Clear weather cache at start of each scan for fresh data
        self._weather_cache = {}
        
        # Wait a bit at start to avoid rate limits from previous scan
        await asyncio.sleep(2)
        
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
            total_markets = (kalshi_details.get('sports_count', 0) + 
                           kalshi_details.get('finance_count', 0) + 
                           kalshi_details.get('entertainment_count', 0))
            
            if kalshi_details.get('weather_markets_found', 0) == 0:
                logger.info(f"   Reason: No city-specific weather markets found for our monitored cities")
                logger.info(f"   Available on Kalshi: {total_markets} total markets")
                logger.info(f"     - Sports: ~{kalshi_details.get('sports_count', 0)}")
                logger.info(f"     - Finance: ~{kalshi_details.get('finance_count', 0)}")
                logger.info(f"     - Entertainment: ~{kalshi_details.get('entertainment_count', 0)}")
                if kalshi_details.get('climate_markets_found', 0) > 0:
                    logger.info(f"     - Climate/Weather (general): {kalshi_details.get('climate_markets_found', 0)}")
            else:
                logger.info(f"   Reason: Found {kalshi_details.get('weather_markets_found', 0)} weather markets but none met +EV threshold")
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
            'climate_markets_found': 0,
            'sports_count': 0,
            'finance_count': 0,
            'entertainment_count': 0,
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
            
            # Get open markets - fetch ALL to get accurate counts
            logger.info("   📥 Fetching open markets from Kalshi...")
            markets = client.get_markets(limit=1000, status='open')
            logger.info(f"   📊 Retrieved {len(markets)} active markets")
            
            # Also check for series-based markets (climate, weather)
            logger.info("   📅 Checking series-based markets (climate/weather)...")
            try:
                # Check climate/weather series
                series_tickers = ['KXHIGHNY', 'KXHIGHLA', 'KXHIGHCHI', 'KXHIGHLON']
                for series_ticker in series_tickers:
                    series_response = client._request("GET", f"/series/{series_ticker}")
                    if series_response and series_response.status_code == 200:
                        # Get markets in this series
                        series_markets_response = client._request("GET", f"/markets?series_ticker={series_ticker}&limit=50")
                        if series_markets_response and series_markets_response.status_code == 200:
                            series_data = series_markets_response.json()
                            series_markets = series_data.get('markets', [])
                            if series_markets:
                                logger.info(f"      ✅ Found series {series_ticker}: {len(series_markets)} markets")
                                markets.extend(series_markets)
                                
                                # Log first few for visibility
                                for m in series_markets[:3]:
                                    logger.info(f"         • {m.get('ticker')}: {m.get('title', 'N/A')[:50]}...")
                
                # Also check specific events (like Grammys)
                event_tickers = ['KXGRAMAOTY-68', 'KXMVESPORTSMULTIGAMEEXTENDED']
                for event_ticker in event_tickers:
                    event_response = client._request("GET", f"/events/{event_ticker}")
                    if event_response and event_response.status_code == 200:
                        event_data = event_response.json()
                        event_markets = event_data.get('markets', [])
                        logger.info(f"      ✅ Found event {event_ticker}: {len(event_markets)} markets")
                        markets.extend(event_markets)
            except Exception as e:
                logger.warning(f"   Series/event check warning: {e}")
            
            # Filter for weather markets
            weather_keywords = ['rain', 'temperature', 'snow', 'weather']
            weather_markets = []
            
            for market in markets:
                title = market.get('title', '').lower()
                ticker = market.get('ticker', '').lower()
                combined = title + ' ' + ticker
                
                # Count by category for reporting (more accurate detection)
                # Check entertainment FIRST (more specific patterns)
                if any(k in combined for k in ['grammy', 'album of the', 'oscar', 'emmy', 'academy award', 'golden globe']):
                    details['entertainment_count'] += 1
                # Finance (specific financial terms)
                elif any(k in combined for k in ['spx', 'nasdaq', 'bitcoin', 'btc', 'eth', 'rate', 'fed', 'cpi', 'inflation', 's&p', 'index', 'price']):
                    details['finance_count'] += 1
                # Sports (game-related)
                elif any(k in combined for k in ['nba', 'nfl', 'nhl', 'mlb', 'soccer', 'points', 'yards', 'goals', 'scored', 'win by', 'over', 'under']) or ' yes ' in combined:
                    details['sports_count'] += 1
                
                # Check for climate markets
                if any(word in combined for word in ['temperature', 'climate', 'degrees', 'celsius', 'fahrenheit', 'heat', 'rain', 'snow', 'weather', 'storm']):
                    details['climate_markets_found'] += 1
                
                # Check for weather markets (specific to our cities)
                if any(word in title for word in weather_keywords):
                    # Check if it's for one of our monitored cities
                    if any(city in title for city in cities):
                        weather_markets.append(market)
                
                # Check for temperature markets (series like KXHIGHNY)
                if 'high temp' in title or 'low temp' in title or 'highest temperature' in title or 'lowest temperature' in title:
                    if any(city in title for city in ['new york', 'nyc', 'los angeles', 'la', 'chicago', 'london']):
                        weather_markets.append(market)
            
            # Filter markets: analyze with reasonable volume and within next 7 days
            filtered_markets = []
            for m in weather_markets:
                # Check volume - be more lenient for testing
                volume = m.get('volume', 0)
                if volume < 100:  # Lower threshold from 500 to 100
                    continue
                
                # Check date - analyze next 7 days (extended from 5)
                ticker = m.get('ticker', '')
                import re
                date_match = re.search(r'-26([A-Z]{3})(\d{2})-', ticker)
                if date_match:
                    month_str = date_match.group(1)
                    day_str = date_match.group(2)
                    months = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                             'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
                    month_num = months.get(month_str, 1)
                    market_date = datetime(2026, month_num, int(day_str))
                    days_until = (market_date - datetime.now()).days
                    
                    if days_until > 7 or days_until < 0:  # Extended to 7 days
                        continue
                else:
                    # If no date in ticker, include it (for testing)
                    pass
                
                filtered_markets.append(m)
            
            details['weather_markets_found'] = len(filtered_markets)
            logger.info(f"   🌦️  Found {len(weather_markets)} weather markets, analyzing {len(filtered_markets)} (filtered by volume/date)")
            
            # Analyze each filtered weather market
            for i, market in enumerate(filtered_markets, 1):
                ticker = market.get('ticker', '')
                title = market.get('title', '')
                
                logger.info(f"   [{i}/{len(filtered_markets)}] Analyzing: {ticker}")
                
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
        """Analyze a Kalshi weather/temperature market with real weather data"""
        ticker = market.get('ticker', '')
        title = market.get('title', '')
        
        # Parse location from title
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
        
        # Fetch weather data (now uses SQLite cache)
        weather_data = await self._fetch_weather(city_name, city_coords[0], city_coords[1])
        
        if not weather_data:
            return None
        
        # Get temperature data
        daily = weather_data.get('daily', {})
        dates = daily.get('time', [])
        max_temps = daily.get('temperature_2m_max', [])
        min_temps = daily.get('temperature_2m_min', [])
        
        if not max_temps or len(max_temps) < 2:
            return None
        
        # Parse date from ticker (e.g., KXHIGHNY-26FEB02-T36 -> 2026-02-02)
        forecast_max = None
        forecast_min = None
        target_date = None
        
        import re
        date_match = re.search(r'-26([A-Z]{3})(\d{2})-', ticker)
        if date_match:
            month_str = date_match.group(1)
            day_str = date_match.group(2)
            
            # Convert month abbreviation to number
            months = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                     'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
            month_num = months.get(month_str, 1)
            
            # Find matching date in forecast
            target_date = f"2026-{month_num:02d}-{day_str}"
            
            for i, date in enumerate(dates):
                if date == target_date:
                    if i < len(max_temps):
                        forecast_max = max_temps[i]
                        forecast_min = min_temps[i] if i < len(min_temps) else forecast_max - 10
                        break
        
        # Fallback to tomorrow if date not found
        if forecast_max is None:
            forecast_max = max_temps[1] if len(max_temps) > 1 else max_temps[0]
            forecast_min = min_temps[1] if len(min_temps) > 1 else forecast_max - 10
            target_date = dates[1] if len(dates) > 1 else dates[0]
        
        # Determine if this is a temperature market or rain market
        is_temp_market = 'temp' in title_lower or 'temperature' in title_lower or 'high' in ticker.lower()
        
        if is_temp_market:
            # Parse temperature threshold from market title
            # Examples: 
            # "Will the **high temp in NYC** be >36°"
            # "Will the **high temp in NYC** be <29°"
            # "Will the **high temp in NYC** be 28-29°"
            
            our_probability = None
            market_threshold = None
            market_type = None  # 'above', 'below', 'range'
            
            # Try to parse threshold from title
            import re
            
            # Check for range (e.g., "28-29°" or "13-14°" or "15-16°")
            # Try multiple patterns
            range_match = None
            
            # Pattern 1: "be 28-29°" or "be 13-14°"
            range_match = re.search(r'be\s+(\d+)[-\u2013]\s*(\d+)', title)
            
            # Pattern 2: "be 13 to 14°"
            if not range_match:
                range_match = re.search(r'be\s+(\d+)\s+to\s+(\d+)', title)
            
            if range_match:
                low_temp = int(range_match.group(1))
                high_temp = int(range_match.group(2))
                market_threshold = (low_temp, high_temp)
                market_type = 'range'
                # Probability that temp falls in this range
                # Simple model: if forecast is in range, high prob
                if low_temp <= forecast_max <= high_temp:
                    our_probability = 0.85  # Forecast says it's in range
                else:
                    our_probability = 0.15  # Forecast says it's outside
            else:
                # Check for > or < threshold
                above_match = re.search(r'>\s*(\d+)', title)
                below_match = re.search(r'<\s*(\d+)', title)
                
                if above_match:
                    market_threshold = int(above_match.group(1))
                    market_type = 'above'
                    # Probability temp > threshold
                    if forecast_max > market_threshold:
                        our_probability = 0.80
                    elif forecast_max < market_threshold - 3:
                        our_probability = 0.10
                    else:
                        our_probability = 0.50  # Uncertain
                        
                elif below_match:
                    market_threshold = int(below_match.group(1))
                    market_type = 'below'
                    # Probability temp < threshold  
                    if forecast_max < market_threshold:
                        our_probability = 0.80
                    elif forecast_max > market_threshold + 3:
                        our_probability = 0.10
                    else:
                        our_probability = 0.50  # Uncertain
            
            if our_probability is None:
                logger.warning(f"Could not parse temperature threshold from: {title}")
                return None
                
            logger.info(f"      📊 Temp forecast for {target_date}: {forecast_max}°F (threshold: {market_threshold}, type: {market_type})")
            
        else:
            # Rain market - use weather code
            weather_codes = daily.get('weathercode', [])
            precipitation = daily.get('precipitation_sum', [])
            
            if not weather_codes or len(weather_codes) < 2:
                return None
            
            tomorrow_code = weather_codes[1]
            tomorrow_rain = precipitation[1] if len(precipitation) > 1 else 0
            our_probability = self._weather_code_to_rain_prob(tomorrow_code, tomorrow_rain)
            market_threshold = None
            market_type = 'rain'
        
        # Get actual market price from Kalshi
        market_probability = None
        price_source = "unknown"
        
        try:
            orderbook = client.get_orderbook(ticker)
            
            if orderbook:
                yes_bids = orderbook.get('yes', [])
                yes_asks = orderbook.get('no', [])
                
                best_bid = yes_bids[0].get('price', 0) / 100 if yes_bids else 0
                no_ask = yes_asks[0].get('price', 0) if yes_asks else 0
                best_ask = (100 - no_ask) / 100 if no_ask > 0 else 0
                
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
        
        # Calculate expected value for BINARY market
        # EV = (Win_Prob × (1 - Price)) - (Lose_Prob × Price)
        if market_probability > 0:
            win_prob = our_probability
            lose_prob = 1 - win_prob
            price = market_probability
            
            expected_value = (win_prob * (1 - price)) - (lose_prob * price)
        else:
            expected_value = 0
        
        # Create opportunity
        opp = {
            'market': title,
            'ticker': ticker,
            'platform': 'kalshi',
            'our_probability': our_probability,
            'market_probability': market_probability,
            'expected_value': expected_value,
            'odds': 1 / market_probability if market_probability > 0 else 0,
            'data_source': 'open-meteo',
            'confidence': 0.85 if is_temp_market else 0.90,
            'category': 'weather',
            'subcategory': 'temperature' if is_temp_market else 'rain',
            'city': city_name,
            'temp_forecast': forecast_max if is_temp_market else None,
            'temp_threshold': market_threshold,
            'market_type': market_type,
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
            weather_data = await self._fetch_weather(city['name'], city['lat'], city['lon'])
            
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
    
    async def _fetch_weather(self, city: str, lat: float, lon: float) -> Optional[Dict]:
        """Fetch weather forecast using OpenWeather API"""
        # Initialize WeatherAPI on first call
        if not hasattr(self, '_weather_api'):
            import subprocess
            result = subprocess.run(
                ['pass', 'show', 'openweather/api-key'],
                capture_output=True, text=True
            )
            api_key = result.stdout.strip().splitlines()[0]
            self._weather_api = WeatherAPI(api_key)
        
        return await self._weather_api.fetch_forecast(city, lat, lon)
    
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
