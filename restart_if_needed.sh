#!/bin/bash
if ! pgrep -f "python3 src/main.py" > /dev/null; then
    cd /root/clawd/trading-agent
    echo "$(date): Bot stopped, restarting..." >> logs/overnight.log
    python3 src/main.py >> logs/trading.log 2>&1 &
fi
