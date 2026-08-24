"""
Materialise a tagadalive variant with scoring constants rewritten.

LeekScript constants are `static` fields compiled into the AI; there is no
runtime injection. The only way to play a candidate weight set is to write it
into a copy of the tree and point the generator at that copy. Each variant
lives under `.cache/variants/<name>/`, named by a hash of the overrides AND of
the source tree's file mtimes, so:

- the same overrides on an unchanged source reuse the existing copy;
- the generator's compile cache, keyed by AI path, never confuses two
  variants or a variant with a stale copy of itself.

Two kinds of key are accepted in `overrides`:

    "KILL_VALUE": 25000              # a `static <type> NAME = ...` anywhere in the tree
    "ENTITY_LEEK.HP": 1.2            # an entry of a row in EntityCoefs' tables

The declared type is respected: an `integer` constant is written rounded, a
`real` one always with a decimal point, a `boolean` as true/false. A key that
matches no declaration, or more than one, is an error rather than a silent
no-op -- a tuner that "fits" a constant nobody rewrote learns nothing.

    from src.tuning.variant import materialize
    ai = materialize({"KILL_VALUE": 25000, "ENTITY_LEEK.HP": 1.2})   # -> "v-3f9a.../main"
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Mapping, Union

from src.common.config import get_paths
from src.common.errors import TagadAIError

Value = Union[int, float, bool]

SOURCE = "tagadalive"
ENTRY = "main"
MANIFEST = "variant.json"
COEFS_FILE = Path("HiddenKnowledges") / "EntityCoefs"
IGNORED = (".git", "__pycache__", "tampermonkey", "TESTS")

_DECL = r"^(?P<head>[ \t]*static (?:final )?(?P<type>integer|real|boolean) {name}[ \t]*=[ \t]*)(?P<value>[^/\n]*?)(?P<tail>[ \t]*(?://.*)?)$"
_ROW = r"^[ \t]*{row}:[ \t]*\["
_ENTRY = r"(?P<head>Stats\.{stat}:[ \t]*)(?P<value>-?[0-9]+(?:\.[0-9]+)?)"


def _format(value: Value, declared: str) -> str:
    if declared == "boolean":
        return "true" if value else "false"
    if declared == "integer":
        return str(int(round(float(value))))
    text = repr(float(value))
    return text if ("." in text or "e" in text) else text + ".0"


def _tree_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in IGNORED for part in p.relative_to(root).parts):
            out.append(p)
    return out


def _source_fingerprint(root: Path) -> str:
    h = hashlib.sha1()
    for p in _tree_files(root):
        st = p.stat()
        h.update(f"{p.relative_to(root)}:{st.st_mtime_ns}:{st.st_size}\n".encode())
    return h.hexdigest()


def variant_name(overrides: Mapping[str, Value], source_fingerprint: str) -> str:
    payload = json.dumps({"overrides": dict(sorted(overrides.items())), "source": source_fingerprint}, sort_keys=True)
    return "v-" + hashlib.sha1(payload.encode()).hexdigest()[:12]


def rewrite_scalar(tree: Path, name: str, value: Value) -> Path:
    """Rewrite `static <type> NAME = ...` in whichever file declares it."""
    pattern = re.compile(_DECL.format(name=re.escape(name)), re.MULTILINE)
    hits = [(p, pattern.findall(p.read_text())) for p in _tree_files(tree)]
    hits = [(p, m) for p, m in hits if m]
    total = sum(len(m) for _, m in hits)
    if total != 1:
        where = ", ".join(str(p.relative_to(tree)) for p, _ in hits) or "nowhere"
        raise TagadAIError(f"constant {name!r} declared {total} times ({where}); need exactly one")
    path = hits[0][0]
    text = path.read_text()
    new, n = pattern.subn(lambda m: m.group("head") + _format(value, m.group("type")) + m.group("tail"), text, count=1)
    assert n == 1
    path.write_text(new)
    return path


def rewrite_coef(tree: Path, row: str, stat: str, value: Value) -> Path:
    """Rewrite `Stats.<stat>: <n>` inside the `<row>: [ ... ]` block of EntityCoefs."""
    path = tree / COEFS_FILE
    if not path.is_file():
        raise TagadAIError(f"{path} not found; coefficient keys need the EntityCoefs tables")
    text = path.read_text()
    starts = list(re.finditer(_ROW.format(row=re.escape(row)), text, re.MULTILINE))
    if len(starts) != 1:
        raise TagadAIError(f"row {row!r} found {len(starts)} times in {path.name}; need exactly one")
    open_at = starts[0].end() - 1
    depth, close_at = 0, -1
    for i in range(open_at, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                close_at = i
                break
    if close_at < 0:
        raise TagadAIError(f"unbalanced brackets after row {row!r} in {path.name}")
    block = text[open_at:close_at]
    pattern = re.compile(_ENTRY.format(stat=re.escape(stat)))
    if len(pattern.findall(block)) != 1:
        raise TagadAIError(f"{row}.{stat}: {len(pattern.findall(block))} entries in the row; need exactly one")
    block = pattern.sub(lambda m: m.group("head") + _format(value, "real"), block, count=1)
    path.write_text(text[:open_at] + block + text[close_at:])
    return path


def apply_overrides(tree: Path, overrides: Mapping[str, Value]) -> None:
    for key, value in overrides.items():
        if "." in key:
            row, stat = key.split(".", 1)
            rewrite_coef(tree, row, stat, value)
        else:
            rewrite_scalar(tree, key, value)


def materialize(
    overrides: Mapping[str, Value],
    source: Union[str, Path] = SOURCE,
    variants_dir: Union[Path, None] = None,
    link: bool = True,
) -> str:
    """Write (or reuse) the variant tree and return its AI path, e.g. `v-3f9a1c2b4d5e/main`.

    `link` exposes the tree inside the generator directory the way
    `src.tools.localfight.link_ai_tree` does for the root trees; tests that
    only check the rewrite pass `link=False`.
    """
    paths = get_paths()
    src = Path(source) if Path(source).is_absolute() else paths.root / source
    if not src.is_dir():
        raise TagadAIError(f"No AI tree at {src}")
    out_root = variants_dir or paths.variants_dir
    out_root.mkdir(parents=True, exist_ok=True)

    fingerprint = _source_fingerprint(src)
    name = variant_name(overrides, fingerprint)
    dst = out_root / name
    manifest = {"source": str(src), "source_fingerprint": fingerprint, "overrides": dict(overrides)}

    if dst.is_dir():
        try:
            if json.loads((dst / MANIFEST).read_text()) == manifest and (dst / ENTRY).is_file():
                if link:
                    _link(dst)
                return f"{name}/{ENTRY}"
        except (OSError, ValueError):
            pass
        shutil.rmtree(dst)

    tmp = out_root / (name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns(*IGNORED))
    try:
        apply_overrides(tmp, overrides)
    except Exception:
        shutil.rmtree(tmp)
        raise
    (tmp / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True))
    tmp.rename(dst)
    if link:
        _link(dst)
    return f"{name}/{ENTRY}"


def _link(dst: Path) -> None:
    from src.tools.localfight import link_ai_tree  # late import: tools depend on this package's siblings
    link_ai_tree(f"{dst.name}/{ENTRY}")


def clean(variants_dir: Union[Path, None] = None) -> int:
    """Delete every materialised variant (and its generator symlink). Returns the count removed."""
    paths = get_paths()
    out_root = variants_dir or paths.variants_dir
    n = 0
    if not out_root.is_dir():
        return 0
    for d in out_root.iterdir():
        if d.is_dir() and d.name.startswith("v-"):
            link = paths.generator_dir / d.name
            if link.is_symlink():
                link.unlink()
            shutil.rmtree(d)
            n += 1
    return n
