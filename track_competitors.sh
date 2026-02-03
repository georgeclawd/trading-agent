#!/bin/bash
cd /root/clawd/trading-agent
python3 src/run_competitor_tracking.py >> logs/competitor_tracking.log 2>&1
