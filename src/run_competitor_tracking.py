"""
Run competitor tracking periodically
"""
import asyncio
import json
import logging
from datetime import datetime
from competitor_tracker import PolymarketTracker, CompetitorWatcher

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('CompetitorTracking')

async def track_competitors():
    """Track all competitors and save data"""
    tracker = PolymarketTracker()
    watcher = CompetitorWatcher(tracker)
    
    # Load profiles
    with open('/root/clawd/trading-agent/data/competitor_profiles.json', 'r') as f:
        data = json.load(f)
    
    profiles = data.get('profiles', [])
    all_results = {}
    
    for profile in profiles:
        name = profile['name']
        address = profile['address']
        
        logger.info(f"🔍 Tracking {name} ({address[:10]}...)")
        
        try:
            result = tracker.track_competitor(name, address)
            all_results[name] = result
            
            # Log summary
            activity_count = len(result.get('activity', []))
            position_count = len(result.get('positions', []))
            logger.info(f"  ✅ {activity_count} activities, {position_count} positions")
            
        except Exception as e:
            logger.error(f"  ❌ Failed to track {name}: {e}")
    
    # Save results
    watcher.save_competitor_data(all_results)
    logger.info("💾 Saved competitor data")
    
    return all_results

if __name__ == "__main__":
    asyncio.run(track_competitors())
