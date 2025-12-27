"""
Training script for the action scoring network.

Usage:
    python -m src.nn.train --max-level 40 --epochs 50 --limit 1000
"""

import argparse
from pathlib import Path
import json
import time

import torch
from torch.utils.data import DataLoader
from torch.optim import Adam
from torch.optim.lr_scheduler import ReduceLROnPlateau

from .dataset import load_dataset, collate_fn
from .model import ActionScoringMLP, RankingLoss
from .features import FeatureExtractor


def train_epoch(
    model: ActionScoringMLP,
    train_loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: RankingLoss,
    device: torch.device,
) -> float:
    """Train for one epoch, return average loss."""
    model.train()
    total_loss = 0.0
    num_batches = 0

    for state, action, label in train_loader:
        state = state.to(device)
        action = action.to(device)
        label = label.to(device)

        optimizer.zero_grad()
        scores = model(state, action)
        loss = criterion(scores, label)
        loss.backward()
        optimizer.step()

        total_loss += loss.item()
        num_batches += 1

    return total_loss / max(num_batches, 1)


def evaluate(
    model: ActionScoringMLP,
    val_loader: DataLoader,
    criterion: RankingLoss,
    device: torch.device,
) -> tuple[float, float]:
    """Evaluate model, return (loss, accuracy)."""
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for state, action, label in val_loader:
            state = state.to(device)
            action = action.to(device)
            label = label.to(device)

            scores = model(state, action)
            loss = criterion(scores, label)

            total_loss += loss.item()

            # Accuracy: score > 0 should correspond to label = 1
            preds = (scores > 0).float()
            correct += (preds == label).sum().item()
            total += label.size(0)

    avg_loss = total_loss / max(len(val_loader), 1)
    accuracy = correct / max(total, 1)
    return avg_loss, accuracy


def train(
    max_level: int = 40,
    limit: int | None = None,
    epochs: int = 50,
    batch_size: int = 64,
    lr: float = 0.001,
    hidden1: int = 32,
    hidden2: int = 16,
    output_dir: str = "data/nn",
) -> ActionScoringMLP:
    """
    Train the action scoring model.

    Args:
        max_level: Maximum leek level for training data
        limit: Maximum fights to use (None for all)
        epochs: Number of training epochs
        batch_size: Batch size
        lr: Learning rate
        hidden1: Hidden layer 1 size
        hidden2: Hidden layer 2 size
        output_dir: Where to save model

    Returns:
        Trained model
    """
    # Setup
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Load data
    train_ds, val_ds = load_dataset(
        fight_type=0,
        max_level=max_level,
        limit=limit,
        train_ratio=0.8,
    )

    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_fn,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        collate_fn=collate_fn,
    )

    # Model
    fe = FeatureExtractor()
    state_dim = fe.extract_state_features.__code__.co_varnames  # Hack to get defaults
    state_dim = 23  # StateFeatures.vector_size()
    action_dim = 34  # ActionFeatures.vector_size()

    model = ActionScoringMLP(
        state_dim=state_dim,
        action_dim=action_dim,
        hidden1=hidden1,
        hidden2=hidden2,
    ).to(device)

    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    # Training setup
    criterion = RankingLoss()
    optimizer = Adam(model.parameters(), lr=lr)
    scheduler = ReduceLROnPlateau(optimizer, mode='min', factor=0.5, patience=5)

    best_val_loss = float('inf')
    best_epoch = 0

    # Training loop
    print(f"\nTraining for {epochs} epochs...")
    print("-" * 60)

    for epoch in range(epochs):
        start = time.time()

        train_loss = train_epoch(model, train_loader, optimizer, criterion, device)
        val_loss, val_acc = evaluate(model, val_loader, criterion, device)

        scheduler.step(val_loss)

        elapsed = time.time() - start

        # Save best
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_epoch = epoch
            torch.save(model.state_dict(), output_path / "best_model.pt")

        # Progress
        lr_current = optimizer.param_groups[0]['lr']
        print(
            f"Epoch {epoch+1:3d}/{epochs} | "
            f"Train Loss: {train_loss:.4f} | "
            f"Val Loss: {val_loss:.4f} | "
            f"Val Acc: {val_acc:.1%} | "
            f"LR: {lr_current:.6f} | "
            f"Time: {elapsed:.1f}s"
        )

    print("-" * 60)
    print(f"Best val loss: {best_val_loss:.4f} at epoch {best_epoch+1}")

    # Load best model
    model.load_state_dict(torch.load(output_path / "best_model.pt"))

    # Save final model and config
    torch.save(model.state_dict(), output_path / "model.pt")

    config = {
        "state_dim": state_dim,
        "action_dim": action_dim,
        "hidden1": hidden1,
        "hidden2": hidden2,
        "max_level": max_level,
        "epochs": epochs,
        "best_epoch": best_epoch,
        "best_val_loss": best_val_loss,
    }
    with open(output_path / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nModel saved to {output_path}")
    return model


def main():
    parser = argparse.ArgumentParser(description="Train action scoring model")
    parser.add_argument("--max-level", type=int, default=40, help="Max leek level")
    parser.add_argument("--limit", type=int, default=None, help="Max fights to use")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--hidden1", type=int, default=32, help="Hidden layer 1 size")
    parser.add_argument("--hidden2", type=int, default=16, help="Hidden layer 2 size")
    parser.add_argument("--output", type=str, default="data/nn", help="Output directory")

    args = parser.parse_args()

    train(
        max_level=args.max_level,
        limit=args.limit,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        hidden1=args.hidden1,
        hidden2=args.hidden2,
        output_dir=args.output,
    )


if __name__ == "__main__":
    main()
