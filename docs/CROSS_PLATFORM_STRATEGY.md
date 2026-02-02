# Trading Agent v2.0 - Cross-Platform Strategy
## Polymarket (Signals) → Kalshi (Execution)

### Core Concept
Use Polymarket as an **information oracle** to make profitable trades on Kalshi.

```
┌─────────────────┐     Detect Signal      ┌─────────────────┐
│   POLYMARKET    │ ─────────────────────→ │     KALSHI      │
│  (Signal Source)│                        │  (Execution)    │
│                 │                        │                 │
│ • Whale moves   │    Same event,         │ • Place trade   │
│ • Insider flow  │    better odds         │ • Legal/Regulated
│ • Smart money   │                        │ • Withdraw profit
│ • Order flow    │                        │                 │
└─────────────────┘                        └─────────────────┘
```

---

## Strategy Components

### 1. Signal Detection (Polymarket)

**What to watch:**
- Whale wallet transactions
- Unusual order flow vs retail
- Large positions opening
- Rapid price movements

**Signal Types:**
| Signal | Description | Strength |
|--------|-------------|----------|
| Whale Buy | Large wallet buys YES while retail sells | ⭐⭐⭐⭐⭐ |
| Insider Flow | Wallet with history of correct calls | ⭐⭐⭐⭐⭐ |
| Order Imbalance | 70%+ retail on one side, smart money opposite | ⭐⭐⭐⭐ |
| Price Spike | Sudden 10%+ move with volume | ⭐⭐⭐ |

### 2. Market Matching (Cross-Platform)

**Find same events on both platforms:**

| Event Type | Polymarket Market | Kalshi Market |
|------------|-------------------|---------------|
| Weather | "NYC Rain Tomorrow?" | "NYC >0.1in rain Feb 2?" |
| Crypto | "BTC >$100k by March?" | "BTC above 100k end of month?" |
| Sports | "Seahawks win Super Bowl?" | "NFL Championship winner?" |
| Economics | "CPI >3% next month?" | "CPI YoY above 3%?" |

**Matching Algorithm:**
1. Normalize event text (remove dates, simplify)
2. Compare semantic similarity
3. Verify same underlying outcome
4. Check both markets are open

### 3. Execution (Kalshi)

**When to trade:**
- Signal detected on Polymarket
- Same market found on Kalshi
- Odds on Kalshi are favorable
- Position size fits risk profile

**Entry criteria:**
- Minimum signal strength: 3/5 stars
- Kalshi odds must be within 5% of Polymarket
- Max 2% of bankroll per trade
- Daily limit: 5 trades max

---

## Information Arbitrage Examples

### Example 1: Weather Insider
**Scenario:**
- Weather API shows 85% chance of rain in NYC tomorrow
- Polymarket: Trading at 70% (retail underestimating)
- Whale buys $50k YES at 0.70
- Kalshi: Same market at 0.72

**Action:**
- Detect whale trade on Polymarket
- Buy YES on Kalshi at 0.72
- Expected value: 85% - 72% = 13% edge

### Example 2: Crypto Whale
**Scenario:**
- BTC approaching $100k resistance
- Polymarket whale suddenly buys "BTC >$100k by Friday"
- May have insider info (ETF approval, institutional buy)
- Kalshi has similar market

**Action:**
- Copy whale's position on Kalshi
- Smaller size ($100 vs whale's $10k)
- Ride the information edge

### Example 3: Sports Fixed Match
**Scenario:**
- Whale with history of correct sports bets
- Suddenly dumps position on favorite team
- Possible insider knowledge (injury, fixing)
- Retail still betting on favorite

**Action:**
- Opposite trade on Kalshi
- Bet against favorite
- Profit when insider proven right

---

## Kalshi API Structure

### Authentication
- **Method:** API Key (simple!)
- **Endpoint:** `https://trading-api.kalshi.com/trade-api/v2/`
- **Headers:** `Authorization: Bearer <token>`

### Key Endpoints
| Endpoint | Purpose |
|----------|---------|
| `GET /markets` | List all markets |
| `GET /markets/{id}` | Market details, orderbook |
| `POST /orders` | Place order |
| `GET /portfolio/positions` | Current positions |
| `GET /balance` | Account balance |
| `WebSocket /ws/market` | Real-time price updates |

### Markets Available
- **Weather:** Rain, snow, temperature, hurricanes
- **Crypto:** BTC, ETH price levels
- **Economics:** CPI, jobs, Fed decisions
- **Politics:** Elections, legislation
- **Sports:** NFL, NBA, etc.

---

## Implementation Plan

### Phase 1: Kalshi Connection
1. Get Kalshi API credentials
2. Test market data fetching
3. Place first test order ($1)
4. Verify execution and settlement

### Phase 2: Polymarket Monitoring
1. Monitor public market data (no auth needed for prices)
2. Track price movements
3. Identify unusual flow
4. Build signal detection

### Phase 3: Cross-Platform Matching
1. Match events between platforms
2. Build market mapping database
3. Test signal-to-execution pipeline
4. Paper trade for 1 week

### Phase 4: Live Trading
1. Deploy with $100 bankroll
2. Conservative position sizing (1-2%)
3. Monitor performance daily
4. Scale up after proven edge

---

## Risk Management

### Cross-Platform Specific Risks
| Risk | Mitigation |
|------|------------|
| Signal false positive | Require 2+ confirmation signals |
| Market mismatch | Verify same underlying event |
| Execution delay | Use market orders for speed |
| Kalshi rejection | Check market liquidity first |
| Polymarket data lag | Use WebSocket for real-time |

### Position Sizing
- **Base:** 1% of bankroll per signal
- **High confidence (4-5⭐):** 2% max
- **Maximum:** 5 trades per day
- **Stop daily:** If 3 losses in a row

---

## Performance Metrics

### Key Metrics to Track
1. **Signal Accuracy:** % of whale trades that are profitable
2. **Execution Speed:** Time from signal to filled order
3. **Cross-Platform Correlation:** Do both markets resolve the same?
4. **Edge Capture:** Are we getting the expected EV?
5. **Overall ROI:** Total profit/loss

### Success Criteria
- **Month 1:** Prove signal edge (>55% win rate)
- **Month 2:** Scale to $5-10 per trade
- **Month 3:** Target $50-100 profit/week

---

## Next Steps

### Immediate (This Week)
1. ✅ Create Kalshi account
2. ✅ Complete KYC
3. ✅ Generate API keys
4. ✅ Deposit $100
5. ✅ Test API connection

### Short Term (Next Week)
1. Build Kalshi order executor
2. Build Polymarket price monitor
3. Create event matching algorithm
4. Paper trade for validation

### Medium Term (Month 1)
1. Deploy live with small size
2. Collect performance data
3. Optimize signal detection
4. Scale position sizes

---

## Resources

### Kalshi
- Docs: https://docs.kalshi.com
- API Reference: https://trading-api.readme.io
- Markets: https://kalshi.com/markets

### Polymarket (Signal Source)
- Markets: https://polymarket.com/explore
- API: https://docs.polymarket.com (for data, not trading)
- Explorer: https://polygonscan.com (track wallets)

### Data Sources
- Weather: Open-Meteo (free)
- Crypto: CoinGecko (free tier)
- Sports: Various APIs

---

**Ready to start with Kalshi setup?** 🚀
