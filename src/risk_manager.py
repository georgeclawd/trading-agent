"""
Risk Manager - Dynamic position sizing and bankroll management
Poker-style strategy: adjust aggression based on performance
"""

import math
from typing import Dict
from dataclasses import dataclass


@dataclass
class RiskProfile:
    """Current risk profile based on bankroll and performance"""
    level: str  # 'tight', 'conservative', 'moderate', 'aggressive'
    max_position_pct: float  # Max % of bankroll per trade
    min_ev_threshold: float  # Minimum expected value to trade
    kelly_multiplier: float  # Fraction of Kelly to use


class RiskManager:
    """
    Manages risk using Kelly Criterion and dynamic bankroll sizing
    Like poker: tighten up when losing, loosen when winning
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.daily_loss = 0.0
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        
    def get_risk_profile(self, bankroll: float, win_rate: float) -> RiskProfile:
        """
        Determine risk profile based on bankroll and performance
        
        Bankroll targets:
        - $100: Starting (conservative)
        - $120+: Moderate (winning)
        - $150+: Aggressive (hot streak)
        - $80: Tight (downswing)
        """
        initial = self.config['initial_bankroll']
        
        # Downswing - tighten up
        if bankroll < initial * 0.8:
            return RiskProfile(
                level='tight',
                max_position_pct=0.01,  # 1% max
                min_ev_threshold=0.10,   # Higher bar
                kelly_multiplier=0.10
            )
        
        # Losing but not critical
        if bankroll < initial:
            return RiskProfile(
                level='conservative',
                max_position_pct=0.02,  # 2% max
                min_ev_threshold=0.07,
                kelly_multiplier=0.15
            )
        
        # Winning - moderate aggression
        if bankroll < initial * 1.5:
            if win_rate > 0.55:
                return RiskProfile(
                    level='moderate-aggressive',
                    max_position_pct=0.04,
                    min_ev_threshold=0.05,
                    kelly_multiplier=0.25
                )
            return RiskProfile(
                level='moderate',
                max_position_pct=0.03,
                min_ev_threshold=0.05,
                kelly_multiplier=0.20
            )
        
        # Hot streak - max aggression
        if win_rate > 0.60:
            return RiskProfile(
                level='aggressive',
                max_position_pct=0.05,  # 5% max (config limit)
                min_ev_threshold=0.04,
                kelly_multiplier=0.30
            )
        
        # High bankroll but not hot
        return RiskProfile(
            level='moderate-aggressive',
            max_position_pct=0.04,
            min_ev_threshold=0.05,
            kelly_multiplier=0.25
        )
    
    def calculate_ev(self, opportunity: Dict) -> float:
        """
        Calculate Expected Value of a trade
        EV = (Probability of Win × Profit) - (Probability of Loss × Loss)
        """
        win_prob = opportunity.get('win_probability', 0.5)
        odds = opportunity.get('odds', 2.0)  # Decimal odds
        
        # Convert odds to implied probability
        implied_prob = 1 / odds
        
        # Edge = our estimated prob - market implied prob
        edge = win_prob - implied_prob
        
        # EV as percentage of stake
        profit = odds - 1  # Profit multiplier
        ev = (win_prob * profit) - ((1 - win_prob) * 1)
        
        return ev
    
    def calculate_position_size(self, bankroll: float, win_rate: float, 
                               ev: float, odds: float) -> float:
        """
        Calculate position size using Kelly Criterion with adjustments
        
        Kelly % = (Win Prob × Odds - Loss Prob) / Odds
        
        We use fractional Kelly for safety
        """
        profile = self.get_risk_profile(bankroll, win_rate)
        
        # Base Kelly calculation
        win_prob = (ev + 1) / odds  # Derive from EV
        loss_prob = 1 - win_prob
        
        kelly_pct = (win_prob * odds - loss_prob) / odds
        
        # Apply fractional Kelly based on risk profile
        position_pct = kelly_pct * profile.kelly_multiplier
        
        # Cap at max position size
        position_pct = min(position_pct, profile.max_position_pct)
        
        # Calculate dollar amount
        position_size = bankroll * position_pct
        
        # Round to reasonable amounts
        if position_size < 1.0:
            return 0.0  # Too small
        elif position_size < 5.0:
            return round(position_size, 1)
        else:
            return round(position_size)
    
    def can_trade(self, bankroll: float) -> bool:
        """Check if we can make new trades"""
        initial = self.config['initial_bankroll']
        
        # Daily loss limit
        if self.daily_loss >= initial * self.config['daily_loss_limit']:
            return False
        
        # Stop if bankroll too low
        if bankroll < initial * 0.5:  # 50% drawdown
            return False
        
        return True
    
    def record_result(self, profit: float):
        """Record trade result for streak tracking"""
        if profit > 0:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.daily_loss += abs(profit)
    
    def reset_daily_stats(self):
        """Reset daily tracking"""
        self.daily_loss = 0.0
