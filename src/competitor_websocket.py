"""
Real-time competitor tracking via Polymarket WebSocket
Gets instant notifications when competitors trade
"""

import asyncio
import json
import logging
import websockets
from typing import Dict, List, Callable
from datetime import datetime

logger = logging.getLogger('CompetitorWebSocket')


class PolymarketWebSocketTracker:
    """
    WebSocket connection to Polymarket for real-time competitor activity
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws"
    
    def __init__(self):
        self.competitors = self._load_competitors()
        self.callbacks: List[Callable] = []
        self.ws = None
        self.running = False
        self.reconnect_delay = 5  # seconds
    
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
        """Connect to WebSocket and subscribe to competitor channels"""
        try:
            logger.info("🔌 Connecting to Polymarket WebSocket...")
            
            async with websockets.connect(self.WS_URL) as ws:
                self.ws = ws
                logger.info("✅ WebSocket connected")
                
                # Subscribe to channels for each competitor
                for competitor in self.competitors:
                    address = competitor.get('address')
                    if address:
                        # Subscribe to user activity channel
                        subscribe_msg = {
                            "type": "subscribe",
                            "channel": "user",
                            "user": address
                        }
                        await ws.send(json.dumps(subscribe_msg))
                        logger.info(f"📡 Subscribed to {competitor['name']} ({address[:10]}...)")
                
                # Also subscribe to market data for BTC 15M
                market_sub = {
                    "type": "subscribe",
                    "channel": "market",
                    "market": "*"  # All markets, filter later
                }
                await ws.send(json.dumps(market_sub))
                logger.info("📡 Subscribed to all market activity")
                
                self.running = True
                
                # Listen for messages
                async for message in ws:
                    await self._handle_message(message)
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("⚠️  WebSocket connection closed")
            self.running = False
        except Exception as e:
            logger.error(f"❌ WebSocket error: {e}")
            self.running = False
    
    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message"""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'trade':
                # A trade happened
                trade = data.get('data', {})
                trader = trade.get('maker_address') or trade.get('taker_address')
                
                # Check if it's one of our competitors
                for competitor in self.competitors:
                    if competitor.get('address', '').lower() == str(trader).lower():
                        # Our competitor traded!
                        notification = {
                            'timestamp': datetime.now().isoformat(),
                            'competitor': competitor['name'],
                            'address': trader,
                            'market': trade.get('market', 'Unknown'),
                            'side': trade.get('side', 'Unknown'),
                            'size': trade.get('size', 0),
                            'price': trade.get('price', 0),
                            'type': 'trade'
                        }
                        
                        logger.info(f"🚨 COMPETITOR TRADE: {competitor['name']}")
                        logger.info(f"   Market: {notification['market']}")
                        logger.info(f"   Side: {notification['side']}")
                        logger.info(f"   Size: {notification['size']}")
                        logger.info(f"   Price: {notification['price']}")
                        
                        # Notify callbacks
                        for callback in self.callbacks:
                            try:
                                await callback(notification)
                            except Exception as e:
                                logger.error(f"Callback error: {e}")
                        
                        # Save to file for analysis
                        self._save_notification(notification)
                        break
            
            elif msg_type == 'order':
                # Order placed/cancelled
                pass  # Could track this too
                
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse message: {message[:100]}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
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
        
        # Keep only last 1000
        notifications = notifications[-1000:]
        
        with open(filepath, 'w') as f:
            json.dump(notifications, f, indent=2, default=str)
    
    async def run_forever(self):
        """Run WebSocket connection with auto-reconnect"""
        while True:
            try:
                await self.connect()
            except Exception as e:
                logger.error(f"Connection failed: {e}")
            
            if not self.running:
                logger.info(f"🔄 Reconnecting in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(self.reconnect_delay * 2, 60)  # Exponential backoff
            else:
                self.reconnect_delay = 5  # Reset on clean disconnect


class ConsensusNotifier:
    """
    Notifies when competitor consensus changes significantly
    """
    
    def __init__(self, ws_tracker: PolymarketWebSocketTracker):
        self.ws_tracker = ws_tracker
        self.last_consensus = None
    
    async def on_competitor_trade(self, notification: Dict):
        """Called when a competitor trades"""
        logger.info(f"📊 Analyzing impact of {notification['competitor']}'s trade...")
        
        # Could trigger immediate consensus recalculation
        # and notify if consensus flipped
        
        # For now, just log it
        pass


async def test_websocket():
    """Test the WebSocket connection"""
    tracker = PolymarketWebSocketTracker()
    
    notifier = ConsensusNotifier(tracker)
    tracker.on_trade(notifier.on_competitor_trade)
    
    logger.info("🚀 Starting WebSocket competitor tracking...")
    await tracker.run_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_websocket())
