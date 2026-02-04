"""
Longshot Weather Strategy - The $64K Weather Bot Algorithm
Based on: Vibe-coded AI bot that made $64K trading weather

Strategy:
1. Target ONLY cheap weather markets (<10¢)
2. Calculate probability with ±3.5°F deviation
3. Edge = (fair_price - market_price) / market_price
4. Buy when edge is significant

Markets: London, NYC, Seoul (original bot cities)
"""

from typing import Dict, List, Optional, Tuple
from strategy_framework import BaseStrategy
from datetime import datetime, timedelta
import logging
import aiohttp
import asyncio

logger = logging.getLogger('LongshotWeather')


class LongshotWeatherStrategy(BaseStrategy):
    """
    The $64K weather bot strategy - proven to work
    
    Key differences from WeatherPrediction:
    - Only trades cheap markets (<10¢)
    - Uses ±3.5°F deviation model
    - Edge = (fair - market) / market
    - Targets longshots with high ROI potential
    """
    
    def __init__(self, config: Dict, client, market_scanner=None, position_manager=None):
        super().__init__(config, client, position_manager)
        self.name = "LongshotWeather"
        self.market_scanner = market_scanner
        
        # Strategy parameters (from $64K bot)
        self.max_market_price = 0.20  # Only markets < 20¢ (adjusted for Kalshi)
        self.min_liquidity = 50  # $50 minimum
        self.deviation_f = 3.5  # ±3.5°F deviation
        self.min_edge = 0.20  # Minimum 20% edge for cheap markets
        self.max_position = config.get('max_position_size', 5)
        
        # Cities to monitor (Kalshi weather markets)
        self.cities = {
            'New York': {'lat': 40.7128, 'lon': -74.0060, 'kalshi_key': ['NYC', 'New York']},
            'Chicago': {'lat': 41.8781, 'lon': -87.6298, 'kalshi_key': ['CHI', 'Chicago']},
            'Philadelphia': {'lat': 39.9526, 'lon': -75.1652, 'kalshi_key': ['PHIL', 'Philadelphia']},
            'Los Angeles': {'lat': 34.0522, 'lon': -118.2437, 'kalshi_key': ['LAX', 'Los Angeles']},
            'Seattle': {'lat': 47.6062, 'lon': -122.3321, 'kalshi_key': ['SEA', 'Seattle']},
            'Houston': {'lat': 29.7604, 'lon': -95.3698, 'kalshi_key': ['HOU', 'Houston']},
        }
        
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def fetch_weather_forecast(self, city: str, lat: float, lon: float) -> Optional[Dict]:
        """Fetch weather forecast from OpenWeather"""
        import subprocess
        
        try:
            api_key = subprocess.run(
                ['pass', 'show', 'openweather/api-key'],
                capture_output=True, text=True
            ).stdout.strip().splitlines()[0]
        except:
            logger.error(f"Could not get OpenWeather API key")
            return None
        
        session = await self._get_session()
        
        try:
            url = (
                f"https://api.openweathermap.org/data/2.5/forecast?"
                f"lat={lat}&lon={lon}&appid={api_key}&units=imperial"
            )
            
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Extract daily forecasts
                    daily_temps = {}
                    for item in data.get('list', []):
                        dt = datetime.fromtimestamp(item['dt'])
                        date_str = dt.strftime('%Y-%m-%d')
                        
                        if date_str not in daily_temps:
                            daily_temps[date_str] = {'highs': [], 'lows': [], 'avgs': []}
                        
                        temp = item['main']['temp']
                        temp_max = item['main']['temp_max']
                        temp_min = item['main']['temp_min']
                        
                        daily_temps[date_str]['avgs'].append(temp)
                        daily_temps[date_str]['highs'].append(temp_max)
                        daily_temps[date_str]['lows'].append(temp_min)
                    
                    # Calculate daily stats
                    result = {}
                    for date, temps in daily_temps.items():
                        result[date] = {
                            'high': max(temps['highs']),
                            'low': min(temps['lows']),
                            'avg': sum(temps['avgs']) / len(temps['avgs'])
                        }
                    
                    return result
                    
        except Exception as e:
            logger.debug(f"Weather fetch error for {city}: {e}")
        
        return None
    
    def calculate_probability_with_deviation(self, forecast_high: float, 
                                             forecast_low: float, threshold: float,
                                             is_above: bool = True) -> float:
        """
        Calculate probability using ±3.5°F deviation model
        
        This is the key insight from the $64K bot - weather forecasts
        have natural deviation, so we model probability as a range
        """
        if is_above:
            # Probability temp > threshold
            # If forecast_high - deviation > threshold, high probability
            # If forecast_high + deviation < threshold, low probability
            
            optimistic = forecast_high + self.deviation_f
            pessimistic = forecast_high - self.deviation_f
            
            if pessimistic > threshold:
                return 0.85  # Very likely
            elif optimistic < threshold:
                return 0.15  # Very unlikely
            else:
                # Linear interpolation between pessimistic and optimistic
                range_size = optimistic - pessimistic
                position = threshold - pessimistic
                prob = 1 - (position / range_size)
                return max(0.15, min(0.85, prob))
        else:
            # Probability temp < threshold
            optimistic = forecast_low - self.deviation_f
            pessimistic = forecast_low + self.deviation_f
            
            if pessimistic < threshold:
                return 0.85
            elif optimistic > threshold:
                return 0.15
            else:
                range_size = optimistic - pessimistic
                position = threshold - optimistic
                prob = position / range_size
                return max(0.15, min(0.85, prob))
    
    def calculate_edge(self, fair_price: float, market_price: float) -> float:
        """
        Calculate edge using $64K bot formula:
        edge = (fair_price - market_price) / market_price
        
        This gives higher edge for cheap markets (where market_price is small)
        """
        if market_price <= 0:
            return 0
        return (fair_price - market_price) / market_price
    
    def extract_city_from_market(self, title: str, ticker: str) -> Optional[Tuple[str, Dict]]:
        """
        Dynamically extract city from market title/ticker
        Returns (city_name, city_data) or None
        """
        title_lower = title.lower()
        ticker_lower = ticker.lower()
        
        # Check known cities first
        for city, data in self.cities.items():
            kalshi_keys = data.get('kalshi_key', [])
            for key in kalshi_keys:
                if key.lower() in title_lower or key.lower() in ticker_lower:
                    return city, data
        
        # Try to extract city from title patterns
        # Pattern: "high temp in [CITY]" or "[CITY] temperature"
        import re
        
        # Common city names to check
        city_patterns = {
            'New York': {'lat': 40.7128, 'lon': -74.0060},
            'Chicago': {'lat': 41.8781, 'lon': -87.6298},
            'Philadelphia': {'lat': 39.9526, 'lon': -75.1652},
            'Los Angeles': {'lat': 34.0522, 'lon': -118.2437},
            'Seattle': {'lat': 47.6062, 'lon': -122.3321},
            'Houston': {'lat': 29.7604, 'lon': -95.3698},
            'Miami': {'lat': 25.7617, 'lon': -80.1918},
            'Boston': {'lat': 42.3601, 'lon': -71.0589},
            'Denver': {'lat': 39.7392, 'lon': -104.9903},
            'Atlanta': {'lat': 33.7490, 'lon': -84.3880},
            'Phoenix': {'lat': 33.4484, 'lon': -112.0740},
            'London': {'lat': 51.5074, 'lon': -0.1278},
            'Seoul': {'lat': 37.5665, 'lon': 126.9780},
            'Tokyo': {'lat': 35.6762, 'lon': 139.6503},
        }
        
        for city_name, coords in city_patterns.items():
            if city_name.lower() in title_lower:
                return city_name, coords
        
        return None, None
    
    async def scan(self) -> List[Dict]:
        """Scan for longshot weather opportunities - DYNAMIC DISCOVERY"""
        opportunities = []
        
        logger.info("  LongshotWeather: Dynamically discovering liquid weather markets...")
        
        # Fetch ALL climate/weather series dynamically
        try:
            response = self.client._request("GET", "/series")
            all_series = response.json().get('series', [])
            climate_series = [s['ticker'] for s in all_series if 'Climate' in s.get('category', '') or 'Weather' in s.get('category', '')]
            logger.info(f"  LongshotWeather: Found {len(climate_series)} climate/weather series")
        except Exception as e:
            logger.error(f"  LongshotWeather: Error fetching series list: {e}")
            climate_series = []
        
        # Get markets by series (not by status filter)
        all_weather_markets = []
        for series in climate_series[:50]:  # Limit to 50 series for performance
            try:
                response = self.client._request("GET", f"/markets?series_ticker={series}&limit=20")
                markets = response.json().get('markets', [])
                all_weather_markets.extend(markets)
            except Exception as e:
                logger.debug(f"  LongshotWeather: Error fetching {series}: {e}")
                continue
        
        logger.info(f"  LongshotWeather: Found {len(all_weather_markets)} total weather markets from series")
        
        # First pass: Find weather markets with ACTUAL LIQUIDITY
        liquid_weather = []
        for m in all_weather_markets:
            title = m.get('title', '')
            ticker = m.get('ticker', '')
            
            # Check for liquidity (this is the key filter)
            try:
                orderbook_response = self.client.get_orderbook(ticker)
                # Kalshi returns {'orderbook': {'yes': [...], 'no': [...]}}
                orderbook = orderbook_response.get('orderbook', {})
                yes_bids = orderbook.get('yes', [])
                no_bids = orderbook.get('no', [])
                
                if yes_bids and no_bids:
                    # Prices are in format [[price_cents, volume], ...]
                    yes_price_cents = yes_bids[0][0] if isinstance(yes_bids[0], list) else yes_bids[0].get('price', 100)
                    no_price_cents = no_bids[0][0] if isinstance(no_bids[0], list) else no_bids[0].get('price', 100)
                    
                    yes_price = yes_price_cents / 100
                    no_price = no_price_cents / 100
                    
                    # Only keep markets with actual prices
                    liquid_weather.append({
                        'market': m,
                        'ticker': ticker,
                        'title': title,
                        'yes_price': yes_price,
                        'no_price': no_price,
                        'volume': m.get('volume', 0)
                    })
                    
                    # Debug log first few liquid markets found
                    if len(liquid_weather) <= 3:
                        logger.info(f"  LongshotWeather: Found liquid - {ticker[:30]} YES={yes_price:.1%} NO={no_price:.1%}")
            except Exception as e:
                # Debug log errors for first few markets
                if len(liquid_weather) < 3:
                    logger.debug(f"  LongshotWeather: Error on {ticker[:30]}: {str(e)[:50]}")
                continue
        
        logger.info(f"  LongshotWeather: Found {len(liquid_weather)} weather markets WITH LIQUIDITY")
        
        # Second pass: Filter for cheap markets and extract cities
        cheap_markets = []
        for item in liquid_weather:
            yes_price = item['yes_price']
            no_price = item['no_price']
            
            # Check if either side is cheap
            if yes_price < self.max_market_price or no_price < self.max_market_price:
                # Determine which side is cheap
                if yes_price < no_price:
                    market_price = yes_price
                    side = 'YES'
                else:
                    market_price = no_price
                    side = 'NO'
                
                # Extract city
                city, city_data = self.extract_city_from_market(item['title'], item['ticker'])
                
                if city and city_data:
                    cheap_markets.append({
                        **item,
                        'market_price': market_price,
                        'side': side,
                        'city': city,
                        'city_data': city_data
                    })
        
        logger.info(f"  LongshotWeather: Found {len(cheap_markets)} cheap weather markets (<{self.max_market_price:.0%})")
        
        # Log discovered markets for visibility
        if cheap_markets:
            logger.info(f"  LongshotWeather: Discovered liquid markets in: {', '.join(set(m['city'] for m in cheap_markets))}")
            # Log first few cheap markets
            for m in cheap_markets[:3]:
                logger.info(f"  LongshotWeather: Cheap market - {m['ticker'][:30]} {m['side']}={m['market_price']:.1%}")
        
        # Analyze each cheap market
        
        # Analyze each cheap market
        for item in cheap_markets:
            market = item['market']
            city = item['city']
            city_data = item['city_data']
            market_price = item['market_price']
            ticker = item['ticker']
            title = item['title']
            cheap_side = item['side']
            
            # Get weather forecast
            forecast = await self.fetch_weather_forecast(city, city_data['lat'], city_data['lon'])
            
            if not forecast:
                continue
            
            # Parse market to extract threshold and date
            import re
            
            # Try to extract threshold (e.g., "will be >37°" or "will be 29-30°")
            threshold = None
            is_above = True
            
            # Pattern: >37 or <30
            match = re.search(r'[><](\d+)', title)
            if match:
                threshold = int(match.group(1))
                is_above = '>' in title
            
            # Pattern: 29-30 (range)
            match = re.search(r'(\d+)-(\d+)', title)
            if match:
                threshold = (int(match.group(1)) + int(match.group(2))) / 2
                is_above = None  # Range market
            
            if threshold is None:
                continue
            
            # Get forecast for relevant date
            # Try to extract date from ticker (format: YY-MMM-DD in series, e.g., KXHIGHNY-26FEB03-T37)
            # Pattern: 2-digit year, 3-letter month, 2-digit day
            date_match = re.search(r'-\d{2}([A-Z]{3})(\d{2})-', ticker)
            if date_match:
                month_str = date_match.group(1)
                day = date_match.group(2)
                months = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6}
                month = months.get(month_str, 2)
                
                forecast_date = f"2026-{month:02d}-{int(day):02d}"
                daily_forecast = forecast.get(forecast_date)
                
                # DEBUG: Log forecast lookup
                if len(opportunities) < 3 and daily_forecast:
                    logger.info(f"  LongshotWeather: DEBUG {ticker[:20]}... date={forecast_date}, forecast={daily_forecast}")
                
                if not daily_forecast:
                    if len(opportunities) < 3:
                        logger.info(f"  LongshotWeather: DEBUG No forecast for {forecast_date}, have={list(forecast.keys())[:3]}")
                    continue
                
                # Calculate fair probability with deviation
                if is_above is not None:
                    # Above/below market
                    forecast_temp = daily_forecast['high'] if is_above else daily_forecast['low']
                    fair_prob = self.calculate_probability_with_deviation(
                        daily_forecast['high'], daily_forecast['low'],
                        threshold, is_above
                    )
                else:
                    # Range market - simplified probability
                    range_center = threshold
                    forecast_temp = daily_forecast['avg']
                    diff = abs(forecast_temp - range_center)
                    if diff < self.deviation_f:
                        fair_prob = 0.7
                    else:
                        fair_prob = 0.3
                
                # Calculate edge using $64K formula
                edge = self.calculate_edge(fair_prob, market_price)
                
                # Log every market analysis
                logger.info(f"  LongshotWeather: {ticker[:30]}... "
                           f"{item['side']}={market_price:.1%}, Fair={fair_prob:.1%}, "
                           f"Edge={edge:.1%} (need >{self.min_edge:.1%})")
                
                # Only trade if edge > threshold (cheap markets need bigger edge)
                if edge > self.min_edge:
                    logger.info(f"  LongshotWeather: ✅ EDGE PASSED - {edge:.1%} > {self.min_edge:.1%}")
                    opp = {
                        'ticker': ticker,
                        'market': title,
                        'city': city,
                        'market_price': market_price,
                        'fair_probability': fair_prob,
                        'expected_value': edge,
                        'edge_formula': '(fair - market) / market',
                        'forecast_temp': forecast_temp,
                        'threshold': threshold,
                        'deviation': self.deviation_f,
                        'strategy': 'longshot_weather'
                    }
                    opportunities.append(opp)
                    logger.info(f"  LongshotWeather: ✅ FOUND - Edge {edge:.1%} > {self.min_edge:.1%}")
                else:
                    logger.info(f"  LongshotWeather: Edge {edge:.1%} too small")
        
        return opportunities
    
    async def execute(self, opportunities: List[Dict]) -> int:
        """Execute longshot trades (real or simulated)"""
        executed = 0
        
        logger.info(f"  LongshotWeather: Execute called with {len(opportunities)} opportunities")
        
        for opp in opportunities:
            ticker = opp['ticker']
            market_price_cents = int(opp['market_price'] * 100)
            
            # Check for duplicate BEFORE executing
            if self.position_manager and self.position_manager.has_open_position(ticker, simulated=self.dry_run):
                logger.debug(f"  LongshotWeather: Skipping {ticker[:30]}... - already have open position")
                continue
            
            if self.dry_run:
                # SIMULATED: Record position without executing
                recorded = self.record_position(
                    ticker=ticker,
                    side='YES',
                    contracts=min(self.max_position, 5),
                    entry_price=market_price_cents,
                    market_title=opp['market']
                )
                if recorded:
                    logger.info(f"    [SIMULATED] ✓ Would execute: {ticker[:30]}... "
                               f"at {opp['market_price']:.1%}, edge={opp['expected_value']:.1%}")
                else:
                    logger.debug(f"    [SIMULATED] Skipping {ticker[:30]}... - already have open position")
                    continue
            else:
                # REAL: Execute via Kalshi API
                try:
                    result = self.client.place_order(
                        market_id=ticker,
                        side='yes',
                        price=market_price_cents,
                        count=min(self.max_position, 5)
                    )
                    if result.get('order_id'):
                        recorded = self.record_position(
                            ticker=ticker,
                            side='YES',
                            contracts=min(self.max_position, 5),
                            entry_price=market_price_cents,
                            market_title=opp['market']
                        )
                        if recorded:
                            logger.info(f"    [REAL] ✓ Executed: {ticker[:30]}... "
                                       f"at {opp['market_price']:.1%}, edge={opp['expected_value']:.1%} Order: {result['order_id']}")
                        else:
                            # Should not happen since we check duplicate first, but log just in case
                            logger.warning(f"    [REAL] Position record failed after order placed: {ticker[:30]}...")
                    else:
                        logger.error(f"    [REAL] ✗ Order failed: {result}")
                except Exception as e:
                    logger.error(f"    [REAL] ✗ Failed to execute {ticker}: {e}")
                    continue
            
            # Track for performance with TIERED EXIT STRATEGY (FEE-ADJUSTED)
            # Fee is fetched dynamically from API fills after each trade
            # Typical: ~$0.001/contract for takers, $0 for makers
            trade = {
                'ticker': ticker,
                'market': opp['market'],
                'city': opp['city'],
                'market_price': opp['market_price'],
                'fair_probability': opp['fair_probability'],
                'expected_value': opp['expected_value'],
                'size': min(self.max_position, 5),
                'timestamp': datetime.now().isoformat(),
                'status': 'open',
                'simulated': self.dry_run,
                'exit_strategy': {
                    'entry_price': market_price_cents,          # Track actual entry
                    'tier1_price': market_price_cents * 4,      # 4x - sell 50% (profit after fees)
                    'tier1_sold': False,
                    'tier2_price': market_price_cents * 6,      # 6x - sell remaining
                    'tier2_sold': False,
                    'stop_price': max(1, market_price_cents - 1),  # Exit if dropping (max loss already)
                    'time_exit_hours': 6,  # Exit if <6h to expiry and unprofitable
                    'partial_position_remaining': 1.0,  # 1.0 = 100%, 0.5 = 50% after tier1
                    'buy_fee': None,  # Will be populated from API after trade
                    'sell_fee': None  # Will be estimated based on latest fills
                }
            }
            self.record_trade(trade)
            executed += 1
        
        return executed
    
    def get_performance(self) -> Dict:
        """Get performance metrics"""
        if not self.trades:
            return {'total_pnl': 0, 'win_rate': 0, 'trades': 0}
        
        total_pnl = sum(t.get('expected_value', 0) * t.get('size', 0) for t in self.trades)
        win_rate = sum(1 for t in self.trades if t.get('expected_value', 0) > 0) / len(self.trades)
        
        return {
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'trades': len(self.trades)
    }
    
    def _get_actual_fee_from_api(self, ticker: str, count: int) -> float:
        """Fetch actual fee paid from API fills for a given ticker and count"""
        try:
            response = self.client._request("GET", "/portfolio/fills")
            if response.status_code == 200:
                fills = response.json().get('fills', [])
                for fill in fills:
                    if fill.get('ticker') == ticker and fill.get('count') == count:
                        return float(fill.get('fee_cost', 0))
        except Exception as e:
            logger.debug(f"Could not fetch fee for {ticker}: {e}")
        return 0.0
    
    def _estimate_sell_fee(self, count: int) -> float:
        """Estimate sell fee based on recent API data
        Pattern: ~$0.001 per contract, rounded to nearest cent, min $0.01 for takers
        """
        estimated = count * 0.001  # $0.001 per contract
        return round(estimated, 2)  # Round to cents
    
    async def check_exits(self):
        """
        TIERED EXIT STRATEGY for cheap weather bets (DYNAMIC FEES):
        - Fees fetched from API (~$0.001/contract for takers)
        - Tier 1: Sell 50% at 4x (profit after fees)
        - Tier 2: Sell remaining at 6x+ (home run)
        - Stop: Exit at entry-1c if dropping (max loss)
        """
        if self.dry_run:
            return  # Don't manage exits in simulation mode
        
        if not self.trades:
            return
        
        for trade in self.trades:
            if trade.get('status') != 'open':
                continue
            
            ticker = trade['ticker']
            exit_strat = trade.get('exit_strategy', {})
            entry_price = exit_strat.get('entry_price', int(trade.get('market_price', 0.01) * 100))
            position_size = trade.get('size', 0)
            
            # Fetch actual buy fee from API if not already stored
            if exit_strat.get('buy_fee') is None:
                exit_strat['buy_fee'] = self._get_actual_fee_from_api(ticker, position_size)
            buy_fee_cents = int(exit_strat.get('buy_fee', 0) * 100)  # Convert to cents
            
            # Estimate sell fee
            sell_fee_dollars = self._estimate_sell_fee(position_size)
            sell_fee_cents = int(sell_fee_dollars * 100)
            exit_strat['sell_fee'] = sell_fee_dollars
            
            # Get current market price
            try:
                orderbook = self.client.get_orderbook(ticker)
                if not orderbook:
                    continue
                
                # Get best bid for YES side
                yes_bids = orderbook.get('orderbook', {}).get('yes', [])
                if not yes_bids:
                    continue
                current_price = int(yes_bids[0].get('price', entry_price))
                
                tier1_price = exit_strat.get('tier1_price', entry_price * 4)  # 4x
                tier2_price = exit_strat.get('tier2_price', entry_price * 6)  # 6x
                stop_price = exit_strat.get('stop_price', max(1, entry_price - 1))
                tier1_sold = exit_strat.get('tier1_sold', False)
                tier2_sold = exit_strat.get('tier2_sold', False)
                remaining_pct = exit_strat.get('partial_position_remaining', 1.0)
                
                # TIER 2: Home run - sell remaining at 6x+
                if current_price >= tier2_price and not tier2_sold and remaining_pct > 0:
                    contracts_to_sell = int(position_size * remaining_pct)
                    if contracts_to_sell > 0:
                        result = self.client.place_order(ticker, 'yes', current_price, contracts_to_sell)
                        if result.get('success'):
                            exit_strat['tier2_sold'] = True
                            exit_strat['partial_position_remaining'] = 0
                            trade['status'] = 'closed'
                            # P&L with dynamic fees
                            total_buy_cost = (entry_price * position_size) + buy_fee_cents
                            sell_revenue = (current_price * contracts_to_sell) - sell_fee_cents
                            pnl = (sell_revenue - (total_buy_cost * remaining_pct)) * 0.01
                            logger.info(f"🎯 TIER 2 EXIT: {ticker} @ {current_price}c (6x+ target)")
                            logger.info(f"   Sold {contracts_to_sell} @ {current_price}c, P&L: ${pnl:+.2f}")
                            continue
                
                # TIER 1: Profit taking - sell 50% at 4x
                if current_price >= tier1_price and not tier1_sold:
                    contracts_to_sell = position_size // 2
                    if contracts_to_sell > 0:
                        result = self.client.place_order(ticker, 'yes', current_price, contracts_to_sell)
                        if result.get('success'):
                            exit_strat['tier1_sold'] = True
                            exit_strat['partial_position_remaining'] = 0.5
                            # P&L with dynamic fees
                            total_buy_cost = (entry_price * position_size) + buy_fee_cents
                            sell_revenue = (current_price * contracts_to_sell) - sell_fee_cents
                            pnl = (sell_revenue - (total_buy_cost * 0.5)) * 0.01
                            logger.info(f"💰 TIER 1 EXIT: {ticker} @ {current_price}c (4x target - profit after fees)")
                            logger.info(f"   Buy: {position_size}@{entry_price}c + ${buy_fee_cents/100:.2f} fee")
                            logger.info(f"   Sell: {contracts_to_sell}@{current_price}c - ${sell_fee_cents/100:.2f} fee")
                            logger.info(f"   Sold {contracts_to_sell} (50%), P&L: ${pnl:+.2f}")
                            logger.info(f"   Holding {contracts_to_sell} for tier 2 (6x target)")
                
                # STOP LOSS: Exit all at entry-1c or lower
                if current_price <= stop_price:
                    contracts_to_sell = int(position_size * remaining_pct)
                    if contracts_to_sell > 0:
                        result = self.client.place_order(ticker, 'yes', current_price, contracts_to_sell)
                        if result.get('success'):
                            exit_strat['tier1_sold'] = True
                            exit_strat['tier2_sold'] = True
                            exit_strat['partial_position_remaining'] = 0
                            trade['status'] = 'closed'
                            # P&L with dynamic fees (will be negative)
                            total_buy_cost = (entry_price * position_size) + buy_fee_cents
                            sell_revenue = (current_price * contracts_to_sell) - sell_fee_cents
                            pnl = (sell_revenue - total_buy_cost) * 0.01
                            logger.info(f"🛑 STOP LOSS: {ticker} @ {current_price}c")
                            logger.info(f"   Buy: {position_size}@{entry_price}c + ${buy_fee_cents/100:.2f} fee")
                            logger.info(f"   Sell: {contracts_to_sell}@{current_price}c - ${sell_fee_cents/100:.2f} fee")
                            logger.info(f"   Sold all {contracts_to_sell}, P&L: ${pnl:+.2f}")
                
                # TIME EXIT: <6h to expiry and not profitable
                # (This would need expiry time parsing from ticker)
                
            except Exception as e:
                logger.debug(f"Error checking exits for {ticker}: {e}")
    
    async def close(self):
        """Close session"""
        if self.session and not self.session.closed:
            await self.session.close()
