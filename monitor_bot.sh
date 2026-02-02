#!/bin/bash
cd /root/clawd/trading-agent

# Check if bot is running
if ! pgrep -f "python3 src/main.py" > /dev/null; then
    echo "$(date): Bot stopped, restarting..." >> logs/overnight.log
    python3 src/main.py >> logs/trading.log 2>&1 &
    echo "$(date): Restarted with PID $!" >> logs/overnight.log
fi

# Log current status
echo "$(date): Bot status check" >> logs/overnight.log
tail -5 logs/trading.log >> logs/overnight.log
echo "---" >> logs/overnight.log
