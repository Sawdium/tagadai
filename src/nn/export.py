"""
Export trained model weights to LeekScript format.

Generates LeekScript code that can be included in the AI.
"""

from pathlib import Path
import json
import numpy as np
import torch

from .model import ActionScoringMLP


def export_to_leekscript(
    model: ActionScoringMLP,
    output_path: Path | str,
    precision: int = 6,
) -> str:
    """
    Export model weights to LeekScript format.

    Args:
        model: Trained model
        output_path: Where to save the LeekScript file
        precision: Decimal precision for weights

    Returns:
        Path to the generated file
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    weights = model.get_weights()

    # Format weights as LeekScript arrays
    def format_array(arr: np.ndarray, name: str) -> str:
        """Format numpy array as LeekScript global variable."""
        if arr.ndim == 1:
            # 1D array (bias)
            values = ", ".join(f"{v:.{precision}f}" for v in arr)
            return f"global {name} = [{values}]"
        else:
            # 2D array (weights) - stored as [out][in]
            rows = []
            for row in arr:
                values = ", ".join(f"{v:.{precision}f}" for v in row)
                rows.append(f"[{values}]")
            return f"global {name} = [{', '.join(rows)}]"

    # Generate LeekScript code
    lines = [
        "// Neural Network Weights",
        "// Auto-generated - do not edit manually",
        f"// Model: {model.state_dim} + {model.action_dim} -> {model.hidden1} -> {model.hidden2} -> 1",
        "",
        "// Layer 1 weights and bias",
        format_array(weights['W1'], 'W1'),
        format_array(weights['b1'], 'b1'),
        "",
        "// Layer 2 weights and bias",
        format_array(weights['W2'], 'W2'),
        format_array(weights['b2'], 'b2'),
        "",
        "// Output layer weights and bias",
        format_array(weights['W3'], 'W3'),
        format_array(weights['b3'], 'b3'),
    ]

    content = "\n".join(lines)

    with open(output_path, 'w') as f:
        f.write(content)

    return str(output_path)


def export_forward_pass(output_path: Path | str) -> str:
    """
    Generate LeekScript code for the forward pass.

    Args:
        output_path: Where to save the LeekScript file

    Returns:
        Path to the generated file
    """
    output_path = Path(output_path)

    code = '''// Neural Network Forward Pass
// Computes score for a (state, action) feature pair

include('Weights')

// ReLU activation
function relu(x) {
    if (x > 0) return x
    return 0
}

// Forward pass through the network
// features: array of floats (state + action features concatenated)
// Returns: score (higher = better action)
function nnForward(features) {
    var inputSize = count(features)

    // Layer 1: input -> hidden1
    var h1Size = count(b1)
    var h1 = []
    for (var i = 0; i < h1Size; i++) {
        var sum = b1[i]
        for (var j = 0; j < inputSize; j++) {
            sum += features[j] * W1[i][j]
        }
        push(h1, relu(sum))
    }

    // Layer 2: hidden1 -> hidden2
    var h2Size = count(b2)
    var h2 = []
    for (var i = 0; i < h2Size; i++) {
        var sum = b2[i]
        for (var j = 0; j < h1Size; j++) {
            sum += h1[j] * W2[i][j]
        }
        push(h2, relu(sum))
    }

    // Output: hidden2 -> score
    var score = b3[0]
    for (var j = 0; j < h2Size; j++) {
        score += h2[j] * W3[0][j]
    }

    return score
}

// Score multiple actions and return index of best
// stateFeatures: array of state features
// actionFeaturesList: array of action feature arrays
// Returns: index of highest-scoring action
function nnSelectBest(stateFeatures, actionFeaturesList) {
    var bestIdx = 0
    var bestScore = -999999

    var numActions = count(actionFeaturesList)
    for (var i = 0; i < numActions; i++) {
        // Concatenate state and action features
        var features = []
        for (var j in stateFeatures) {
            push(features, stateFeatures[j])
        }
        for (var j in actionFeaturesList[i]) {
            push(features, actionFeaturesList[i][j])
        }

        var score = nnForward(features)
        if (score > bestScore) {
            bestScore = score
            bestIdx = i
        }
    }

    return bestIdx
}
'''

    with open(output_path, 'w') as f:
        f.write(code)

    return str(output_path)


def export_features(output_path: Path | str) -> str:
    """
    Generate LeekScript code for feature extraction.

    Args:
        output_path: Where to save the LeekScript file

    Returns:
        Path to the generated file
    """
    output_path = Path(output_path)

    code = '''// Feature extraction for Neural Network
// Extracts state and action features from fight state

// Extract state features (context)
// Returns: array of 23 floats
function extractStateFeatures(selfEntity, enemyEntity, turn, dangerCurrent, dangerBest) {
    var selfLife = getLife(selfEntity)
    var selfTotalLife = getTotalLife(selfEntity)
    var selfTP = getTP(selfEntity)
    var selfMP = getMP(selfEntity)
    var selfStr = getStrength(selfEntity)
    var selfMgc = getMagic(selfEntity)
    var selfAgi = getAgility(selfEntity)
    var selfRst = getResistance(selfEntity)

    var enemyLife = getLife(enemyEntity)
    var enemyTotalLife = getTotalLife(enemyEntity)
    var enemyTP = getTP(enemyEntity)
    var enemyMP = getMP(enemyEntity)
    var enemyStr = getStrength(enemyEntity)
    var enemyMgc = getMagic(enemyEntity)

    var distance = getCellDistance(getCell(selfEntity), getCell(enemyEntity))

    // Normalize values
    var features = [
        selfLife / max(selfTotalLife, 1),           // self_hp_ratio
        selfTP / 20.0,                               // self_tp_norm
        selfMP / 10.0,                               // self_mp_norm
        selfStr / 500.0,                             // self_str_norm
        selfMgc / 500.0,                             // self_mgc_norm
        selfAgi / 500.0,                             // self_agi_norm
        selfRst / 500.0,                             // self_rst_norm
        enemyLife / max(enemyTotalLife, 1),         // enemy_hp_ratio
        enemyTP / 20.0,                              // enemy_tp_norm
        enemyMP / 10.0,                              // enemy_mp_norm
        enemyStr / 500.0,                            // enemy_str_norm
        enemyMgc / 500.0,                            // enemy_mgc_norm
        distance / 20.0,                             // distance_norm
        dangerCurrent / max(selfTotalLife, 1),      // danger_current_norm
        dangerBest / max(selfTotalLife, 1),         // danger_best_norm
        dangerBest > 0 ? dangerCurrent / dangerBest : 1.0,  // danger_ratio
        0.0,  // self_has_poison (TODO: implement)
        0.0,  // self_has_shield (TODO: implement)
        0.0,  // enemy_has_poison (TODO: implement)
        0.0,  // enemy_has_shield (TODO: implement)
        turn / 64.0,                                 // turn_norm
        0.0,  // can_kill_this_turn (TODO: implement)
        dangerCurrent >= selfLife ? 1.0 : 0.0       // at_risk
    ]

    return features
}

// Extract action features for a single action
// Returns: array of 34 floats
function extractActionFeatures(
    actionType,      // 'weapon', 'chip', 'move', 'end'
    itemId,          // weapon or chip ID (null for move/end)
    selfEntity,
    enemyEntity,
    damageDealt,
    healDone,
    shieldAdded,
    poisonApplied,
    tpCost,
    mpCost,
    dangerAfter,
    dangerBefore,
    cellAfter
) {
    var selfTP = getTP(selfEntity)
    var selfMP = getMP(selfEntity)
    var selfLife = getLife(selfEntity)
    var selfTotalLife = getTotalLife(selfEntity)
    var enemyLife = getLife(enemyEntity)
    var enemyTotalLife = getTotalLife(enemyEntity)

    // Item property features (20 floats)
    var itemFeatures = getItemFeatures(actionType, itemId)

    // Consequence features (14 floats)
    var distBefore = getCellDistance(getCell(selfEntity), getCell(enemyEntity))
    var distAfter = getCellDistance(cellAfter, getCell(enemyEntity))

    var conseqFeatures = [
        damageDealt / max(enemyTotalLife, 1),           // damage_dealt_norm
        enemyLife > 0 ? damageDealt / enemyLife : 0,    // damage_dealt_ratio
        healDone / max(selfTotalLife, 1),               // heal_done_norm
        shieldAdded / max(selfTotalLife, 1),            // shield_added_norm
        poisonApplied / max(enemyTotalLife, 1),         // poison_applied_norm
        selfTP > 0 ? tpCost / selfTP : 0,               // tp_cost_ratio
        selfMP > 0 ? mpCost / selfMP : 0,               // mp_cost_ratio
        dangerAfter / max(selfTotalLife, 1),            // danger_after_norm
        (dangerAfter - dangerBefore) / max(selfTotalLife, 1),  // danger_delta_norm
        distAfter / 20.0,                               // distance_after_norm
        (distAfter - distBefore) / 20.0,                // distance_delta_norm
        damageDealt >= enemyLife ? 1.0 : 0.0,           // is_kill
        cellAfter == getCell(selfEntity) ? 1.0 : 0.0,   // is_self_target
        dangerAfter >= selfLife ? 1.0 : 0.0             // will_die_after
    ]

    // Concatenate
    var features = []
    for (var f in itemFeatures) push(features, itemFeatures[f])
    for (var f in conseqFeatures) push(features, conseqFeatures[f])

    return features
}

// Get item property features (20 floats)
function getItemFeatures(actionType, itemId) {
    // Item type flags
    var isWeapon = actionType == 'weapon' ? 1.0 : 0.0
    var isChip = actionType == 'chip' ? 1.0 : 0.0
    var isMove = actionType == 'move' ? 1.0 : 0.0
    var isEnd = actionType == 'end' ? 1.0 : 0.0

    // Effect type flags (simplified - would need item lookup table)
    var isDamage = (actionType == 'weapon') ? 1.0 : 0.0
    var isHeal = 0.0
    var isShield = 0.0
    var isBuff = 0.0
    var isPoison = 0.0
    var isDebuff = 0.0
    var isSummon = 0.0
    var isUtility = 0.0
    var isDmgReturn = 0.0

    // Damage type
    var isPhysical = (actionType == 'weapon') ? 1.0 : 0.0
    var isMagic = (actionType == 'chip') ? 1.0 : 0.0

    // Costs and ranges (normalized)
    var tpCostNorm = 0.15  // Default ~3/20
    var minRangeNorm = 0.08  // Default 1/12
    var maxRangeNorm = 0.5   // Default 6/12
    var hasAoe = 0.0
    var levelReqNorm = 0.1   // Default low level

    return [
        isWeapon, isChip, isMove, isEnd,
        isDamage, isHeal, isShield, isBuff, isPoison, isDebuff, isSummon, isUtility, isDmgReturn,
        isPhysical, isMagic,
        tpCostNorm, minRangeNorm, maxRangeNorm,
        hasAoe, levelReqNorm
    ]
}
'''

    with open(output_path, 'w') as f:
        f.write(code)

    return str(output_path)


def export_all(
    model: ActionScoringMLP,
    output_dir: Path | str,
) -> dict[str, str]:
    """
    Export all LeekScript files needed for the NN AI.

    Args:
        model: Trained model
        output_dir: Directory to save files

    Returns:
        Dict mapping file type to path
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {
        'weights': export_to_leekscript(model, output_dir / 'Weights'),
        'forward': export_forward_pass(output_dir / 'Forward'),
        'features': export_features(output_dir / 'Features'),
    }

    print(f"Exported LeekScript files to {output_dir}:")
    for name, path in paths.items():
        print(f"  {name}: {path}")

    return paths


def main():
    """Export a trained model to LeekScript."""
    import argparse

    parser = argparse.ArgumentParser(description="Export model to LeekScript")
    parser.add_argument("--model", type=str, default="data/nn/model.pt",
                       help="Path to trained model")
    parser.add_argument("--output", type=str, default="tagadann/NN",
                       help="Output directory for LeekScript files")

    args = parser.parse_args()

    # Load model
    model = ActionScoringMLP()
    model.load_state_dict(torch.load(args.model))
    model.eval()

    # Export
    export_all(model, args.output)


if __name__ == "__main__":
    main()
