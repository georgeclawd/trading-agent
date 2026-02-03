#!/usr/bin/env python3
import sys
sys.path.insert(0, 'src')

from kalshi_client import KalshiClient
import subprocess
import json

# Load credentials
result = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], capture_output=True, text=True)
api_key_id = result.stdout.strip()
result = subprocess.run(['pass', 'show', 'kalshi/api_key'], capture_output=True, text=True)
api_key = result.stdout.strip()

client = KalshiClient(api_key_id, api_key, demo=False)

# Check orderbook structure
print("=== CHECKING ORDERBOOK STRUCTURE ===")

ticker = 'KXETH15M-26FEB031815'
ob = client.get_orderbook(ticker)

if ob:
    print(f"Orderbook keys: {list(ob.keys())}")
    print(f"\nFull orderbook (first 500 chars):")
    print(json.dumps(ob, indent=2)[:500])
else:
    print("No orderbook")
