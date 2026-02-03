"""
Simple competitor follower - When they trade, we trade

Integration with existing CryptoMomentum strategy
"""

import json
import logging
from typing import Dict, List
from datetime import datetime, timedelta

logger = logging.getLogger('CompetitorFollower')


class CompetitorFollower:
    """
    Follow competitor trades in real-time
    """
    
    def __init__(self):
        self.recent_trades = []
        self.last_check = datetime.now()
    
    def get_competitor_signal(self) -> Dict:
        """
        Get current signal from competitors
        
        Returns:
        {
            'signal': 'YES' | 'NO' | 'NEUTRAL',
            'confidence': float,
            'recent_trades': list
        }
        """
        # Load latest competitor data
        filepath = '/root/clawd/trading-agent/data/competitor_data.json'
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
        except:
            return {'signal': 'NEUTRAL', 'confidence': 0, 'recent_trades': []}
        
        # Look at recent trades (last 5 minutes)
        now = datetime.now()
        recent_trades = []
        
        for name, records in data.items():
            if not records:
                continue
            
            latest = records[-1] if isinstance(records, list) else records
            activity = latest.get('activity', [])
            
            for trade in activity[:5]:
                trade_time = trade.get('timestamp', '')
                if trade_time:
                    try:
                        # Parse timestamp
                        if isinstance(trade_time, str):
                            trade_dt = datetime.fromisoformat(trade_time.replace('Z', ''))
                        else:
                            trade_dt = datetime.fromtimestamp(trade_time)
                        
                        # Only count recent trades (last 10 min)
                        if (now - trade_dt).total_seconds() < 600:
                            recent_trades.append({
                                'competitor': name,
                                'side': trade.get('side', 'UNKNOWN'),
                                'market': trade.get('market', 'Unknown'),
                                'size': trade.get('size', 0),
                                'time': trade_dt
                            })
                    except:
                        pass
        
        # Determine consensus from recent trades
        if not recent_trades:
            return {'signal': 'NEUTRAL', 'confidence': 0, 'recent_trades': []}
        
        # Count YES vs NO trades
        yes_votes = len([t for t in recent_trades if t['side'] == 'BUY'])
        no_votes = len([t for t in recent_trades if t['side'] == 'SELL'])
        
        total = yes_votes + no_votes
        if total == 0:
            return {'signal': 'NEUTRAL', 'confidence': 0, 'recent_trades': recent_trades}
        
        # Determine signal
        if yes_votes > no_votes:
            signal = 'YES'
            confidence = yes_votes / total
        elif no_votes > yes_votes:
            signal = 'NO'
            confidence = no_votes / total
        else:
            signal = 'NEUTRAL'
            confidence = 0.5
        
        return {
            'signal': signal,
            'confidence': confidence,
            'recent_trades': recent_trades
        }


# Quick test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    follower = CompetitorFollower()
    result = follower.get_competitor_signal()
    
    print("Competitor Signal:")
    print(f"  Signal: {result['signal']}")
    print(f"  Confidence: {result['confidence']:.0%}")
    print(f"  Recent trades: {len(result['recent_trades'])}")
    
    for trade in result['recent_trades'][:3]:
        print(f"    {trade['competitor']}: {trade['side']} on {trade['market'][:30]}...")
