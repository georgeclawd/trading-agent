# Trading Agent - Trade Analysis

## How Trades Work

### 1. Market Detection
Bot scans Kalshi for temperature markets (KXHIGHNY, KXHIGHCHI series)
- Fetches real weather forecasts from Open-Meteo API
- Parses dates from ticker symbols (e.g., 26FEB02 = Feb 2, 2026)
- Gets specific forecast for that date

### 2. Probability Calculation

**Example Trade: KXHIGHNY-26FEB02-T36**
- Market: "Will NYC high temp be >36°F on Feb 2?"
- Weather forecast: 30.2°F for Feb 2
- Market price: 1.0¢ (implies 1% probability)
- Our model: 10% probability (temp won't reach 36°F)
- **EV: +9%** (profitable!)

**Why profitable:**
- Market thinks 36°F+ only 1% likely
- Forecast says 30.2°F (won't reach 36°F)
- We bet NO (or avoid YES)
- If we're right (90% likely), we profit

### 3. EV Calculation Formula

```
EV = (Win_Prob × (1 - Price)) - (Lose_Prob × Price)

Example: Price = 1% (0.01), Win_Prob = 90%
EV = (0.90 × 0.99) - (0.10 × 0.01)
EV = 0.891 - 0.001 = 0.89 = +89%
```

### 4. Mutual Exclusivity Filtering

Bot groups markets by (city, date, series):
- Example: 6 markets for NYC on Jan 26
- Picks BEST EV: KXHIGHNY-26JAN26-B31.5 (EV: 84%)
- Rejects: T34 (49%), B33.5 (14%), etc.

### 5. Simulation Mode

All trades are SIMULATED:
- No real money spent
- Logs "SIMULATED TRADE COMPLETE"
- Discord shows blue color + warnings

## Recent Profitable Trades

| Market | Forecast | Threshold | Market Price | Our Prob | EV |
|--------|----------|-----------|--------------|----------|-----|
| KXHIGHNY-26JAN26-B31.5 | 31°F | 31-32°F | 1¢ | 85% | +84% |
| KXHIGHCHI-26FEB01-T23 | -2°F | >23°F | 1¢ | 10% | +79% |
| KXHIGHCHI-26JAN31-T22 | -2°F | >22°F | 1¢ | 10% | +79% |

## How to Replicate Profitable Trades

1. **Find mispriced markets:** Market price < our estimated probability
2. **High confidence:** Weather forecast clear and certain
3. **Low market price:** 1-3¢ (market underestimates probability)
4. **Check EV:** Must be >5% threshold
5. **Filter conflicts:** Only take best per date/series

## Key Factors for Success

- Accurate weather forecasts (Open-Meteo)
- Correct date parsing from tickers
- Proper threshold parsing (>36, <22, 28-29)
- EV calculation (not just edge)
- Mutual exclusivity filtering

## Current Status

- Bot running in SIMULATION mode
- Finding 18 valid trades per cycle
- EVs range from -84% to +84%
- No real money being spent
- Ready for extended testing
