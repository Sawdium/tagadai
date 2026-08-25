"""
Texel fit: eval coefficients from (state, outcome) pairs, no fights per candidate.

Record the state every time the AI is asked to move, label it with the
fight's outcome, fit a logistic regression of the label on the eval's own
stat sums (allies minus enemies). The label stays win/loss only.

    python -m src.tuning.texel collect --roster data/roster.json --fights 1000 --csv data/c.csv
    python -m src.tuning.texel fit --csv data/c.csv --fe build

`collect` plays fights with a tagadalive copy whose `Benchmark.DEBUG_TUNE`
is on (one `TXL|` line per turn, a few hundred ops). `fit` reports the
ENTITY_LEEK row normalised to HP = 1 next to the hand-tuned values.
Fixed effects (`--fe matchup|build|farmer`, sparse) give each identity its
own intercept so a stat only earns credit from what moves. States are
weighted one vote per fight (`--per-state` to disable): draws run to the
turn cap and would otherwise dominate.

Known limit: a state coefficient (the value of *having* a stat) is not the
delta coefficient the eval applies (the value of *changing* it). ml/TODO.md §2.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from src.common.errors import TagadAIError
from src.localfight.batch import GeneratorPool
from src.localfight.logs import collect_logs
from src.localfight.pool import LeekPool
from src.tools.localfight import build_scenario
from src.tuning.variant import materialize

PROBE_TAG = "TXL|"

# Order of the per-entity fields in the probe line, after id:side:bulb.
STATS = ["HP", "HPMAX", "ABSSHIELD", "RELSHIELD", "DMGRETURN", "STR", "MGC", "SNC", "RST", "WSD", "AGI", "TP", "MP"]

# The hand-tuned ENTITY_LEEK row (HiddenKnowledges/EntityCoefs) for the same
# stats, to read the fit against. Delta-only coefs (HPTIME, DEBUFF, ANTIDOTE,
# PWR, KILL) have no state counterpart and are not fitted here.
HAND_TUNED = {"HP": 1.0, "HPMAX": 10.0, "ABSSHIELD": 3.0, "RELSHIELD": 6.0, "DMGRETURN": 3.0,
              "STR": 1.0, "MGC": 1.0, "SNC": 1.0, "RST": 0.8, "WSD": 0.8, "AGI": 0.6, "TP": 40.0, "MP": 60.0}

DEFAULT_PAIRS = [
    "Claudius,Claudias",
    "Claudius,tagadagain:JCGloomy",
    "Claudias,tagadagain:RebeccaSyphilis",
    "Claudios,tagadalone:twogether",
]

CSV_FIELDS = ["matchup", "seed", "orientation", "turn", "logger", "logger_team", "win",
              "entity", "side", "bulb", *STATS]


# ----------------------------------------------------------------- collect


def probe_ai() -> str:
    """The tagadalive copy with the probe compiled in (rebuilt when the source changes)."""
    return materialize({"DEBUG_TUNE": True})


def parse_probe_lines(result: dict) -> list[dict]:
    """Rows for every TXL line of one fight. `win` is 1/0/0.5 for the logger's team."""
    leeks = (result.get("fight") or {}).get("leeks") or []
    team_of = {int(l["id"]): int(l["team"]) for l in leeks if "id" in l and "team" in l}
    # `winner` is a 0-based index into the scenario's team list, while
    # `leeks[].team` carries the 1-based team id (src/localfight/README.md).
    team_index = {t: i for i, t in enumerate(sorted(set(team_of.values())))}
    winner = result.get("winner", -1)
    rows = []
    for eid, _level, text in collect_logs(result):
        if not text.startswith(PROBE_TAG):
            continue
        parts = text[len(PROBE_TAG):].split("|")
        turn, self_id = int(parts[0]), int(parts[1])
        team = team_of.get(self_id)
        if team is None:
            continue
        win = 0.5 if winner < 0 else (1.0 if winner == team_index[team] else 0.0)
        for ent in parts[2:]:
            f = ent.split(":")
            if len(f) != 3 + len(STATS):
                raise TagadAIError(f"probe entry has {len(f)} fields, expected {3 + len(STATS)}: {ent!r}")
            rows.append({
                "turn": turn, "logger": self_id, "logger_team": team, "win": win,
                "entity": int(f[0]), "side": int(f[1]), "bulb": int(f[2]),
                **{name: int(v) for name, v in zip(STATS, f[3:])},
            })
    return rows


