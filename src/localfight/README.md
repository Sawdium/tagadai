# Local Fight Runner

Run fights locally using the LeekWars Java generator for ML training data.

## Prerequisites

Requires the LeekWars generator JAR at `.cache/leek-wars-generator/generator.jar`.

## Usage

Library module - used programmatically:

```python
from src.localfight import Scenario, LeekConfig, run_fight, parse_fight_result

# Define a fight scenario
leek1 = LeekConfig(level=100, ai_file="path/to/ai.leek")
leek2 = LeekConfig(level=100, ai_file="path/to/enemy.leek")
scenario = Scenario(team1=[leek1], team2=[leek2])

# Run fight locally
result = run_fight(scenario, timeout=30.0)

# Parse for training data
fight_result = parse_fight_result(result)
training_example = extract_training_data(fight_result)
```

## Components

| Module | Description |
|--------|-------------|
| `scenario.py` | `Scenario`, `LeekConfig`, `MapConfig` for fight setup |
| `runner.py` | `run_fight()` - executes JAR and captures output |
| `parser.py` | `parse_fight_result()` - extracts training features |

## Features

- **Offline execution**: No API calls, unlimited fights
- **Scenario generation**: Randomized leek configs for diverse training
- **Training data extraction**: Converts fight results to ML features
- **Configurable**: Custom maps, leek stats, AI files

## Generating Training Data

```python
from src.localfight import generate_scenarios

# Generate diverse scenarios for training
scenarios = generate_scenarios(count=1000, level_range=(50, 301))

for scenario in scenarios:
    result = run_fight(scenario)
    # ... extract and store training data
```
