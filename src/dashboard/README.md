# Training Dashboard

Web-based interface to monitor ML training progress in real-time.

## Usage

```bash
python -m src.dashboard              # Start server on http://127.0.0.1:8080
python -m src.dashboard --port 9000  # Custom port
python -m src.dashboard --demo       # Demo mode with simulated data
```

## Features

- Real-time fight generation progress
- Training metrics visualization (loss, accuracy curves)
- WebSocket updates for live monitoring
- Integrates with `src.ml` trainer callbacks

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
