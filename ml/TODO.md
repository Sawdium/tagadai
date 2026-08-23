# ML / tuning programme

Working notes for making `tagadalive`'s scoring tunable. Everything here
assumes the constraint we settled on early: **the only true signal is
win/loss at the end of the fight.** Damage is a proxy, and tuning against
it would delete exactly the positional/temporal judgement that makes the
current hand-tuned scoring good.

Status legend: `[ ]` open · `[~]` in progress · `[x]` done

---

## 0. The fork: danger model first, or weights first?

- [ ] **Decide the order.** Not yet discussed together.

The danger model feeds the eval. Every weight downstream of it is fitted
*through* it. If the danger model is systematically wrong, tuning weights
on top of it does not fix the error — it fits compensating weights that
bake the error in and make it harder to remove later.

Arguments for **danger first**:
- It is a prediction with a ground truth (see §1.2), so it can be checked
  without any optimiser at all.
- Errors here are structural, not scalar. No weight can undo them.
- It is cheap to measure — we already log `Position.dmg`.

Arguments for **weights first**:
- The harness (§2) has to be built either way, and building it against
  weights is the simpler first target.
- The danger model may already be good enough that the effort is wasted.

Suggested resolution: run §1.2 *before* the discussion, so we argue from
measurements instead of intuition.

**Prerequisite either way:** `tagadalive/TODO.md` §1.5 — the ally-in-danger
boost currently reaches only mid-turn summons, never ally leeks. Whatever we
tune first, `ALLY_CANDIE_MODIFIER` must not be fitted before that ordering is
settled, or the fitted value silently changes meaning when it is.

---

## 1. Investigations

### 1.1 Local-vs-live divergence at action 17

- [ ] Set `context` in the scenario and re-run seed 432077940.

What we know: the local generator reproduces a live fight **exactly** for
map, placement and the first 16 actions, then diverges on a weapon choice
at action 17.

Ruled out: the Level-1 scoring refactor. Pre- and post-refactor action
lists were byte-identical, 931/931 actions.

Remaining suspects:
1. Generator version skew (local JAR vs the live server's build)
2. `CONTEXT_TEST` vs `CONTEXT_GARDEN`

Suspect 2 is a one-line experiment, so it goes first.

**Why this blocks everything else:** local fights are the only free,
unlimited signal we have. If they diverge from live in ways that matter,
every number the tuning harness produces is measuring a different game
than the one we are trying to win. This should be settled before any
optimiser runs.

### 1.2 Danger model accuracy

- [ ] Compare predicted `Position.dmg` against realized damage taken on
      the following turn, across a spread of seeds and archetypes.

Report should separate:
- **Bias** — do we systematically over- or under-predict?
- **Variance** — how noisy is the prediction around its mean?
- **Conditioning** — is the error uniform, or concentrated in particular
  situations (many enemies, specific archetypes, low MP, corner cells)?

Bias is correctable with a scalar. Conditioned error is not, and would be
the strongest possible argument for §0 = danger first.

---

## 2. Tuning harness

Blocked on §0, but the design constraints are already known.

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

---

## 3. Carnet

Public journal at `ideesnoires.fr/leekwars/carnet/`.
Source: `~/Desktop/ideesnoires/leekwars/carnet/`.

### 3.1 Article I — qualify the Stockfish claim

- [ ] Article I says Stockfish *"fonctionne pareil"*. It does not, in the
      one way that matters most here.

Stockfish searches deep and evaluates leaves. `tagadalive` has **no
lookahead beyond the current turn** — the entire future lives inside the
single-turn eval (`turnsLeft`, `durationMitigation`,
`getEffectiveDuration`, turn-order modifiers, danger and threat maps).

The shape is shared (search + eval), the depth is not. And this is not a
footnote: it is why the eval carries so much strategy, and therefore why
tuning it is the whole project. Worth a short paragraph rather than a
correction — it sets up everything after.

### 3.2 Article II — "Le banc d'essai"

- [ ] Write it. The material is real and already measured.

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
- **The 1.1% damage metric** — and why we are not tuning on it.
