"""Tests for AI log parsing (pure, no generator)."""

from src.localfight.logs import TurnStats, collect_logs, parse_turn_stats


def _result(entries):
    return {"logs": {"0": {"0": entries}}}


def test_parse_turn_stats_pairs_combos_with_marker():
    r = _result([
        [0, 1, "ComboExplorer: 3 combos, best=P1:Jump>c6 score=103220 <Combo: [...]"],
        [0, 1, "##MARKER##T1|n:Claudius|o:6124147/19000000|hp:2610/2610|tp:1/26|mp:1/8"],
        [1, 1, "ComboExplorer: 4 combos, best=P1:Jump>c26 score=60585"],
        [1, 1, "##MARKER##T1|n:Claudias|o:8216541/18000000|hp:2850/2850"],
        [0, 1, "some unrelated debug line"],
        [0, 1, "ComboExplorer: 177 combos, best=P0:Stay score=29109"],
        [0, 1, "##MARKER##T2|n:Claudius|o:14555876/19000000|hp:3388/3512"],
    ])
    stats = parse_turn_stats(r)
    assert stats == [
        TurnStats(0, 1, "Claudius", 6124147, 19000000, 3),
        TurnStats(1, 1, "Claudias", 8216541, 18000000, 4),
        TurnStats(0, 2, "Claudius", 14555876, 19000000, 177),
    ]
    assert abs(stats[2].ops_ratio - 14555876 / 19000000) < 1e-9


def test_marker_without_explorer_line_reports_minus_one():
    r = _result([[3, 1, "##MARKER##T5|n:bulb|o:100/1000000|hp:1/1"]])
    assert parse_turn_stats(r) == [TurnStats(3, 5, "bulb", 100, 1000000, -1)]


def test_collect_logs_names_system_codes():
    r = _result([[0, 3, "", 1001, [42]], [0, 1]])
    assert collect_logs(r) == [(0, 3, "CHIP_NOT_EQUIPPED [42]")]
