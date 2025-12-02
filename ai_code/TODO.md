# AI Code TODO - Static Analysis Issues

Reference for fixing issues found in the LeekScript combat AI.

---

## Critical Issues

### Null Pointer Dereferences

- [ ] **AI/AI.ls:122** - `getPotentialCombo()` returns `bestCombo!` but can be null if no reachable cells
- [ ] **AI/AI.ls:148** - `findBestDanger()` returns `bestDanger!` but can be null if no reachable cells
- [ ] **Controlers/Fight.ls:162** - Variable shadowing: `integer self = self.turnOrder` shadows static `self` Entity
- [ ] **Services/Damages.ls:16** - No null check on `MapDanger._map_entity_item_danger[e]![item]![cell]!`

### Uninitialized Variables

- [ ] **Controlers/Items.ls:123** - `getOrderedDefensiveItems()` iterates over uninitialized `effects` array instead of `item.effects`
- [ ] **Model/Combos/Position.ls:2-3** - Fields `danger` and `consequences` have no type or initialization

### Logic Errors

- [ ] **Model/Combos/Combo.ls:32-36** - `score` initialized to `null` then accumulated with `+=` (should init to `0.0`)
- [ ] **Model/Combos/Consequences.ls:65** - Comparing nullable `boostMP` with integer `boostMPbefore`

---

## Medium Issues

### Dead Code / Incomplete Implementations

- [ ] **AI/AI.ls:154-158** - `findBestPosition()` is empty (TODO stub)
- [ ] **Model/GameObject/Item.ls:67-75** - Target type logic is commented out, causing `targetKey` to always be `NONE` (except lasers)
- [ ] **Model/GameObject/Item.ls:137** - `targetSet()` missing default return statement

### Hardcoded Magic Numbers

- [ ] **Model/GameObject/Cell.ls:15-18** - Magic cell ID `1312` used as self-cast sentinel (should be constant)
- [ ] **Model/Combos/Consequences.ls:155,169,192,207,215** - Erosion divisor `20` should be constant
- [ ] **Model/GameObject/EntityEffect.ls:17** - Infinite duration `-1` mapped to arbitrary `7`

### Type Safety

- [ ] **Services/Benchmark.ls:45** - `format(num)` missing parameter and return types
- [ ] **Controlers/Maps/MapPath.ls:5** - `refresh()` missing return type annotation

---

## Low Priority

### Performance

- [ ] **Model/GameObject/Cell.ls:77-231** - Heavy area initialization (11 arrays × 613 cells)
- [ ] **Model/Combos/Consequences.ls:25-26** - Deep clone on every action evaluation
- [ ] **main.ls:31-39** - `failSafe()` uses force-unwrap on items that may not be equipped

### Code Quality

- [ ] Standardize comments language (currently mixed French/English)
- [ ] **Services/Targets.ls:153-292** - Refactor duplicate launch type handlers
- [ ] **AI/Scoring.ls:31-46** - Remove unused `computeCoef` map with function values

---

## Quick Reference

| File | Line | Severity | Issue |
|------|------|----------|-------|
| AI/AI.ls | 122 | Critical | Null deref on bestCombo |
| AI/AI.ls | 148 | Critical | Null deref on bestDanger |
| Fight.ls | 162 | Critical | Variable shadowing `self` |
| Damages.ls | 16 | Critical | Unchecked map access |
| Items.ls | 123 | Critical | Uninitialized `effects` |
| Position.ls | 2-3 | Critical | Untyped fields |
| Combo.ls | 32 | Critical | Null score accumulation |
| Consequences.ls | 65 | Critical | Null comparison |
| AI.ls | 154 | Medium | Empty function |
| Item.ls | 67 | Medium | Commented out logic |
| Item.ls | 137 | Medium | Missing return |
| Cell.ls | 15 | Medium | Magic number 1312 |
| Consequences.ls | 155 | Medium | Magic number 20 |
| EntityEffect.ls | 17 | Medium | Magic number 7 |
| Benchmark.ls | 45 | Medium | Missing types |
| MapPath.ls | 5 | Medium | Missing return type |

---

## Notes

- Code is LeekScript v4 (typed variant)
- Cell 1312 is a sentinel for "self-cast" actions (out of valid range 0-612)
- `Fight.selfCell` references this sentinel cell
- The commented-out Item target logic at line 67-75 is likely causing targeting issues
