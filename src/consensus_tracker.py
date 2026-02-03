"""
Consensus Tracker - Combines our algorithm with competitor signals
Implements "wisdom of the crowd" approach
"""

import logging
import json
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from competitor_tracker import PolymarketTracker

logger = logging.getLogger('ConsensusTracker')


class ConsensusTracker:
    """
    Tracks competitor positions and calculates consensus
    Helps validate our algorithm's decisions
    """
    
    def __init__(self):
        self.tracker = PolymarketTracker()
        self.competitors = self._load_competitors()
        self.consensus_threshold = 0.6  # 60% agreement required
    
    def _load_competitors(self) -> List[Dict]:
        """Load competitor profiles"""
        filepath = '/root/clawd/trading-agent/data/competitor_profiles.json'
        
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
                return data.get('profiles', [])
        return []
    
    def get_competitor_consensus(self, market_slug: str = None) -> Dict:
        """
        Get consensus from all tracked competitors
        
        Returns:
            {
                'total_traders': int,
                'bullish_count': int,
                'bearish_count': int,
                'neutral_count': int,
                'consensus_side': str,  # 'YES', 'NO', or 'NEUTRAL'
                'agreement_ratio': float,  # 0.0 to 1.0
                'details': [{
                    'name': str,
                    'side': str,
                    'confidence': float
                }]
            }
        """
        votes = []
        
        for competitor in self.competitors:
            name = competitor.get('name')
            address = competitor.get('address')
            
            try:
                # Get positions
                positions = self.tracker.get_user_positions(address)
                
                # Determine if they're bullish or bearish on BTC
                # Look for BTC 15M market positions
                btc_positions = [
                    p for p in positions 
                    if 'BTC' in str(p.get('market', '')).upper() or 
                       'bitcoin' in str(p.get('market', '')).lower()
                ]
                
                if btc_positions:
                    # Sum up their YES vs NO positions
                    yes_size = sum(
                        float(p.get('size', 0)) for p in btc_positions 
                        if p.get('side', '').upper() == 'YES'
                    )
                    no_size = sum(
                        float(p.get('size', 0)) for p in btc_positions 
                        if p.get('side', '').upper() == 'NO'
                    )
                    
                    if yes_size > no_size:
                        side = 'YES'
                        confidence = min(yes_size / (yes_size + no_size + 0.001), 1.0)
                    elif no_size > yes_size:
                        side = 'NO'
                        confidence = min(no_size / (yes_size + no_size + 0.001), 1.0)
                    else:
                        side = 'NEUTRAL'
                        confidence = 0.5
                    
                    votes.append({
                        'name': name,
                        'side': side,
                        'confidence': confidence,
                        'yes_size': yes_size,
                        'no_size': no_size
                    })
                else:
                    # No BTC positions - check recent activity
                    activity = self.tracker.get_user_activity(address, limit=10)
                    btc_trades = [
                        a for a in activity
                        if 'BTC' in str(a.get('market', '')).upper()
                    ]
                    
                    if btc_trades:
                        # Most recent trade direction
                        recent = btc_trades[0]
                        side = recent.get('side', 'NEUTRAL').upper()
                        votes.append({
                            'name': name,
                            'side': side,
                            'confidence': 0.5,
                            'recent_trade': True
                        })
                    else:
                        votes.append({
                            'name': name,
                            'side': 'NEUTRAL',
                            'confidence': 0.0,
                            'no_data': True
                        })
                        
            except Exception as e:
                logger.warning(f"Failed to get consensus for {name}: {e}")
                votes.append({
                    'name': name,
                    'side': 'UNKNOWN',
                    'confidence': 0.0,
                    'error': str(e)
                })
        
        # Calculate consensus
        bullish = len([v for v in votes if v['side'] == 'YES'])
        bearish = len([v for v in votes if v['side'] == 'NO'])
        neutral = len([v for v in votes if v['side'] in ['NEUTRAL', 'UNKNOWN']])
        
        total_with_opinion = bullish + bearish
        
        if total_with_opinion > 0:
            if bullish > bearish:
                consensus_side = 'YES'
                agreement_ratio = bullish / total_with_opinion
            elif bearish > bullish:
                consensus_side = 'NO'
                agreement_ratio = bearish / total_with_opinion
            else:
                consensus_side = 'NEUTRAL'
                agreement_ratio = 0.5
        else:
            consensus_side = 'NEUTRAL'
            agreement_ratio = 0.0
        
        return {
            'total_traders': len(votes),
            'bullish_count': bullish,
            'bearish_count': bearish,
            'neutral_count': neutral,
            'consensus_side': consensus_side,
            'agreement_ratio': agreement_ratio,
            'details': votes
        }
    
    def make_consensus_decision(self, our_signal: str, our_confidence: float) -> Dict:
        """
        Combine our algorithm with competitor consensus
        
        Args:
            our_signal: 'YES', 'NO', or 'NO_TRADE'
            our_confidence: 0.0 to 1.0
            
        Returns:
            {
                'final_signal': str,
                'our_signal': str,
                'consensus_signal': str,
                'agreement': bool,
                'confidence': float,
                'reason': str
            }
        """
        consensus = self.get_competitor_consensus()
        consensus_signal = consensus['consensus_side']
        agreement_ratio = consensus['agreement_ratio']
        
        # If we don't have a signal, follow consensus
        if our_signal == 'NO_TRADE':
            if agreement_ratio >= self.consensus_threshold:
                return {
                    'final_signal': consensus_signal,
                    'our_signal': our_signal,
                    'consensus_signal': consensus_signal,
                    'agreement': False,
                    'confidence': agreement_ratio * 0.7,  # Lower confidence without our signal
                    'reason': f'Following consensus ({agreement_ratio:.0%} agreement)'
                }
            else:
                return {
                    'final_signal': 'NO_TRADE',
                    'our_signal': our_signal,
                    'consensus_signal': consensus_signal,
                    'agreement': False,
                    'confidence': 0.0,
                    'reason': 'No clear consensus and no our signal'
                }
        
        # We have a signal - check if consensus agrees
        if consensus_signal == our_signal:
            # Strong agreement
            combined_confidence = (our_confidence + agreement_ratio) / 2
            return {
                'final_signal': our_signal,
                'our_signal': our_signal,
                'consensus_signal': consensus_signal,
                'agreement': True,
                'confidence': combined_confidence,
                'reason': f'Our signal + consensus agree ({agreement_ratio:.0%})'
            }
        elif consensus_signal == 'NEUTRAL':
            # No strong consensus - trust our signal
            return {
                'final_signal': our_signal,
                'our_signal': our_signal,
                'consensus_signal': consensus_signal,
                'agreement': False,
                'confidence': our_confidence * 0.8,
                'reason': 'Consensus neutral, using our signal'
            }
        else:
            # Disagreement - be cautious
            if agreement_ratio >= self.consensus_threshold:
                # Strong consensus against us - reduce confidence or skip
                return {
                    'final_signal': 'NO_TRADE',
                    'our_signal': our_signal,
                    'consensus_signal': consensus_signal,
                    'agreement': False,
                    'confidence': 0.0,
                    'reason': f'Strong consensus ({agreement_ratio:.0%}) disagrees with our signal'
                }
            else:
                # Weak disagreement - reduce position size
                return {
                    'final_signal': our_signal,
                    'our_signal': our_signal,
                    'consensus_signal': consensus_signal,
                    'agreement': False,
                    'confidence': our_confidence * 0.5,
                    'reason': 'Consensus disagrees but weak - reducing size'
                }
