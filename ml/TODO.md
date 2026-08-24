# ML / tuning programme

Working notes for making `tagadalive`'s scoring tunable. Everything here
assumes the constraint we settled on early: **the only true signal is
win/loss at the end of the fight.** Damage is a proxy, and tuning against
it would delete exactly the positional/temporal judgement that makes the
current hand-tuned scoring good.

Status legend: `[ ]` open · `[~]` in progress · `[x]` done

**Where it stands:** the danger model went first, was measured, was fixed, and
is now **frozen** (§1). §2, the tuning harness, is the active work.
Closed decisions are listed in §4 so they are not re-argued.

---

## 1. Danger model — frozen, low priority

Reference for anything that touches it later. The map is a **conditional worst
case**: per enemy, take the best damage-per-TP item and spend that enemy's TP on
it, respecting use limits and cooldowns (`Items.getOrderedOffensiveItems`, then
the item loop in `Damages.computeDanger`). It answers *what could this cell cost
me if every enemy went fully offensive*, not *what will it cost me*.

So **the gap between predicted and realized is not an error and not a metric** —
a well-chosen cell is one the enemy declines to attack. Exactly one thing counts:

> **when does the realized damage come in ABOVE the danger predicted?**

Measured over 20 seeds per matchup with `python -m src.tools.dangerprobe`
(the probe block in `tagadalive/main` is gated on `Benchmark.DEBUG_DANGER`, a
compile-time constant, false in the shipped AI): 5.9% breaches on magic mirrors
up to 16.8% on strength matchups. **The error is conditioned, not scalar** —
0.7% against 20.3% between two leeks in the same fights, 0.6% at 2-6 cells
against 7.6% at 7+ — which is why no fitted weight can absorb it, and why the
model had to come before the weights.

What is left breaches by cause (JCGloomy mirror, ~12% baseline): liberation
53%, teleportation 53%, stalactite 25%, inversion 17%. Adrenaline sits *below*
baseline; danger-map truncation is 1 turn in 1364, at `E:5/5` — both hypotheses
closed.

### Rules any future metric over this data must respect

1. **Nova damage is not damage.** `EffectNovaDamage` calls
   `removeLife(0, value, ...)` — everything into erosion, capped at the HP
   already missing. Action 107 lowers MAX life; current life never moves.
   Counting it invented a 63% breach rate out of nothing.
2. **The bound is on the total, not the components.** The enemy's whole TP goes
   to its best damage-per-TP item, so a poison build leaves `dmg` at 0 and fires
   anyway. `dmg` alone reads 48%; `dmg + psnDmg` against instant + poison reads
   12%. `Danger.score` uses the sum, so the sum is the bound.
3. **Ally healing is already subtracted from the prediction**, so it has to be
   netted off the realized side too.
4. **Poison is charged at the start of the victim's own turn**, outside the
   "between our turns" window — it needs window A *and* our next turn. And
   `psnDmg` is duration-mitigated, so one turn of ticks under it is expected.
5. **Poison already ticking on us is not the cell's fault.** Left in, it *was*
   the measurement: 154 of 208 breaches were pure pre-existing poison at a
   median 15 cells from the nearest enemy. Subtracting `Entity.psnTurn` took the
   mirror from 13.8% to 5.9%.

### The measurement is the bottleneck

- Runs are **not paired**. Changing the danger changes which cells the AI picks,
  so fights diverge from turn one. A slice moved 50.0 -> 56.1 -> 55.5 across
  three runs that changed nothing about it: ~5 points is the noise floor.
- **Paired-prefix comparison is the one paired signal this harness produces.**
  Both runs share seeds, so each fight is identical until the changed danger
  first alters a choice. Filtering to turns where turn, cell, hp, tp, mp, enemy
  count, both shields, distance and `libe_mapped` all match gave 862 truly
  paired turns for the `effectiveRel` fix — 852 unchanged, 10 changed, 9 of them
  upward, median +243 HP. Reuse it for any change too small for the aggregate.
- Anything finer needs prediction scored against *recorded* fights instead of
  freshly played ones.

Datasets kept for re-analysis (`--report-only --csv <file>`, no fights
replayed): `data/danger_20260824_*.csv`, `data/danger_after_*.csv`.

### Open

- [ ] *(low)* Liberation without the TP debit. The branch charges the enemy
      5 TP, which costs more predicted damage than the halved shield adds back —
      the likely reason the liberation fix did not move the rate. A worst case
      should assume both.
- [ ] *(low)* Teleportation and inversion: the enemy ends up somewhere the reach
      maps never credited. Second and third largest breach classes, unmodelled.
