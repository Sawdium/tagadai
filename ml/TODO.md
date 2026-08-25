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

**Where it stands (2026-08-25).** Fights are 8x cheaper, the eval's base row
is validated on 12k real fights, and the state-based fit has hit its ceiling:
what it measures (the value of *having* a stat) is not what the eval applies
(the value of *changing* it). Next is the delta dump and a bench panel with
power. Details of how each result was obtained are in §4 and the carnet.

Tools: `src/tuning/` — `variant` (rewrite constants into a playable copy),
`texel` (probe corpus + logistic fit), `roster` (real builds), `replay`
(site fights -> states). `src/localfight/batch.py` runs the generator.

### Open

- [ ] **Delta dump** (§2.1): record what each *chosen combo* changes, not the
      state, and fit on that. Needs surplus cores: the AI saturates its op
      budget, so a dump that costs ops truncates the search it records.
- [ ] **Bench panel with power**: on the current panel 91% of seed-pairs are
      decided by the seat. Play each candidate matchup on the current tree vs
      itself, keep the matchups with the highest discordance.
- [ ] **Evaluation-count gate** (§2.3): `turn_stats` records ops and
      ComboExplorer evaluations per turn; the gate that rejects a candidate
      that thinks less is not written. A weight change can truncate the
      search without any score being wrong.
- [ ] **Modifier scales** (§2.4): `getChipReadyModifier` reaches x17 where
      its siblings clamp near [0.5, 1.5], all in the same `base *=` chain
      (`Scoring:307/314`). Fit an exponent per modifier rather than compress
      by hand; record any bound the tuner respects here first.
- [ ] `tagadalive/TODO.md` §1.5 before fitting anything that touches
      `ALLY_CANDIE_MODIFIER`: the ally-in-danger boost only reaches mid-turn
      summons today.
- [ ] Shields and base stats need deltas or "quiet" states: in a state they
      are reactions (a shield up means under attack).
- [ ] *(low)* Fresh 301 solo scrape for a temporal check: which coefficients
      move with the meta.
- [ ] *(later)* Farmer and team fights: same machinery, plus bulb rows and
      the team-state terms.

### Superseded

- SPSA / CMA-ES over the 178 constants (old §2.2): one paired evaluation is
  ~1,300 fights; thousands of them are not a plan. Fit on recorded data,
  bench only to validate.

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
      échecs" (`/carnet/iii/`). Bullet plan: throughput, Texel, the site
      corpus, the bench verdict.
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
- **Texel, corpus 1** (2026-08-24, 800 fights, 5 builds): 92% accuracy but
  identity alone gives 92%. Five builds cannot identify anything.
- **Texel, corpus 2** (56 real builds, 5,000 fights, build FE, per-fight):
  TP 58 [50, 65], MP 102 [92, 112], RELSHIELD 5.5 [5.1, 6.1], MGC 1.4.
  Real packages via `/leek/get`, never random stats: the generator only sees
  the package's final numbers and random stats fit a world nobody plays.
- **Texel, site corpus** (11,834 real 301 solo fights, Dec 2025, farmer FE):
  TP 38 [33, 41], MP 54 [46, 64], RELSHIELD 7.4, ABS 2.2, RETURN 2.6,
  STR 1.3, MGC 1.5 -- **the hand-tuned row is right for everything a state
  can see.** HPMAX, SNC, RST, WSD unidentifiable (collinear or reactions).
- **One vote per fight** (2026-08-25). Draws are 18% of fights but 50% of
  states (they run to the turn cap); unweighted, TP fitted at 4. `texel fit`
  weights each state by 1/(states of its fight).
- **Replayer validated** (2026-08-25): 3,354 values, 0 mismatches. `112`
  raises max life only, `104` both; `[12, chip]` carries the chip id (100),
  its effect the item id (174); the pre-`init()` manumission is skipped.
- **Bench verdict** (2026-08-25): `MP=102` p = 0.52, `TP=58+MP=102` p = 0.82,
  240 pairs each, ~20 discordant. Nothing ships. A state coefficient is not
  the delta coefficient the eval applies (MP moves 2.7 per fight); and the
  panel is seat-decided, so the bench had no power.
- **`getChipReadyModifier` clamps to `CHIP_READY_MAX`** (2026-08-23). Ceiling
  20.0 is above the 19.0 a build can reach, so it changed no behaviour — it is
  there so the term saturates instead of running away once fitted.
