"""
Price Lag Measurement Tool

Compares Polymarket vs Kalshi prices in real-time to measure latency.
Logs timestamp differences and price divergences.
"""

import asyncio
import logging
import json
from datetime import datetime, timezone, timedelta
from collections import deque

logger = logging.getLogger('PriceLagMonitor')


class PriceLagMonitor:
    """Monitor and measure lag between Polymarket and Kalshi prices"""
    
    def __init__(self, kalshi_client):
        self.client = kalshi_client
        self.running = False
        
        # Track price history for lag calculation
        self.pm_history = deque(maxlen=1000)  # Polymarket price history
        self.kalshi_history = deque(maxlen=1000)  # Kalshi price history
        
        # Current prices
        self.current_pm = {}  # {crypto: price}
        self.current_kalshi = {}  # {crypto: price}
        
        # Lag measurements
        self.lag_measurements = []  # List of measured lags
        
        logger.info("🔍 Price Lag Monitor initialized")
    
    async def get_polymarket_price(self, crypto: str) -> float:
        """
        Get current price from Polymarket for a crypto.
        For now, we'll use baguette's recent trade prices as proxy.
        """
        from competitor_tracker import PolymarketTracker
        
        tracker = PolymarketTracker()
        address = '0xe00740bce98a594e26861838885ab310ec3b548c'
        
        try:
            activity = tracker.get_user_activity(address, limit=5)
            
            for trade in activity:
                if trade.get('type') != 'TRADE':
                    continue
                
                slug = trade.get('slug', '')
                parts = slug.split('-')
                if len(parts) < 1:
                    continue
                
                trade_crypto = parts[0].upper()
                if trade_crypto == 'BITCOIN':
                    trade_crypto = 'BTC'
                elif trade_crypto == 'ETHEREUM':
                    trade_crypto = 'ETH'
                elif trade_crypto == 'SOLANA':
                    trade_crypto = 'SOL'
                
                if trade_crypto == crypto:
                    price = float(trade.get('price', 0))
                    timestamp = trade.get('timestamp', '')
                    return price, timestamp
            
            return None, None
            
        except Exception as e:
            logger.error(f"Error getting Polymarket price: {e}")
            return None, None
    
    async def get_kalshi_price(self, crypto: str) -> float:
        """Get current price from Kalshi for a crypto"""
        series_map = {
            'BTC': 'KXBTC15M',
            'ETH': 'KXETH15M', 
            'SOL': 'KXSOL15M'
        }
        
        series = series_map.get(crypto)
        if not series:
            return None, None
        
        try:
            # Get current window market
            markets = self.client.get_markets(series_ticker=series, limit=10)
            
            now = datetime.now(timezone.utc)
            current_minute = now.minute
            window_start_minute = (current_minute // 15) * 15
            window_end = now.replace(minute=window_start_minute, second=0, microsecond=0) + timedelta(minutes=15)
            
            for m in markets:
                if m.get('status') != 'active':
                    continue
                
                close_time = m.get('close_time', '')
                if close_time:
                    close_dt = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
                    if close_dt == window_end:
                        # Get detailed price
                        r = self.client._request("GET", f"/markets/{m['ticker']}")
                        if r.status_code == 200:
                            market = r.json().get('market', {})
                            # Return mid price (bid+ask)/2
                            bid = market.get('yes_bid', 0)
                            ask = market.get('yes_ask', 0)
                            if bid > 0 and ask > 0:
                                mid = (bid + ask) / 2 / 100  # Convert cents to decimal
                                return mid, datetime.now(timezone.utc).isoformat()
                            elif bid > 0:
                                return bid / 100, datetime.now(timezone.utc).isoformat()
            
            return None, None
            
        except Exception as e:
            logger.error(f"Error getting Kalshi price: {e}")
            return None, None
    
    async def measure_lag(self, crypto: str):
        """Measure the lag between Polymarket and Kalshi for a crypto"""
        pm_price, pm_ts = await self.get_polymarket_price(crypto)
        kalshi_price, kalshi_ts = await self.get_kalshi_price(crypto)
        
        if pm_price is None or kalshi_price is None:
            return None
        
        # Store in history
        now = datetime.now(timezone.utc)
        
        self.pm_history.append({
            'crypto': crypto,
            'price': pm_price,
            'timestamp': now.isoformat(),
            'source': 'polymarket'
        })
        
        self.kalshi_history.append({
            'crypto': crypto,
            'price': kalshi_price,
            'timestamp': now.isoformat(),
            'source': 'kalshi'
        })
        
        # Calculate price difference
        price_diff = abs(pm_price - kalshi_price)
        price_diff_pct = (price_diff / pm_price * 100) if pm_price > 0 else 0
        
        # Find lag by looking for when Kalshi catches up
        # Look back in PM history to find when PM had Kalshi's current price
        lag_seconds = None
        
        for i, pm_record in enumerate(reversed(self.pm_history)):
            if pm_record['crypto'] == crypto:
                if abs(pm_record['price'] - kalshi_price) < 0.01:  # Within 1 cent
                    # Found it - PM had this price i records ago
                    lag_seconds = i * 5  # Assuming 5 second intervals
                    break
        
        result = {
            'timestamp': now.isoformat(),
            'crypto': crypto,
            'polymarket_price': pm_price,
            'kalshi_price': kalshi_price,
            'price_diff': price_diff,
            'price_diff_pct': price_diff_pct,
            'estimated_lag_seconds': lag_seconds,
            'polymarket_lead': pm_price > kalshi_price
        }
        
        self.lag_measurements.append(result)
        
        return result
    
    async def run(self, duration_minutes=60):
        """Run the lag monitor for specified duration"""
        logger.info(f"🔍 Starting Price Lag Monitor for {duration_minutes} minutes")
        logger.info("=" * 70)
        
        self.running = True
        start_time = datetime.now(timezone.utc)
        
        cryptos = ['BTC', 'ETH', 'SOL']
        
        while self.running:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
            
            if elapsed >= duration_minutes:
                logger.info("=" * 70)
                logger.info("⏰ Monitoring complete - generating report")
                await self._generate_report()
                break
            
            logger.info(f"\n⏱️  Elapsed: {int(elapsed)}m | Measuring lag...")
            
            for crypto in cryptos:
                result = await self.measure_lag(crypto)
                
                if result:
                    lag_str = f"{result['estimated_lag_seconds']}s" if result['estimated_lag_seconds'] else "Unknown"
                    lead_str = "PM leads" if result['polymarket_lead'] else "Kalshi leads"
                    
                    logger.info(f"   {crypto}:")
                    logger.info(f"     Polymarket: {result['polymarket_price']:.3f}")
                    logger.info(f"     Kalshi:     {result['kalshi_price']:.3f}")
                    logger.info(f"     Diff:       {result['price_diff']:.3f} ({result['price_diff_pct']:.1f}%)")
                    logger.info(f"     Lag:        {lag_str} ({lead_str})")
                else:
                    logger.info(f"   {crypto}: Could not measure")
            
            # Wait 10 seconds between measurements
            await asyncio.sleep(10)
    
    async def _generate_report(self):
        """Generate final lag analysis report"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 PRICE LAG ANALYSIS REPORT")
        logger.info("=" * 70)
        
        if not self.lag_measurements:
            logger.info("No measurements collected")
            return
        
        # Calculate average lag per crypto
        for crypto in ['BTC', 'ETH', 'SOL']:
            crypto_measurements = [m for m in self.lag_measurements if m['crypto'] == crypto]
            
            if not crypto_measurements:
                continue
            
            # Average price difference
            avg_diff = sum(m['price_diff'] for m in crypto_measurements) / len(crypto_measurements)
            avg_diff_pct = sum(m['price_diff_pct'] for m in crypto_measurements) / len(crypto_measurements)
            
            # Average lag (only where we could measure)
            lags = [m['estimated_lag_seconds'] for m in crypto_measurements if m['estimated_lag_seconds']]
            avg_lag = sum(lags) / len(lags) if lags else None
            
            # How often PM leads
            pm_leads = sum(1 for m in crypto_measurements if m['polymarket_lead'])
            pm_lead_pct = (pm_leads / len(crypto_measurements)) * 100
            
            logger.info(f"\n{crypto}:")
            logger.info(f"   Measurements: {len(crypto_measurements)}")
            logger.info(f"   Avg price diff: {avg_diff:.3f} ({avg_diff_pct:.1f}%)")
            logger.info(f"   Avg lag: {avg_lag:.1f}s" if avg_lag else "   Avg lag: Unknown")
            logger.info(f"   PM leads: {pm_lead_pct:.0f}% of time")
        
        # Overall conclusion
        logger.info("\n" + "=" * 70)
        logger.info("💡 CONCLUSION:")
        logger.info("=" * 70)
        
        all_lags = [m['estimated_lag_seconds'] for m in self.lag_measurements if m['estimated_lag_seconds']]
        if all_lags:
            overall_avg_lag = sum(all_lags) / len(all_lags)
            logger.info(f"   Estimated Kalshi lag: {overall_avg_lag:.1f} seconds behind Polymarket")
        else:
            logger.info("   Could not determine lag - prices may be too different")
        
        # Save detailed data
        with open('logs/price_lag_analysis.json', 'w') as f:
            json.dump({
                'measurements': self.lag_measurements,
                'pm_history': list(self.pm_history),
                'kalshi_history': list(self.kalshi_history)
            }, f, indent=2, default=str)
        
        logger.info(f"\n   Detailed data saved to: logs/price_lag_analysis.json")
        logger.info("=" * 70)


# Standalone execution
if __name__ == "__main__":
    import sys
    sys.path.insert(0, 'src')
    from kalshi_client import KalshiClient
    import subprocess
    
    # Get credentials
    api_key_id = subprocess.run(['pass', 'show', 'kalshi/api_key_id'], capture_output=True, text=True).stdout.strip().splitlines()[0]
    api_key = subprocess.run(['pass', 'show', 'kalshi/api_key'], capture_output=True, text=True).stdout.strip()
    
    client = KalshiClient(api_key_id=api_key_id, api_key=api_key, demo=False)
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/price_lag.log'),
            logging.StreamHandler()
        ]
    )
    
    # Run monitor
    monitor = PriceLagMonitor(client)
    asyncio.run(monitor.run(duration_minutes=60))  # Run for 1 hour
