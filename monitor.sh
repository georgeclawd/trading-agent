#!/bin/bash
# Monitor trading bot and report status

LOG_FILE="/root/clawd/trading-agent/logs/trading.log"
PID=$(pgrep -f "python3 src/main.py" | head -1)

echo "=== TRADING BOT MONITOR - $(date) ==="
echo ""

# Check if running
if [ -n "$PID" ]; then
    echo "✅ Bot running (PID: $PID)"
    echo "Runtime: $(ps -p $PID -o etime= 2>/dev/null | tr -d ' ')"
else
    echo "❌ Bot NOT RUNNING"
    echo "Attempting to restart..."
    cd /root/clawd/trading-agent
    nohup python3 src/main.py >> logs/trading.log 2>&1 &
    echo "Restarted with PID: $!"
fi

echo ""
echo "=== RECENT ACTIVITY (last 50 lines) ==="
tail -50 "$LOG_FILE" 2>/dev/null | grep -E "(CYCLE|Strategy|SpreadTrading|WeatherPrediction|opportunit|trades|EV:|Error|Traceback)" | tail -15

echo ""
echo "=== PERFORMANCE SUMMARY ==="
# Count cycles
cycles=$(grep -c "TRADING CYCLE" "$LOG_FILE" 2>/dev/null || echo "0")
echo "Total cycles completed: $cycles"

# Count opportunities
opps=$(grep -c "✓ PASSED" "$LOG_FILE" 2>/dev/null || echo "0")
echo "Opportunities found: $opps"

# Check for errors
errors=$(grep -c "Error\|Traceback\|Exception" "$LOG_FILE" 2>/dev/null || echo "0")
if [ "$errors" -gt 0 ]; then
    echo "⚠️  Errors found: $errors"
    grep -E "(Error|Traceback)" "$LOG_FILE" | tail -3
else
    echo "✅ No errors detected"
fi

echo ""
echo "Next check in 5 minutes..."
