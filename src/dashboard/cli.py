"""
CLI entry point for the training dashboard.

Usage:
    python -m src.dashboard              # Start dashboard server
    python -m src.dashboard --demo       # Start with demo data simulation
    python -m src.dashboard --port 8080  # Custom port
"""

import argparse
import asyncio
import random
import threading
import time


def run_demo_simulation(collector):
    """Simulate training progress for demo/testing."""
    from .metrics import collector as mc

    mc = collector

    # Phase 1: Generate fights
    mc.start(phase="generating", target_fights=1000)

    team1 = 0
    team2 = 0
    draws = 0

    for i in range(1, 1001):
        # Simulate fight result
        result = random.random()
        if result < 0.52:  # Slight bias
            team1 += 1
        elif result < 0.97:
            team2 += 1
        else:
            draws += 1

        mc.update_fights(i, team1, team2, draws)
        time.sleep(0.02)  # ~50 fights/sec simulation

    # Phase 2: Training
    mc.set_phase("training", "Starting model training...")
    time.sleep(0.5)

    total_epochs = 20
    steps_per_epoch = 50
    total_steps = total_epochs * steps_per_epoch

    train_loss = 0.7
    val_loss = 0.75
    val_accuracy = 0.5

    for epoch in range(1, total_epochs + 1):
        mc.metrics.epoch = epoch
        mc.metrics.total_epochs = total_epochs

        for step in range(steps_per_epoch):
            global_step = (epoch - 1) * steps_per_epoch + step + 1

            # Simulate decreasing loss
            train_loss *= 0.995
            train_loss += random.gauss(0, 0.005)
            train_loss = max(0.01, train_loss)

            val_loss *= 0.994
            val_loss += random.gauss(0, 0.008)
            val_loss = max(0.02, val_loss)

            # Simulate increasing accuracy
            val_accuracy += random.gauss(0.005, 0.01)
            val_accuracy = min(0.95, max(0.45, val_accuracy))

            mc.update_training(
                epoch=epoch,
                step=global_step,
                train_loss=train_loss,
                val_loss=val_loss if step % 10 == 0 else None,
                val_accuracy=val_accuracy if step % 10 == 0 else None,
                total_steps=total_steps,
            )

            time.sleep(0.05)

    mc.set_phase("done", f"Training complete! Final accuracy: {val_accuracy*100:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="TagadAI Training Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    parser.add_argument("--demo", action="store_true", help="Run with demo simulation")
    args = parser.parse_args()

    from .metrics import collector
    from .server import create_app

    app = create_app(collector)

    if args.demo:
        # Start demo simulation in background thread
        demo_thread = threading.Thread(target=run_demo_simulation, args=(collector,), daemon=True)
        demo_thread.start()

    print(f"\n  TagadAI Training Dashboard")
    print(f"  ==========================")
    print(f"  URL: http://{args.host}:{args.port}")
    if args.demo:
        print(f"  Mode: Demo simulation")
    print(f"\n  Press Ctrl+C to stop\n")

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
