# HTTP Response Caching

InkyPi includes an HTTP response cache to dramatically reduce redundant API calls and improve performance, especially important on resource-constrained devices like Raspberry Pi.

## Overview

The HTTP cache automatically stores successful API responses and reuses them for subsequent requests within a configurable time-to-live (TTL) period. This reduces:
- Network requests to external APIs
- API quota usage
- Response latency
- Power consumption on battery-powered devices

## Features

- **Automatic caching**: Enabled by default for all GET requests
- **TTL-based expiration**: Configurable time-to-live per entry
- **Cache-Control support**: Respects HTTP `Cache-Control` headers
- **LRU eviction**: Automatically removes least-used entries when full
- **Thread-safe**: Safe for concurrent use across plugins
- **Statistics tracking**: Monitor cache hit rates and performance
- **Per-request control**: Can bypass cache for specific requests

## Configuration

Configure caching via environment variables:

```bash
# Enable/disable caching (default: true)
export INKYPI_HTTP_CACHE_ENABLED=true

# Default TTL in seconds (default: 300 = 5 minutes)
export INKYPI_HTTP_CACHE_TTL_S=600

# Maximum cache entries (default: 100)
export INKYPI_HTTP_CACHE_MAX_SIZE=200
```

## Usage

### Automatic Caching (Default)

```python
from utils.http_utils import http_get

# First request fetches from API and caches
response = http_get("https://api.example.com/data")

# Second request uses cached response (if within TTL)
response = http_get("https://api.example.com/data")
```

### Custom TTL

```python
# Cache for 1 hour instead of default 5 minutes
response = http_get(
    "https://api.example.com/data",
    cache_ttl=3600  # seconds
)
```

### Bypass Cache

```python
# Force fresh request, bypass cache
response = http_get(
    "https://api.example.com/data",
    use_cache=False
)
```

### Query Parameters

Query parameters are part of the cache key:

```python
# Different cache entries for different parameters
resp1 = http_get("https://api.example.com/weather", params={"city": "NYC"})
resp2 = http_get("https://api.example.com/weather", params={"city": "LA"})
```

## Cache Statistics

Monitor cache performance:

```python
from utils.http_cache import get_cache_stats, clear_cache

# Get statistics
stats = get_cache_stats()
print(f"Hit rate: {stats['hit_rate']}%")
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
print(f"Size: {stats['size']}/{stats['max_size']}")

# Clear cache manually
cleared = clear_cache()
print(f"Cleared {cleared} entries")
```

Example output:
```python
{
    'hits': 45,
    'misses': 12,
    'expirations': 3,
    'evictions': 0,
    'errors': 0,
    'hit_rate': 78.95,
    'size': 25,
    'max_size': 100,
    'enabled': True
}
```

## Cache-Control Headers

The cache respects standard HTTP Cache-Control directives:

```python
# Server responds with: Cache-Control: max-age=3600
# Cache uses 3600 seconds TTL instead of default

# Server responds with: Cache-Control: no-cache
# Response is not cached

# Server responds with: Cache-Control: max-age=0
# Response is not cached
```

## Plugin Integration

Plugins automatically benefit from caching without code changes:

### Weather Plugin Example

```python
# weather.py - No changes needed!
response = http_get(
    WEATHER_URL.format(lat=lat, lon=lon, api_key=api_key)
)

# First call fetches from API
# Subsequent calls within 5 minutes use cache
# Reduces API quota usage from ~288 calls/day to ~12 calls/day (5 min refresh)
```

### Custom Cache TTL for Specific APIs

```python
# Cache weather for 10 minutes
weather_data = http_get(
    weather_url,
    params={"lat": lat, "lon": lon},
    cache_ttl=600  # 10 minutes
)

# Cache news headlines for 30 minutes
news_data = http_get(
    news_url,
    cache_ttl=1800  # 30 minutes
)

# Don't cache real-time stock prices
stock_data = http_get(
    stock_url,
    use_cache=False  # Always fresh
)
```

## Performance Impact

**Example: Weather Plugin with 5-minute display refresh**

Without cache:
- API calls per day: ~288 (every 5 minutes)
- Network requests: ~288
- API quota consumed: 288 requests

With cache (5-minute TTL):
- API calls per day: ~288 (same refresh rate)
- **Network requests: ~12** (cached for 5 minutes)
- **API quota consumed: ~12 requests** (96% reduction!)

**Example: Multiple plugins using same API**

```python
# Weather plugin requests at 00:00
weather = http_get(weather_api_url, params={"location": "NYC"})

# Calendar plugin requests at 00:02 (same location)
calendar = http_get(weather_api_url, params={"location": "NYC"})
# ^ Uses cached response from weather plugin!

# Total API calls: 1 instead of 2
```

## Advanced Usage

### Programmatic Cache Access

```python
from utils.http_cache import get_cache

cache = get_cache()

# Get specific entry
entry = cache.get("https://api.example.com/data")

# Manually add to cache
cache.put(url, response, ttl=600)

# Remove expired entries
expired_count = cache.remove_expired()

# Clear everything
cache.clear()
```

### Development/Testing

```python
# Disable cache for testing
import os
os.environ["INKYPI_HTTP_CACHE_ENABLED"] = "false"

# Or bypass for specific test
response = http_get(url, use_cache=False)
```

## Best Practices

1. **Use default caching** - Most plugins benefit from the default 5-minute TTL
2. **Longer TTL for stable data** - News headlines, weather forecasts (15-30 min)
3. **Bypass for real-time data** - Stock prices, live scores (use_cache=False)
4. **Monitor hit rates** - Aim for >70% hit rate for frequently called APIs
5. **Consider API quotas** - Match cache TTL to your API refresh requirements

## Troubleshooting

### Cache not working?

Check if caching is enabled:
```python
from utils.http_cache import get_cache_stats
stats = get_cache_stats()
print(f"Enabled: {stats['enabled']}")
```

### High miss rate?

- Check if each request uses different parameters
- Verify TTL isn't too short
- Ensure requests use same URL format

### Memory concerns?

Reduce cache size:
```bash
export INKYPI_HTTP_CACHE_MAX_SIZE=50
```

Or disable caching:
```bash
export INKYPI_HTTP_CACHE_ENABLED=false
```

## Implementation Details

- **Thread-safe**: Uses RLock for concurrent access
- **LRU eviction**: Evicts least recently used entries when full
- **Hit count tracking**: Frequently accessed entries stay in cache longer
- **Automatic cleanup**: Expired entries removed on access
- **Transparent**: Drop-in replacement for existing `http_get()` calls