def _panel_jobs(pairs: list[str], seeds: int, first_seed: int, turns: int, ai: str, account: str | None):
    pool = LeekPool(account) if account else LeekPool()
    jobs_list = []
    for spec in pairs:
        a, b = (s.strip() for s in spec.split(","))
        ra, rb = pool.resolve(a), pool.resolve(b)
        for seed in range(first_seed, first_seed + seeds):
            for orientation, (t1, t2) in enumerate(((ra, rb), (rb, ra))):
                entities = [pool.entity(t1, 1, ai), pool.entity(t2, 2, ai)]
                if entities[0]["id"] == entities[1]["id"]:
                    entities[1]["id"] += 1
                jobs_list.append((spec, seed, orientation, json.dumps(build_scenario(entities, seed, turns))))
    print(f"{len(jobs_list)} fights ({len(pairs)} matchups x {seeds} seeds x 2 orientations)", file=sys.stderr)
    return jobs_list


def _roster_jobs(roster_path: Path, fights: int, first_seed: int, turns: int, ai: str, rng_seed: int):
    """Random distinct pairs from the roster, both orientations, one seed per pair."""
    import random
    from src.tuning import roster as R
    roster = R.load(roster_path)
    leeks = roster["leeks"]
    if len(leeks) < 2:
        raise TagadAIError(f"{roster_path} holds {len(leeks)} builds; need at least 2")
    rng = random.Random(rng_seed)
    jobs_list = []
    pairs = fights // 2
    for i in range(pairs):
        a, b = rng.sample(leeks, 2)
        seed = first_seed + i
        spec = f"{a['name']}#{a['id']},{b['name']}#{b['id']}"
        for orientation, (t1, t2) in enumerate(((a, b), (b, a))):
            entities = [R.entity(roster, t1, 1, ai), R.entity(roster, t2, 2, ai)]
            jobs_list.append((spec, seed, orientation, json.dumps(build_scenario(entities, seed, turns))))
    print(f"{len(jobs_list)} fights ({pairs} random pairs from {len(leeks)} builds x 2 orientations, "
          f"cores {roster['cores']})", file=sys.stderr)
    return jobs_list


def collect(pairs: list[str], seeds: int, first_seed: int, turns: int, jobs: int | None,
            out: Path, account: str | None, roster: Path | None = None, fights: int = 1000,
            rng_seed: int = 0) -> int:
    ai = probe_ai()
    print(f"probe AI: {ai}", file=sys.stderr)
    if roster is not None:
        jobs_list = _roster_jobs(roster, fights, first_seed, turns, ai, rng_seed)
    else:
        jobs_list = _panel_jobs(pairs, seeds, first_seed, turns, ai, account)

    out.parent.mkdir(parents=True, exist_ok=True)
    n_rows = 0
    with GeneratorPool(workers=jobs) as gen, open(out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()

        def progress(done, total):
            print(f"\r  {done}/{total} fights", end="", file=sys.stderr)

        results = gen.map([j[3] for j in jobs_list], progress=progress)
        print(file=sys.stderr)
        failed = 0
        for (spec, seed, orientation, _), result in zip(jobs_list, results):
            if result is None:
                failed += 1
                continue
            for row in parse_probe_lines(result):
                writer.writerow({"matchup": spec, "seed": seed, "orientation": orientation, **row})
                n_rows += 1
    print(f"{n_rows} rows -> {out}" + (f" ({failed} fights failed)" if failed else ""), file=sys.stderr)
    if n_rows == 0:
        raise TagadAIError("no probe lines came back; check that the copied tree compiled (run one fight with --logs)")
    return n_rows


# --------------------------------------------------------------------- fit


@dataclass
class Fit:
    weights: dict[str, float]      # per raw stat unit, logger's view (allies - enemies)
    bias: float
    n_states: int
    n_fights: int
    log_loss: float
    baseline_log_loss: float
    accuracy: float


def load_states(path: Path, leeks_only: bool = True):
    """Aggregate CSV rows into one feature vector per logged state: sum(side * stat).

    Also returns, per state, the identities a fixed-effects fit can absorb:
    the matchup+orientation+side, and the own / enemy leek ids.
    """
    import numpy as np

    states: dict[tuple, list] = defaultdict(lambda: [0.0] * len(STATS))
    labels: dict[tuple, float] = {}
    ident: dict[tuple, dict] = defaultdict(dict)
    fights = set()
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if leeks_only and row["bulb"] == "1":
                continue
            key = (row["matchup"], row["seed"], row["orientation"], row["logger"], row["turn"])
            side = int(row["side"])
            vec = states[key]
            for i, name in enumerate(STATS):
                vec[i] += side * float(row[name])
            labels[key] = float(row["win"])
            ident[key]["matchup"] = (row["matchup"], row["orientation"], row["logger_team"])
            # In-fight entity ids are renumbered 0,1,2... by the generator, so
            # the build is read off the matchup label (`Name#id,Name#id`),
            # which names team 1's build first in orientation 0.
            ident[key]["own"], ident[key]["enemy"] = _builds_of(row)
            if row.get("farmer"):
                ident[key]["farmer"], ident[key]["enemy_farmer"] = row["farmer"], row["enemy_farmer"]
            fights.add(key[:3])
    keys = sorted(states)
    X = np.array([states[k] for k in keys], dtype=float)
    y = np.array([labels[k] for k in keys], dtype=float)
    idents = [ident[k] for k in keys]
    for k, d in zip(keys, idents):
        d["fight"] = k[:3]
        d["turn"] = int(k[4])
    return X, y, len(fights), idents


def _builds_of(row: dict) -> tuple[str, str]:
    """(own build, enemy build) for a CSV row's logger, as labels."""
    a, _, b = row["matchup"].partition(",")
    if row["orientation"] == "1":
        a, b = b, a
    own_is_team1 = row["logger_team"] == "1"
    return (a, b) if own_is_team1 else (b, a)


def _dummies(ident: list[dict], kind: str):
    """One-hot identity columns (sparse): `matchup` (pair x orientation x side),
    `build` (own leek, enemy leek) or `farmer` (own player, enemy player)."""
    import numpy as np
    from scipy import sparse
    if kind == "matchup":
        keys = [[("m", d.get("matchup"))] for d in ident]
    elif kind == "build":
        keys = [[("o", d.get("own")), ("e", d.get("enemy"))] for d in ident]
    elif kind == "farmer":
        keys = [[("o", d.get("farmer")), ("e", d.get("enemy_farmer"))] for d in ident]
    else:
        raise TagadAIError(f"unknown fixed-effects kind {kind!r}")
    levels = sorted({k for ks in keys for k in ks if k[1]})
    idx = {k: i for i, k in enumerate(levels)}
    rows, cols = [], []
    for r, ks in enumerate(keys):
        for k in ks:
            if k[1]:
                rows.append(r)
                cols.append(idx[k])
    return sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(len(ident), len(levels)))


