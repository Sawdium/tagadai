# LeekScript Operation Costs

Empirically verified from fight #51227567 (scenario 38117).

## Arithmetic Operators

| Operator | Cost |
|----------|------|
| `+` `-` | 4 |
| `*` | 5 |
| `/` `%` | 8 |
| `**` | 43 |

## Bitwise Operators

| Operator | Cost |
|----------|------|
| `&` `\|` `^` `~` | 4 |
| `<<` `>>` | 4 |
| `bitCount()` | 4 |
| `trailingZeros()` | 4 |
| `leadingZeros()` | 4 |

## Array Operations

| Operation | Cost | Complexity |
|-----------|------|------------|
| `arr[i]` read | 5 | O(1) |
| `arr[i] = v` write | 5 | O(1) |
| `push()` | 4 | O(1) |
| `pop()` | 5 | O(1) |
| `count()` | 4 | O(1) |
| `inArray()` | 9 | O(n) |
| `arrayConcat(a,b)` | ~3 + 1.25n | O(n) |

## Set Operations

| Operation | Cost | Complexity |
|-----------|------|------------|
| `setPut()` | 5 | O(1) |
| `setContains()` | 5 | O(1) |
| `setUnion(a,b)` | ~3 + 2n | **O(n)** |
| `setDifference(a,b)` | ~3 + 2n | **O(n)** |
| `setIntersection(a,b)` | ~3 + 2n | **O(n)** |

Scaling verified:
- 3+3 elements: 15 ops
- 10+10 elements: 43 ops
- 50+50 elements: 203 ops

## Conversions

| Operation | Cost | Complexity |
|-----------|------|------------|
| `arrayToSet()` | ~4 + 2n | O(n) |
| `setToArray()` | ~3 + 2n | O(n) |
| `intervalToArray()` | ~5 + 2n | O(n) |

## Control Flow

| Operation | Cost |
|-----------|------|
| `if (true) {work}` | 4 |
| `if (false) {skip}` | 3 |
| `cond ? a : b` | 4 |

## Loop Costs (per iteration)

| Loop Type | Cost/iter | Notes |
|-----------|-----------|-------|
| `for (v in array)` | **1.3** | Fastest for value access |
| `for (i=0; i<n; i++)` | 3.4 | Just loop overhead |
| `while (i < n)` | 3.3 | Similar to for |
| `for (k:v in map)` | ~1.7 | Efficient |

With array access in body:
- `for-in + work`: 2.3/iter
- `indexed for + arr[i] + work`: 6.4/iter

**Key insight**: `for-in` is 2-3x faster than indexed loops when you need values.

## Map Operations

| Operation | Cost | Complexity |
|-----------|------|------------|
| `map[k]` read | 5 | O(1) |
| `map[k] = v` write | 6 | O(1) |
| `map[k] = v` insert | 6 | O(1) |
| `mapSize()` | 4 | O(1) |
| `mapKeys()` | 3 | O(1)* |
| `mapValues()` | 3 | O(1)* |
| `map[k] != null` check | 6 | O(1) |
| `for (k:v in map)` | ~1.7/iter | O(n) |

*mapKeys/mapValues return lazy iterators - cost is O(1) to create, iteration is separate.

## Math Functions

| Function | Cost |
|----------|------|
| `abs()` | 5 |
| `min()` `max()` | 4 |
| `floor()` `ceil()` `round()` | 4 |
| `sqrt()` | 10 |

## Game Functions

| Function | Cost | Notes |
|----------|------|-------|
| `getCellX()` | ~5-6 | Built-in coordinate lookup |
| `getCellY()` | ~5-6 | Built-in coordinate lookup |
| `isObstacle()` | ~8+ | Map check, cache if called repeatedly |

## Variable Scope

| Pattern | Cost | Notes |
|---------|------|-------|
| Global map access | 5 | `GLOBAL_MAP[k]` - standard map lookup |
| Local variable assignment | ~1 | `var x = globalMap` - reference copy |
| Local via cached global | 5 | No savings vs direct global access |

**Key insight**: Caching globals as locals does NOT save ops. The assignment cost offsets any theoretical access savings. LeekScript resolves globals efficiently.

## Summary

- **Base overhead**: Most operations have 3-5 ops base cost
- **Set bulk ops are O(n)**: ~2 ops per element, NOT O(1)
- **For-in is fast**: Contrary to some claims, for-in is the fastest loop
- **Maps are efficient**: O(1) for read/write/size, similar cost to arrays
- **Globals are fast**: No benefit to caching globals as locals
- **Avoid**: `**` (43 ops), `sqrt` (10 ops), set bulk operations on large sets
