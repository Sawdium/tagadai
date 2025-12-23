# Fight Scraper

Politely downloads fight data from LeekWars API for ML training.

## Usage

Library module - no CLI. Used programmatically:

```python
from src.scraper import FightScraper, FightDatabase

db = FightDatabase("data/fights.db")
scraper = FightScraper(db)

# Start scraping in background
scraper.start()

# Check progress
print(scraper.stats)  # ScraperStats with counts, queue size, etc.

# Stop gracefully
scraper.stop()
```

## Features

- **Rate limiting**: Configurable delay, respects API limits
- **Auto-discovery**: Finds top players via rankings/tournaments
- **Queue-based**: Priority queue with resumable state
- **SQLite storage**: Efficient local database with deduplication
- **Real-time stats**: Track progress, errors, rate limit hits

## Database Schema

Stored in SQLite via `FightDatabase`:
- `fights` - Raw fight JSON with metadata
- `players` - Discovered player/leek info
- `queue` - Pending fight IDs to download

## Architecture

- `scraper.py` - FightScraper with background thread execution
- `db.py` - FightDatabase for SQLite operations
