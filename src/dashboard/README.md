# Training Dashboard

Web-based interface to monitor ML training, fight data, and AI models in real-time.

## Usage

```bash
python -m src.dashboard              # Start server on http://127.0.0.1:8080
python -m src.dashboard --port 9000  # Custom port
python -m src.dashboard --demo       # Demo mode with simulated data
```

## Tabs

The dashboard has 5 main tabs:

| Tab | Purpose |
|-----|---------|
| **Training** | Control training, monitor progress, view loss/accuracy charts, GPU info, checkpoints |
| **RL** | Run duels and scenarios, view telemetry from reinforcement learning runs |
| **Scraper** | Control fight data scraper, view collection stats and database breakdown |
| **Data** | Analytics: level distribution, date distribution, build balance, exploration stats |
| **Models** | Leaderboard, H2H predictions, AI version management |

A unified **Logs** drawer (toggle with `Ctrl+L`) shows logs from all systems with category filters.

## Features

- Real-time fight generation progress
- Training metrics visualization (loss, accuracy curves)
- WebSocket updates for live monitoring
- Unified logging across training, scraper, and RL systems
- Data analytics with level/date distribution charts
- AI model leaderboard and head-to-head predictions

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Start/pause training |
| `Escape` | Stop training |
| `Ctrl+S` | Save training |
| `Ctrl+L` | Toggle logs drawer |

## Architecture

- `server.py` - FastAPI/Starlette app with WebSocket support
- `metrics.py` - MetricsCollector for aggregating training stats
- `cli.py` - CLI entry point
- `static/` - Frontend (HTML/CSS/JS)

## Integration

The dashboard receives updates via the `MetricsCollector`:

```python
from src.dashboard import MetricsCollector

collector = MetricsCollector()
collector.start(phase="training", target_fights=1000)
collector.update_training(epoch=1, train_loss=0.5, val_accuracy=0.6)
```

Pass the collector to the trainer for automatic updates.
