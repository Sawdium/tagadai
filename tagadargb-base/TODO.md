# tagadargb — improvement backlog

Everything below keeps the current foundations: the six-step turn (generate →
simulate → score → execute → repeat → reposition), the capital-ratio scoring,
and generic effect handling driven off each entity's own kit.

**The enabling fact**: peak measured usage is ~125k of 1,000,000 operations.
Roughly 6–8× the budget is idle. Almost every item here is affordable.

Status key: `[ ]` open · `[~]` in progress · `[x]` done

---

## A. Search — measured, and it is NOT the gap

> **Result, 2026-08-09.** A1–A3 were implemented in full — a beam over action
> sequences (WIDE 8 / BEAM 3 / DEPTH 3) that scored each opening by the best
> turn that could follow it, chained simulations so combos were visible, paid
> the weapon swap out of the whole sequence, and anchored every sequence to the
> cell the opener would actually leave us standing on.
>
> It **changed ~36% of decisions** (mostly `motivation → protein` and
> `rock → pistol`) and won **302W–296L, 50.5%** over 600 fights on fresh seeds.
> A null, at 2.5× the operations (peak 46k → 117k) and ~230 lines.
>
> The likely reason: `Brain` already re-plans from scratch after every single
> action, and greedy-with-replanning recovers almost all of the value of
> searching a 2–3 action sequence. Lookahead only pays where there is a real
> commitment cost, and the one this kit has — the 1 TP weapon swap — is worth
> too little to change the optimum, because `rock` (chip, 5 TP, no swap) and
> `shotgun` (weapon, 5+1 TP) are near enough equal.
>
> Reverted. The implementation is kept in `tagadargb-seq/` because A4 needs the
> same machinery. **Do not re-attempt A1–A3 on their own** — the measurement is
> the reason, not lack of effort.

- [x] ~~**A1. TP knapsack over the turn.**~~ Measured case: `shotgun ×2` ≈ 220 dmg
      for 10 TP beats `rock + pistol` ≈ 162 for 9 TP, but per-TP rate picks rock
      first and can then no longer afford shotgun. Search sequences over
      (remaining TP, uses left, cooldowns), execute only the first action, let
      the existing loop re-plan.
- [x] ~~**A2. Sequence-aware combos.**~~ The shotgun's −25 absolute-shield debuff
      makes the *next* hit better. The loop benefits from it only by accident
      (it re-scores after firing); it never *chooses* shotgun first because of
      the follow-up.
- [x] ~~**A3. Weapon-swap amortisation.**~~ The +1 TP swap is charged entirely to
      the first shot, so a weapon looks worse than a chip even when committing
      to it pays off across two shots.
- [ ] **A4. Beam over firing positions.** Now the most promising search item,
      and the one A1–A3 did *not* test: position is still chosen by whichever
      cell the top action happens to be firable from, so a whole turn is never
      planned around a cell. Unlike action ordering, this is a real commitment
      — MP spent cannot be taken back — which is exactly the condition under
      which lookahead pays. Reuse `Plan.rank` from `tagadargb-seq/`, iterating
      candidate stand cells at the outer level.
- [ ] **A5. `Brain.TRIES = 8` is an arbitrary cutoff.** If the top 8 candidates
      are all unreachable, the turn silently stops attacking.

## B. Action generation — the "advanced version" of step 1

- [ ] **B6. AoE grouping.** Impact cells are entity cells plus a few empties for
      support chips, so it will never find the cell between two enemies that
      catches both. Union the area-radius neighbourhoods of each enemy, dedupe,
      simulate once per distinct impact.
- [ ] **B7. Offensive casts at empty cells** — only support items get empty-cell
      candidates today.
- [ ] **B8. Equivalence classes.** Many impact cells simulate identically;
      grouping them cuts generation cost and is what makes B6 affordable.

## C. Movement — the "advanced version" of step 4

- [ ] **C9. Movement chips.** Teleport, jump, grapple, boxing glove, inversion
      are unmodelled. Clean design: a movement chip is an action that changes our
      cell, then re-enter step 1 — the loop already supports that structurally.
- [ ] **C10. Firing-cell choice is "nearest wins".** Tie-break equally-cheap
      cells on positional score, and consider paying +1 MP for a much safer one.
- [ ] **C11. No MP reserve.** The plan called for capping movement so MP is left
      to hide with. Nearest-first is only a proxy.
- [ ] **C12. Guard rails for C9** — no teleport + jump just to land a spark.

## D. Positioning and danger

- [ ] **D13. Threat is a shape, not a damage number.** `W_THREAT` is an
      arbitrary weight in a function whose every other term is in hit points.
      Estimate real incoming damage per cell (enemy output × can-reach ×
      can-see) and the magic constant disappears.
- [ ] **D14. Enemy reach is an obstacle-blind Manhattan disc**, overestimating
      threat around walls.
- [ ] **D15. Enemy cooldowns and spent `max_uses` ignored** when sizing threat.
- [ ] **D16. Obstacle-shadow map unbuilt.** Exact LOS is affordable for ~40
      reachable cells but cannot plan multi-turn approaches; a cheap shadow
      field over all 613 cells can.
