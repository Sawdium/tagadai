# tagadargb

A combat AI for the `tagadargb` account's leek `rgb`, built to run inside
**one core — 1,000,000 operations per turn**.

That budget is the whole design constraint. `tagadalive` spends roughly a
whole core on `init()` alone, materialising 613 `Cell` objects before it makes
a single decision, so nothing here is shared with it but knowledge. Measured on
rgb's live build: **peak ~125k operations on turn one** (the board tables),
**12k–80k after** — under 13% of budget at worst.

## The turn

Straight out of the plan this was written to:

1. **Generate** every possible action — each item crossed with each entity on
   the board, plus, for support items with a minimum range, the nearest legal
   empty cells (otherwise a chip that cannot be aimed at your own feet is
   unusable).
2. **Simulate** its effects, area falloff, target masks and all.
3. **Score** it by what it does to `ourCapital / theirCapital`.
4. **Execute** the best-rated one: walk to the cheapest cell it can be fired
   from and fire.
5. **Repeat from 1** if anything landed — the board has changed.
6. **Reposition**.

## Scoring: one currency

Everything is priced in hit points, in two pools.

**Defence** is effective HP: life divided by the relative-shield factor, plus
absolute shield over the hits it will absorb, plus whatever healing and
shielding that entity can still apply to itself.

**Offence** is the damage an entity will deal over the next few turns, and it
is subtracted from the *other* side's pool. A leek that hits harder does not
become harder to kill — it makes its target's life worth less. That one
asymmetry is what lets a strength buff and a shotgun be compared on the same
scale.

An action's score is the resulting change in `ours / theirs`. A kill drives the
denominator to its floor, so "finish them" needs no bonus constant; it is just
what the ratio does. Actions are then ordered by score **per TP**, because the
loop re-runs after every action and value-per-TP is the right greedy order when
you get to choose again.

## Effects are handled generically

There is no list of known items anywhere. Every effect the engine can produce
is mapped to one of thirteen stat slots, and a stat is priced by asking what
that entity's own kit does with it: change the stat, re-run its damage formula,
and the difference over the horizon is the value. So `protein` is worth exactly
the extra damage rgb's best weapon will deal for the two turns it lasts, and
re-equipping the leek re-prices everything with no code change.

This matters more than it sounds. An earlier cut classified items into
"damages an enemy" and "heals or shields me" and silently dropped everything
else — which quietly threw away two of rgb's six chips, including the strongest
one in the kit.

**Output is gated on engagement.** A stat that boosts damage is only worth what
you can actually deliver, so an entity with nothing in reach counts its output
at 15%. Without that the AI spends its turns re-buffing strength while the
enemy is twelve cells away and every buff expires before contact — observed,
not hypothetical: twelve turns of a real fight, zero damage.

## Positioning

With 4 MP the reachable set is only ~40 cells, small enough to skip the
obstacle-shadow heuristic the plan suggested and just ask the engine whether
each enemy can see each candidate — the exact answer, 31 operations a pair.

Four terms: **power** (how much of the kit can fire from here), **cover** (a
foe that could reach us cannot see us), **threat** (we are in a foe's
move-and-shoot envelope, in the open), and **advance** (the fallback).

Power is a sum, not a flag. Scored as a flag, the AI parks at maximum range and
plinks with its cheapest weapon forever; as a sum, a cell at range 5 that
brings the short heavy half of the kit online outscores one at range 10 where
only the long item reaches.

The threat weight scales with how hurt we are, which is the only thing that
makes the AI break off at low life.

## Notes for whoever touches this next

**Cover and a firing lane are the same lane.** Every item in this kit needs
line of sight and the engine's sight test is symmetric, so a hiding spot is a
genuine local optimum: stepping out gives up the cover bonus *and* takes on the
threat penalty, a cliff no per-cell approach gradient sensibly outweighs. That
is why `advance()` exists — when nothing on the whole reachable set can shoot,
cover is worth nothing. Without it: a 65-turn draw with zero attacks, twice.

**Manhattan distance is obstacle-blind.** In a pocket, every reachable cell
measures no closer than the one you stand on and the AI re-picks its own cell
forever; escaping means walking around the wall, which looks like retreating.
The last resort hands the move to `moveToward`, which paths properly.

**Launch types are an inverted bitmask** — a bit that is *not* set forbids that
family of offsets. bit 1 = orthogonal, bit 2 = diagonal, bit 4 = everything
else. Casting on your own cell is legal before the mask is consulted.

**Never name a field or local after a native.** A `boolean isSummon` field
makes `isSummon(id)` inside that class resolve to the field, and the engine
logs `58 ['false']` once per call, silently, forever. Same trap for `abs`.

**The expensive natives are the targeting helpers.** `getCellsToUseWeapon`
costs 25,834 operations and `getCellToUseWeapon` 38,080; a handful would eat
the turn. Doing the geometry by hand — `getCellDistance` at 15, `lineOfSight`
at 31 — is what makes this fit. `canUseWeaponOnCell` at 45 is used only as a
final check before paying 3000 for the actual use.

**`getItemUses(id)` exists** and is a per-turn counter the engine maintains, so
`max_uses` needs no local bookkeeping. **`setWeapon` costs 1 TP** even when
re-selecting the weapon already in hand.

**Enemy threat radius must use `getTotalMP`, not `getMP`.** The latter reports
what is left this round, so an enemy that already played looks immobile.

**A chip's API `template` is the generator's chip id**, not the `template`
field inside `chips.json`. Mapping through that field silently swaps every chip
for an unrelated one. `src/tools/localfight.py` says so in a comment now,
because it cost an hour.

## Files

| File | What's in it |
|---|---|
| `main` | Entry point. Runs a turn, logs the operation count. |
| `auto` | Include aggregator. |
| `Board` | Cell tables, walk BFS, range and launch-type geometry. |
| `Kit` | Our items and every entity's output profile, read once per fight. |
| `State` | Per-turn snapshot of everyone on the board. |
| `Sim` | Effect simulation and the capital model. |
| `Plan` | Action generation and execution. |
| `Field` | Where to stand. |
| `Brain` | The loop. |

## Running it

```bash
python -m src.tools.localfight --account tagadargb --ai tagadargb/main rgb rgb --seed 42
python -m src.tools.fight --account tagadargb          # free test fight vs Domingo
python -m src.tools.editor --account tagadargb         # the only way to see compiler warnings
```

Set `Plan.TRACE = true` to have every action it weighs printed to the fight
log; that is how most of the above was found.

Uploading. The account also carries a copy of `tagadalive` at the tree root, so
this AI lives in its own remote folder `rgb/` and nothing gets overwritten:

```bash
for f in Board Kit State Sim Plan Field Brain auto main; do
  python -m src.tools.aisync --account tagadargb put "rgb/$f" "tagadargb/$f"
done
```

Individual files report "has ERRORS" on upload because each is compiled alone
without its includes; `auto` and `main` are the ones that must be VALID. Trust
`src.tools.editor` over that.

The leek points at `rgb/main`.
