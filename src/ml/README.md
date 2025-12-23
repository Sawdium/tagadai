# ML Training Infrastructure

Neural network training for fight outcome prediction.

## Usage

Library module - used programmatically:

```python
from src.ml import WinPredictor, FightDataset, KFoldTrainer, VersionRegistry

# Load dataset from scraped fights
dataset = FightDataset.from_database("data/fights.db")

# Train with K-fold cross-validation
trainer = KFoldTrainer(k=5, epochs=50, batch_size=256)
result = trainer.train(dataset)
print(result.summary())  # Accuracy: 65.2% ± 1.3%

# Save as versioned model
registry = VersionRegistry("data/models")
version = registry.create_version(trainer.best_model, result)
```

## Components

| Module | Description |
|--------|-------------|
| `model.py` | `WinPredictor` neural network architecture |
| `dataset.py` | `FightDataset` for loading/preprocessing fight data |
| `trainer.py` | `KFoldTrainer` with early stopping, mixed precision |
| `version.py` | `VersionRegistry` for model versioning and tracking |
| `arena.py` | `Arena` for comparing AI versions via simulated fights |

## Features

- **K-fold cross-validation** with stratified splits
- **Early stopping** to prevent overfitting
- **Mixed precision** (AMP) for GPU acceleration
- **Version management** with metadata tracking
- **Arena battles** to compare model versions

## Integration with Dashboard

Pass a callback to get real-time updates:

```python
from src.dashboard import MetricsCollector

collector = MetricsCollector()
trainer.train(dataset, progress_callback=collector.update_training)
```
