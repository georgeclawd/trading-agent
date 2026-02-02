"""
Alert System - Sends notifications to Discord
Trade alerts, performance updates, risk warnings
"""

import aiohttp
from typing import Dict
from datetime import datetime


class AlertSystem:
    """Sends alerts to Discord for trades, performance, and warnings"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.webhook_url = None  # Loaded from pass
        self._load_webhook()
    
    def _load_webhook(self):
        """Load Discord webhook from pass"""
        import subprocess
        try:
            result = subprocess.run(
                ['pass', 'show', 'trading-agent/discord-webhook'],
                capture_output=True, text=True, timeout=5
            )
            self.webhook_url = result.stdout.strip().split('\n')[0]
        except:
            self.webhook_url = None
    
    async def send_alert(self, title: str, message: str, color: int = 0x3498db):
        """Send general alert to Discord"""
        if not self.webhook_url:
            print(f"[ALERT] {title}: {message}")
            return
        
        async with aiohttp.ClientSession() as session:
            data = {
                "embeds": [{
                    "title": title,
                    "description": message,
                    "color": color,
                    "timestamp": datetime.now().isoformat(),
                    "footer": {"text": "Trading Agent - SIMULATION MODE"}
                }]
            }
            
            try:
                async with session.post(self.webhook_url, json=data) as resp:
                    if resp.status != 204:
                        print(f"Discord alert failed: {resp.status}")
            except Exception as e:
                print(f"Alert error: {e}")
    
    async def send_trade_notification(self, trade: Dict):
        """Send trade execution notification"""
        if not self.webhook_url:
            print(f"[TRADE] {trade}")
            return
        
        market = trade.get('market', 'Unknown')
        size = trade.get('position_size', 0)
        side = trade.get('side', 'buy').upper()
        ev = trade.get('expected_value', 0) * 100
        is_simulated = trade.get('simulated', True)
        
        # Blue for simulation, green/red for real
        if is_simulated:
            color = 0x3498db  # Blue
            title_prefix = "🧪 SIMULATED Trade"
            warning = "\n\n⚠️ **THIS IS A SIMULATION - NO REAL MONEY WAS SPENT**"
        else:
            color = 0x2ecc71 if side == 'BUY' else 0xe74c3c
            title_prefix = f"🚀 Trade Executed - {side}"
            warning = ""
        
        async with aiohttp.ClientSession() as session:
            data = {
                "embeds": [{
                    "title": title_prefix,
                    "description": f"**{market}**{warning}",
                    "color": color,
                    "fields": [
                        {"name": "Position Size", "value": f"${size:.2f}", "inline": True},
                        {"name": "Expected Value", "value": f"+{ev:.1f}%", "inline": True},
                        {"name": "Trade ID", "value": trade.get('trade_id', 'N/A')[:20], "inline": True}
                    ],
                    "timestamp": datetime.now().isoformat(),
                    "footer": {"text": "Trading Agent - SIMULATION MODE 🔒"}
                }]
            }
            
            try:
                async with session.post(self.webhook_url, json=data) as resp:
                    pass
            except Exception as e:
                print(f"Trade alert error: {e}")
    
    async def send_performance_update(self, stats: Dict):
        """Send daily/weekly performance update"""
        pnl = stats.get('total_pnl', 0)
        win_rate = stats.get('win_rate', 0) * 100
        bankroll = stats.get('current_bankroll', 0)
        
        color = 0x2ecc71 if pnl >= 0 else 0xe74c3c
        emoji = "📈" if pnl >= 0 else "📉"
        
        message = f"""
**PNL:** ${pnl:+.2f}
**Win Rate:** {win_rate:.1f}%
**Bankroll:** ${bankroll:.2f}
**Total Trades:** {stats.get('total_trades', 0)}

🔒 All trades are SIMULATED - no real money spent
        """
        
        await self.send_alert(f"{emoji} Performance Update (SIM)", message, color)
    
    async def send_risk_warning(self, message: str):
        """Send risk management warning"""
        await self.send_alert("⚠️ Risk Warning", message, color=0xf39c12)
