# ML / tuning programme

Working notes for making `tagadalive`'s scoring tunable. Everything here
assumes the constraint we settled on early: **the only true signal is
win/loss at the end of the fight.** Damage is a proxy, and tuning against
it would delete exactly the positional/temporal judgement that makes the
current hand-tuned scoring good.

Status legend: `[ ]` open · `[~]` in progress · `[x]` done

---

## 0. The fork: danger model first, or weights first?

- [x] **Resolved 2026-08-24: danger model first.** §1.1 measured it instead of
      arguing it. The error is conditioned, not scalar — 0.7% against 20.3%
      breaches between two leeks in the same fights, 0.6% against 7.6% by
      distance — and no fitted weight absorbs a spread like that.

The danger model feeds the eval. Every weight downstream of it is fitted
*through* it. If the danger model is systematically wrong, tuning weights
on top of it does not fix the error — it fits compensating weights that
bake the error in and make it harder to remove later.

Arguments for **danger first**:
- It is a prediction with a ground truth (see §1.1), so it can be checked
  without any optimiser at all.
- Errors here are structural, not scalar. No weight can undo them.
- It is cheap to measure — we already log `Position.dmg`.

Arguments for **weights first**:
- The harness (§2) has to be built either way, and building it against
  weights is the simpler first target.
- The danger model may already be good enough that the effort is wasted.

That is what happened: §1.1 ran first, and the measurement settled it.

**Prerequisite either way:** `tagadalive/TODO.md` §1.5 — the ally-in-danger
boost currently reaches only mid-turn summons, never ally leeks. Whatever we
tune first, `ALLY_CANDIE_MODIFIER` must not be fitted before that ordering is
settled, or the fitted value silently changes meaning when it is.

---

## 1. Investigations

Local fights are trusted: the local generator matches the live server on
map, obstacles and placement for the same seed (checked 2026-08-24), and it
tracks upstream master.

### 1.1 Danger model accuracy

The danger map is a **conditional worst case**: per enemy it takes the best
damage-per-TP item and spends that enemy's TP on it, respecting use limits and
cooldowns, until the TP runs out (`Items.getOrderedOffensiveItems`, then the
item loop in `Damages.computeDanger`). It answers *what could this cell cost
me if every enemy went fully offensive*, not *what will it cost me*.

**The gap between predicted and realized is therefore not an error, and is not
a metric.** A well-chosen cell is one the enemy declines to attack — it buffs
instead — so danger going unspent is the map working. Measuring "tightness"
scores the AI's positioning as if it were a modelling defect. There is exactly
one defect worth counting:

> **when does the realized damage come in ABOVE the danger predicted?**

Everything else the tool prints is context for reading those cases.

- [x] Harness built (2026-08-24): `python -m src.tools.dangerprobe`.
      `tagadalive/main` logs one line per turn under
      `Benchmark.DEBUG_DANGER` (a compile-time constant, false in the shipped
      AI, flipped only in the throwaway `.dangerprobe/` copy the tool makes),
      carrying the Danger of the cell we actually end on. The tool replays
      seeded local fights, reads the realized damage victim-side out of the
      action list, and reports coverage plus slices.
- [x] Measured, 2026-08-24. Everything below is what the runs actually said.

**Coverage, 20 seeds per matchup, local self-play**

| matchup | exposed turns | breaches | median overshoot |
|---|---|---|---|
| Claudius mirror (MGC/SNC) | 1503 | 5.9% | 98 HP (2.6% max HP) |
| Claudius vs Claudias | 519 | 10.0% | 238 HP |
| JCGloomy mirror (STR 730) | 1199 | 12.6% | 698 HP (16.0% max HP) |
| JCGloomy vs SweetDude | 1294 | 16.8% | 448 HP |

- Magic builds understate the problem: their damage is poison, spread over
  turns and discounted by `durationMitigation`. Strength builds land it inside
  the window and breach twice as often, three times as hard.
- **The error is conditioned, not scalar.** Claudias 0.7% against Claudius
  20.3% in the same fights; 0.6% at 2-6 cells against 7.6% at 7+; 1.2% on
  T1-3 against 6.5% from T9. No fitted scalar touches a spread like that ->
  **§0 resolves to danger first.**

**What breaches, by what the enemy did that turn** (JCGloomy mirror, 12.0%
baseline)

- liberation cast: 56.9% -- it strips shields the map assumed would hold
- teleportation cast: 50.8% -- reach maps never credit the destination
- inversion: 21.2% -- swaps positions, nothing models it
- adrenaline: 5.8%, *below* baseline. The +4 TP hypothesis was not supported.
- danger-map truncation: 1 turn in 1364, and that one at `E:5/5`. The
  round-robin early exit is **not** a cause. Hypothesis closed.

**Liberation, chased to the end**

- Three gates had to be open. Two were shut for any low-RST build:
  `BattleState:114` keyed the coverage map on the RST *stat* (>= 200) while
  shields come from chips, and both trigger sites tested relative shield only.
