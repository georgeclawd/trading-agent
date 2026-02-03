#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')

from kalshi_client import KalshiClient
import subprocess
from datetime import datetime, timezone

# Load Kalshi credentials from pass
result = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], capture_output=True, text=True)
api_key_id = result.stdout.strip()

result = subprocess.run(['pass', 'show', 'kalshi/api_key'], capture_output=True, text=True)
api_key = result.stdout.strip()

client = KalshiClient(api_key_id, api_key, demo=False)

print("=== ALL 15M markets ===")
for series in ['KXBTC15M', 'KXETH15M', 'KSOL15M']:
    try:
        markets = client.get_markets(series_ticker=series, limit=20)
        print(f"\n{series}: {len(markets)} markets")
        for m in markets:
            ticker = m.get('ticker', 'N/A')
            status = m.get('status', 'N/A')
            close = m.get('close_time', 'N/A')
            print(f"  {ticker} ({status}) closes: {close}")
    except Exception as e:
        print(f"{series}: Error - {e}")

print("\n\n=== What we need to map to ===")
print("Polymarket: btc-updown-15m-1770159600 (timestamp)")
print("Timestamp 1770159600 = 2026-02-03 18:00 EST")
print("Kalshi has: KXBTC15M-26FEB031815-15 (1815, not 1800!)")
print("")
print("The 1800 market might be closed, 1815 is the next active one!")
