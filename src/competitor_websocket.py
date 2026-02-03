"""
Real-time competitor tracking via Polymarket WebSocket
Gets instant notifications when competitors trade

Based on: https://docs.polymarket.com/quickstart/websocket/WSS-Quickstart
"""

import asyncio
import json
import logging
import websockets
from typing import Dict, List, Callable, Optional
from datetime import datetime
import subprocess

logger = logging.getLogger('CompetitorWebSocket')


class PolymarketWebSocketTracker:
    """
    WebSocket connection to Polymarket for real-time competitor activity
    
    Uses the CLOB WebSocket endpoint with proper authentication:
    wss://ws-subscriptions-clob.polymarket.com/ws/market
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com"
    MARKET_CHANNEL = "market"
    USER_CHANNEL = "user"
    
    def __init__(self):
        self.competitors = self._load_competitors()
        self.competitor_addresses = {
            c['address'].lower(): c['name'] 
            for c in self.competitors 
            if c.get('address')
        }
        self.callbacks: List[Callable] = []
        self.ws = None
        self.running = False
        self.reconnect_delay = 5
        self.last_message_time = None
        self.auth = self._load_auth()
        
    def _load_auth(self) -> Optional[Dict]:
        """Load Polymarket API credentials from pass"""
        try:
            api_key = subprocess.run(
                ['pass', 'show', 'polymarket/api_key'],
                capture_output=True, text=True
            ).stdout.strip().split('\n')[0]
            
            api_secret = subprocess.run(
                ['pass', 'show', 'polymarket/api_secret'],
                capture_output=True, text=True
            ).stdout.strip().split('\n')[0]
            
            passphrase = subprocess.run(
                ['pass', 'show', 'polymarket/passphrase'],
                capture_output=True, text=True
            ).stdout.strip().split('\n')[0]
            
            return {
                "apiKey": api_key,
                "secret": api_secret,
                "passphrase": passphrase
            }
        except Exception as e:
            logger.error(f"Failed to load auth: {e}")
            return None
    
    def _load_competitors(self) -> List[Dict]:
        """Load competitor addresses"""
        import os
        filepath = '/root/clawd/trading-agent/data/competitor_profiles.json'
        
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
                return data.get('profiles', [])
        return []
    
    def on_trade(self, callback: Callable):
        """Register callback for trade notifications"""
        self.callbacks.append(callback)
    
    async def connect_market_channel(self):
        """Connect to market channel for trade notifications"""
        uri = f"{self.WS_URL}/ws/{self.MARKET_CHANNEL}"
        
        try:
            logger.info(f"🔌 Connecting to Polymarket Market WebSocket: {uri}")
            
            async with websockets.connect(uri) as ws:
                self.ws = ws
                logger.info("✅ WebSocket connected")
                
                # Subscribe to market channel with auth
                # Get BTC 15M market asset IDs first
                asset_ids = await self._get_btc_market_asset_ids()
                
                subscribe_msg = {
                    "type": self.MARKET_CHANNEL,
                    "assets_ids": asset_ids if asset_ids else [],
                    "auth": self.auth
                }
                
                await ws.send(json.dumps(subscribe_msg))
                logger.info(f"📡 Subscribed to {len(asset_ids)} BTC markets")
                
                self.running = True
                self.last_message_time = datetime.now()
                
                # Start ping task
                ping_task = asyncio.create_task(self._ping(ws))
                
                try:
                    # Listen for messages
                    async for message in ws:
                        self.last_message_time = datetime.now()
                        await self._handle_message(message)
                finally:
                    ping_task.cancel()
                    try:
                        await ping_task
                    except asyncio.CancelledError:
                        pass
                    
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"⚠️  WebSocket closed: {e}")
            self.running = False
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
            self.running = False
    
    async def _get_btc_market_asset_ids(self) -> List[str]:
        """Get BTC 15M market asset IDs from Gamma API"""
        try:
            import aiohttp
            
            async with aiohttp.ClientSession() as session:
                # Query Gamma API for BTC markets
                url = "https://gamma-api.polymarket.com/markets"
                params = {
                    "active": "true",
                    "archived": "false",
                    "closed": "false",
                    "limit": "50"
                }
                
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        markets = data.get('markets', [])
                        
                        # Filter for BTC 15M markets
                        btc_asset_ids = []
                        for m in markets:
                            slug = m.get('marketSlug', '').lower()
                            if 'btc' in slug and '15m' in slug:
                                # Get outcome assets
                                outcomes = m.get('outcomes', [])
                                for outcome in outcomes:
                                    asset_id = outcome.get('assetId')
                                    if asset_id:
                                        btc_asset_ids.append(asset_id)
                        
                        logger.info(f"Found {len(btc_asset_ids)} BTC 15M asset IDs")
                        return btc_asset_ids[:10]  # Limit to 10
                        
        except Exception as e:
            logger.error(f"Failed to get BTC asset IDs: {e}")
        
        return []
    
    async def _ping(self, ws):
        """Send PING every 10 seconds to keep connection alive"""
        try:
            while self.running:
                await asyncio.sleep(10)
                if ws and self.running:
                    try:
                        await ws.send("PING")
                        logger.debug("📡 Sent PING")
                    except Exception as e:
                        logger.warning(f"Ping failed: {e}")
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ping error: {e}")
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            # Check if it's a PONG response
            if message == "PONG":
                logger.debug("📨 Received PONG")
                return
            
            # Try to parse as JSON
            data = json.loads(message)
            
            # Handle trade events
            event_type = data.get('event_type')
            
            if event_type == 'trade':
                await self._handle_trade(data)
            elif event_type == 'order_book_update':
                # Could track orderbook changes
                pass
            else:
                logger.debug(f"Received event: {event_type}")
                
        except json.JSONDecodeError:
            # Not JSON, might be a simple message
            logger.debug(f"Received: {message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _handle_trade(self, data: Dict):
        """Process a trade event"""
        trade = data.get('payload', {})
        
        # Get trader addresses
        maker = trade.get('maker', '').lower()
        taker = trade.get('taker', '').lower()
        
        # Check if it's one of our competitors
        competitor_name = None
        competitor_address = None
        side = None
        
        if maker in self.competitor_addresses:
            competitor_name = self.competitor_addresses[maker]
            competitor_address = maker
            side = 'SELL'  # Maker is selling
        elif taker in self.competitor_addresses:
            competitor_name = self.competitor_addresses[taker]
            competitor_address = taker
            side = 'BUY'   # Taker is buying
        
        if competitor_name:
            # Our competitor traded!
            notification = {
                'timestamp': datetime.now().isoformat(),
                'competitor': competitor_name,
                'address': competitor_address,
                'market': trade.get('market', 'Unknown'),
                'asset_id': trade.get('asset_id', 'Unknown'),
                'side': side,
                'size': trade.get('size', 0),
                'price': trade.get('price', 0),
                'type': 'trade',
                'trade_id': trade.get('transaction_hash', 'Unknown')[:16]
            }
            
            logger.info("=" * 60)
            logger.info("🚨 COMPETITOR TRADE DETECTED!")
            logger.info("=" * 60)
            logger.info(f"👤 Trader: {competitor_name}")
            logger.info(f"📊 Market: {notification['asset_id'][:30]}...")
            logger.info(f"📈 Side: {side}")
            logger.info(f"💰 Size: {notification['size']}")
            logger.info(f"💵 Price: {notification['price']}")
            logger.info("=" * 60)
            
            # Notify callbacks
            for callback in self.callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(notification)
                    else:
                        callback(notification)
                except Exception as e:
                    logger.error(f"Callback error: {e}")
            
            # Save to file
            self._save_notification(notification)
    
    def _save_notification(self, notification: Dict):
        """Save notification to file"""
        import os
        filepath = '/root/clawd/trading-agent/data/competitor_notifications.json'
        
        notifications = []
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    notifications = json.load(f)
            except:
                pass
        
        notifications.append(notification)
        notifications = notifications[-500:]  # Keep last 500
        
        try:
            with open(filepath, 'w') as f:
                json.dump(notifications, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save notification: {e}")
    
    async def run_forever(self):
        """Run WebSocket connection with auto-reconnect"""
        logger.info("🚀 Starting Polymarket WebSocket competitor tracker...")
        logger.info(f"📊 Monitoring {len(self.competitors)} competitors:")
        for c in self.competitors:
            logger.info(f"   • {c['name']}")
        
        while True:
            try:
                await self.connect_market_channel()
            except Exception as e:
                logger.error(f"Connection error: {e}")
            
            if not self.running:
                logger.info(f"🔄 Reconnecting in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
                # Exponential backoff up to 60 seconds
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)
            else:
                self.reconnect_delay = 5


# Simple test
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    async def main():
        tracker = PolymarketWebSocketTracker()
        
        async def on_trade(notification):
            print("\n" + "=" * 60)
            print("🚨 ALERT: Competitor Trade!")
            print("=" * 60)
            print(f"Trader: {notification['competitor']}")
            print(f"Side: {notification['side']}")
            print(f"Size: {notification['size']} @ {notification['price']}")
            print("=" * 60)
        
        tracker.on_trade(on_trade)
        
        print("\n" + "=" * 60)
        print("POLYMARKET WEBSOCKET MONITOR")
        print("=" * 60)
        print("Waiting for competitor trades...")
        print("Press Ctrl+C to stop")
        print("=" * 60 + "\n")
        
        await tracker.run_forever()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Stopped by user")
