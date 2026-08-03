#!/usr/bin/env python3
"""
Bulk-upload the tagadalive/ LeekScript tree, with a deprecated code-fix pass.

The original version scrubbed circular `include('../auto')` lines on a pre-LS4
codebase. That fix is no longer needed — current files are already LS4-clean,
and the path-based API uploads raw content unchanged.

This module is retained as a thin wrapper over `aisync push`. Prefer using
`python -m src.tools.aisync push tagadalive` directly.
"""

import sys

from src.tools.aisync import main as aisync_main

TAGADALIVE_DIR = "tagadalive"


def main():
    sys.argv = [sys.argv[0], "push", TAGADALIVE_DIR, *sys.argv[1:]]
    aisync_main()


if __name__ == "__main__":
    main()