- [ ] *(low)* `Entity.nextLiberation` is written at `MapDanger:138` and read
      nowhere. Delete the call or wire it up.

---

## 2. Tuning harness — active

**Prerequisite:** `tagadalive/TODO.md` §1.5 — the ally-in-danger boost reaches
only mid-turn summons, never ally leeks. `ALLY_CANDIE_MODIFIER` must not be
fitted before that ordering is settled, or the fitted value silently changes
meaning when it is.

### 2.0 Plumbing — done 2026-08-24

- [x] **Fights are 8x cheaper.** Compile cache on (was `--nocache` on every
      fight: 10.3s -> 3.4s), persistent generator JVMs (`src/localfight/batch.py`),
      measured JVM flags. 0.26 -> 2.07 fights/s on 8 workers, ~7,500/hour.
      Numbers and reasons in `src/localfight/README.md`.
- [x] **§2.3 counters surfaced** without touching the AI: `FightResult.turn_stats`
      reads the `ComboExplorer: N combos` and `##MARKER##…|o:ops/max` lines the
      AI already logs every turn.
- [x] **Variant materialiser** (`src/tuning/variant.py`): `materialize({"KILL_VALUE": 25000,
      "ENTITY_LEEK.HP": 1.2})` -> a rewritten copy under `.cache/variants/`, named
      by overrides + source fingerprint, playable as an AI path.

### 2.0b Direction — Texel first (2026-08-24)

The win-rate loop is the *validator*, not the optimiser. One `aibench`
evaluation with enough discordant pairs to see a 60/40 edge is ~1,300 fights;
even at 2 fights/s that is ~3 evaluations an hour, and SPSA/CMA-ES over 178
constants needs thousands. Instead: record the state every time the AI is
asked to move, label it with the fight's outcome, and fit the eval's own
coefficients by logistic regression over the corpus -- Texel tuning. Zero
fights per candidate; the label stays win/loss only. `src/tuning/texel.py`.

