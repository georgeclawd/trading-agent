"""
Kalshi API Integration - Based on official docs
https://docs.kalshi.com/getting_started/quick_start_authenticated_requests
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
    
    Auth: RSA-PSS-SHA256 signatures (per official docs)
    """
    
    BASE_URL = "https://api.elections.kalshi.com"
    DEMO_URL = "https://demo-api.kalshi.co"
    API_PREFIX = "/trade-api/v2"
    
    def __init__(self, api_key_id: str, api_key: str, demo: bool = False):
        self.api_key_id = api_key_id
        self.api_key = api_key
        self.demo = demo
        self.base_url = self.DEMO_URL if demo else self.BASE_URL
        self._session = requests.Session()
        self._private_key = None
        self._load_private_key()
    
    def _load_private_key(self):
        """Load and format the private key"""
        key_data = self.api_key
        
        # Handle escaped newlines
        if '\\n' in key_data:
            key_data = key_data.replace('\\n', '\n')
        
        # Fix one-line PEM format (add newlines every 64 chars)
        if '-----BEGIN' in key_data and key_data.count('\n') <= 2:
            # Extract base64 content
            start = key_data.find('-----BEGIN RSA PRIVATE KEY-----') + len('-----BEGIN RSA PRIVATE KEY-----')
            end = key_data.find('-----END RSA PRIVATE KEY-----')
            if start > 0 and end > start:
                base64_content = key_data[start:end].strip()
                # Add newlines every 64 characters
                lines = [base64_content[i:i+64] for i in range(0, len(base64_content), 64)]
                key_data = '-----BEGIN RSA PRIVATE KEY-----\n' + '\n'.join(lines) + '\n-----END RSA PRIVATE KEY-----'
        
        self._private_key = serialization.load_pem_private_key(key_data.encode(), password=None)
    
    def _create_signature(self, timestamp: str, method: str, path: str) -> str:
        """
        Create RSA-PSS-SHA256 signature per Kalshi docs
        
        Message: timestamp + METHOD + path (no query params)
        Algorithm: RSA-PSS with SHA256, MGF1, PSS.DIGEST_LENGTH salt
        """
        # Strip query parameters from path before signing
        path_without_query = path.split('?')[0]
        
        # Create message: timestamp + METHOD + path
        message = f"{timestamp}{method.upper()}{path_without_query}".encode('utf-8')
        
        # Sign with RSA-PSS-SHA256 (per official docs)
        signature = self._private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        
        return base64.b64encode(signature).decode('utf-8')
    
    def _request(self, method: str, endpoint: str, data: Dict = None) -> requests.Response:
        """Make authenticated request"""
        # Full path includes API_PREFIX for signature
        full_path = f"{self.API_PREFIX}{endpoint}"
        url = f"{self.base_url}{full_path}"
        
        timestamp = str(int(time.time() * 1000))
        signature = self._create_signature(timestamp, method, full_path)
        
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
        """Test API connection"""
        try:
            response = self._request("GET", "/portfolio/balance")
            if response.status_code == 200:
                data = response.json()
                print(f"[Kalshi] Connected! Balance: ${data.get('balance', 0)/100:.2f}")
                return True
            else:
                print(f"[Kalshi] Connection failed: {response.status_code} - {response.text[:200]}")
                return False
        except Exception as e:
            print(f"[Kalshi] Connection error: {e}")
            return False
    
    def get_markets(self, series_ticker: str = None, status: str = "open", limit: int = 100) -> List[Dict]:
        """Get markets"""
        try:
            endpoint = f"/markets?status={status}&limit={limit}"
            if series_ticker:
                endpoint += f"&series_ticker={series_ticker}"
            
            response = self._request("GET", endpoint)
            if response.status_code == 200:
                return response.json().get("markets", [])
            return []
        except Exception as e:
            print(f"[Kalshi] Error getting markets: {e}")
            return []
    
    def get_orderbook(self, market_id: str) -> Optional[Dict]:
        """Get orderbook"""
        try:
            response = self._request("GET", f"/markets/{market_id}/orderbook")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            print(f"[Kalshi] Error getting orderbook: {e}")
            return None
    
    def place_order(self, market_id: str, side: str, price: float, count: int) -> Dict:
        """Place a limit order per Kalshi API docs"""
        import uuid
        
        data = {
            "ticker": market_id,
            "action": "buy",
            "side": side.lower(),
            "count": int(count),
            "type": "limit",
            "client_order_id": str(uuid.uuid4())
        }
        
        # Price field depends on side
        if side.lower() == "yes":
            data["yes_price"] = int(price)
        else:
            data["no_price"] = int(price)
        
        try:
            response = self._request("POST", "/portfolio/orders", data)
            
            if response.status_code == 201:  # Created
                result = response.json()
                return {
                    "success": True,
                    "order_id": result.get("order", {}).get("order_id"),
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
            return {"success": False, "error": str(e)}
    
    def get_positions(self) -> List[Dict]:
        """Get positions"""
        try:
            response = self._request("GET", "/portfolio/positions")
            if response.status_code == 200:
                return response.json().get("positions", [])
            return []
        except Exception as e:
            return []
    
    def get_balance(self) -> Optional[Dict]:
        """Get balance"""
        try:
            response = self._request("GET", "/portfolio/balance")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception as e:
            return None
