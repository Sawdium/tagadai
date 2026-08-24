"""Tests for the variant materialiser (pure text rewriting, no generator)."""

import json
import shutil

import pytest

from src.common.errors import TagadAIError
from src.tuning import variant


SCORING = """class ScoringConfig {
\tstatic boolean DYNAMIC_COEFS = false
\tstatic integer KILL_VALUE = 30000
\tstatic real AOE_DECAY_RATE = 0.2  // damage/effect ratio drops by this per cell
\tstatic final boolean FLAG = true
}
"""

COEFS = """class EntityCoefs {
\tstatic Map<integer, Map<integer, real>> entityCoefs = [
\t\tENTITY_LEEK: [
\t\t\tStats.HP: 1.0, Stats.HPTIME: 1.0, Stats.HPMAX: 10.0,
\t\t\tStats.TP: 40.0, Stats.MP: 60.0
\t\t],
\t\tENTITY_BULB: [
\t\t\tStats.HP: 0.5, Stats.HPMAX: 1.0,
\t\t\tStats.TP: 10.0, Stats.MP: 15.0
\t\t]
\t]
\tstatic Map<integer, Map<integer, real>> bulbCoefs = [
\t\tBULB_HEALER: [
\t\t\tStats.HP: 0.5, Stats.TP: 8.0
\t\t]
\t]
}
"""


@pytest.fixture
def tree(tmp_path):
    src = tmp_path / "fake"
    (src / "HiddenKnowledges").mkdir(parents=True)
    (src / "HiddenKnowledges" / "ScoringConfig").write_text(SCORING)
    (src / "HiddenKnowledges" / "EntityCoefs").write_text(COEFS)
    (src / "main").write_text("include('auto')\n")
    return src


def _materialize(tree, tmp_path, overrides):
    return variant.materialize(overrides, source=tree, variants_dir=tmp_path / "variants", link=False)


def test_scalar_rewrite_keeps_type_and_comment(tree, tmp_path):
    ai = _materialize(tree, tmp_path, {"KILL_VALUE": 25000.7, "AOE_DECAY_RATE": 1, "DYNAMIC_COEFS": True})
    out = tmp_path / "variants" / ai.split("/")[0] / "HiddenKnowledges" / "ScoringConfig"
    text = out.read_text()
    assert "static integer KILL_VALUE = 25001\n" in text
    assert "static real AOE_DECAY_RATE = 1.0  // damage/effect ratio drops by this per cell\n" in text
    assert "static boolean DYNAMIC_COEFS = true\n" in text
    assert "static final boolean FLAG = true" in text  # untouched


def test_coef_rewrite_targets_the_right_row(tree, tmp_path):
    ai = _materialize(tree, tmp_path, {"ENTITY_LEEK.HP": 1.25, "ENTITY_BULB.TP": 12, "BULB_HEALER.HP": 0.75})
    text = (tmp_path / "variants" / ai.split("/")[0] / "HiddenKnowledges" / "EntityCoefs").read_text()
    leek = text[text.index("ENTITY_LEEK"):text.index("ENTITY_BULB")]
    bulb = text[text.index("ENTITY_BULB"):text.index("bulbCoefs")]
    healer = text[text.index("BULB_HEALER"):]
    assert "Stats.HP: 1.25," in leek and "Stats.TP: 40.0" in leek
    assert "Stats.HP: 0.5," in bulb and "Stats.TP: 12.0" in bulb
    assert "Stats.HP: 0.75," in healer


def test_unknown_or_ambiguous_keys_fail_loudly(tree, tmp_path):
    with pytest.raises(TagadAIError, match="declared 0 times"):
        _materialize(tree, tmp_path, {"NO_SUCH_CONSTANT": 1})
    with pytest.raises(TagadAIError, match="need exactly one"):
        _materialize(tree, tmp_path, {"ENTITY_TURRET.HP": 1})
    with pytest.raises(TagadAIError, match="need exactly one"):
        _materialize(tree, tmp_path, {"ENTITY_LEEK.NOPE": 1})
    # a failed rewrite leaves no half-built tree behind
    assert not list((tmp_path / "variants").glob("v-*"))


def test_same_overrides_reuse_and_source_change_renames(tree, tmp_path):
    a = _materialize(tree, tmp_path, {"KILL_VALUE": 1})
    b = _materialize(tree, tmp_path, {"KILL_VALUE": 1})
    assert a == b
    manifest = json.loads((tmp_path / "variants" / a.split("/")[0] / variant.MANIFEST).read_text())
    assert manifest["overrides"] == {"KILL_VALUE": 1}

    # touching the source tree changes the fingerprint, hence the name
    p = tree / "main"
    p.write_text(p.read_text() + "// edit\n")
    c = _materialize(tree, tmp_path, {"KILL_VALUE": 1})
    assert c != a
    assert (tmp_path / "variants" / c.split("/")[0] / "main").read_text().endswith("// edit\n")


def test_empty_overrides_is_a_plain_copy(tree, tmp_path):
    ai = _materialize(tree, tmp_path, {})
    d = tmp_path / "variants" / ai.split("/")[0]
    assert (d / "HiddenKnowledges" / "ScoringConfig").read_text() == SCORING
    assert ai.endswith("/main")
