#!/usr/bin/env python3
"""
End-to-end test for Trading Agent
Verifies weather API, Kalshi API, and opportunity detection
"""

import asyncio
import sys
sys.path.insert(0, '/root/clawd/trading-agent/src')

from market_scanner import MarketScanner

async def test_full_pipeline():
    """Test the complete pipeline"""
    print("="*70)
    print("🧪 TESTING TRADING AGENT PIPELINE")
    print("="*70)
    
    config = {
        'min_ev_threshold': 0.05,
        'max_daily_trades': 5,
    }
    
    scanner = MarketScanner(config)
    
    # Test 1: Weather API
    print("\n1️⃣  Testing Weather API...")
    async with scanner:
        weather = await scanner._fetch_weather(40.7128, -74.0060)
        if weather:
            print("   ✅ Weather API working")
            daily = weather.get('daily', {})
            codes = daily.get('weathercode', [])
            rain = daily.get('precipitation_sum', [])
            print(f"   NYC Weather Code: {codes[1] if len(codes) > 1 else 'N/A'}")
            print(f"   NYC Rain: {rain[1] if len(rain) > 1 else 'N/A'}mm")
        else:
            print("   ❌ Weather API failed")
    
    # Test 2: Full scan
    print("\n2️⃣  Testing Full Market Scan...")
    async with scanner:
        opps = await scanner.find_opportunities()
        print(f"   Found {len(opps)} opportunities")
    
    print("\n" + "="*70)
    print("✅ TEST COMPLETE")
    print("="*70)

if __name__ == '__main__':
    asyncio.run(test_full_pipeline())
