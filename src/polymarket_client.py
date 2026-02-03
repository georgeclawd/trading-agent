"""
Polymarket CLOB API Client using official py-clob-client

Uses the official Polymarket client library for trading.
"""

import logging
from typing import Dict, List, Optional
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
import subprocess

logger = logging.getLogger('PolymarketClient')


class PolymarketClient:
    """
    Polymarket CLOB API Client using official library
    """
    
    CLOB_HOST = "https://clob.polymarket.com"
    
    def __init__(self):
        self.api_key = None
        self.api_secret = None
        self.passphrase = None
        self.client = None
        self._load_credentials()
        self._init_client()
    
    def _load_credentials(self):
        """Load credentials from pass"""
        try:
            self.api_key = subprocess.run(
                ['pass', 'show', 'polymarket/api_key'],
                capture_output=True, text=True
            ).stdout.strip().split('\n')[0]
            
            self.api_secret = subprocess.run(
                ['pass', 'show', 'polymarket/api_secret'],
                capture_output=True, text=True
            ).stdout.strip().split('\n')[0]
            
            self.passphrase = subprocess.run(
                ['pass', 'show', 'polymarket/passphrase'],
                capture_output=True, text=True
            ).stdout.strip().split('\n')[0]
            
            logger.info("✅ Loaded Polymarket credentials")
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
    
    def _init_client(self):
        """Initialize the CLOB client"""
        try:
            # Create API credentials
            creds = ApiCreds(
                api_key=self.api_key,
                api_secret=self.api_secret,
                api_passphrase=self.passphrase
            )
            
            # Initialize client
            self.client = ClobClient(self.CLOB_HOST, creds=creds)
            logger.info("✅ Polymarket CLOB client initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize client: {e}")
    
    def get_markets(self, active: bool = True) -> List[Dict]:
        """Get available markets"""
        try:
            if self.client:
                markets = self.client.get_markets()
                if active:
                    # Filter to only active markets
                    return [m for m in markets if m.get('active', False)]
                return markets
            return []
        except Exception as e:
            logger.error(f"Error getting markets: {e}")
            return []
    
    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """Get orderbook for a token"""
        try:
            if self.client:
                return self.client.get_order_book(token_id)
            return None
        except Exception as e:
            logger.error(f"Error getting orderbook: {e}")
            return None
    
    def get_balance(self) -> Dict:
        """Get USDC balance"""
        try:
            if self.client:
                # Get balance via API
                balance = self.client.get_balance()
                return {
                    'usdc_balance': balance,
                    'available': balance
                }
            return {}
        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return {}
    
    def place_order(self, token_id: str, side: str, size: float, price: float) -> Dict:
        """
        Place an order
        
        Args:
            token_id: The asset/token ID
            side: "BUY" or "SELL"
            size: Amount to trade
            price: Price (0-1)
        """
        try:
            if not self.client:
                return {"error": "Client not initialized"}
            
            # Create and place order
            from py_clob_client.clob_types import OrderArgs
            
            order_args = OrderArgs(
                price=price,
                size=size,
                side=side.lower(),
                token_id=token_id
            )
            
            # Create and sign order
            signed_order = self.client.create_order(order_args)
            
            # Post order
            result = self.client.post_order(signed_order)
            
            logger.info(f"✅ Order placed: {result.get('orderID', 'N/A')}")
            return result
            
        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return {"error": str(e)}
    
    def get_btc_15m_markets(self) -> List[Dict]:
        """Get BTC 15M markets"""
        markets = self.get_markets(active=True)
        btc_markets = []
        
        for m in markets:
            slug = m.get('market_slug', '').lower()
            if 'btc' in slug and '15m' in slug:
                btc_markets.append(m)
        
        return btc_markets


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    client = PolymarketClient()
    
    print("Testing Polymarket client...")
    print(f"API Key: {client.api_key[:10]}..." if client.api_key else "No API key")
    
    if client.client:
        # Get balance
        balance = client.get_balance()
        print(f"Balance: {balance}")
        
        # Get BTC markets
        print("\nFetching BTC 15M markets...")
        btc_markets = client.get_btc_15m_markets()
        print(f"Found {len(btc_markets)} BTC 15M markets")
        
        for m in btc_markets[:3]:
            print(f"  - {m.get('market_slug')}: {m.get('question', '')[:50]}...")
            
            # Get orderbook
            token_id = m.get('tokens', [{}])[0].get('token_id')
            if token_id:
                ob = client.get_orderbook(token_id)
                if ob:
                    bids = ob.get('bids', [])
                    asks = ob.get('asks', [])
                    print(f"    Bids: {len(bids)}, Asks: {len(asks)}")
    else:
        print("❌ Client not initialized - check credentials")
