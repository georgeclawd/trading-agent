"""
Maps Polymarket markets to equivalent Kalshi markets

Both platforms have BTC 15M markets, but with different formats:
- Polymarket: "Will BTC be above $X at HH:MM?"
- Kalshi: "KXBTC15M-YYMMDDHHMM-XX" (XX = price level)
"""

import logging
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger('MarketMapper')


class PolymarketKalshiMapper:
    """
    Maps between Polymarket and Kalshi BTC 15M markets
    """
    
    @staticmethod
    def parse_polymarket_market(market_slug: str, question: str) -> Optional[Dict]:
        """
        Parse a Polymarket BTC market to extract:
        - Target price
        - Close time
        - Side (above/below)
        
        Example: "Will BTC be above 97000 at Feb 3, 2025 2:45pm?"
        """
        try:
            # Extract price from question
            # Format: "Will BTC be above $X..." or "Will BTC be below $X..."
            question_lower = question.lower()
            
            # Determine side
            if 'above' in question_lower:
                side = 'ABOVE'
            elif 'below' in question_lower:
                side = 'BELOW'
            else:
                return None
            
            # Extract price - look for numbers after above/below
            import re
            price_match = re.search(r'(?:above|below)\s*\$?(\d+(?:,\d+)*)', question_lower)
            if not price_match:
                return None
            
            price_str = price_match.group(1).replace(',', '')
            target_price = int(price_str)
            
            # Extract datetime - look for patterns like "Feb 3, 2025 2:45pm"
            # or "2025-02-03 14:45"
            dt_match = re.search(r'([A-Za-z]+\s+\d{1,2},?\s+\d{4}\s+\d{1,2}:\d{2}(?:am|pm)?)', question)
            
            close_time = None
            if dt_match:
                dt_str = dt_match.group(1)
                try:
                    # Try various formats
                    for fmt in ['%b %d, %Y %I:%M%p', '%b %d %Y %I:%M%p', '%B %d, %Y %I:%M%p']:
                        try:
                            close_time = datetime.strptime(dt_str, fmt)
                            break
                        except:
                            continue
                except:
                    pass
            
            return {
                'target_price': target_price,
                'side': side,
                'close_time': close_time,
                'market_slug': market_slug,
                'question': question
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse Polymarket market: {e}")
            return None
    
    @staticmethod
    def kalshi_ticker_to_details(ticker: str) -> Optional[Dict]:
        """
        Parse Kalshi ticker format:
        KXBTC15M-26FEB031545-45
        
        Returns:
        - Date: Feb 3, 2025
        - Time: 15:45
        - Price level: 45 (meaning $45,000? or specific level)
        """
        try:
            # Remove prefix
            if not ticker.startswith('KXBTC15M-'):
                return None
            
            parts = ticker.split('-')
            if len(parts) < 3:
                return None
            
            # Parse date/time part: 26FEB031545
            datetime_part = parts[1]
            if len(datetime_part) != 11:
                return None
            
            # 26FEB031545 -> 2026 Feb 03 15:45
            year = 2000 + int(datetime_part[0:2])
            month_str = datetime_part[2:5]
            day = int(datetime_part[5:7])
            hour = int(datetime_part[7:9])
            minute = int(datetime_part[9:11])
            
            month_map = {
                'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
            }
            month = month_map.get(month_str.upper(), 0)
            
            if month == 0:
                return None
            
            close_time = datetime(year, month, day, hour, minute)
            
            # Parse price level: 45 -> $45,000 or $4,500 or specific strike
            price_level = parts[2]
            
            return {
                'close_time': close_time,
                'price_level': price_level,
                'ticker': ticker,
                'year': year,
                'month': month,
                'day': day,
                'hour': hour,
                'minute': minute
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse Kalshi ticker: {e}")
            return None
    
    @staticmethod
    def find_equivalent_kalshi_market(pm_market: Dict, kalshi_markets: list) -> Optional[str]:
        """
        Find the Kalshi market that matches a Polymarket market
        
        Matching criteria:
        1. Close time within 15 minutes
        2. Similar price level
        """
        if not pm_market or not pm_market.get('close_time'):
            return None
        
        pm_close = pm_market['close_time']
        pm_price = pm_market['target_price']
        
        best_match = None
        best_score = float('inf')
        
        for km in kalshi_markets:
            ticker = km.get('ticker', '')
            details = PolymarketKalshiMapper.kalshi_ticker_to_details(ticker)
            
            if not details:
                continue
            
            # Check time difference
            time_diff = abs((details['close_time'] - pm_close).total_seconds())
            
            # Check price similarity (Kalshi price level might encode the strike)
            # This is approximate - need to understand Kalshi's price encoding
            kl_price = int(details['price_level']) * 1000  # Assume 45 = 45,000
            price_diff = abs(kl_price - pm_price)
            
            # Score: lower is better
            score = time_diff + (price_diff / 1000) * 60  # Weight price diff
            
            if score < best_score and time_diff < 900:  # Within 15 min
                best_score = score
                best_match = ticker
        
        return best_match


# Test the mapper
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    mapper = PolymarketKalshiMapper()
    
    # Test parsing
    test_questions = [
        "Will BTC be above $97000 at Feb 3, 2025 2:45pm?",
        "Will BTC be below $95000 at Feb 3, 2025 3:00pm?",
    ]
    
    for q in test_questions:
        result = mapper.parse_polymarket_market("test-market", q)
        if result:
            print(f"\nParsed: {q}")
            print(f"  Price: ${result['target_price']}")
            print(f"  Side: {result['side']}")
            print(f"  Close: {result['close_time']}")
    
    # Test Kalshi parsing
    test_tickers = [
        "KXBTC15M-26FEB031545-45",
        "KXBTC15M-26FEB031500-97",
    ]
    
    for t in test_tickers:
        result = mapper.kalshi_ticker_to_details(t)
        if result:
            print(f"\nParsed: {t}")
            print(f"  Close: {result['close_time']}")
            print(f"  Price level: {result['price_level']}")
