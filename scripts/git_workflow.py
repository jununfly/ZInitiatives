#!/usr/bin/env python3
"""Safe Git workflow helpers for the GitHub-hosted Registry."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from compile_registry import ROOT


DEFAULT_MAP = Path.home() / ".config/zj-initiative-registry/checkouts.json"


def run_git(*args: str, execute: bool = True) -> str:
    if not execute:
        return "git " + " ".join(args)
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def ensure_clean() -> None:
    status = run_git("status", "--porcelain")
    if status:
        raise SystemExit("working tree is not clean; commit or stash before Registry sync")


def branch_name(scope: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", scope.lower()).strip("-")
    if not normalized:
        raise SystemExit("scope must contain at least one alphanumeric character")
    return f"zj/registry/{normalized}"


def sync(args: argparse.Namespace) -> None:
    branch = args.branch or run_git("branch", "--show-current")
    if not args.execute:
        print(f"git -C {ROOT} fetch --prune {args.remote}")
        print(f"git -C {ROOT} rev-list --left-right --count HEAD...{args.remote}/{branch}")
        return
    ensure_clean()
    subprocess.run(["git", "-C", str(ROOT), "fetch", "--prune", args.remote], check=True)
    remote_ref = f"{args.remote}/{branch}"
    try:
        counts = run_git("rev-list", "--left-right", "--count", f"HEAD...{remote_ref}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"remote branch unavailable: {remote_ref}") from exc
    ahead, behind = (int(value) for value in counts.split())
    if behind:
        raise SystemExit(f"remote moved: {behind} commit(s) behind {remote_ref}; rebase or merge explicitly")
    print(f"sync safe: branch={branch} ahead={ahead} behind={behind}")


def create_branch(args: argparse.Namespace) -> None:
    name = branch_name(args.scope)
    if not args.execute:
        print(f"would create branch: {name}")
        print(f"git -C {ROOT} switch -c {name}")
        return
    ensure_clean()
    existing = run_git("branch", "--list", name)
    if existing:
        raise SystemExit(f"local branch already exists: {name}")
    subprocess.run(["git", "-C", str(ROOT), "switch", "-c", name], check=True)
    print(f"created branch: {name}")


def publish_plan(args: argparse.Namespace) -> None:
    name = branch_name(args.scope)
    print(f"git -C {ROOT} fetch --prune {args.remote}")
    print(f"git -C {ROOT} status --porcelain")
    print(f"git -C {ROOT} add registry generated schemas scripts")
    print(f"git -C {ROOT} commit -m \"chore(registry): update {args.scope}\"")
    print(f"git -C {ROOT} push --set-upstream {args.remote} {name}")
    print(f"gh pr create --repo {args.repo} --head {name} --base {args.base} --fill")


def load_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise SystemExit(f"invalid checkout map: {path}")
    return value


def checkout_map(args: argparse.Namespace) -> None:
    path = args.config.expanduser()
    mapping = load_map(path)
    if args.map_command == "set":
        local_path = args.path.expanduser().resolve()
        if not local_path.is_dir():
            raise SystemExit(f"checkout path is not a directory: {local_path}")
        mapping[args.id] = str(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(sorted(mapping.items())), indent=2) + "\n", encoding="utf-8")
        print(f"mapped {args.id} -> {local_path}")
    elif args.map_command == "get":
        try:
            print(mapping[args.id])
        except KeyError as exc:
            raise SystemExit(f"no checkout mapping: {args.id}") from exc
    else:
        print(json.dumps(mapping, indent=2))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    sync_parser = commands.add_parser("sync")
    sync_parser.add_argument("--remote", default="origin")
    sync_parser.add_argument("--branch")
    sync_parser.add_argument("--execute", action="store_true")
    sync_parser.set_defaults(handler=sync)

    branch_parser = commands.add_parser("create-branch")
    branch_parser.add_argument("scope")
    branch_parser.add_argument("--execute", action="store_true")
    branch_parser.set_defaults(handler=create_branch)

    publish_parser = commands.add_parser("publish-plan")
    publish_parser.add_argument("scope")
    publish_parser.add_argument("--repo", default="jununfly/ZInitiatives")
    publish_parser.add_argument("--remote", default="origin")
    publish_parser.add_argument("--base", default="main")
    publish_parser.set_defaults(handler=publish_plan)

    map_parser = commands.add_parser("checkout-map")
    map_sub = map_parser.add_subparsers(dest="map_command", required=True)
    map_sub.add_parser("list").set_defaults(handler=checkout_map)
    get_parser = map_sub.add_parser("get")
    get_parser.add_argument("id")
    get_parser.set_defaults(handler=checkout_map)
    set_parser = map_sub.add_parser("set")
    set_parser.add_argument("id")
    set_parser.add_argument("path", type=Path)
    set_parser.set_defaults(handler=checkout_map)
    for item in map_sub.choices.values():
        item.add_argument("--config", type=Path, default=DEFAULT_MAP)
    return root


def main() -> int:
    args = parser().parse_args()
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
