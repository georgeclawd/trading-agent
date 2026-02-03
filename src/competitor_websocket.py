"""
Real-time competitor tracking via Polymarket WebSocket
Gets instant notifications when competitors trade

Note: Polymarket WebSocket requires proper subscription format
and keepalive messages to stay connected.
"""

import asyncio
import json
import logging
import websockets
from typing import Dict, List, Callable, Optional
from datetime import datetime

logger = logging.getLogger('CompetitorWebSocket')


class PolymarketWebSocketTracker:
    """
    WebSocket connection to Polymarket for real-time competitor activity
    
    Uses the CLOB WebSocket endpoint:
    wss://ws-subscriptions-clob.polymarket.com/ws/market
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
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
    
    async def connect(self):
        """Connect to WebSocket and handle messages"""
        try:
            logger.info(f"🔌 Connecting to {self.WS_URL}...")
            
            async with websockets.connect(self.WS_URL) as ws:
                self.ws = ws
                logger.info("✅ WebSocket connected")
                
                # Subscribe to trade channel
                subscribe_msg = {
                    "type": "subscribe",
                    "channel": "trade",
                    "markets": ["*"]  # All markets
                }
                await ws.send(json.dumps(subscribe_msg))
                logger.info("📡 Subscribed to trade channel")
                
                self.running = True
                self.last_message_time = datetime.now()
                
                # Start keepalive task
                keepalive_task = asyncio.create_task(self._keepalive())
                
                try:
                    # Listen for messages
                    async for message in ws:
                        self.last_message_time = datetime.now()
                        await self._handle_message(message)
                finally:
                    keepalive_task.cancel()
                    try:
                        await keepalive_task
                    except asyncio.CancelledError:
                        pass
                    
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"⚠️  WebSocket closed: {e}")
            self.running = False
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
            self.running = False
    
    async def _keepalive(self):
        """Send periodic keepalive pings"""
        try:
            while self.running and self.ws:
                await asyncio.sleep(30)  # Ping every 30 seconds
                if self.ws and self.running:
                    try:
                        await self.ws.send(json.dumps({"type": "ping"}))
                        logger.debug("📡 Sent keepalive ping")
                    except Exception as e:
                        logger.warning(f"Keepalive failed: {e}")
                        break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Keepalive error: {e}")
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'trade':
                await self._handle_trade(data.get('data', {}))
            elif msg_type == 'ping':
                # Respond to server ping
                if self.ws:
                    await self.ws.send(json.dumps({"type": "pong"}))
            elif msg_type == 'pong':
                # Server responded to our ping
                pass
            else:
                logger.debug(f"Received message type: {msg_type}")
                
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse message: {message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _handle_trade(self, trade: Dict):
        """Process a trade message"""
        maker = trade.get('maker_address', '').lower()
        taker = trade.get('taker_address', '').lower()
        
        # Check if it's one of our competitors
        competitor_name = None
        competitor_address = None
        
        if maker in self.competitor_addresses:
            competitor_name = self.competitor_addresses[maker]
            competitor_address = maker
        elif taker in self.competitor_addresses:
            competitor_name = self.competitor_addresses[taker]
            competitor_address = taker
        
        if competitor_name:
            # Our competitor traded!
            notification = {
                'timestamp': datetime.now().isoformat(),
                'competitor': competitor_name,
                'address': competitor_address,
                'market': trade.get('market', 'Unknown'),
                'market_slug': trade.get('market_slug', 'Unknown'),
                'side': trade.get('side', 'Unknown'),
                'size': trade.get('size', 0),
                'price': trade.get('price', 0),
                'type': 'trade',
                'trade_id': trade.get('transaction_hash', 'Unknown')[:16]
            }
            
            logger.info("=" * 60)
            logger.info("🚨 COMPETITOR TRADE DETECTED!")
            logger.info("=" * 60)
            logger.info(f"👤 Trader: {competitor_name}")
            logger.info(f"📊 Market: {notification['market_slug']}")
            logger.info(f"📈 Side: {notification['side']}")
            logger.info(f"💰 Size: {notification['size']}")
            logger.info(f"💵 Price: {notification['price']}")
            logger.info(f"🔗 Tx: {notification['trade_id']}...")
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
        logger.info("🚀 Starting WebSocket competitor tracker...")
        logger.info(f"📊 Monitoring {len(self.competitors)} competitors:")
        for c in self.competitors:
            logger.info(f"   • {c['name']}")
        
        while True:
            try:
                await self.connect()
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
            print(f"Market: {notification['market_slug']}")
            print(f"Side: {notification['side']}")
            print(f"Size: {notification['size']} @ {notification['price']}")
            print("=" * 60)
        
        tracker.on_trade(on_trade)
        
        print("\n" + "=" * 60)
        print("COMPETITOR WEBSOCKET MONITOR")
        print("=" * 60)
        print("Waiting for competitor trades...")
        print("Press Ctrl+C to stop")
        print("=" * 60 + "\n")
        
        await tracker.run_forever()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Stopped by user")
