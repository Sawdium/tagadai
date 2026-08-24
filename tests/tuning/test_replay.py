"""Replayer semantics on a synthetic action log (no generator)."""

from src.tuning.replay import replay_states

LEEKS = [
    {"id": 0, "team": 1, "life": 1000, "strength": 100, "magic": 0, "science": 0, "resistance": 0,
     "wisdom": 0, "agility": 0, "tp": 10, "mp": 3},
    {"id": 1, "team": 2, "life": 800, "strength": 0, "magic": 50, "science": 0, "resistance": 0,
     "wisdom": 0, "agility": 0, "tp": 12, "mp": 4},
]


def _states(actions):
    return [(s.turn, s.actor, s.leeks) for s in replay_states(LEEKS, actions)]


def test_damage_erosion_heal_and_vitality():
    # A snapshot is taken at the first real action after `[7, id]`: anything
    # before it (poison ticks, heal-over-time, expiries) is start-of-turn
    # bookkeeping the probe already sees, so the tests put a `[16, ...]` first.
    acts = [
        [6, 1], [7, 0], [16, 5, 1], [101, 1, 300, 30], [8, 0],
        [7, 1], [16, 5, 1], [103, 1, 50], [104, 1, 40], [112, 1, 25], [107, 0, 60, 0], [8, 1],
        [6, 2], [7, 0], [8, 0],
    ]
    s = _states(acts)
    # leek 1 seen by leek 1 at its turn: 800-300 = 500 life, 800-30 = 770 max
    assert s[1][2][1]["HP"] == 500 and s[1][2][1]["HPMAX"] == 770
    # at turn 2: heal +50, vitality +40 (both), nova vitality +25 (max only); nova on leek 0: max -60
    t2 = s[2][2]
    assert t2[1]["HP"] == 590 and t2[1]["HPMAX"] == 835
    assert t2[0]["HP"] == 1000 and t2[0]["HPMAX"] == 940


def test_effects_add_stack_update_remove_and_sign():
    acts = [
        [6, 1], [7, 0],
        [302, 9, 1, 0, 0, 6, 100, 2],      # absolute shield +100 on leek 0
        [302, 9, 2, 0, 1, 18, 3, 2],       # TP shackle -3 on leek 1
        [302, 9, 3, 0, 0, 26, 20, 2],      # vulnerability: relative shield -20 on leek 0
        [8, 0], [7, 1], [16, 5, 1],
        [14, 1, 50],                       # shield stacks to 150
        [304, 2, 1],                       # liberation: shackle now -1
        [8, 1], [6, 2], [7, 0],
        [303, 3],                          # vulnerability ends
        [8, 0], [7, 1], [8, 1],
    ]
    s = _states(acts)
    assert s[1][2][0]["ABSSHIELD"] == 100 and s[1][2][1]["TP"] == 9 and s[1][2][0]["RELSHIELD"] == -20
    # the vulnerability expires at the start of turn 2, before leek 0's snapshot
    assert s[2][2][0]["ABSSHIELD"] == 150 and s[2][2][1]["TP"] == 11 and s[2][2][0]["RELSHIELD"] == 0


def test_snapshot_skips_pre_init_manumission_and_dead_leeks():
    acts = [
        [6, 1], [7, 0], [302, 9, 1, 1, 0, 17, 2, 2], [8, 0],       # MP shackle -2 on leek 0
        [7, 1], [8, 1],
        [6, 2], [7, 0], [12, 100, 5, 1], [100, 0, 1], [303, 1], [308, 0],
        [302, 174, 2, 0, 0, 32, 2, 1], [10, 0, 7, [7]], [8, 0],    # manumission, then a move
        [7, 1], [101, 1, 800, 0], [5, 1], [8, 1],
        [6, 3], [7, 0], [8, 0], [7, 1], [8, 1],
    ]
    s = _states(acts)
    # turn 2, leek 0: the probe would see MP back to 3 and the +2 TP already applied
    t2 = next(l for t, a, l in s if t == 2 and a == 0)
    assert t2[0]["MP"] == 3 and t2[0]["TP"] == 12
    # leek 1 died on turn 2: no snapshot for it afterwards, and it is absent from leek 0's
    assert not any(t == 3 and a == 1 for t, a, _ in s)
    assert 1 not in next(l for t, a, l in s if t == 3 and a == 0)
