#!/usr/bin/env python3
"""
Editor Problems Tool — reads the LeekScript editor's problems panel (warnings,
errors, info) by driving the LeekWars web editor with a headless browser.

The LeekWars compiler surfaces warnings (e.g. "comparison is always false",
"unnecessary non-null assertion") only in the web editor's problems panel —
they are not returned by the AI read/write API. This tool logs in, opens the
editor, and scrapes that panel so warnings can be inspected from the CLI.

Usage:
    python -m src.tools.editor                          # All problems, grouped by file
    python -m src.tools.editor Model/GameObject/Entity  # Only that file's problems
    python -m src.tools.editor --json                   # Machine-readable
    python -m src.tools.editor --account tagadanar      # Switch account
    python -m src.tools.editor --headed                 # Show the browser (debug)

Requires: playwright (`pip install playwright && playwright install chromium`).
"""

import argparse
import json
import sys

from src.common.credentials import load_credentials
from src.common.errors import TagadAIError

BASE_URL = "https://leekwars.com"
# The compiler finishes analysing the whole AI tree a few seconds after the
# editor mounts; the problems panel is populated only once that completes.
ANALYZE_WAIT_MS = 6000


def fetch_problems(login: str, password: str, headed: bool = False) -> list[dict]:
    """Log into LeekWars, open the editor, and scrape the problems panel.

    Returns a list of {file, severity, message, location} dicts.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise TagadAIError(
            "playwright is not installed. Run:\n"
            "    pip install playwright && playwright install chromium"
        ) from e

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_context().new_page()
        try:
            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page.fill("input[name=login]", login)
            page.fill("input[name=password]", password)
            page.click("button:has-text('Log in')")
            page.wait_for_timeout(3000)
            if page.url.rstrip("/").endswith("/login"):
                raise TagadAIError("Login failed — check credentials in .env")

            page.goto(f"{BASE_URL}/editor", wait_until="networkidle")
            # Wait for the problems panel to appear, then for analysis to settle.
            page.wait_for_selector(".problems-details", timeout=20000)
            page.wait_for_timeout(ANALYZE_WAIT_MS)

            # Each file group is a `.file` header followed by a sibling div of
            # `.problem` entries. Walk the panel and attribute problems to the
            # nearest preceding file header.
            problems = page.evaluate(
                r"""() => {
                    const out = [];
                    const panel = document.querySelector('.problems-details');
                    if (!panel) return out;
                    let currentFile = null;
                    const walk = (node) => {
                        for (const el of node.children) {
                            if (el.classList && el.classList.contains('file')) {
                                currentFile = el.textContent.trim()
                                    .replace(/\s+\d+$/, '').trim();
                            } else if (el.classList && el.classList.contains('problem')) {
                                const lineEl = el.querySelector('.line');
                                const location = lineEl ? lineEl.textContent.trim() : '';
                                const icon = el.querySelector('.v-icon');
                                const cls = icon ? icon.className : '';
                                let severity = 'warning';
                                for (const s of ['error', 'warning', 'todo', 'info']) {
                                    if (cls.split(/\s+/).includes(s)) { severity = s; break; }
                                }
                                let msg = el.textContent.trim();
                                if (location) msg = msg.replace(location, '').trim();
                                out.push({file: currentFile, severity, message: msg, location});
                            } else {
                                walk(el);
                            }
                        }
                    };
                    walk(panel);
                    return out;
                }"""
            )
            return problems
        finally:
            browser.close()


def format_human(problems: list[dict], file_filter: str | None) -> str:
    if file_filter:
        problems = [p for p in problems if p["file"] == file_filter]

    if not problems:
        scope = f" for '{file_filter}'" if file_filter else ""
        return f"No problems found{scope}."

    by_file: dict[str, list[dict]] = {}
    for prob in problems:
        by_file.setdefault(prob["file"], []).append(prob)

    lines = []
    total = len(problems)
    lines.append(f"{total} problem(s) across {len(by_file)} file(s)\n")
    for fpath in sorted(by_file):
        items = by_file[fpath]
        lines.append(f"{fpath}  ({len(items)})")
        for prob in items:
            sev = prob["severity"].upper()
            loc = f"  {prob['location']}" if prob["location"] else ""
            lines.append(f"  [{sev}]{loc}  {prob['message']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def main():
    parser = argparse.ArgumentParser(
        description="Read the LeekWars editor problems panel (warnings/errors)."
    )
    parser.add_argument(
        "file", nargs="?", help="Only show problems for this AI path "
        "(e.g. Model/GameObject/Entity)"
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    parser.add_argument("--headed", action="store_true", help="Show the browser window")
    args = parser.parse_args()

    try:
        login, password = load_credentials()
        if args.account:
            login = args.account

        problems = fetch_problems(login, password, headed=args.headed)

        if args.file:
            problems = [p for p in problems if p["file"] == args.file]

        if args.json:
            print(json.dumps(problems, indent=2, ensure_ascii=False))
        else:
            print(format_human(problems, None))
    except TagadAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
