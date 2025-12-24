# RL Module

Reinforcement learning capabilities for LeekWars AI training. Inspired by [LeekWarsRLEnv](https://github.com/PLNech/LeekWarsRLEnv).

## Quick Start

```bash
# Run a single duel
python -m src.tools.rl duel --seed 42

# Run scenarios from YAML
python -m src.tools.rl scenario scenarios/sample_scenarios.yml --workers 4

# Test the RL environment
python -m src.tools.rl env --episodes 5
```

## Architecture

| Component | File | Purpose |
|-----------|------|---------|
| Environment | `src/rl/environment.py` | Gymnasium-compatible `LeekWarsEnv` |
| Spaces | `src/rl/spaces.py` | Action/observation space definitions |
| Rewards | `src/rl/rewards.py` | Configurable reward functions |
| Scenarios | `src/rl/scenarios.py` | YAML scenario runner |
| Telemetry | `src/rl/telemetry.py` | Fight metrics extraction |
| Parallel | `src/localfight/parallel.py` | Concurrent fight execution |
| CLI | `src/tools/rl.py` | Command-line interface |

## CLI Commands

### duel
Run a single duel with telemetry output.

```bash
python -m src.tools.rl duel                    # Random seed
python -m src.tools.rl duel --seed 42          # Reproducible
python -m src.tools.rl duel --telemetry        # Detailed output
python -m src.tools.rl duel --summary          # JSON output
```

### scenario
Run batch scenarios from YAML files.

```bash
python -m src.tools.rl scenario scenarios/sample.yml
python -m src.tools.rl scenario scenarios/sample.yml --workers 4
```

### env
Test the RL environment.

```bash
python -m src.tools.rl env --episodes 5
```

## Python API

### RL Environment

```python
from src.rl import LeekWarsEnv, RewardConfig

# Create environment
env = LeekWarsEnv(seed=42)

# Run episode
obs, info = env.reset()
obs, reward, done, truncated, info = env.step(0)
print(f"Won: {info['won']}, Reward: {reward:.2f}")
```

### Parallel Execution

```python
from src.localfight.parallel import ParallelRunner, BatchBuilder

# Build batch of fights
batch = (BatchBuilder()
    .add_1v1("bot1.leek", "bot2.leek", seed=42)
    .add_1v1("bot1.leek", "bot2.leek", seed=43)
    .build())

# Run in parallel
runner = ParallelRunner(max_workers=4)
results = runner.run_batch(batch)
```

### Telemetry

```python
from src.rl import extract_telemetry, aggregate_metrics
from src.localfight import run_fight, parse_fight_result, Scenario

# Run fight
scenario = Scenario.create_1v1_pistol(seed=42)
result = parse_fight_result(run_fight(scenario))

# Extract telemetry
telemetry = extract_telemetry(result)
print(f"Winner: Team {telemetry.winner + 1}")
print(f"Turns: {telemetry.total_turns}")

# Per-agent stats
for metrics in telemetry.agent_metrics.values():
    print(f"{metrics.name}: {metrics.total_damage_dealt} damage")
```

## YAML Scenarios

Define batch experiments in YAML:

```yaml
# scenarios/my_training.yml
log_dir: "data/my_logs"
max_workers: 4

scenarios:
  - name: "my_experiment"
    repetitions: 100
    seed: 42
    bots:
      - name: "Agent"
        path: "my/agent.leek"
        team: 1
      - name: "Opponent"
        path: "test/ai/simple.leek"
        team: 2
```

Run with:
```bash
python -m src.tools.rl scenario scenarios/my_training.yml
```

## Dashboard Integration

The RL tab in the dashboard (`python -m src.dashboard`) provides:

1. **Quick Duel**: Run single duels with configurable bots and seed
2. **Scenario Runner**: Execute YAML scenarios with progress tracking
3. **Telemetry Viewer**: Inspect fight metrics and per-agent stats

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/rl/status` | GET | RL module status |
| `/api/rl/duel` | POST | Run single duel |
| `/api/rl/scenarios` | GET | List scenario files |
| `/api/rl/scenario/run` | POST | Start scenario |
| `/api/rl/scenario/stop` | POST | Stop scenario |
| `/api/rl/scenario/progress` | GET | Get progress |
| `/api/rl/results` | GET | Get results |

## Dependencies

```
gymnasium>=0.29.0
pyyaml>=6.0
```

## Design Decisions

1. **JAR-based simulation**: Keeps accuracy with real game mechanics
2. **Gymnasium** (not gym): Modern RL library compatibility
3. **Episodic environment**: Each step runs a complete fight
4. **Shaped rewards**: Win/loss + damage + efficiency bonuses
5. **Deterministic seeds**: Reproducible experiments