def fight_weights(ident: list[dict], draws_y=None):
    """One vote per fight: a state weighs 1 / (states of its fight).

    Without this a drawn fight, which runs to the turn cap, contributes four
    times the states of a decisive one and drags every coefficient to 0.5.
    """
    import numpy as np
    from collections import Counter
    n = Counter(d["fight"] for d in ident)
    w = np.array([1.0 / n[d["fight"]] for d in ident])
    return w * len(w) / w.sum()


def fit(path: Path, l2: float = 1e-3, fixed_effects: str = "none",
        per_fight: bool = True, draws: bool = True) -> Fit:
    """Logistic fit of the outcome on the 13 stat sums.

    `fixed_effects="matchup"` adds one intercept per (pair, orientation, side);
    `"build"` one per own build and one per enemy build; `"farmer"` one per
    player on each side. Either way a stat can only earn a coefficient from
    how it *moves* relative to its group's baseline -- which is what stops a
    build constant from standing in for "who is fighting".
    `per_fight` weights states so every fight counts once; `draws=False`
    drops drawn fights altogether.
    """
    import numpy as np

    X, y, n_fights, ident = load_states(path)
    if len(y) == 0:
        raise TagadAIError(f"no states in {path}")
    if not draws:
        keep = y != 0.5
        X, y = X[keep], y[keep]
        ident = [d for d, k in zip(ident, keep) if k]
        n_fights = len({d["fight"] for d in ident})
    return _fit_arrays(X, y, n_fights, ident, l2, fixed_effects,
                       weights=fight_weights(ident) if per_fight else None)