- Fixed: `allyHasShield` (shields present, or an RST chip ready via
  `rstCount`), plus `ScoringConfig.libeWorthCasting(abs, rel)` shared by
  `Damages:92` and `MapDanger:86`. Gates 1 and 2 now open on 66.7% of
  liberation turns, up from never.
- Gate 3 fires on 35% of them: this build's shields are abs median 90, max
  235, rel ~0, against a 200 abs-alone trigger.
- **Breach rate did not improve** (12.6% -> 13.3%). Most likely the TP debit:
  the branch charges the enemy 5 TP, which costs more predicted damage than
  the halved shield adds back. Next experiment is to strip the shields without
  charging the TP -- a worst case should assume both.

**The measurement is now the bottleneck**

- Runs are NOT paired. Changing the danger changes which cells the AI picks,
  so fights diverge from turn one. Teleport-turn breaches moved 50.0 -> 56.1
  -> 55.5 across three runs that changed nothing about teleport: that is the
  noise floor, ~5 points on a slice.
- Anything finer needs prediction scored against *recorded* fights instead of
  freshly played ones. Until then, only effects bigger than ~5 points are
  visible.

**Five traps, all of which produced wrong numbers before being fixed.** They
are the reason the first four reports were nonsense, and any future metric
over this data has to respect them:

1. **Nova damage is not damage.** `EffectNovaDamage` calls
   `removeLife(0, value, ...)` — pv zero, everything into erosion, capped at
   the HP already missing. Action 107 lowers MAX life; current life never
   moves. Counting it as HP taken invented a 63% breach rate out of nothing;
   on a science build it is the biggest number in the log (808 against 146 of
   real damage on the first turn checked).
2. **The bound is on the total, not on the components.** Because the enemy's
   whole TP goes to its best damage-per-TP item, a poison build puts
   everything in `psnDmg` and leaves `dmg` at 0 — then fires a weapon anyway.
   Checking `dmg` alone reported a 48% breach rate; checking
   `dmg + psnDmg` against instant + poison reports 12%. `Danger.score` uses
   the sum, so the sum is the bound. The split being wrong is still worth
   counting, and the tool reports it separately.
3. **Ally healing is already subtracted from the prediction.** The ally branch
   of `computeDanger` takes heals off `dmg`, so the realized side has to be
   netted the same way or every bulb heal reads as model pessimism.
4. **Poison is charged to the victim at the start of its own turn**, so it
   lands outside the "between our turns" window. It needs window A *and* our
   own next turn. And `psnDmg` is duration-mitigated — it stands for several
   future turns, so one turn of ticks coming in under it is expected, not
   slack.
5. **Poison already ticking on us is not the cell's fault.** It lands wherever
   we stand, so a cell's Danger never claimed to bound it — but it arrives on
   the same action codes. Left in, it *was* the measurement: of 208 breaches,
   154 were pure pre-existing poison at a median distance of 15 cells from the
   nearest enemy. `Entity.psnTurn` (net of heal-over-time) is what the AI
   already knows about it, so the probe logs it and the tool subtracts it.
   Correcting this alone took the mirror matchup from 13.8% to 5.9%.

Hypotheses killed by the instrumentation, each in one run, all recorded so
they are not re-run: shields filtering items out of `offensiveItems` (shields
were 0 in the breaches), the danger budget truncating the round-robin before
every item got a reach map (items kept == items mapped), stale enemy MP
(`Entity.mp` is `getMP(id)`, but the closest enemy had full MP in 217 of 223
exposed turns), and the turn-order wrap in
`Fight.getEntitiesAfterSelfInOrder` (correct).

Datasets kept for re-analysis (`--report-only`, no fights replayed):
`data/danger_20260824_*.csv` and `data/danger_after_libe*.csv`.

**Settled 2026-08-24: `effectiveRel` now snapshots after the liberation block.**
It used to be taken before, while the same formula read `absShield` after, so a
liberating enemy got credit for stripping one shield and not the other.

- Aggregate breach rate did not move (13.3% -> 13.6%, median overshoot
  735 -> 717 HP). Expected: the effect is far under the ~5-point noise floor.
- **Paired-prefix comparison is what showed it works.** Both runs share seeds,
  so each fight is identical until the changed danger first alters a choice.
  Restricting to turns where turn, cell, hp, tp, mp, enemy count, both shields,
  nearest distance and `libe_mapped` all match gives 862 truly paired turns:
  852 unchanged, 10 changed, **9 of them upward**, median **+243 HP** (5.4% of
  max HP). Upward is the direction a missing shield-strip should move a worst
  case. This technique is the only paired signal this harness can produce —
  reuse it for any change too small for the aggregate.
- Reachable on 194 turns (14%), but this build's relative shields cap at 25, so
  halving one moves the multiplier 0.75 -> 0.875 and rarely crosses a threshold.

