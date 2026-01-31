"""
Whale Watcher - Monitor insider/whale wallets for anomalous trades
Copy-trade strategy based on unusual trading patterns
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass


@dataclass
class WhaleTrade:
    """Detected whale trade"""
    wallet: str
    market_id: str
    market_name: str
    outcome: str  # 'YES' or 'NO'
    size: float  # USD value
    timestamp: datetime
    retail_sentiment: str  # What retail is doing
    anomaly_score: float  # How unusual this trade is


class WhaleWatcher:
    """
    Monitors specific wallets for insider trading signals
    
    Strategy: When a watched whale trades against retail sentiment,
    copy the trade (potential insider information)
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.watched_wallets: Set[str] = set()
        self.recent_trades: List[WhaleTrade] = []
        self.min_trade_size = 1000  # Minimum $1000 to be a "whale" trade
        self.anomaly_threshold = 2.0  # Standard deviations above mean
        
        self._load_watched_wallets()
    
    def _load_watched_wallets(self):
        """Load list of wallets to monitor"""
        # Wallets will be stored in config or added dynamically
        default_wallets = self.config.get('whale_wallets', [])
        self.watched_wallets = set(default_wallets)
    
    def add_wallet(self, wallet_address: str, label: str = None):
        """Add a wallet to watch list"""
        self.watched_wallets.add(wallet_address.lower())
        print(f"👁️ Added whale wallet: {wallet_address[:10]}... ({label or 'unnamed'})")
    
    async def scan_for_whale_trades(self) -> List[WhaleTrade]:
        """
        Scan Polymarket for trades from watched wallets
        
        Returns trades that are:
        1. From watched wallets
        2. Above minimum size threshold
        3. Anomalous (contrary to retail sentiment)
        """
        signals = []
        
        for wallet in self.watched_wallets:
            try:
                trades = await self._get_wallet_trades(wallet, hours=1)
                
                for trade in trades:
                    # Check if it's a significant trade
                    if trade['size_usd'] < self.min_trade_size:
                        continue
                    
                    # Get retail sentiment for this market
                    sentiment = await self._get_retail_sentiment(trade['market_id'])
                    
                    # Calculate anomaly score
                    anomaly = self._calculate_anomaly(trade, sentiment)
                    
                    # If whale is trading against retail → potential insider signal
                    if anomaly > self.anomaly_threshold:
                        whale_trade = WhaleTrade(
                            wallet=wallet,
                            market_id=trade['market_id'],
                            market_name=trade['market_name'],
                            outcome=trade['outcome'],
                            size=trade['size_usd'],
                            timestamp=datetime.now(),
                            retail_sentiment=sentiment['direction'],
                            anomaly_score=anomaly
                        )
                        signals.append(whale_trade)
                        
            except Exception as e:
                print(f"Error scanning wallet {wallet[:10]}: {e}")
        
        # Sort by anomaly score (highest first)
        signals.sort(key=lambda x: x.anomaly_score, reverse=True)
        return signals
    
    async def _get_wallet_trades(self, wallet: str, hours: int = 1) -> List[Dict]:
        """
        Get recent trades for a specific wallet
        
        Uses Polymarket subgraph or API
        """
        # TODO: Implement Polymarket subgraph query
        # For now, return example structure
        
        # Example query would be:
        # query {
        #   orders(where: {maker: "wallet_address", createdAt_gt: timestamp}) {
        #     id
        #     market { id question }
        #     side
        #     size
        #     price
        #   }
        # }
        
        return []
    
    async def _get_retail_sentiment(self, market_id: str) -> Dict:
        """
        Get retail sentiment for a market
        
        Returns:
        - direction: 'YES_heavy', 'NO_heavy', or 'balanced'
        - yes_percentage: % of retail buying YES
        - volume_24h: 24h volume
        """
        # TODO: Implement sentiment analysis from order book
        # - Calculate buy/sell ratio
        # - Look at order book depth
        # - Track recent trade flow
        
        return {
            'direction': 'balanced',
            'yes_percentage': 50.0,
            'volume_24h': 0
        }
    
    def _calculate_anomaly(self, trade: Dict, sentiment: Dict) -> float:
        """
        Calculate how anomalous this trade is
        
        High anomaly = whale trading against retail sentiment
        """
        trade_outcome = trade['outcome']  # 'YES' or 'NO'
        retail_direction = sentiment['direction']
        
        # Base anomaly from trade size (standardized)
        size_anomaly = min(trade['size_usd'] / self.min_trade_size, 10)
        
        # Direction anomaly (trading against retail)
        direction_anomaly = 0
        
        if retail_direction == 'YES_heavy' and trade_outcome == 'NO':
            # Retail buying YES, whale buying NO → HIGH anomaly
            direction_anomaly = 3.0
        elif retail_direction == 'NO_heavy' and trade_outcome == 'YES':
            # Retail buying NO, whale buying YES → HIGH anomaly
            direction_anomaly = 3.0
        elif retail_direction == 'balanced':
            # No clear retail direction
            direction_anomaly = 1.0
        else:
            # Whale trading with retail (less anomalous)
            direction_anomaly = 0.5
        
        # Combined anomaly score
        return size_anomaly * direction_anomaly
    
    def should_copy_trade(self, whale_trade: WhaleTrade) -> bool:
        """
        Decide if we should copy this whale trade
        
        Criteria:
        - Anomaly score > threshold
        - Trade size reasonable (not too large for our bankroll)
        - Market has sufficient liquidity
        """
        if whale_trade.anomaly_score < self.anomaly_threshold:
            return False
        
        # Don't copy if whale is buying with retail (no edge)
        if (whale_trade.retail_sentiment == 'YES_heavy' and whale_trade.outcome == 'YES') or \
           (whale_trade.retail_sentiment == 'NO_heavy' and whale_trade.outcome == 'NO'):
            return False
        
        return True
    
    def calculate_copy_size(self, whale_trade: WhaleTrade, bankroll: float) -> float:
        """
        Calculate how much to copy-trade
        
        Scale down whale's position to our bankroll
        """
        # Whale might trade $10k-$100k, we trade $10-$100
        whale_size = whale_trade.size
        
        # Copy 1-5% of whale's position
        copy_ratio = min(bankroll * 0.05 / whale_size, 0.05)
        
        copy_size = whale_size * copy_ratio
        
        # Ensure minimum trade size
        if copy_size < 5:
            return 0  # Too small
        
        # Cap at 2% of our bankroll
        max_size = bankroll * 0.02
        return min(copy_size, max_size)
    
    def get_trade_opportunity(self, whale_trade: WhaleTrade, bankroll: float) -> Optional[Dict]:
        """
        Convert whale trade into a trade opportunity for our bot
        """
        if not self.should_copy_trade(whale_trade):
            return None
        
        copy_size = self.calculate_copy_size(whale_trade, bankroll)
        
        if copy_size <= 0:
            return None
        
        return {
            'market': whale_trade.market_name,
            'market_id': whale_trade.market_id,
            'platform': 'polymarket',
            'strategy': 'whale_copy',
            'outcome': whale_trade.outcome,
            'position_size': copy_size,
            'original_whale_size': whale_trade.size,
            'whale_wallet': whale_trade.wallet[:10] + '...',
            'anomaly_score': whale_trade.anomaly_score,
            'retail_sentiment': whale_trade.retail_sentiment,
            'expected_value': 0.02,  # Conservative 2% edge assumption
            'confidence': min(whale_trade.anomaly_score / 5, 0.95),
            'category': 'whale_copy',
            'rationale': f"Copying whale trading against {whale_trade.retail_sentiment}"
        }
    
    async def get_all_opportunities(self, bankroll: float) -> List[Dict]:
        """Get all copy-trade opportunities from whale watching"""
        whale_trades = await self.scan_for_whale_trades()
        
        opportunities = []
        for trade in whale_trades:
            opp = self.get_trade_opportunity(trade, bankroll)
            if opp:
                opportunities.append(opp)
        
        return opportunities
