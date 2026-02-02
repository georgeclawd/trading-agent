"""
Kalshi API Integration - Simplified REST API client
Based on Kalshi Trade API v2 documentation
"""

import requests
import json
import time
import base64
from typing import Dict, List, Optional
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


class KalshiClient:
    """
    Kalshi Exchange API Client
    
    Authentication: RSA-SHA256 signatures
    - KALSHI-ACCESS-KEY: Your API key ID
    - KALSHI-ACCESS-SIGNATURE: RSA-SHA256 signature
    - KALSHI-ACCESS-TIMESTAMP: Unix timestamp in milliseconds
    """
    
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    
    def __init__(self, api_key_id: str, api_key: str):
        self.api_key_id = api_key_id
        self.api_key = api_key
        self._session = requests.Session()
        
    def _create_signature(self, timestamp: str, method: str, path: str) -> str:
        """Create RSA signature for Kalshi authentication
        
        Message format: timestamp + method + path (no spaces, no base URL)
        Example: 1706886000000GET/markets
        """
        # Message to sign: timestamp + method + path
        # Ensure path starts with /
        if not path.startswith('/'):
            path = '/' + path
        message = f"{timestamp}{method.upper()}{path}"
        
        # Clean up key format
        key_data = self.api_key
        if '\\n' in key_data:
            key_data = key_data.replace('\\n', '\n')
        
        # Fix PEM format - needs newlines every 64 characters
        if '-----BEGIN' in key_data and '\n' not in key_data:
            # Key is all on one line, needs reformatting
            start = key_data.find('-----BEGIN RSA PRIVATE KEY-----') + len('-----BEGIN RSA PRIVATE KEY-----')
            end = key_data.find('-----END RSA PRIVATE KEY-----')
            if start > 0 and end > start:
                base64_content = key_data[start:end]
                lines = [base64_content[i:i+64] for i in range(0, len(base64_content), 64)]
                key_data = '-----BEGIN RSA PRIVATE KEY-----\n' + '\n'.join(lines) + '\n-----END RSA PRIVATE KEY-----'
        
        try:
            # Load private key
            private_key = serialization.load_pem_private_key(
                key_data.encode(),
                password=None
            )
            
            # Sign with RSA-SHA256 using PKCS1v15 padding
            signature = private_key.sign(
                message.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            
            return base64.b64encode(signature).decode()
        except Exception as e:
            print(f"[Kalshi] Signature creation failed: {e}")
            raise
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> requests.Response:
        """Make authenticated request to Kalshi API"""
        url = f"{self.BASE_URL}{endpoint}"
        timestamp = str(int(time.time() * 1000))
        
        try:
            signature = self._create_signature(timestamp, method, endpoint)
        except Exception as e:
            print(f"[Kalshi] Failed to create signature: {e}")
            raise
        
        headers = {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp
        }
        
        if method == "GET":
            return self._session.get(url, headers=headers, timeout=30)
        elif method == "POST":
            return self._session.post(url, headers=headers, json=data, timeout=30)
        elif method == "DELETE":
            return self._session.delete(url, headers=headers, timeout=30)
        else:
            raise ValueError(f"Unsupported method: {method}")
    
    def test_connection(self) -> bool:
        """Test API connection by fetching markets"""
        try:
            response = self._make_request("GET", "/markets?limit=1")
            print(f"[Kalshi] Test connection: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"[Kalshi] Connected! Found {len(data.get('markets', []))} markets")
                return True
            else:
                print(f"[Kalshi] Connection failed: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"[Kalshi] Connection error: {e}")
            return False
    
    def get_markets(self, status: str = "open", limit: int = 100) -> List[Dict]:
        """Get list of available markets"""
        try:
            response = self._make_request("GET", f"/markets?status={status}&limit={limit}")
            if response.status_code == 200:
                return response.json().get("markets", [])
            return []
        except Exception as e:
            print(f"[Kalshi] Error getting markets: {e}")
            return []
    
    def get_orderbook(self, market_id: str) -> Optional[Dict]:
        """Get orderbook for a market"""
        try:
            response = self._make_request("GET", f"/markets/{market_id}/orderbook")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"[Kalshi] Error getting orderbook: {e}")
            return None
    
    def place_order(self, market_id: str, side: str, price: float, 
                   count: int, expiration_ts: int = None) -> Dict:
        """
        Place an order on Kalshi
        
        Args:
            market_id: Market ticker
            side: "yes" or "no"
            price: Price in cents (1-99)
            count: Number of contracts
        """
        data = {
            "ticker": market_id,
            "side": side.lower(),
            "price": int(price),
            "count": int(count)
        }
        
        if expiration_ts:
            data["expiration_ts"] = expiration_ts
        
        try:
            # Try the correct endpoint
            response = self._make_request("POST", "/portfolio/orders", data)
            
            print(f"[Kalshi] Order response: {response.status_code}")
            if response.text:
                print(f"[Kalshi] Response body: {response.text[:300]}")
            
            if response.status_code == 200:
                result = response.json()
                return {
                    "success": True,
                    "order_id": result.get("order_id"),
                    "market": market_id,
                    "side": side,
                    "price": price,
                    "count": count
                }
            else:
                return {
                    "success": False,
                    "error": response.text[:200] if response.text else f"HTTP {response.status_code}",
                    "status_code": response.status_code
                }
                
        except Exception as e:
            print(f"[Kalshi] Order error: {e}")
            return {"success": False, "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get current portfolio positions"""
        try:
            response = self._make_request("GET", "/portfolio/positions")
            if response.status_code == 200:
                return response.json().get("positions", [])
            return []
        except Exception as e:
            print(f"[Kalshi] Error getting positions: {e}")
            return []
    
    def get_balance(self) -> Optional[Dict]:
        """Get account balance"""
        try:
            response = self._make_request("GET", "/portfolio/balance")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"[Kalshi] Error getting balance: {e}")
            return None
