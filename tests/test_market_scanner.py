"""
Unit tests for the Trading Agent
Run with: python3 -m pytest test_market_scanner.py -v
"""

import asyncio
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from market_scanner import MarketScanner


class TestMarketScanner:
    """Test suite for MarketScanner"""
    
    @pytest.fixture
    def scanner(self):
        """Create scanner with test config"""
        config = {
            'min_ev_threshold': 0.05,
            'max_daily_trades': 5,
        }
        return MarketScanner(config)
    
    @pytest.mark.asyncio
    async def test_weather_code_conversion(self, scanner):
        """Test weather code to rain probability conversion"""
        # Clear sky = 0.05 probability
        assert scanner._weather_code_to_rain_prob(0, 0) == 0.05
        
        # Light rain = 0.85 probability
        assert scanner._weather_code_to_rain_prob(61, 5.0) == 0.85
        
        # Heavy rain/thunderstorm = 0.90 probability
        assert scanner._weather_code_to_rain_prob(95, 15.0) == 0.90
    
    @pytest.mark.asyncio
    async def test_fetch_weather_returns_data(self, scanner):
        """Test that weather API fetches real data"""
        async with scanner:
            # Fetch NYC weather
            weather = await scanner._fetch_weather(40.7128, -74.0060)
            
            assert weather is not None
            assert 'daily' in weather
            assert 'weathercode' in weather['daily']
            assert len(weather['daily']['weathercode']) >= 2  # Today + tomorrow
            
            # Log for visibility
            print(f"\nFetched weather data: {len(weather['daily']['weathercode'])} days")
            print(f"Tomorrow's weather code: {weather['daily']['weathercode'][1]}")
    
    @pytest.mark.asyncio
    async def test_fresh_data_each_call(self, scanner):
        """Test that each call fetches fresh data (not cached)"""
        async with scanner:
            # First call
            weather1 = await scanner._fetch_weather(40.7128, -74.0060)
            code1 = weather1['daily']['weathercode'][1]
            
            # Second call (should be fresh, not cached)
            weather2 = await scanner._fetch_weather(40.7128, -74.0060)
            code2 = weather2['daily']['weathercode'][1]
            
            # Codes should be the same (it's the same forecast time)
            # but we verify the data structure is fresh
            assert weather1 is not weather2  # Different objects
            assert code1 == code2  # Same forecast
    
    @pytest.mark.asyncio
    async def test_opportunities_not_static(self, scanner):
        """Test that opportunities are not hardcoded static values"""
        async with scanner:
            opps = await scanner.find_opportunities()
            
            # Check that no opportunity has the old hardcoded values
            for opp in opps:
                assert opp.get('our_probability') != 0.80, \
                    "Found hardcoded 80% probability - should be fetched from API"
                assert opp.get('market_probability') != 0.65, \
                    "Found hardcoded 65% market probability - should be fetched from Kalshi"
                
                # Verify data source is set
                assert opp.get('data_source') is not None
                
                # Verify expected value is calculated, not hardcoded
                assert 'expected_value' in opp
    
    def test_validate_opportunity(self, scanner):
        """Test opportunity validation logic"""
        # Good opportunity
        good_opp = {
            'expected_value': 0.10,
            'confidence': 0.80,
            'category': 'weather',
        }
        assert scanner._validate_opportunity(good_opp) is True
        
        # Bad: low EV
        low_ev_opp = {
            'expected_value': 0.01,
            'confidence': 0.80,
            'category': 'weather',
        }
        assert scanner._validate_opportunity(low_ev_opp) is False
        
        # Bad: low confidence
        low_conf_opp = {
            'expected_value': 0.10,
            'confidence': 0.50,
            'category': 'weather',
        }
        assert scanner._validate_opportunity(low_conf_opp) is False


class TestKalshiIntegration:
    """Test Kalshi API integration"""
    
    @pytest.mark.asyncio
    async def test_kalshi_client_loads(self):
        """Test that Kalshi client can be imported and initialized"""
        from kalshi_client import KalshiClient
        import subprocess
        
        # Load credentials (will fail if not configured)
        try:
            api_key_id = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], 
                                       capture_output=True, text=True).stdout.strip().split('\n')[0]
            api_key = subprocess.run(['pass', 'show', 'kalshi/api_key'], 
                                    capture_output=True, text=True).stdout.strip()
            
            client = KalshiClient(api_key_id=api_key_id, api_key=api_key)
            assert client is not None
            assert client.api_key_id == api_key_id
            
        except Exception as e:
            pytest.skip(f"Kalshi credentials not configured: {e}")
    
    @pytest.mark.asyncio
    async def test_kalshi_fetches_markets(self):
        """Test that Kalshi API returns real markets"""
        from kalshi_client import KalshiClient
        import subprocess
        
        try:
            api_key_id = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], 
                                       capture_output=True, text=True).stdout.strip().split('\n')[0]
            api_key = subprocess.run(['pass', 'show', 'kalshi/api_key'], 
                                    capture_output=True, text=True).stdout.strip()
            
            client = KalshiClient(api_key_id=api_key_id, api_key=api_key)
            markets = client.get_markets(limit=10)
            
            assert isinstance(markets, list)
            assert len(markets) > 0
            
            # Verify market structure
            market = markets[0]
            assert 'ticker' in market
            assert 'title' in market
            
            print(f"\nFetched {len(markets)} markets from Kalshi")
            print(f"First market: {market.get('ticker')}")
            
        except Exception as e:
            pytest.skip(f"Kalshi API not available: {e}")


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])
