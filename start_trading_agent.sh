#!/bin/bash
cd /root/clawd/trading-agent
source /root/.bashrc 2>/dev/null

# Log startup
echo "[$(date)] Starting Trading Agent..." >> logs/trading.log

# Run the agent
python3 src/main.py >> logs/trading.log 2>&1 &
PID=$!
echo $PID > trading_agent.pid

echo "[$(date)] Trading Agent started with PID: $PID" >> logs/trading.log
echo "Trading Agent running (PID: $PID)"
