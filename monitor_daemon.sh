#!/bin/bash
# Background monitoring daemon for Trading Agent

LOG_FILE="/root/clawd/trading-agent/logs/overnight.log"
PID_FILE="/tmp/trading_agent_monitor.pid"

echo "$$" > "$PID_FILE"

echo "$(date '+%Y-%m-%d %H:%M:%S') - Monitor daemon started" >> "$LOG_FILE"

while true; do
    # Check if bot is running
    if ! pgrep -f "python3 src/main.py" > /dev/null; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Bot not running, restarting..." >> "$LOG_FILE"
        cd /root/clawd/trading-agent
        python3 src/main.py >> logs/trading.log 2>&1 &
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Restarted bot with PID $!" >> "$LOG_FILE"
    fi
    
    # Log status every 30 minutes
    if [ $(($(date +%s) % 1800)) -lt 60 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Status check" >> "$LOG_FILE"
        tail -3 /root/clawd/trading-agent/logs/trading.log >> "$LOG_FILE"
        echo "---" >> "$LOG_FILE"
    fi
    
    # Check for profitable trades every hour and log them
    if [ $(($(date +%s) % 3600)) -lt 60 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Checking for profitable trades..." >> "$LOG_FILE"
        grep "SIMULATED TRADE COMPLETE" /root/clawd/trading-agent/logs/trading.log | tail -5 >> "$LOG_FILE"
        echo "---" >> "$LOG_FILE"
    fi
    
    sleep 60
done
