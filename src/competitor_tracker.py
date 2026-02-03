"""
Polymarket Competitor Tracker

Tracks competitor trading activity via Polymarket Data API
"""

import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
import os

logger = logging.getLogger('CompetitorTracker')


class PolymarketTracker:
    """
    Track competitor activity on Polymarket
    Uses Data API: https://data-api.polymarket.com
    """
    
    BASE_URL = "https://data-api.polymarket.com"
    
    def __init__(self, api_key: str = None, api_secret: str = None, passphrase: str = None):
        self.api_key = api_key
        self.api_secret = api_secret  
        self.passphrase = passphrase
        self.session = requests.Session()
        
        # Load from pass if not provided
        if not all([api_key, api_secret, passphrase]):
            self._load_credentials()
    
    def _load_credentials(self):
        """Load credentials from pass"""
        try:
            import subprocess
            
            result = subprocess.run(
                ['pass', 'show', 'polymarket/api_key'],
                capture_output=True, text=True
            )
            self.api_key = result.stdout.strip().split('\n')[0]
            
            result = subprocess.run(
                ['pass', 'show', 'polymarket/api_secret'],
                capture_output=True, text=True
            )
            self.api_secret = result.stdout.strip().split('\n')[0]
            
            result = subprocess.run(
                ['pass', 'show', 'polymarket/passphrase'],
                capture_output=True, text=True
            )
            self.passphrase = result.stdout.strip().split('\n')[0]
            
            logger.info("✅ Loaded Polymarket credentials from pass")
        except Exception as e:
            logger.error(f"Failed to load credentials: {e}")
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make authenticated request to Polymarket Data API"""
        try:
            url = f"{self.BASE_URL}{endpoint}"
            
            headers = {
                "Content-Type": "application/json"
            }
            
            # Add authentication if available
            if self.api_key:
                headers["POLYMARKET-API-KEY"] = self.api_key
            
            response = self.session.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"API error {response.status_code}: {response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None
    
    def get_user_activity(self, address: str, limit: int = 50) -> List[Dict]:
        """
        Get recent trading activity for a user
        
        Args:
            address: Wallet address (e.g., "0x1234...")
            limit: Number of trades to fetch
            
        Returns:
            List of trade activity
        """
        endpoint = "/activity"
        params = {
            "address": address,
            "limit": limit
        }
        
        data = self._make_request(endpoint, params)
        
        if data:
            activities = data.get('activities', [])
            logger.info(f"Fetched {len(activities)} activities for {address[:10]}...")
            return activities
        
        return []
    
    def get_user_positions(self, address: str) -> List[Dict]:
        """
        Get current positions for a user
        
        Args:
            address: Wallet address
            
        Returns:
            List of positions
        """
        endpoint = "/positions"
        params = {"address": address}
        
        data = self._make_request(endpoint, params)
        
        if data:
            positions = data.get('positions', [])
            logger.info(f"Fetched {len(positions)} positions for {address[:10]}...")
            return positions
        
        return []
    
    def track_competitor(self, name: str, address: str) -> Dict:
        """
        Track a competitor's recent activity
        
        Args:
            name: Friendly name for the competitor
            address: Wallet address
            
        Returns:
            Dict with activity and positions
        """
        logger.info(f"🔍 Tracking competitor: {name} ({address[:10]}...)")
        
        activity = self.get_user_activity(address)
        positions = self.get_user_positions(address)
        
        return {
            'name': name,
            'address': address,
            'activity': activity,
            'positions': positions,
            'tracked_at': datetime.now().isoformat()
        }
    
    def compare_with_our_signal(self, competitor_trade: Dict, our_signal: str) -> Dict:
        """
        Compare competitor's trade with our algorithm's signal
        
        Args:
            competitor_trade: Trade from competitor
            our_signal: Our algorithm's signal ("YES", "NO", or "NO_TRADE")
            
        Returns:
            Comparison result
        """
        trade_side = competitor_trade.get('side', '').upper()
        trade_market = competitor_trade.get('market', 'Unknown')
        trade_price = competitor_trade.get('price', 0)
        
        # Determine if we agree
        if our_signal == "NO_TRADE":
            agreement = "DIVERGENCE"
            note = "We didn't trade, they did"
        elif trade_side == our_signal:
            agreement = "AGREE"
            note = "Same direction"
        else:
            agreement = "CONTRARIAN"
            note = "Opposite direction"
        
        return {
            'market': trade_market,
            'competitor_side': trade_side,
            'our_signal': our_signal,
            'agreement': agreement,
            'note': note,
            'timestamp': datetime.now().isoformat()
        }


class CompetitorWatcher:
    """
    Watch multiple competitors and compare to our algorithm
    """
    
    def __init__(self, tracker: PolymarketTracker):
        self.tracker = tracker
        self.competitors = []
        self.load_competitors()
    
    def load_competitors(self):
        """Load competitor list from file"""
        filepath = '/root/clawd/trading-agent/data/competitor_profiles.json'
        
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                data = json.load(f)
                self.competitors = data.get('profiles', [])
                logger.info(f"Loaded {len(self.competitors)} competitors")
    
    def save_competitor_data(self, data: Dict):
        """Save tracked data to file"""
        filepath = '/root/clawd/trading-agent/data/competitor_data.json'
        
        existing = {}
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                existing = json.load(f)
        
        # Merge new data
        for name, info in data.items():
            if name not in existing:
                existing[name] = []
            existing[name].append(info)
        
        with open(filepath, 'w') as f:
            json.dump(existing, f, indent=2, default=str)
        
        logger.info(f"💾 Saved competitor data to {filepath}")
    
    async def poll_all_competitors(self):
        """Poll all competitors for new activity"""
        results = {}
        
        for competitor in self.competitors:
            name = competitor.get('name')
            # Note: We need the wallet address, not the username
            # Polymarket profiles use usernames but API needs addresses
            # This is a limitation - we need to resolve username to address
            
            logger.info(f"Would track: {name}")
            # TODO: Resolve username to address via Polymarket API or scraping
        
        return results


# Example usage
if __name__ == "__main__":
    # Test the tracker
    tracker = PolymarketTracker()
    
    # To use: need actual wallet addresses
    # tracker.track_competitor("distinct-baguette", "0x...")
    
    print("Competitor tracker initialized")
    print("To track competitors, need their wallet addresses (not usernames)")
