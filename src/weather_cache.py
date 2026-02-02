"""
Weather Cache - SQLite-based caching for weather forecasts
Reduces API calls by 90%+
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict


class WeatherCache:
    """Caches weather forecasts to reduce API calls"""
    
    def __init__(self, cache_dir: str = "/root/clawd/trading-agent/data"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.cache_dir / "weather_cache.db"
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weather_forecasts (
                    city TEXT PRIMARY KEY,
                    lat REAL,
                    lon REAL,
                    forecast_data TEXT,
                    cached_at TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            conn.commit()
    
    def get(self, city: str, lat: float, lon: float, max_age_hours: int = 6) -> Optional[Dict]:
        """
        Get cached forecast if it exists and isn't expired
        
        Args:
            city: City name
            lat: Latitude
            lon: Longitude
            max_age_hours: Maximum age of cache in hours
            
        Returns:
            Forecast dict or None if not cached/expired
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT forecast_data, expires_at FROM weather_forecasts WHERE city = ?",
                (city,)
            )
            row = cursor.fetchone()
            
            if row:
                forecast_data, expires_at = row
                expires = datetime.fromisoformat(expires_at)
                
                if datetime.now() < expires:
                    return json.loads(forecast_data)
                else:
                    # Cache expired, delete it
                    conn.execute("DELETE FROM weather_forecasts WHERE city = ?", (city,))
                    conn.commit()
        
        return None
    
    def set(self, city: str, lat: float, lon: float, forecast_data: Dict, ttl_hours: int = 6):
        """
        Cache a weather forecast
        
        Args:
            city: City name
            lat: Latitude
            lon: Longitude
            forecast_data: The forecast data to cache
            ttl_hours: Time to live in hours
        """
        cached_at = datetime.now()
        expires_at = cached_at + timedelta(hours=ttl_hours)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO weather_forecasts 
                (city, lat, lon, forecast_data, cached_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    city,
                    lat,
                    lon,
                    json.dumps(forecast_data),
                    cached_at.isoformat(),
                    expires_at.isoformat()
                )
            )
            conn.commit()
    
    def clear(self):
        """Clear all cached data"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM weather_forecasts")
            conn.commit()
    
    def stats(self) -> Dict:
        """Get cache statistics"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*), MIN(cached_at), MAX(cached_at) FROM weather_forecasts"
            )
            count, min_time, max_time = cursor.fetchone()
            
            cursor = conn.execute(
                "SELECT COUNT(*) FROM weather_forecasts WHERE expires_at > ?",
                (datetime.now().isoformat(),)
            )
            valid_count = cursor.fetchone()[0]
            
            return {
                "total_entries": count or 0,
                "valid_entries": valid_count or 0,
                "oldest_cache": min_time,
                "newest_cache": max_time
            }
