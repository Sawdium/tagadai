# tagadargb — improvement backlog

Everything below keeps the current foundations: the six-step turn (generate →
simulate → score → execute → repeat → reposition), the capital-ratio scoring,
and generic effect handling driven off each entity's own kit.

**The enabling fact**: peak measured usage is ~136k of 1,000,000 operations.
Roughly 6–7× the budget is idle. Almost every item here is affordable.

Status key: `[ ]` open · `[~]` in progress · `[x]` done

> **The measurement bottleneck.** `aibench` resolves roughly a 5-point edge at
> 600 fights (standard error ~2 points at 600, ~1.8 at 800). Every change
> shipped so far lands inside that band, so individual results are directional
> at best. Worse, a **mirror match structurally cannot measure** anything whose
> value depends on the opponent being different from us — derived risk, the
> winning modifier and `canDie` all evaluate near-neutral when both sides have
> identical builds and identical life. Before much more effort goes in, this
> wants either far larger runs or a non-mirror opponent (a pinned older
> revision, or scripted Domingo-like behaviour).

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

- [x] **B6. AoE grouping.** Done in `Plan.aims`. Rather than tabulate fifteen
      area shapes, it asks the engine which cells a blast aimed at each entity
      covers and unions them — for every symmetric shape that set is exactly
      the set of cells whose blast would cover the entity. Costs nothing when
      it buys nothing: for a point item `splash` short-circuits without a
      native call.
      **Unmeasurable on this build** — all eight of rgb's items are
      `AREA_POINT`, so it contributes exactly zero here. Verified out-of-band
      by equipping a grenade launcher locally: 18 shots / 10 aimed at an empty
      cell / 1 catching two enemies at a cell neither stood on, against
      5 / 0 / 0 for the entity-cells-only generator, which cannot produce that
      row at all. Re-measure if an area item is ever equipped.
- [x] **B7. Offensive casts at empty cells** — falls out of B6 for area items.
      Still open for point items, where an empty cell can never be better.
- [ ] **B8. Equivalence classes.** Many impact cells simulate identically;
      grouping them would cut generation cost on an area build.

## C. Movement — the "advanced version" of step 4

- [ ] **C9. Movement chips.** Teleport, jump, grapple, boxing glove, inversion
      are unmodelled. Clean design: a movement chip is an action that changes our
      cell, then re-enter step 1 — the loop already supports that structurally.
> **Result, 2026-08-09. C10 and C11 were built and measured, and both failed.**
> Making the firing step danger-aware looks like the obvious remaining gap — it
> is the last decision taken without consulting the danger model — and it is
> wrong three ways over. 800 fights each:
>
> | variant | rate |
> |---|---|
> | safest legal cell + decline shots costing more danger than they buy | **21.9%** |
> | safest legal cell, no declining | **30.9%** |
> | cheapest cell, danger only breaking ties between equal-cost cells | **49.6%** |
>
> Two independent reasons, both worth remembering:
>
> **Peril is not a cost of firing.** The enemy closes on us whether or not we
> shoot, so hanging back never avoids the damage — it only forgoes dealing any.
> Danger buys reach. That trade is already made, correctly, in `Field.score`
> against firepower; charging it again in `Plan.fire` double-counts it and
> teaches the AI to stand still and lose.
>
> **Nearest-first is load-bearing, not a placeholder.** `Brain` fires up to
> twelve times a turn. Walking to a safer cell for the first shot spends the MP
> the later shots needed to reach at all — damage dealt fell 340 → 282 on
> exactly that.
>
> Kept from the attempt: `Field.peril` split out of `Field.score` (so the two
> can never disagree about what danger means) and cached per turn, and
> `gauge`/`survey` hoisted into `Brain`. Behaviour-neutral, and re-measured
> neutral.

- [x] ~~**C10. Firing-cell choice is "nearest wins".**~~ Measured, reverted.
      See the box above — **do not re-attempt as stated**.
- [ ] **C11. No MP reserve.** Still open, but the shot-gating formulation is
      dead. What is left is the *literal* version from the original plan: cap
      how much MP the firing step may spend so some is guaranteed to remain for
      the retreat — a budget, not a per-shot judgement.
- [ ] **C12. Guard rails for C9** — no teleport + jump just to land a spark.

## D. Positioning and danger

- [x] **D13. Threat is a shape, not a damage number.** Done. `Kit.arsenalOf`
      prices any entity's items by *that entity's* stats and `Kit.burstAt`
      greedily fills its TP budget with whatever reaches, so firepower and
      threat became two readings of the same instrument, in hit points. Deleted
      `W_POWER`, `W_COVER` and `W_THREAT`. The one term left — what a hit point
      taken costs relative to one dealt — is derived from the two life pools.
      Measured 50.0% / 50.2%: no better, no worse, three fewer magic numbers.
