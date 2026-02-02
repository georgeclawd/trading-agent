# Kalshi Market Structure - Complete Discovery

## Overview
Kalshi has **8,225 series** across 16+ categories.

## Market Endpoints

### 1. Markets
- `GET /markets` - List all markets
  - Query params: `status`, `limit`, `series_ticker`, `cursor`
- `GET /markets/{ticker}` - Specific market details
- `GET /markets/{ticker}/orderbook` - YES/NO orderbook

### 2. Series
- `GET /series` - List all 8,225 series
- `GET /series/{ticker}` - Specific series info
- `GET /series/{ticker}/markets` - Markets in series

### 3. Events
- `GET /events/{event_ticker}` - Event details with markets

### 4. Portfolio
- `GET /portfolio/positions` - Current positions
- `GET /portfolio/balance` - Account balance
- `GET /orders` - Open orders

## Categories (by volume)

| Category | Series Count | Opportunity |
|----------|--------------|-------------|
| Politics | 2,279 | High volume, news-driven |
| Entertainment | 2,105 | Awards, releases |
| Sports | 1,171 | Games, stats |
| Elections | 532 | Results, outcomes |
| **Climate/Weather** | **241** | **Our focus** |
| Economics | 387 | Jobs, inflation |
| Financials | 173 | Stocks, crypto |
| Crypto | 205 | Bitcoin, ETH |

## Weather Series (241 total)

We were scanning: **3 series** (NYC, Chicago, LA)
Available: **241 series**

### Temperature Series:
- KXHIGHNY - Highest temperature in NYC
- KXHIGHCHI - Highest temperature in Chicago
- KXHIGHLA - Highest temperature in LA
- KXHIGHSF - Highest temperature in SF
- KXHIGHPHI - Highest temperature in Philadelphia
- KXHIGHSAT - Highest temperature in Seattle
- KXHIGHMIA - Highest temperature in Miami
- Plus 200+ more cities

### Other Weather:
- Arctic sea ice
- Hurricane predictions
- Natural disasters
- Rainfall/snowfall
- Climate change metrics

## Trading Strategy Opportunities

### Current (Limited):
- 3 cities (NYC, CHI, LA)
- ~100 markets

### Expanded (Full):
- 241 weather series
- ~10,000+ markets
- Multiple cities, dates, thresholds

### New Approach:
1. Scan ALL 241 weather series
2. Filter by: volume > $500, date within 5 days
3. Analyze ~200 markets per scan
4. Trade spreads on cheap markets (1-10%)

## Implementation Notes

### Series Structure:
```json
{
  "ticker": "KXHIGHNY",
  "title": "Highest temperature in NYC",
  "category": "Climate and Weather",
  "tags": ["Daily temperature"],
  "frequency": "daily",
  "settlement_sources": [...]
}
```

### Market Discovery:
```python
# Get all weather series
response = client._request("GET", "/series")
series = response.json()['series']
weather = [s for s in series if s['category'] == 'Climate and Weather']

# Get markets for each series
for s in weather:
    markets = client.get_markets(series_ticker=s['ticker'], limit=50)
```

## Next Steps

1. Expand bot to scan all 241 weather series
2. Implement series-based market discovery
3. Add more cities to trading strategy
4. Filter by liquidity and date

## API Limits

Current issue: Weather API rate limiting
Solution: OpenWeather API (1000 calls/day)

---

*Discovered: 2026-02-02*
*Total Series: 8,225*
*Weather Series: 241*