- [x] Probe: `Benchmark.DEBUG_TUNE` gates a `TXL|` line after `init()` in
      `main` (every living entity's stats, +1 ally / -1 enemy). A few hundred
      ops a turn; it does not truncate the search it observes.
- [x] Go/no-go, 2026-08-24: 800 fights (aibench panel + mirror, 100 seeds x 2
      orientations), 31,510 states, `data/texel_20260824.csv`. **Go, but not
      on this corpus.** Log-loss 0.22 vs 0.69 baseline, 92% accuracy -- but
      matchup x side dummies alone reach 0.245 / 92.0%; the stats add only
      0.245 -> 0.216. Five builds, near-deterministic outcomes per matchup.
      What moves within a fight (HP, HPMAX, TP, MP) fits with the right sign
      and scale and survives fixed effects (TP 85 vs hand 40, MP 112 vs 60).
      What does not move (STR, RST, MGC...) is build identity: RST -24 is
      "Claudias loses to Claudius". RELSHIELD stays negative under fixed
      effects: a shield up means under attack -- the "king in check" problem.
- [x] **Corpus 2: 56 real builds** (`src/tuning/roster.py`: own leeks on the
      five accounts + their garden opponents + ladder top, full packages via
      `/leek/get`, cores/ram overridden to ours), 500 random pairs x 2
      orientations, `data/texel_roster_20260824.csv`, 58,220 states, 15% draws.
      Not random builds: a leek is a package (capital + components + chips +
      weapons) and the generator only sees its final numbers; random stats
      would fit a world nobody plays. Log-loss: build identity only 0.540,
      stats only 0.561, both 0.500 (acc 75%). Stats now add information on
      top of who is fighting. `fit --fe build` is the honest fit.
      - **Measurable:** TP 60 / MP 70 vs hand 40 / 60 -- above the hand value
        on both corpora, with and without fixed effects. First candidate
        for an `aibench` validation.
      - RELSHIELD flipped positive (4.4 vs hand 6) once builds varied.
      - HPMAX ~0: collinear with HP in a state, and the hand 10 pays a
        *loss* of max HP (erosion), which a state does not show.
      - Base stats (STR, RST, AGI, WSD) still unidentifiable: under build
        fixed effects they only move through buffs/debuffs, which are
        reactions ("king in check" again). Needs quiet states or deltas.
- [x] **Replayer** (`src/tuning/replay.py`, 2026-08-25): scraped `/fight/get`
      replays -> the same states the probe logs. Validated on local fights:
      3,354 values, 0 mismatches. Traps found on the way: `112` nova
      vitality raises max life only (`104` raises both); `[12, chip, ...]`
      carries the CHIP id (manumission = 100) while the effect it adds
      carries the ITEM id (174); tagadalive casts manumission before
      `init()`, so the snapshot skips that cast and its removals.
- [x] **Site corpus** `data/texel_site_2025-12.csv`: 11,834 solo 301-vs-301
      fights from `fights.db` (Dec 2025), 1,816 leeks, 773 farmers, 533k
      states. **Per-fight weighting is mandatory**: draws are 18% of fights
      but 50% of states (they run to the 64-turn cap) and drag every
      coefficient toward 0.5. `fit` now weights each state by 1/(states of
      its fight); `--per-state` restores the old behaviour, `--no-draws`
      drops draws. Fixed effects are sparse (`--fe farmer` for the site).
- [x] **Result** (farmer FE, per-fight, 90% bootstrap CI over fights):
      TP 38 [33, 41] vs hand 40; MP 54 [46, 64] vs 60; RELSHIELD 7.4 [6.8, 8.3]
      vs 6; ABSSHIELD 2.2 vs 3; DMGRETURN 2.6 vs 3; STR 1.3 [1.2, 1.4] vs 1;
      MGC 1.5 vs 1. **The hand-tuned row is validated on real fights for
      everything a state can see.** Still unidentifiable: HPMAX (collinear;
      the hand value pays erosion), SNC ~0, RST < 0, WSD ~0.
      Corpus 2 re-fitted per-fight: TP 51 [35, 64], MP 109 [84, 134] -- MP
      disjoint from the site interval: play-dependent, or corpus 2 too small.
- [ ] Corpus 2 x4 (4,000 fights, ~35 min) to settle MP under our play; then
      `aibench` on `ENTITY_LEEK.MP` at the fitted value vs current.
- [ ] Shields and base stats need a delta-based or "quiet state" treatment
      before their coefficients mean anything.
- [ ] Re-scrape fresh 301 solo fights for the temporal check (which
      coefficients move with the meta).
- [ ] Then: modifier exponents (§2.4 as a fit), per-archetype conditioning
      (§2.2 as a regression term), `aibench` on the fitted candidate.

### 2.1 Position dump under a surplus-cores harness

- [~] Dump evaluated positions with their outcome labels. **The per-turn
      state dump (§2.0b) is done and is enough for Texel.** What is left
      open is dumping the *evaluated combos* too, which is what needs the
      surplus cores below.

Must run with **more cores than the live budget**. The AI deliberately
saturates its op budget — it runs as many evaluations as fit in the turn.
A dump that costs operations therefore truncates the very search it is
trying to record, and the corpus silently becomes a sample of shallow
turns. Give the dump headroom so it observes without perturbing.

### 2.2 Optimiser, per archetype

- [ ] SPSA or CMA-ES, fitted separately per archetype.

Build and weights interact. A single global fit averages over archetypes
that want genuinely different trade-offs, and the average may be worse for
every one of them than its own fit would be.

### 2.3 Gate on evaluation count, not just score

- [~] The harness must record evaluations-per-turn alongside win rate, and
      reject candidates that reduce it. Recording is done (`turn_stats`);
      the gate itself is not written.

This is the subtle one. A weight change can **truncate the search** without
any individual score being wrong — make the eval more expensive, fewer
combos fit in the budget, strength drops. The score function looks fine in
isolation; the AI is simply thinking less. Win rate alone cannot separate
"worse judgement" from "less search", and the fix for each is opposite.

### 2.4 Modifier scales are not commensurable

- [ ] Decide whether `getChipReadyModifier`'s *range* should be compressed, not
      just clamped.

The clamp (`CHIP_READY_MAX`, added 2026-08-23) stops a runaway; it does not make
the term comparable to its neighbours. Measured on the live roster, this one
modifier multiplies a coefficient by **x17.0** (Claudias/Claudies, RST 8.5),
x13.0 (Claudius, WSD 6.5) and x10.0 (AGI 5.0), while every sibling in
`ScoringModifiers` clamps to roughly [0.5, 1.5] or [1, 5] — and all of them
multiply into the same `base *=` chain at `Scoring:307/314`.

So chip-readiness currently dominates that product by an order of magnitude.
That may be exactly what was intended when it was hand-tuned, which is why
compressing it is a decision and not a cleanup: dropping the ceiling to 5.0
would take Claudias and Claudies from x17 to x5 on resistance scoring and
needs win-rate validation, not just a smoke test.

**Why it matters for fitting**: an optimiser perturbing several modifiers at
once cannot tell "this weight is important" from "this weight sits on a
scale ten times larger than the others". Any per-modifier bound the tuner
respects should be recorded here before the first SPSA/CMA-ES run.

---

## 3. Carnet

Public journal, now a blog: `ideesnoires.fr/leekwars/carnet/` lists the
entries, each entry lives at `/carnet/<numeral>/`. Source:
`~/Desktop/ideesnoires/leekwars/carnet/`, deployed with `leekwars/deploy.sh`
(rsync + chown, no service restart).

Articles I and II are published as **illustrated bullet plans, not finished
prose** — deliberate, the prose gets written over them.

- [ ] **Article I** — "Où branche-t-on un réseau sur un poireau ?"
      (`/carnet/i/`). Write the prose over the plan. The plan already carries
      the correction that prompted the rewrite: the article had said Stockfish
      *"fonctionne pareil"*. The shape is shared (search + eval), the depth is
      not — `tagadalive` has **no lookahead beyond the current turn**, so the
      whole future lives inside the single-turn eval (`turnsLeft`,
      `durationMitigation`, `getEffectiveDuration`, turn-order modifiers, danger
      and threat maps). That is why the eval carries so much strategy, and
      therefore why tuning it is the whole project.
- [ ] **Article II** — "La seule chose que mon IA prédit vraiment"
      (`/carnet/ii/`). Write the prose over the plan.
- [x] **Article III** — "Huit fois plus de combats, et une idée volée aux
      échecs" (`/carnet/iii/`), 2026-08-24. Illustrated bullet plan like I
      and II: the compile pipeline and where a fight's time goes, the
      throughput bars, the Texel idea with a dataset grid and the first fit.
- [ ] **Article IV** — "Le banc d'essai". Not started. Article II ends on the
      noise floor, which is exactly what this one is about.

Material on hand for IV:
- **The forced-50% artifact.** `aibench` returned exactly 50%, every time.
  Cause, read out of the generator source: `StartOrder.compute` draws turn
  order weighted only by `frequency`, and consumes the same RNG values in
  both orientations — so on a mirrored build, identical AIs are *forced*
  to 1W-1L per seed. A benchmark that cannot report anything but a tie.
  Good opening: the instrument was broken in a way that looked like a
  perfectly clean result.
- **Seed pairs and McNemar.** Why paired seeds, why only discordant pairs
  carry information, and why this is the right test.
- **Sampling noise vs replication noise.** Same seed reproduces; different
  seeds do not. These are two different uncertainties and conflating them
  is how people talk themselves into fake improvements.
- **The unpaired-run trap, from §1** — and the paired-prefix trick that gets a
  signal out of it anyway.
- **The 1.1% damage metric** — and why we are not tuning on it.

---

## 4. Closed decisions

Recorded so they are not re-argued. Detail is in git history and in the carnet.

- **Danger model before weights** (2026-08-24). Every weight is fitted *through*
  the danger model, and §1 showed its error is conditioned rather than scalar,
  so no fitted weight could have absorbed it.
- **Danger model now frozen** (2026-08-24). Accurate enough to tune through, and
  the harness cannot resolve anything below ~5 points, so further modelling is
  untestable until §2 exists.
- **Local fights are trusted** (2026-08-24). The local generator matches the
  live server on map, obstacles and placement for the same seed, and it tracks
  upstream master.
- **`allyHasShield` replaced `allyHasRst`, and `libeWorthCasting` gates both
  liberation trigger sites** (2026-08-24). The coverage map was keyed on the RST
  *stat* while shields come from chips, so the whole simulation was unreachable
  for low-RST builds. Gates now open on 66.7% of liberation turns, up from
  never. It did not move the breach rate — see the TP debit, §1.
- **`effectiveRel` snapshots after the liberation block** (2026-08-24), so a
  liberating enemy is credited with stripping both shields instead of only the
  absolute one.
- **The liberation strip stays sign-blind** (2026-08-24). Halving a *negative*
  relative shield looked like the model assuming the enemy removes its own
  debuff, but it is faithful: liberation is `EffectDebuff` -> `reduceEffects`,
  which scales every reducible effect on the target, vulnerability included
  (`EffectVulnerability` is an ordinary effect setting `STAT_RELATIVE_SHIELD` to
  `-value`), and `Effect.reduce` scales negative stats toward zero on purpose —
  `Math.abs(statValue) * reduction * Math.signum(statValue)`. The enemy does not
  get to strip selectively, so neither should the model.
- **`getChipReadyModifier` clamps to `CHIP_READY_MAX`** (2026-08-23). Ceiling
  20.0 is above the 19.0 a build can reach, so it changed no behaviour — it is
  there so the term saturates instead of running away once fitted.
