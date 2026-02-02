# Trading Bot - Dry Run & Position Persistence Design

## Requirements
1. **Position Persistence** - Save all open positions to disk
2. **Dry Run Mode** - Simulate trades without real money for weather strategies
3. **Trade Tracking** - Track simulated trades and their hypothetical outcomes
4. **Real Trading** - CryptoMomentum trades with real money
5. **Graceful Recovery** - Handle crashes, restarts, API failures

## Architecture

### 1. Position Management System
```
positions/
├── positions.json          # Current open positions
├── simulated_positions.json # Simulated (dry run) positions  
└── trade_history.json      # All trades (real + simulated)
```

### 2. Position Schema
```json
{
  "ticker": "KXBTC15M-T1230-B98",
  "side": "YES",
  "contracts": 5,
  "entry_price": 45,
  "entry_time": "2026-02-02T18:30:00",
  "strategy": "CryptoMomentum",
  "simulated": false,
  "status": "open",
  "expected_settlement": "2026-02-02T19:00:00",
  "market_title": "BTC above $98k at 12:30"
}
```

### 3. Configuration
```yaml
strategies:
  CryptoMomentum:
    enabled: true
    real_trading: true      # Real money
    max_position: 10
    
  WeatherPrediction:
    enabled: true
    dry_run: true           # Simulated only
    track_performance: true # Track hypothetical P&L
    
  LongshotWeather:
    enabled: true
    dry_run: true
    track_performance: true
    
  SpreadTrading:
    enabled: true
    dry_run: true
    track_performance: true
```

### 4. Position Manager Class
```python
class PositionManager:
    - load_positions()      # Load from disk on startup
    - save_positions()      # Save to disk atomically
    - open_position()       # Record new position
    - close_position()      # Record settlement
    - reconcile_positions() # Check vs exchange API
    - get_simulated_pnl()   # Calculate hypothetical P&L
    - get_real_pnl()        # Calculate actual P&L
```

### 5. Dry Run Execution Flow
1. Strategy identifies opportunity
2. PositionManager records simulated position (no API call)
3. Track market price movement
4. At settlement, calculate hypothetical P&L
5. Log "would have made $X.XX"

### 6. Real Trading Execution Flow
1. Strategy identifies opportunity
2. Execute real order via Kalshi API
3. PositionManager records real position
4. Monitor for settlement
5. Record actual P&L

### 7. Recovery Scenarios

**Scenario A: Bot crashes mid-trade**
- Position saved to disk before API call
- On restart, check for "pending" positions
- Reconcile with exchange API
- Mark as filled or failed

**Scenario B: API call succeeds but save fails**
- Atomic file operations prevent corruption
- On restart, reconcile with exchange
- Rebuild position state from API

**Scenario C: Market settles while bot down**
- On restart, fetch recent settlements
- Close any positions that settled
- Calculate P&L

### 8. Weekly Competition Tracking
```
Strategy Performance (Week of 2026-02-02):
┌───────────────────┬─────────┬─────────┬─────────┬──────────┐
│ Strategy          │ Trades  │ Win %   │ P&L     │ Status   │
├───────────────────┼─────────┼─────────┼─────────┼──────────┤
│ CryptoMomentum    │ 12      │ 58%     │ +$23.40 │ REAL     │
│ WeatherPrediction │ 8       │ 75%     │ +$18.50 │ SIMULATED│
│ LongshotWeather   │ 3       │ 33%     │ -$5.00  │ SIMULATED│
│ SpreadTrading     │ 5       │ 60%     │ +$12.30 │ SIMULATED│
└───────────────────┴─────────┴─────────┴─────────┴──────────┘

Winner: CryptoMomentum (+$23.40 real money)
```

## Implementation Order

1. Position persistence layer (atomic writes, validation)
2. PositionManager class
3. Dry run mode in BaseStrategy
4. Update each strategy for dry_run config
5. Weekly performance tracking/reporting
6. Recovery/reconciliation logic

## Edge Cases to Handle

- Position file corrupted → Backup and start fresh
- Exchange API down → Queue trades, retry with backoff
- Partial fill → Track average entry price
- Market cancelled → Remove position, log reason
- Duplicate position detection → Prevent double-counting
- Timezone issues → All times in UTC
