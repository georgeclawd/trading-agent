#!/usr/bin/env python3
"""
Trading Agent Monitor - Enhanced visibility dashboard
Shows real-time scanning, decision-making, and trading activity
"""

import json
import time
from datetime import datetime
from pathlib import Path
import subprocess

class TradingMonitor:
    """Monitor and display Trading Agent activity"""
    
    def __init__(self):
        self.log_file = Path("/root/clawd/trading-agent/logs/trading.log")
        self.data_dir = Path("/root/clawd/trading-agent/data")
        
    def show_status(self):
        """Show current bot status"""
        print("\n" + "="*70)
        print("🤖 TRADING AGENT - LIVE DASHBOARD")
        print("="*70)
        print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print("")
        
        # Check if running
        result = subprocess.run(
            ["pgrep", "-f", "python3 src/main.py"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            pid = result.stdout.strip()
            print(f"🟢 Status: RUNNING (PID: {pid})")
        else:
            print("🔴 Status: STOPPED")
            return
        
        # Show recent activity
        print("\n📊 RECENT ACTIVITY (last 10 minutes):")
        print("-" * 70)
        
        if self.log_file.exists():
            # Get last 50 lines
            result = subprocess.run(
                ["tail", "-50", str(self.log_file)],
                capture_output=True, text=True
            )
            
            lines = result.stdout.strip().split('\n')
            
            # Parse and display relevant entries
            for line in lines[-20:]:  # Last 20 relevant lines
                if any(x in line for x in ['Bankroll', 'Found', 'Executing', 'Trade', 'Signal']):
                    # Format nicely
                    if 'Bankroll' in line:
                        print(f"💰 {line.split(' - ')[-1]}")
                    elif 'Found' in line:
                        print(f"🔍 {line.split(' - ')[-1]}")
                    elif 'Executing' in line:
                        print(f"🚀 {line.split(' - ')[-1]}")
                    elif 'Trade' in line:
                        print(f"📈 {line.split(' - ')[-1]}")
                    elif 'Signal' in line:
                        print(f"🐋 {line.split(' - ')[-1]}")
        
        print("\n" + "-" * 70)
        
    def show_detailed_scan(self):
        """Show what markets are being scanned"""
        print("\n🔍 SCANNING ACTIVITY:")
        print("-" * 70)
        print("Markets being monitored:")
        print("  • Weather (NYC, London, Tokyo) - High confidence predictions")
        print("  • Crypto (BTC, ETH) - Price levels")
        print("  • Sports - NFL, NBA, Soccer")
        print("  • Politics - Elections, policy")
        print("")
        print("Strategies active:")
        print("  1. Arbitrage: YES+NO < $1.00 (risk-free)")
        print("  2. High-Confidence: >95% outcomes")
        print("  3. Weather API: Open-Meteo data vs market pricing")
        print("  4. Whale Watch: Copy insider signals (when configured)")
        
    def show_decision_criteria(self):
        """Show what criteria trigger trades"""
        print("\n🎯 DECISION CRITERIA:")
        print("-" * 70)
        print("Current Risk Profile: Conservative (Testing Phase)")
        print("")
        print("Trade Requirements:")
        print("  ✓ Expected Value > 5%")
        print("  ✓ Position Size: 1-2% of bankroll ($1-2)")
        print("  ✓ Max Daily Trades: 5")
        print("  ✓ Max Daily Loss: 20% ($20)")
        print("")
        print("Risk Levels:")
        print("  $80-100  → Tight (1% max, high EV threshold)")
        print("  $100-120 → Conservative (2% max)")
        print("  $120-150 → Moderate (3% max)")
        print("  $150+    → Aggressive (5% max)")
        
    def show_last_trades(self):
        """Show trade history"""
        print("\n📈 RECENT TRADES:")
        print("-" * 70)
        
        trades_file = self.data_dir / 'trades.json'
        if trades_file.exists():
            with open(trades_file) as f:
                trades = json.load(f)
            
            if trades:
                print(f"Total trades: {len(trades)}")
                print("")
                for trade in trades[-5:]:  # Last 5
                    ts = trade.get('timestamp', 'Unknown')
                    market = trade.get('market', 'Unknown')
                    side = trade.get('side', '?')
                    size = trade.get('position_size', 0)
                    print(f"  {ts[:10]} | {side} ${size} | {market[:30]}...")
            else:
                print("No trades yet - bot is scanning for first opportunity")
        else:
            print("No trade history yet")
            
    def show_live_log(self, lines=20):
        """Show live log entries"""
        print(f"\n📝 LIVE LOG (last {lines} lines):")
        print("-" * 70)
        
        if self.log_file.exists():
            result = subprocess.run(
                ["tail", "-n", str(lines), str(self.log_file)],
                capture_output=True, text=True
            )
            print(result.stdout)
        else:
            print("No log file found")


def main():
    """Main dashboard"""
    monitor = TradingMonitor()
    
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            monitor.show_status()
        elif sys.argv[1] == "scan":
            monitor.show_detailed_scan()
        elif sys.argv[1] == "criteria":
            monitor.show_decision_criteria()
        elif sys.argv[1] == "trades":
            monitor.show_last_trades()
        elif sys.argv[1] == "log":
            monitor.show_live_log(lines=int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        elif sys.argv[1] == "all":
            monitor.show_status()
            monitor.show_detailed_scan()
            monitor.show_decision_criteria()
            monitor.show_last_trades()
        else:
            print("Usage: python3 monitor.py [status|scan|criteria|trades|log|all]")
    else:
        # Default: show everything
        monitor.show_status()
        monitor.show_detailed_scan()
        monitor.show_decision_criteria()
        monitor.show_last_trades()


if __name__ == '__main__':
    main()