- [ ] **D17. No turn-order awareness.** Standing in an envelope matters far more
      if that enemy acts before us.
- [ ] **D18. No multi-turn positioning.** Every decision is one turn deep.

## E. Simulation fidelity

- [ ] **E19. Effect stacking is naive.** Deltas accumulate; the engine's
      non-stackable effects *replace*. Casting helmet twice double-counts.
- [ ] **E20. `MODIFIER_*` bits ignored** — `ON_CASTER`,
      `MULTIPLIED_BY_TARGETS`, `IRREDUCTIBLE`.
- [ ] **E21. Unmapped effects, all scoring 0**: `DAMAGE_RETURN` (no stat slot at
      all), `STEAL_LIFE`, `STEAL_ABSOLUTE_SHIELD`, `DEBUFF` / `TOTAL_DEBUFF`,
      `ANTIDOTE`, `REMOVE_SHACKLES`, `ADD_STATE`, `SUMMON`, `RESURRECT`,
      `TELEPORT`, `INVERT`, `ATTRACT`, `PUSH`, `PROPAGATION`.
- [ ] **E22. Erosion unmodelled** — every hit permanently removes 5% of damage
      dealt from max HP, 10% for poison.
- [ ] **E23. Criticals** are in `Sim.output` but not in per-action damage.
- [ ] **E24. Poison** uses a flat `LATER = 0.75` discount instead of modelling
      damage arriving on specific turns.

## F. Capital model

- [ ] **F25. `HITS = 2.0` and `HORIZON = 2.5` are hand-set.** Both are
      derivable — hits-per-turn from the enemy's kit, horizon from expected
      remaining fight length.
- [ ] **F26. Summons count as full leeks.** `Ent.summoned` is read but
      `defence()` does not discount it.
- [ ] **F27. `ours / theirs` is scale-sensitive**, inflating with ally count.
- [ ] **F28. Kill ordering unvalued** — killing whoever acts next is worth more.
- [ ] **F29. `engagement` is a 1.0 / 0.15 cliff**; a ramp in turns-to-contact
      would behave better.

## G. Team play

- [ ] **G30.** Ally support is a single proximity term. No focus-fire agreement,
      no "don't block an ally's line", no prioritising heals by ally value, no
      shared intent. `Sim.pressure` already prices ally buffs correctly, so the
      foundation exists.

## H. Engine exploitation and operations

- [ ] **H31. `Board.init` is wasteful** — 613 × (`getCellX` + `getCellY` +
      `isObstacle`). `getObstacles()` costs 85 once, and x/y has a verified
      closed form: `cellId = 306 + 18x + 17y`.
- [ ] **H32. Enemy active effects unread** — `getEffects(enemy)` exposes shield
      and buff expiry.
- [ ] **H33. `mark` / `markText`** (164 ops) for visual debugging in reports.
- [ ] **H34. Turn number and fight length unused** — no endgame behaviour.

## I. Tooling, tuning, testing

- [x] **I35. Evaluation harness.** `python -m src.tools.aibench` plays two AI
      revisions head to head on the same build over N seeds, each seed played
      both ways to cancel the first-turn advantage. Calibrates at exactly 50.0%
      when run against itself. Needed `--ai2` on `localfight`.
- [ ] **I36. No weight tuning.** Once I35 exists, hill-climb `W_POWER`,
      `W_COVER`, `W_THREAT`, `HITS`, `HORIZON`.
- [ ] **I37. No tests.** `Sim` invariants are easy to assert: a kill beats
      partial damage, healing at full HP scores 0, self-splash is negative.
- [ ] **I38. Constants scattered** across `Sim`, `Field`, `Brain`. tagadalive
      centralises them in `ScoringConfig` for exactly this reason.
- [ ] **I39. No cross-fight telemetry** to tell whether a revision helped.

## J. Outside the AI

- [ ] **J40. The build is currently the binding constraint.** rgb is 254 HP /
      190 strength / **0 resistance** at level 19, against a Domingo with
      roughly double the HP pool — which is why it out-damaged and still lost
      several fights. No AI work closes a 2× HP gap.

---

## Order of attack

1. ~~**I35** — the harness, so everything after is measurable.~~ Done.
2. ~~**A1–A3** — turn knapsack, combo awareness, swap amortisation.~~ Done,
   measured at 50.5% over 600 fights, reverted. See the box in section A.
3. **B6** — AoE grouping. Now first: it adds actions the AI cannot currently
   see at all, rather than reordering ones it already considers, so unlike
   A1–A3 it cannot be silently recovered by re-planning.
4. **A4** — beam over firing positions, the one search axis still untested.
5. **D13** — put threat in hit points so `W_THREAT` stops being a free
   parameter.

**Benchmarking note.** `aibench` resolves roughly a 5-point edge at 600 fights.
Anything smaller needs either far more fights or a more discriminating
opponent than a mirror match — 300 seeds is about 4 minutes at `--jobs 8`.