def _fit_arrays(X, y, n_fights, ident, l2, fixed_effects, stats_too: bool = True, weights=None) -> Fit:
    import numpy as np
    from scipy import sparse
    from scipy.optimize import minimize

    n_stats = X.shape[1]
    wt = np.ones(len(y)) if weights is None else np.asarray(weights)
    # Standardise the stats for conditioning; weights are mapped back to raw
    # units after. Identity dummies are appended unscaled, as a sparse block.
    mu, sd = X.mean(axis=0), X.std(axis=0)
    sd[sd == 0] = 1.0
    Zs = (X - mu) / sd
    blocks = [sparse.csr_matrix(Zs)] if stats_too else []
    if fixed_effects != "none":
        blocks.append(_dummies(ident, fixed_effects))
    Z = sparse.hstack(blocks).tocsr()
    n, d = Z.shape

    def loss(theta):
        w, b = theta[:d], theta[d]
        z = Z @ w + b
        p = 1.0 / (1.0 + np.exp(-z))
        eps = 1e-12
        ll = -np.sum(wt * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))) / n + l2 * np.dot(w, w) / 2
        grad_w = Z.T @ (wt * (p - y)) / n + l2 * w
        grad_b = np.sum(wt * (p - y)) / n
        return ll, np.append(grad_w, grad_b)

    res = minimize(loss, np.zeros(d + 1), jac=True, method="L-BFGS-B", options={"maxiter": 500})
    theta = res.x
    p = 1.0 / (1.0 + np.exp(-(Z @ theta[:d] + theta[d])))
    if stats_too:
        w_raw = theta[:n_stats] / sd
        b_raw = theta[d] - float(np.dot(w_raw, mu))
    else:
        w_raw, b_raw = np.zeros(n_stats), float(theta[d])
    eps = 1e-12
    ll = float(-np.sum(wt * (y * np.log(p + eps) + (1 - y) * np.log(1 - p + eps))) / n)
    base = float(np.clip(np.sum(wt * y) / n, eps, 1 - eps))
    baseline = float(-np.sum(wt * (y * np.log(base) + (1 - y) * np.log(1 - base))) / n)
    acc = float(np.sum(wt * ((p > 0.5) == (y > 0.5))) / n)
    return Fit({name: float(v) for name, v in zip(STATS, w_raw[:n_stats])}, float(b_raw), n, n_fights, ll, baseline, acc)


def report(f: Fit) -> None:
    hp = f.weights["HP"]
    scale = 1.0 / hp if hp != 0 else 1.0
    print(f"states {f.n_states}  fights {f.n_fights}  log-loss {f.log_loss:.4f} (baseline {f.baseline_log_loss:.4f})  accuracy {f.accuracy:.3f}")
    print(f"{'stat':10s} {'fitted':>10s} {'/HP':>9s} {'hand':>8s}")
    for name in STATS:
        print(f"{name:10s} {f.weights[name]:10.5f} {f.weights[name] * scale:9.3f} {HAND_TUNED[name]:8.2f}")
    print(f"bias {f.bias:.4f}   (fitted /HP column is comparable to the hand-tuned ENTITY_LEEK row)")


# --------------------------------------------------------------------- CLI


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="play fights with the probe and write the CSV")
    c.add_argument("--pair", action="append", help="matchup `A,B` (repeatable; default: the aibench panel)")
    c.add_argument("--seeds", type=int, default=100)
    c.add_argument("--first-seed", type=int, default=1)
    c.add_argument("--turns", type=int, default=64)
    c.add_argument("--jobs", type=int, default=None, help="parallel fights (default: physical cores)")
    c.add_argument("--csv", type=Path, default=Path("data/texel.csv"))
    c.add_argument("--account", help="override LEEKWARS_LOGIN for bare leek names")
    c.add_argument("--roster", type=Path, help="random pairs from a src.tuning.roster JSON instead of --pair")
    c.add_argument("--fights", type=int, default=1000, help="with --roster: fights to play (2 per pair)")
    c.add_argument("--rng-seed", type=int, default=0, help="with --roster: pair sampling seed")
    f = sub.add_parser("fit", help="fit the ENTITY_LEEK row to a CSV")
    f.add_argument("--csv", type=Path, default=Path("data/texel.csv"))
    f.add_argument("--l2", type=float, default=1e-3)
    f.add_argument("--fe", choices=["none", "matchup", "build", "farmer"], default="none",
                   help="fixed effects: intercept per matchup x side, per own/enemy build, or per player")
    f.add_argument("--per-state", action="store_true", help="weight states equally instead of fights")
    f.add_argument("--no-draws", action="store_true", help="drop drawn fights")
    args = ap.parse_args()
    try:
        if args.cmd == "collect":
            collect(args.pair or DEFAULT_PAIRS, args.seeds, args.first_seed, args.turns, args.jobs, args.csv,
                    args.account, roster=args.roster, fights=args.fights, rng_seed=args.rng_seed)
        else:
            report(fit(args.csv, args.l2, args.fe, per_fight=not args.per_state, draws=not args.no_draws))
    except TagadAIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
