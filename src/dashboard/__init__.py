"""
Training dashboard for ML visualization.

Provides a web-based interface to monitor:
- Fight generation progress
- Training metrics (loss, accuracy)
- Model predictions
- Real-time updates via WebSocket
"""

from .metrics import MetricsCollector, TrainingMetrics
from .server import create_app

__all__ = ["MetricsCollector", "TrainingMetrics", "create_app"]
