#!/usr/bin/env python3
"""
Bulk-upload the tagadalive/ LeekScript tree to the authenticated account.

This is a thin wrapper over `python -m src.tools.aisync push tagadalive`.
Prefer calling aisync directly; this entry point is kept for backward-compat.
"""

import sys

from src.tools.aisync import main as aisync_main

TAGADALIVE_DIR = "tagadalive"


def main():
    sys.argv = [sys.argv[0], "push", TAGADALIVE_DIR, *sys.argv[1:]]
    aisync_main()


if __name__ == "__main__":
    main()
