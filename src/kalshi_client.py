"""
Kalshi API Integration - Simple REST API client
Much easier than Polymarket US (no Ed25519 signatures!)
"""

import requests
import json
import time
from typing import Dict, List, Optional
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import base64


class KalshiClient:
    """
    Kalshi Exchange API Client
    
    Kalshi is CFTC regulated, fully legal in US
    Simple API key authentication (unlike Polymarket's complex signatures)
    """
    
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
    
    def __init__(self, api_key_id: str, api_key: str):
        self.api_key_id = api_key_id
        self.api_key = api_key
        self.token = None  # Will be set after auth
        
    def authenticate(self) -> bool:
        """
        Authenticate with Kalshi API
        
        Kalshi uses API keys with Bearer token auth (much simpler!)
        """
        try:
            # Test auth by fetching user data
            response = self._request("GET", "/exchange/user")
            
            if response.status_code == 200:
                self.token = self.api_key  # Kalshi uses API key as Bearer token
                print("✅ Kalshi authentication successful")
                return True
            else:
                print(f"❌ Kalshi auth failed: {response.status_code}")
                print(response.text)
                return False
                
        except Exception as e:
            print(f"❌ Kalshi auth error: {e}")
            return False
    
    def _create_signature(self, timestamp: str, method: str, path: str) -> str:
        """Create RSA signature for Kalshi authentication"""
        import base64
        
        # Message to sign: timestamp + method + path
        message = f"{timestamp}{method}{path}"
        
        # Ensure proper newlines in key
        key_data = self.api_key
        if '\\n' in key_data:
            key_data = key_data.replace('\\n', '\n')
        
        # Load private key
        private_key = serialization.load_pem_private_key(
            key_data.encode(),
            password=None
        )
        
        # Sign with RSA-SHA256
        signature = private_key.sign(
            message.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        
        return base64.b64encode(signature).decode()
    
    def _request(self, method: str, endpoint: str, data: Dict = None) -> requests.Response:
        """Make authenticated request to Kalshi API"""
        import time
        
        url = f"{self.BASE_URL}{endpoint}"
        
        # Create timestamp (milliseconds)
        timestamp = str(int(time.time() * 1000))
        
        # Create signature
        try:
            signature = self._create_signature(timestamp, method, endpoint)
        except Exception as e:
            print(f"Signature creation failed: {e}")
            # Fallback to simple request for public endpoints
            signature = ""
        
        headers = {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp
        }
        
        try:
            if method == "GET":
                return requests.get(url, headers=headers, timeout=30)
            elif method == "POST":
                return requests.post(url, headers=headers, json=data, timeout=30)
            elif method == "DELETE":
                return requests.delete(url, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
        except Exception as e:
            print(f"Request error: {e}")
            raise
    
    def get_markets(self, status: str = "open", limit: int = 100) -> List[Dict]:
        """
        Get list of available markets
        
        Categories: weather, crypto, sports, politics, economics
        """
        try:
            response = self._request("GET", f"/markets?status={status}&limit={limit}")
            
            if response.status_code == 200:
                data = response.json()
                markets = data.get("markets", [])
                print(f"[Kalshi] Retrieved {len(markets)} markets (status={status})")
                return markets
            else:
                print(f"[Kalshi] Error fetching markets: {response.status_code}")
                print(f"[Kalshi] Response: {response.text[:200]}")
                return []
                
        except Exception as e:
            print(f"[Kalshi] Error getting markets: {e}")
            return []
    
    def get_market(self, market_id: str) -> Optional[Dict]:
        """Get specific market details"""
        try:
            response = self._request("GET", f"/markets/{market_id}")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error fetching market {market_id}: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Error getting market: {e}")
            return None
    
    def get_orderbook(self, market_id: str) -> Optional[Dict]:
        """
        Get orderbook for a market
        
        Returns bids (NO) and asks (YES) with prices
        """
        try:
            response = self._request("GET", f"/markets/{market_id}/orderbook")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error fetching orderbook: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"Error getting orderbook: {e}")
            return None
    
    def place_order(self, market_id: str, side: str, price: float, 
                   count: int, expiration_ts: int = None) -> Dict:
        """
        Place an order on Kalshi
        
        Args:
            market_id: Market ticker (e.g., "WEATH-NYC-20250202-RAIN")
            side: "yes" or "no"
            price: Price in cents (0-100)
            count: Number of contracts
            expiration_ts: Unix timestamp for order expiration (optional)
        
        Returns:
            Order result with order_id
        """
        data = {
            "ticker": market_id,
            "side": side,
            "price": price,
            "count": count,
        }
        
        if expiration_ts:
            data["expiration_ts"] = expiration_ts
        
        try:
            response = self._request("POST", "/orders", data)
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Order placed: {result.get('order_id')}")
                return {
                    "success": True,
                    "order_id": result.get("order_id"),
                    "market": market_id,
                    "side": side,
                    "price": price,
                    "count": count
                }
            else:
                error_msg = response.json().get("error", "Unknown error")
                print(f"❌ Order failed: {error_msg}")
                return {
                    "success": False,
                    "error": error_msg
                }
                
        except Exception as e:
            print(f"❌ Order error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order"""
        try:
            response = self._request("DELETE", f"/orders/{order_id}")
            return response.status_code == 200
        except Exception as e:
            print(f"Cancel error: {e}")
            return False
    
    def get_positions(self) -> List[Dict]:
        """Get current portfolio positions"""
        try:
            response = self._request("GET", "/portfolio/positions")
            
            if response.status_code == 200:
                data = response.json()
                return data.get("positions", [])
            else:
                print(f"Error fetching positions: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"Error getting positions: {e}")
            return []
    
    def get_balance(self) -> Dict:
        """Get account balance"""
        try:
            response = self._request("GET", "/portfolio/balance")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error fetching balance: {response.status_code}")
                return {}
                
        except Exception as e:
            print(f"Error getting balance: {e}")
            return {}
    
    def get_orders(self, status: str = "open") -> List[Dict]:
        """Get open orders"""
        try:
            response = self._request("GET", f"/orders?status={status}")
            
            if response.status_code == 200:
                data = response.json()
                return data.get("orders", [])
            else:
                return []
                
        except Exception as e:
            print(f"Error getting orders: {e}")
            return []


class KalshiMarketFinder:
    """Helper to find matching markets between Kalshi and Polymarket"""
    
    def __init__(self, kalshi_client: KalshiClient):
        self.kalshi = kalshi_client
        self.market_cache = {}
    
    def search_weather_markets(self, city: str = None) -> List[Dict]:
        """Find weather prediction markets"""
        markets = self.kalshi.get_markets(status="open")
        
        weather_markets = []
        for market in markets:
            ticker = market.get("ticker", "")
            title = market.get("title", "").lower()
            
            # Filter for weather markets
            if "rain" in title or "temp" in title or "weather" in title:
                if city and city.lower() in title:
                    weather_markets.append(market)
                elif not city:
                    weather_markets.append(market)
        
        return weather_markets
    
    def search_crypto_markets(self, symbol: str = None) -> List[Dict]:
        """Find crypto price markets"""
        markets = self.kalshi.get_markets(status="open")
        
        crypto_markets = []
        for market in markets:
            ticker = market.get("ticker", "")
            title = market.get("title", "").lower()
            
            if symbol and symbol.lower() in title:
                crypto_markets.append(market)
            elif any(x in title for x in ["bitcoin", "btc", "eth", "ethereum"]):
                crypto_markets.append(market)
        
        return crypto_markets
    
    def find_matching_market(self, polymarket_event: str) -> Optional[Dict]:
        """
        Find a Kalshi market matching a Polymarket event
        
        This is the key function for cross-platform arbitrage
        """
        # TODO: Implement semantic matching
        # Normalize both event texts and compare
        return None
