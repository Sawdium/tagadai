#!/usr/bin/env python3
"""
AI Sync Tool — manage LeekScript AI files on LeekWars (path-based API).

Everything is addressed by path now (no integer IDs). The root folder is "".
Folders are created implicitly by file creation only if the parent exists;
use `mkdir` for new folder hierarchies.

Usage:
    python -m src.tools.aisync list [--json] [--folders] [--bin]
    python -m src.tools.aisync get <path> [-o file]          # - or omit = stdout
    python -m src.tools.aisync put <path> <file>             # file can be -
    python -m src.tools.aisync new <path> [--version 4]      # path = folder/name
    python -m src.tools.aisync rename <path> <new_name>
    python -m src.tools.aisync mv <path> <dest_folder>       # dest "" = root
    python -m src.tools.aisync rm <path>
    python -m src.tools.aisync restore <trash_name>
    python -m src.tools.aisync mkdir <path>
    python -m src.tools.aisync rmdir <path>
    python -m src.tools.aisync download <dir>
    python -m src.tools.aisync sync <dir> [--account login]  # compare local<->remote
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_list(api: LeekWarsAPI, args):
    tree = api.get_ai_tree()
    if args.json:
        print(json.dumps(tree, indent=2))
        return

    if args.folders:
        folders = sorted(tree.get("folders", []))
        print("FOLDERS:")
        print("-" * 60)
        for f in folders:
            print(f"  {f}")
        print(f"\nTotal: {len(folders)} folders")
        return

    if args.bin:
        items = tree.get("bin", [])
        print("BIN:")
        print("-" * 60)
        for b in items:
            valid = "+" if b.get("valid") else "-"
            print(f"  {valid} {b['path']:40}  v{b.get('version', '?')}")
        print(f"\nTotal: {len(items)} in bin")
        return

    files = sorted(tree.get("files", []), key=lambda x: x["path"])
    print("AI FILES:")
    print("-" * 60)
    for f in files:
        valid = "+" if f.get("valid") else "-"
        v = f.get("version", "?")
        lines = f.get("total_lines", "?")
        print(f"  {valid} {f['path']:50}  v{v}  {lines} lines")
    print(f"\nTotal: {len(files)} files, {len(tree.get('folders', []))} folders")


def cmd_get(api: LeekWarsAPI, args):
    code = api.read_ai(args.path)
    if args.output and args.output != "-":
        Path(args.output).write_text(code, encoding="utf-8")
        print(f"Saved {len(code)} chars to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(code)


def cmd_put(api: LeekWarsAPI, args):
    if args.file == "-":
        code = sys.stdin.read()
    else:
        code = Path(args.file).read_text(encoding="utf-8")

    api.write_ai(args.path, code)
    print(f"Uploaded {len(code)} chars to '{args.path}'", file=sys.stderr)

    # Fresh tree to report validity
    api.refresh_farmer()
    entry = next((f for f in api.list_ais() if f["path"] == args.path), None)
    if entry is None:
        print(f"WARN: '{args.path}' not in tree after upload", file=sys.stderr)
    elif entry.get("valid"):
        print(f"'{args.path}' is VALID", file=sys.stderr)
    else:
        print(f"'{args.path}' has ERRORS", file=sys.stderr)


def cmd_new(api: LeekWarsAPI, args):
    path = args.path.strip("/")
    if "/" in path:
        folder, name = path.rsplit("/", 1)
    else:
        folder, name = "", path
    result = api.create_ai(name, folder=folder, version=args.version)
    print(f"Created '{result.get('path', path)}'", file=sys.stderr)
    print(result.get("path", path))


def cmd_rename(api: LeekWarsAPI, args):
    api.rename_ai(args.path, args.new_name)
    print(f"Renamed '{args.path}' -> '{args.new_name}'", file=sys.stderr)


def cmd_mv(api: LeekWarsAPI, args):
    dest = args.dest.strip("/")
    api.move_ai(args.path, dest)
    print(f"Moved '{args.path}' -> '{dest or '(root)'}'", file=sys.stderr)


def cmd_rm(api: LeekWarsAPI, args):
    result = api.delete_ai(args.path)
    trash = result.get("trash_name", args.path)
    print(f"Deleted '{args.path}' (bin: '{trash}')", file=sys.stderr)


def cmd_restore(api: LeekWarsAPI, args):
    api.restore_ai(args.trash_name)
    print(f"Restored '{args.trash_name}' from bin", file=sys.stderr)


def cmd_mkdir(api: LeekWarsAPI, args):
    api.create_folder(args.path.strip("/"))
    print(f"Created folder '{args.path}'", file=sys.stderr)


def cmd_rmdir(api: LeekWarsAPI, args):
    api.delete_folder(args.path.strip("/"))
    print(f"Deleted folder '{args.path}'", file=sys.stderr)


def cmd_download(api: LeekWarsAPI, args):
    output_dir = Path(args.directory)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = api.list_ais()
    count = 0
    errors = []
    for entry in files:
        path = entry["path"]
        dest = output_dir / path
        try:
            code = api.read_ai(path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(code, encoding="utf-8")
            print(f"  {dest}", file=sys.stderr)
            count += 1
            time.sleep(0.1)
        except Exception as e:
            errors.append(f"{path}: {e}")
            print(f"  ERROR: {path} — {e}", file=sys.stderr)

    print(f"Downloaded {count}/{len(files)} files to {output_dir}", file=sys.stderr)
    if errors:
        print(f"Errors: {len(errors)}", file=sys.stderr)
        sys.exit(1)


def _collect_local(root: Path) -> dict[str, int]:
    """Collect LeekScript files under root. Returns {relative_path: size}."""
    SKIP_DIRS = {".git", "tampermonkey", "docs", "__pycache__"}
    SKIP_EXACT = {"LICENSE", "readme.md", "TODO.md", ".gitignore"}
    SKIP_EXT = {".md", ".js", ".json", ".txt", ".py", ".yml", ".yaml"}

    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name in SKIP_EXACT:
                continue
            if any(name.endswith(ext) for ext in SKIP_EXT):
                continue
            full = Path(dirpath) / name
            rel = full.relative_to(root).as_posix()
            out[rel] = full.stat().st_size
    return out


def cmd_push(api: LeekWarsAPI, args):
    """Upload every local file under <directory> to its matching remote path.

    Creates missing folders & files. Optionally restricts to files that differ
    from the remote (--only-changed, based on byte length — remote char count
    can differ slightly due to UTF-8 multi-byte but catches most real changes).
    """
    root = Path(args.directory)
    local = _collect_local(root)
    if not local:
        print("No local files found", file=sys.stderr)
        return

    remote = {f["path"]: f for f in api.list_ais()}
    remote_folders = set(api.list_ai_folders())

    if args.only_changed:
        targets = {
            p: sz for p, sz in local.items()
            if p not in remote or remote[p].get("total_chars", -1) != sz
        }
    else:
        targets = dict(local)

    if not targets:
        print("Nothing to upload (everything matches).", file=sys.stderr)
        return

    # Ensure parent folders exist (deepest-last)
    needed_folders = set()
    for p in targets:
        parts = p.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            needed_folders.add("/".join(parts[:i]))
    for folder in sorted(needed_folders, key=lambda x: x.count("/")):
        if folder not in remote_folders:
            try:
                api.create_folder(folder)
                remote_folders.add(folder)
                print(f"  mkdir  {folder}", file=sys.stderr)
                time.sleep(0.2)
            except Exception as e:
                print(f"  WARN: mkdir {folder} failed: {e}", file=sys.stderr)

    # Upload files
    uploaded = 0
    for path in sorted(targets):
        code = (root / path).read_text(encoding="utf-8")
        try:
            if path not in remote:
                folder = path.rsplit("/", 1)[0] if "/" in path else ""
                name = path.rsplit("/", 1)[-1]
                api.create_ai(name, folder=folder, version=4)
                time.sleep(0.2)
            api.write_ai(path, code)
            print(f"  push   {path} ({len(code)} chars)", file=sys.stderr)
            uploaded += 1
            time.sleep(0.15)
        except Exception as e:
            print(f"  ERROR  {path}: {e}", file=sys.stderr)

    print(f"Uploaded {uploaded}/{len(targets)} files.", file=sys.stderr)


def cmd_sync(api: LeekWarsAPI, args):
    local = _collect_local(Path(args.directory))
    remote = {f["path"]: f for f in api.list_ais()}

    only_local = sorted(set(local) - set(remote))
    only_remote = sorted(set(remote) - set(local))
    both = sorted(set(local) & set(remote))

    acct = api.farmer.get("login", "?")
    print(f"=== sync status: local={args.directory}  remote={acct} ===")
    print(f"  local files:  {len(local)}")
    print(f"  remote files: {len(remote)}")
    print(f"  overlap:      {len(both)}")
    print(f"  only local:   {len(only_local)}")
    print(f"  only remote:  {len(only_remote)}")

    if only_local:
        print("\n-- only local (would upload) --")
        for p in only_local:
            print(f"  + {p} ({local[p]} B)")
    if only_remote:
        print("\n-- only remote (would pull) --")
        for p in only_remote:
            print(f"  - {p} ({remote[p].get('total_chars', '?')} chars)")

    if args.json:
        print(json.dumps({
            "account": acct,
            "only_local": only_local,
            "only_remote": only_remote,
            "overlap": both,
        }, indent=2))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main():
    p = argparse.ArgumentParser(description="Manage AI files on LeekWars (path-based)")
    p.add_argument("--account", help="Override LEEKWARS_LOGIN (password from .env)")
    sub = p.add_subparsers(dest="command", required=False)

    sp = sub.add_parser("list", help="List AI files")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--folders", action="store_true")
    sp.add_argument("--bin", action="store_true")

    sp = sub.add_parser("get", help="Download AI code")
    sp.add_argument("path")
    sp.add_argument("-o", "--output")

    sp = sub.add_parser("put", help="Upload AI code")
    sp.add_argument("path")
    sp.add_argument("file")

    sp = sub.add_parser("new", help="Create new AI file")
    sp.add_argument("path", help="Full path (folder/name)")
    sp.add_argument("--version", type=int, default=4)

    sp = sub.add_parser("rename", help="Rename AI file")
    sp.add_argument("path")
    sp.add_argument("new_name")

    sp = sub.add_parser("mv", help="Move AI file")
    sp.add_argument("path")
    sp.add_argument("dest", help="Destination folder path ('' for root)")

    sp = sub.add_parser("rm", help="Delete AI file (moves to bin)")
    sp.add_argument("path")

    sp = sub.add_parser("restore", help="Restore AI file from bin")
    sp.add_argument("trash_name")

    sp = sub.add_parser("mkdir", help="Create folder")
    sp.add_argument("path")

    sp = sub.add_parser("rmdir", help="Delete folder")
    sp.add_argument("path")

    sp = sub.add_parser("download", help="Download all files")
    sp.add_argument("directory")

    sp = sub.add_parser("sync", help="Compare local directory vs remote tree")
    sp.add_argument("directory")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("push", help="Upload local directory to remote (bulk)")
    sp.add_argument("directory")
    sp.add_argument("--only-changed", action="store_true",
                    help="Skip files whose remote char-count matches local byte-count")

    args = p.parse_args()

    if not args.command:
        p.print_help()
        sys.exit(1)

    try:
        login, password = load_credentials()
        if args.account:
            login = args.account
        api = LeekWarsAPI()
        api.login(login, password)

        {
            "list":     cmd_list,
            "get":      cmd_get,
            "put":      cmd_put,
            "new":      cmd_new,
            "rename":   cmd_rename,
            "mv":       cmd_mv,
            "rm":       cmd_rm,
            "restore":  cmd_restore,
            "mkdir":    cmd_mkdir,
            "rmdir":    cmd_rmdir,
            "download": cmd_download,
            "sync":     cmd_sync,
            "push":     cmd_push,
        }[args.command](api, args)

    except TagadAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
