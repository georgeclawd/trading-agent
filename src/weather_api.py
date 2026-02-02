"""
Weather API - OpenWeather integration
Replaces Open-Meteo to avoid rate limiting
"""

import aiohttp
import asyncio
from typing import Dict, Optional
from weather_cache import WeatherCache


class WeatherAPI:
    """
    OpenWeather API client
    Free tier: 60 calls/minute, 1,000,000 calls/month
    """
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openweathermap.org/data/2.5"
        self.cache = WeatherCache()
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def fetch_forecast(self, city: str, lat: float, lon: float) -> Optional[Dict]:
        """
        Fetch 5-day forecast from OpenWeather
        
        Returns data in similar format to Open-Meteo for compatibility
        """
        # Check cache first
        cached = self.cache.get(city, lat, lon, max_age_hours=6)
        if cached:
            return cached
        
        session = await self._get_session()
        
        try:
            # OpenWeather 5-day forecast API
            url = (
                f"{self.base_url}/forecast?"
                f"lat={lat}&lon={lon}&appid={self.api_key}&units=imperial"
            )
            
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Convert OpenWeather format to match Open-Meteo structure
                    formatted = self._format_openweather_data(data)
                    
                    # Cache the result
                    self.cache.set(city, lat, lon, formatted, ttl_hours=6)
                    return formatted
                elif response.status == 429:
                    print(f"OpenWeather rate limited, waiting...")
                    await asyncio.sleep(1)
                    return None
                else:
                    print(f"OpenWeather API error: {response.status}")
                    return None
                    
        except Exception as e:
            print(f"Weather fetch error: {e}")
            return None
    
    def _format_openweather_data(self, data: Dict) -> Dict:
        """
        Convert OpenWeather format to match Open-Meteo structure
        for compatibility with existing code
        """
        # Extract daily forecasts (OpenWeather returns 3-hour intervals)
        # Group by date and take max temp
        from collections import defaultdict
        from datetime import datetime
        
        daily_data = defaultdict(lambda: {'temps': [], 'weather': []})
        
        for item in data.get('list', []):
            dt = datetime.fromtimestamp(item['dt'])
            date_str = dt.strftime('%Y-%m-%d')
            
            daily_data[date_str]['temps'].append(item['main']['temp_max'])
            daily_data[date_str]['temps'].append(item['main']['temp_min'])
            daily_data[date_str]['weather'].append(item['weather'][0]['id'] if item['weather'] else 800)
        
        # Format to match Open-Meteo
        dates = sorted(daily_data.keys())
        max_temps = [max(daily_data[d]['temps']) for d in dates]
        min_temps = [min(daily_data[d]['temps']) for d in dates]
        weather_codes = [daily_data[d]['weather'][0] for d in dates]
        
        return {
            'daily': {
                'time': dates,
                'temperature_2m_max': max_temps,
                'temperature_2m_min': min_temps,
                'weathercode': weather_codes,
                'precipitation_sum': [0.0] * len(dates)  # OpenWeather doesn't include this easily
            }
        }
    
    async def close(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()
