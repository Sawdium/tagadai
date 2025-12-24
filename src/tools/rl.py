#!/usr/bin/env python3
"""
CLI tool for LeekWars RL training and experimentation.

Usage:
    python -m src.tools.rl duel [options]
    python -m src.tools.rl scenario <yaml_file> [options]
    python -m src.tools.rl env [options]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.localfight.runner import check_generator, run_fight
from src.localfight.scenario import Scenario
from src.localfight.parser import parse_fight_result
from src.localfight.parallel import run_parallel
from src.rl.scenarios import load_yaml, ScenarioRunner
from src.rl.telemetry import extract_telemetry, aggregate_metrics, telemetry_from_batch


def cmd_duel(args):
    """Run a single duel between two bots."""
    if not check_generator():
        print("Error: Generator not available. Build it first.", file=sys.stderr)
        return 1

    # Create scenario
    if args.seed is not None:
        seed = args.seed
    else:
        import random
        seed = random.randint(0, 2**31)

    scenario = Scenario.create_1v1_pistol(
        seed=seed,
        ai1=args.bot1,
        ai2=args.bot2,
    )

    print(f"Running duel (seed={seed})...")
    print(f"  Bot 1: {args.bot1}")
    print(f"  Bot 2: {args.bot2}")
    print()

    try:
        raw_result = run_fight(scenario, timeout=args.timeout)
        result = parse_fight_result(raw_result)
    except Exception as e:
        print(f"Error running fight: {e}", file=sys.stderr)
        return 1

    # Display result
    winner_str = {0: "Bot 1 wins!", 1: "Bot 2 wins!", -1: "Draw"}.get(result.winner, "Unknown")

    print(f"=== Result ===")
    print(f"Outcome: {winner_str}")
    print(f"Duration: {result.duration} turns")
    print(f"Execution time: {result.execution_time / 1e6:.1f}ms")
    print()

    # Extract telemetry if requested
    if args.telemetry:
        telemetry = extract_telemetry(result)
        print(f"=== Telemetry ===")
        for eid, metrics in telemetry.agent_metrics.items():
            print(f"Entity {metrics.name} (Team {metrics.team}):")
            print(f"  Damage dealt: {metrics.total_damage_dealt}")
            print(f"  Damage taken: {metrics.total_damage_taken}")
            print(f"  TP efficiency: {metrics.tp_efficiency:.2f}")
            print(f"  Final HP: {metrics.final_hp}/{metrics.max_hp}")
            print()

    # Save to file if requested
    if args.output:
        telemetry = extract_telemetry(result)
        output_path = Path(args.output)
        telemetry.save(output_path)
        print(f"Telemetry saved to: {output_path}")

    # JSON output
    if args.json:
        telemetry = extract_telemetry(result)
        print(telemetry.to_json())

    return 0


def cmd_scenario(args):
    """Run scenarios from a YAML file."""
    if not check_generator():
        print("Error: Generator not available. Build it first.", file=sys.stderr)
        return 1

    yaml_path = Path(args.yaml_file)
    if not yaml_path.exists():
        print(f"Error: File not found: {yaml_path}", file=sys.stderr)
        return 1

    print(f"Loading scenarios from: {yaml_path}")

    try:
        config = load_yaml(yaml_path)
    except Exception as e:
        print(f"Error parsing YAML: {e}", file=sys.stderr)
        return 1

    print(f"Found {len(config.scenarios)} scenario(s)")

    total_fights = sum(s.repetitions for s in config.scenarios)
    print(f"Total fights to run: {total_fights}")
    print(f"Workers: {args.workers or 'auto'}")
    print()

    # Override workers if specified
    if args.workers:
        config.max_workers = args.workers

    # Progress tracking
    completed = [0]
    def progress_callback(done, total, result):
        completed[0] = done
        pct = done * 100 // total
        bar = "=" * (pct // 5) + " " * (20 - pct // 5)
        print(f"\rProgress: [{bar}] {done}/{total} ({pct}%)", end="", flush=True)

    runner = ScenarioRunner(
        config,
        progress_callback=progress_callback if not args.quiet else None,
    )

    try:
        results = runner.run()
    except Exception as e:
        print(f"\nError running scenarios: {e}", file=sys.stderr)
        return 1

    if not args.quiet:
        print()  # Newline after progress bar

    # Display results
    print()
    print("=== Results ===")
    all_telemetry = []

    for scenario_result in results:
        batch = scenario_result.batch_result
        print(f"\n{scenario_result.scenario_name}:")
        print(f"  Fights: {batch.success_count}/{batch.total_count}")
        print(f"  Time: {batch.total_time:.2f}s ({batch.fights_per_second:.1f} fights/sec)")

        if batch.errors:
            print(f"  Errors: {batch.error_count}")

        # Extract telemetry
        telemetry_list = telemetry_from_batch(batch.results)
        all_telemetry.extend(telemetry_list)

        if telemetry_list:
            stats = aggregate_metrics(telemetry_list)
            print(f"  Team 1 win rate: {stats['team1_win_rate']*100:.1f}%")
            print(f"  Team 2 win rate: {stats['team2_win_rate']*100:.1f}%")
            print(f"  Avg turns: {stats['avg_turns']:.1f}")

    # Overall summary
    if len(all_telemetry) > 1:
        print()
        print("=== Overall Summary ===")
        overall_stats = aggregate_metrics(all_telemetry)
        print(f"Total fights: {overall_stats['total_fights']}")
        print(f"Team 1 wins: {overall_stats['team1_wins']} ({overall_stats['team1_win_rate']*100:.1f}%)")
        print(f"Team 2 wins: {overall_stats['team2_wins']} ({overall_stats['team2_win_rate']*100:.1f}%)")
        print(f"Draws: {overall_stats['draws']}")
        print(f"Avg damage per fight: {overall_stats['avg_damage_per_fight']:.1f}")

    # Save summary if requested
    if args.summary:
        summary_path = Path(args.summary)
        summary_data = {
            "scenarios": [
                {
                    "name": r.scenario_name,
                    "success_count": r.batch_result.success_count,
                    "error_count": r.batch_result.error_count,
                    "total_time": r.batch_result.total_time,
                }
                for r in results
            ],
            "overall": aggregate_metrics(all_telemetry) if all_telemetry else {},
        }
        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=2)
        print(f"\nSummary saved to: {summary_path}")

    # Save telemetry if requested
    if args.log_dir:
        log_dir = Path(args.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        for i, telemetry in enumerate(all_telemetry):
            telemetry.save(log_dir / f"fight_{i:04d}.json")
        print(f"\nTelemetry saved to: {log_dir}")

    return 0


def cmd_env(args):
    """Test the RL environment."""
    if not check_generator():
        print("Error: Generator not available. Build it first.", file=sys.stderr)
        return 1

    from src.rl.environment import LeekWarsEnv, EnvConfig

    print("Creating LeekWars RL environment...")

    config = EnvConfig(
        agent_ai=args.agent,
        opponent_ai=args.opponent,
    )

    env = LeekWarsEnv(
        config=config,
        seed=args.seed,
        render_mode="human" if not args.quiet else None,
    )

    print(f"Observation space: {env.observation_space}")
    print(f"Action space: {env.action_space}")
    print()

    # Run episodes
    total_reward = 0
    wins = 0

    for episode in range(args.episodes):
        print(f"Episode {episode + 1}/{args.episodes}")
        obs, info = env.reset()

        # Take random action (or specified)
        action = args.action if args.action is not None else env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)

        total_reward += reward
        if info.get("won"):
            wins += 1

        if not args.quiet:
            print(f"  Reward: {reward:.2f}")
            print(f"  Won: {info.get('won')}")
            print()

    print("=== Summary ===")
    print(f"Episodes: {args.episodes}")
    print(f"Wins: {wins} ({wins*100/args.episodes:.1f}%)")
    print(f"Total reward: {total_reward:.2f}")
    print(f"Avg reward: {total_reward/args.episodes:.2f}")

    env.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="LeekWars RL training and experimentation CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m src.tools.rl duel --seed 42
  python -m src.tools.rl scenario scenarios/sample_scenarios.yml --workers 4
  python -m src.tools.rl env --episodes 10
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Duel command
    duel_parser = subparsers.add_parser("duel", help="Run a single duel")
    duel_parser.add_argument(
        "--bot1", "-1",
        default="test/ai/simple.leek",
        help="Path to bot 1 AI file",
    )
    duel_parser.add_argument(
        "--bot2", "-2",
        default="test/ai/simple.leek",
        help="Path to bot 2 AI file",
    )
    duel_parser.add_argument(
        "--seed", "-s",
        type=int,
        help="Random seed for reproducibility",
    )
    duel_parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=30.0,
        help="Fight timeout in seconds",
    )
    duel_parser.add_argument(
        "--telemetry",
        action="store_true",
        help="Show detailed telemetry",
    )
    duel_parser.add_argument(
        "--output", "-o",
        help="Save telemetry to JSON file",
    )
    duel_parser.add_argument(
        "--json",
        action="store_true",
        help="Output result as JSON",
    )

    # Scenario command
    scenario_parser = subparsers.add_parser("scenario", help="Run scenarios from YAML")
    scenario_parser.add_argument(
        "yaml_file",
        help="Path to YAML scenario file",
    )
    scenario_parser.add_argument(
        "--workers", "-w",
        type=int,
        help="Number of parallel workers (default: auto)",
    )
    scenario_parser.add_argument(
        "--summary",
        help="Save summary to JSON file",
    )
    scenario_parser.add_argument(
        "--log-dir",
        help="Directory to save fight telemetry",
    )
    scenario_parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress progress output",
    )

    # Env command
    env_parser = subparsers.add_parser("env", help="Test the RL environment")
    env_parser.add_argument(
        "--agent",
        default="test/ai/simple.leek",
        help="Path to agent AI file",
    )
    env_parser.add_argument(
        "--opponent",
        default="test/ai/simple.leek",
        help="Path to opponent AI file",
    )
    env_parser.add_argument(
        "--seed", "-s",
        type=int,
        help="Random seed",
    )
    env_parser.add_argument(
        "--episodes", "-n",
        type=int,
        default=1,
        help="Number of episodes to run",
    )
    env_parser.add_argument(
        "--action", "-a",
        type=int,
        help="Fixed action to take (default: random)",
    )
    env_parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress output",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "duel":
        return cmd_duel(args)
    elif args.command == "scenario":
        return cmd_scenario(args)
    elif args.command == "env":
        return cmd_env(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
