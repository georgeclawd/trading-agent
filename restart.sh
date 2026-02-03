#!/bin/bash
# Restart trading bot

cd /root/clawd/trading-agent

# Kill existing
pkill -9 -f "src/main.py" 2>/dev/null
sleep 3

# Clear logs
> logs/trading.log

# Start
nohup python3 src/main.py > logs/trading.log 2>&1 &
echo $! > /tmp/bot.pid

echo "Bot restarted"
sleep 2
ps aux | grep "python3 src/main" | grep -v grep