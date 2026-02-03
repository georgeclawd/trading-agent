"""
Market Mapping: Polymarket -> Kalshi

Maps markets between the two platforms
"""

# Weather market mappings
WEATHER_MAPPINGS = {
    # Polymarket slug pattern -> Kalshi ticker pattern
    # NYC Weather
    "nyc-weather": {
        "kalshi_series": "KXWEATHERNYC",
        "description": "NYC Weather markets"
    },
    "new-york-weather": {
        "kalshi_series": "KXWEATHERNYC", 
        "description": "NYC Weather markets"
    },
    
    # Chicago Weather
    "chicago-weather": {
        "kalshi_series": "KXWEATHERCHI",
        "description": "Chicago Weather markets"
    },
    
    # Boston Weather  
    "boston-weather": {
        "kalshi_series": "KXWEATHERBOS",
        "description": "Boston Weather markets"
    },
    
    # Miami Weather
    "miami-weather": {
        "kalshi_series": "KXWEATHERMIA",
        "description": "Miami Weather markets"
    },
}

# BTC/Crypto mappings
CRYPTO_MAPPINGS = {
    "btc-15m": {
        "kalshi_series": "KXBTC15M",
        "description": "BTC 15 minute markets"
    },
    "bitcoin-15m": {
        "kalshi_series": "KXBTC15M",
        "description": "BTC 15 minute markets"
    },
    "eth-15m": {
        "kalshi_series": "KXETH15M", 
        "description": "ETH 15 minute markets"
    },
    "ethereum-15m": {
        "kalshi_series": "KXETH15M",
        "description": "ETH 15 minute markets"
    },
    "sol-15m": {
        "kalshi_series": "KSOL15M",
        "description": "SOL 15 minute markets"
    },
    "solana-15m": {
        "kalshi_series": "KSOL15M",
        "description": "SOL 15 minute markets"
    },
}


def find_kalshi_equivalent(polymarket_slug: str, polymarket_question: str) -> str:
    """
    Find Kalshi equivalent for a Polymarket market
    
    Returns Kalshi ticker or empty string if no match
    """
    slug_lower = polymarket_slug.lower()
    question_lower = polymarket_question.lower()
    
    # Check weather markets
    for pattern, info in WEATHER_MAPPINGS.items():
        if pattern in slug_lower or pattern in question_lower:
            # Extract date from question/slug
            # Format would be like: "nyc-weather-feb-3-2025" or similar
            # Return series name - would need to construct full ticker
            return info["kalshi_series"]
    
    # Check crypto markets
    for pattern, info in CRYPTO_MAPPINGS.items():
        if pattern in slug_lower or pattern in question_lower:
            return info["kalshi_series"]
    
    return ""


def parse_polymarket_timestamp(question: str) -> str:
    """
    Extract date from Polymarket question
    
    Example: "Will BTC be above $97000 at Feb 3, 2025 2:45pm?"
    Returns: "26FEB031545" (Kalshi format)
    """
    import re
    from datetime import datetime
    
    # Look for date patterns
    # Feb 3, 2025 or Feb 3 2025 or 2025-02-03
    patterns = [
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})',
        r'(\d{4})-(\d{2})-(\d{2})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, question, re.IGNORECASE)
        if match:
            try:
                # Parse and convert to Kalshi format
                # This is simplified - real implementation would need proper parsing
                return "DATE_PLACEHOLDER"
            except:
                pass
    
    return ""


# Export all mappings
ALL_MAPPINGS = {
    **WEATHER_MAPPINGS,
    **CRYPTO_MAPPINGS,
}