**The remaining downward turn is a real defect, older than this change.**
Seed 17 turn 7 carries `rel_shield` = **-5** — an enemy debuff on us, not a
shield. `Damages:99-101` multiplies both shields by `LIBE_DEBUFF_FACTOR`
unconditionally, so the simulated liberation halves the enemy's own debuff and
*lowers* predicted danger. A conditional worst case must never assume the enemy
helps us.

- [ ] Guard the liberation strip so it only shrinks shields that are positive
      (`Damages:99-101`, and `libeFactor` with it). One line each; the paired
      prefix above is how to check it.

**Danger model is frozen here for now** (decided 2026-08-24). It is accurate
enough to tune weights through, and the harness cannot resolve anything smaller
than ~5 points, so further modelling work is untestable until §2 exists. The
items below stay open at **low priority**:

- [ ] *(low)* Liberation without the TP debit (see above).
- [ ] *(low)* Teleportation and inversion: the enemy ends up somewhere the reach
      maps never credited. Second and third largest breach classes, both
      unmodelled.
- [ ] *(low)* `Entity.nextLiberation` is written at `MapDanger:138` and read
      nowhere. Delete the call or wire it up.

---

## 2. Tuning harness

**Unblocked (2026-08-24).** §0 sent the danger model first, §1.1 measured and
fixed it, and it is now frozen: accurate enough to tune through, and anything
further is below what the harness can resolve. This is the active work.

### 2.1 Position dump under a surplus-cores harness

- [ ] Dump evaluated positions with their outcome labels.

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

- [ ] The harness must record evaluations-per-turn alongside win rate, and
      reject candidates that reduce it.

This is the subtle one. A weight change can **truncate the search** without
any individual score being wrong — make the eval more expensive, fewer
combos fit in the budget, strength drops. The score function looks fine in
isolation; the AI is simply thinking less. Win rate alone cannot separate
"worse judgement" from "less search", and the fix for each is opposite.

### 2.4 Modifier scales are not commensurable

- [x] `getChipReadyModifier` now clamps to `ScoringConfig.CHIP_READY_MAX`
      (2026-08-23). The ceiling is 20.0, above the 19.0 a build can actually
      reach, so it changed no behaviour — it is there so the term saturates
      instead of running away when `CHIP_READY_FACTOR` is fitted.
- [ ] Decide whether its *range* should be compressed as well.

The clamp stops a runaway, it does not make the term comparable to its
neighbours. Measured on the live roster, this one modifier multiplies a
coefficient by **x17.0** (Claudias/Claudies, RST 8.5), x13.0 (Claudius,
WSD 6.5) and x10.0 (AGI 5.0), while every sibling in `ScoringModifiers`
clamps to roughly [0.5, 1.5] or [1, 5] — and all of them multiply into the
same `base *=` chain at `Scoring:307/314`.

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
entries, each entry lives at `/carnet/<numeral>/`.
Source: `~/Desktop/ideesnoires/leekwars/carnet/`, deployed with
`leekwars/deploy.sh` (rsync + chown, no service restart).

Both published entries are **illustrated bullet plans, not finished prose** —
that is deliberate, the prose gets written over them.

### 3.1 Article I — "Où branche-t-on un réseau sur un poireau ?"

- [x] Published at `/carnet/i/` (2026-08-24) as a bullet plan, with three new
      inline SVGs: search-vs-eval depth, the accumulator delta, the shape the
      op budget imposes. The era table, both budget charts, the two-feature
      list and the six-step outline carried over verbatim. The original prose
      is parked outside the deployed tree at
      `~/Desktop/ideesnoires/leekwars-attic/carnet-I-prose-originale.html`.
- [ ] Write the prose over the plan.

The plan carries the correction that prompted the rewrite: Article I said
Stockfish *"fonctionne pareil"*. The shape is shared (search + eval), the
depth is not — `tagadalive` has **no lookahead beyond the current turn**, so
the entire future lives inside the single-turn eval (`turnsLeft`,
`durationMitigation`, `getEffectiveDuration`, turn-order modifiers, danger
and threat maps). That is why the eval carries so much strategy, and
therefore why tuning it is the whole project.

### 3.2 Article II — "La seule chose que mon IA prédit vraiment"

- [x] Published at `/carnet/ii/` (2026-08-24) as a bullet plan, covering §1.1:
      danger as a conditional worst case, why the predicted-vs-realized gap is
      not an error, the five ways of counting wrong, the coverage numbers, the
      breach rate by what the enemy cast, and the noise floor. Two SVGs: the
      measurement window (which codes count, in which window), and the breach
      rate per chip against the 12% baseline.
- [ ] Write the prose over the plan.

### 3.3 Article III — "Le banc d'essai"

- [ ] Write it. The material is real and already measured, and it now has a
      natural place: article II ends on the noise floor, which is exactly what
      this one is about.

Content on hand:
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
- **The unpaired-run trap, from §1.1.** Changing the danger changes which
  cells the AI picks, so seeds no longer hold the fight fixed: a slice moved
  five points across three runs that changed nothing about it.
- **The 1.1% damage metric** — and why we are not tuning on it.