- [x] **D14. Enemy reach is an obstacle-blind Manhattan disc.** Done.
      `Board.reach` gives each foe its true reachable stand cells and threat is
      priced from the closest one its legs can actually get to.
      **Deliberately not a flood field**: range in this game is Manhattan
      whatever stands between, so a wall decides whether a shot *connects* (a
      separate question, asked separately via LOS) but never how far the target
      *counts as* being. Measured 52.5% together with D15.
- [x] **D15. Enemy cooldowns ignored** when sizing threat. Done — `burstAt` no
      longer credits an entity with a chip it cannot cast, which forced the
      burst cache to become per-turn rather than per-fight. **Spent `max_uses`
      remains unmodelled for enemies**: `getItemUses` is self-only.
- [ ] **D16. Obstacle-shadow map unbuilt.** Exact LOS is affordable for ~40
      reachable cells but cannot plan multi-turn approaches; a cheap shadow
      field over all 613 cells can.
- [~] **D17. Turn-order awareness.** Half done: `Sim.liveTurns` now shortens an
      effect landing on someone who plays before us. Threat is still not
      weighted by who acts first.
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
- [x] **E24. Poison** used a flat `LATER = 0.75` discount. Replaced by the
      ported duration model (below), which prices it by how many turns we will
      actually collect. Not yet turn-by-turn arrival.

## E-bis. Scoring ported from tagadalive (2026-08-09)

The build-independent half only. The coefficient tables (`EntityCoefs`,
`KILL_VALUE`) were deliberately **not** taken: they are tuned on tagadalive's
build and entity zoo, key on entity types rgb never meets, name chips rgb does
not own, and would pull in `Consequences`/`BattleState`/`Stats` on a 1-core
budget — trading a model that re-derives itself from the kit for one hand-tuned
against a different leek. Measured 51.5% as a group.

- [x] `getEffectiveDuration` + `durationMitigation` → `Sim.liveTurns` /
      `Sim.durationWorth`. Duration is capped by fight length, decremented when
      the target plays before us, full-value for 3 turns then half for the tail.
- [x] `getWinningModifier` → `Field.winning()`. Replaced a hand-rolled
      `1 + 2*(1 - lifeRatio)` that reached 3.0 at death's door and made the AI
      stop fighting exactly when trading was the only thing that could win.
- [x] `getOpportunityCost` base CD penalty → `Shot.rate = score / (TP + cooldown)`,
      so a six-turn chip stops looking as cheap as a repeatable one. The
      item-specific handlers were not ported; they are per-item and build-bound.
- [x] `canDie` / `CANDIE_MODIFIER` → `Field.LETHAL`. A cell where incoming
      exceeds our remaining life takes a 5× penalty, because dying is not a
      linear amount of bad. Built on D14's danger number.
- [ ] `getTurnOrderModifier` — not ported; see D17.

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
- [~] **H34. Turn number and fight length.** `Sim.liveTurns` now caps a
      duration by how much fight is left, so a buff cast on turn 60 is priced
      as the near-worthless thing it is. No other endgame behaviour.

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

Done: **I35** (harness) · **D13** · **B6** · **D14** · **D15** · the tagadalive
scoring port · derived risk. **A1–A3** measured at 50.5% and reverted.

Cumulative for the day: **51.9%** over 800 fights (415W–385L), damage
differential 226/230 → 341/325. About one standard error — a consistent
positive lean, not a significant result. Read the measurement-bottleneck box at
the top before reading much into any single number here.

Next, in order:

1. **E19** — effect stacking is a correctness bug, not a refinement: deltas
   accumulate but the engine *replaces* non-stackable effects, so casting
   helmet twice double-counts. Unlike the positioning work, this is a case of
   the model computing the wrong number, which no amount of tuning fixes.
2. **H31** — `Board.init` burns 35k ops on 613×3 natives when `getObstacles()`
   is 85 and x/y has a verified closed form. Pure win, no behaviour change.
3. **A4** — beam over firing positions, the one search axis A1–A3 never tested
   and the only one with a real commitment cost. Note the C10 result first:
   MP is a genuine commitment, but spending it for *safety* measured badly, so
   A4 should search it for *reach*, not for cover.
4. **D17 / F25** — finish turn-order weighting; derive `HITS` and `HORIZON`.
5. **C11 proper** — an MP budget for the firing step, not a per-shot gate.

**A pattern worth naming.** Three of the last four "obvious gaps" measured null
or negative: A1–A3 (50.5%), C10 (30.9%), C11 (21.9%). The ones that helped were
not the clever additions but the corrections of *wrong numbers* — pricing threat
in hit points, using real reachability, honouring cooldowns. When choosing what
to do next, prefer "this computes something false" over "this could consider
more options".
