#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')

from kalshi_client import KalshiClient
import subprocess

# Load credentials
result = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], capture_output=True, text=True)
api_key_id = result.stdout.strip()
result = subprocess.run(['pass', 'show', 'kalshi/api_key'], capture_output=True, text=True)
api_key = result.stdout.strip()

client = KalshiClient(api_key_id, api_key, demo=False)

# Check specific tickers
print("=== CHECKING SPECIFIC TICKERS ===")
tickers = [
    'KXETH15M-26FEB031815',
    'KXETH15M-26FEB031830-30',
    'KXETH15M-26FEB031830',
    'KXBTC15M-26FEB031830-30',
]

for ticker in tickers:
    try:
        ob = client.get_orderbook(ticker)
        if ob:
            print(f"{ticker}: FOUND")
        else:
            print(f"{ticker}: NOT FOUND")
    except Exception as e:
        print(f"{ticker}: ERROR - {e}")
