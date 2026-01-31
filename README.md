# Trading Agent

Autonomous trading system for Polymarket and crypto markets.

## Architecture

```
Trading Agent
├── Market Scanner (find +EV opportunities)
├── Risk Manager (Kelly criterion, bankroll management)
├── Trade Executor (Polymarket API, wallet management)
├── Portfolio Tracker (PNL, exposure, performance)
└── Alert System (Discord notifications)
```

## Risk Management Strategy

Dynamic position sizing based on performance (poker-style):

| Bankroll | Position Size | Risk Level | Criteria |
|----------|---------------|------------|----------|
| $100 | $1-2 | Conservative | Initial testing phase |
| $120+ | $2-4 | Moderate | 3+ consecutive wins |
| $150+ | $4-8 | Aggressive | Win rate > 60%, hot streak |
| $80 | $0.50-1 | Tight | Downswing, < 50% win rate |

## Kelly Criterion

Position size = (Win Probability × Odds - Loss Probability) / Odds × Bankroll %

Adjusted for volatility: Kelly % × 0.25 (fractional Kelly)

## Markets Traded

- Polymarket prediction markets
- Crypto price predictions
- Sports (Premier League, etc.)
- Weather markets
- Political events
- Any +EV opportunity

## Configuration

See `config/trading_config.yaml` for settings.

## Running

```bash
python3 src/main.py
```

## Safety

- Max 5% of bankroll per trade
- Daily loss limit: 20% of bankroll
- Auto-stop on consecutive losses
- All trades logged to Discord
