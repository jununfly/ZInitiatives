#!/usr/bin/env python3
"""Manage Registry manifests and inspect semantic changes."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from compile_registry import ROOT, build_registry, render_json


ID_FIELDS = {
    "initiative": ("id",),
    "spec": ("id", "initiativeId"),
    "plan": ("id", "initiativeId", "specId"),
}


def json_files(directory: Path) -> list[Path]:
    return sorted(directory.rglob("*.json")) if directory.exists() else []


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def config() -> dict[str, Any]:
    return load(ROOT / "registry/registry.config.json")


def manifest_directory(kind: str) -> Path:
    key = {"initiative": "initiatives", "spec": "specs", "plan": "plans"}[kind]
    return ROOT / config()["manifestDirectories"][key]


def find_manifest(kind: str, entity_id: str) -> Path | None:
    for path in json_files(manifest_directory(kind)):
        if path.name == "registry.config.json":
            continue
        if load(path).get("id") == entity_id:
            return path
    return None


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compile_and_validate() -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts/compile_registry.py")], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/validate_registry.py")], check=True)


def register(args: argparse.Namespace) -> None:
    if find_manifest(args.kind, args.id):
        raise SystemExit(f"{args.kind} already exists: {args.id}")
    if args.kind == "initiative":
        value = {
            "$schema": "zj-initiative/v1",
            "id": args.id,
            "label": args.label,
            "kind": args.kind_value,
            "lifecycle": args.lifecycle,
            "repository": args.repository,
            "defaultBranch": args.default_branch,
            "owner": args.owner,
        }
        path = manifest_directory(args.kind) / f"{args.id}.json"
    elif args.kind == "spec":
        value = {
            "$schema": "zj-initiative-spec/v1",
            "id": args.id,
            "initiativeId": args.initiative_id,
            "label": args.label,
            "kind": args.kind_value,
            "path": args.path,
        }
        path = manifest_directory(args.kind) / args.initiative_id / f"{args.id}.json"
    else:
        value = {
            "$schema": "zj-initiative-plan/v1",
            "id": args.id,
            "initiativeId": args.initiative_id,
            "specId": args.spec_id,
            "label": args.label,
            "path": args.path,
            "engine": args.engine,
        }
        path = manifest_directory(args.kind) / args.initiative_id / f"{args.id}.json"
    write_json(path, value)
    try:
        compile_and_validate()
    except subprocess.CalledProcessError:
        path.unlink(missing_ok=True)
        subprocess.run([sys.executable, str(ROOT / "scripts/compile_registry.py")], check=False)
        raise
    print(f"registered {args.kind}: {args.id}")


def remove(args: argparse.Namespace) -> None:
    path = find_manifest(args.kind, args.id)
    if path is None:
        raise SystemExit(f"{args.kind} not found: {args.id}")
    if not args.confirm:
        raise SystemExit("removal requires --confirm")
    original = path.read_bytes()
    path.unlink()
    try:
        compile_and_validate()
    except subprocess.CalledProcessError:
        path.write_bytes(original)
        subprocess.run([sys.executable, str(ROOT / "scripts/compile_registry.py")], check=False)
        raise
    print(f"removed {args.kind}: {args.id}")


def show(args: argparse.Namespace) -> None:
    for kind in ("initiative", "spec", "plan"):
        path = find_manifest(kind, args.id)
        if path is not None:
            print(json.dumps(load(path), ensure_ascii=False, indent=2))
            return
    raise SystemExit(f"entity not found: {args.id}")


def flatten(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for initiative in registry["initiatives"]:
        result[initiative["id"]] = {"type": "initiative", **initiative}
        for spec in initiative["specs"]:
            result[spec["id"]] = {"type": "spec", "initiativeId": initiative["id"], **spec}
            for plan in spec["plans"]:
                result[plan["id"]] = {"type": "plan", "initiativeId": initiative["id"], "specId": spec["id"], **plan}
    return result


def semantic_diff(args: argparse.Namespace) -> None:
    current = build_registry(args.commit)
    previous = load(Path(args.against)) if args.against else None
    if previous is None:
        try:
            raw = subprocess.check_output(["git", "show", f"{args.ref}:generated/global-initiative-registry.json"], text=True, cwd=ROOT)
            previous = json.loads(raw)
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot read comparison Registry: {exc}")
    before = flatten(previous)
    after = flatten(current)
    for entity_id in sorted(set(before) | set(after)):
        if entity_id not in before:
            print(f"ADDED {after[entity_id]['type']} {entity_id}")
        elif entity_id not in after:
            print(f"REMOVED {before[entity_id]['type']} {entity_id}")
        elif before[entity_id] != after[entity_id]:
            print(f"CHANGED {after[entity_id]['type']} {entity_id}")


def check_drift(args: argparse.Namespace) -> None:
    initiatives = {item["id"]: item for item in (load(path) for path in json_files(manifest_directory("initiative")))}
    specs = [load(path) for path in json_files(manifest_directory("spec"))]
    plans = [load(path) for path in json_files(manifest_directory("plan"))]
    broken = 0
    warnings = 0
    for initiative_id, initiative in sorted(initiatives.items()):
        name = urlparse(initiative["repository"]).path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        checkout = args.workspace_root.expanduser().resolve() / name
        if not checkout.is_dir():
            print(f"WARNING checkout unavailable {initiative_id} {checkout}")
            warnings += 1
            continue
        registered_specs = {item["path"] for item in specs if item["initiativeId"] == initiative_id}
        registered_plans = {item["path"] for item in plans if item["initiativeId"] == initiative_id}
        for path in sorted(registered_specs | registered_plans):
            if not (checkout / path).is_file():
                print(f"BROKEN {initiative_id} {path}")
                broken += 1
        for path in sorted((checkout / "docs/prds").glob("*.md")) if (checkout / "docs/prds").is_dir() else []:
            relative = path.relative_to(checkout).as_posix()
            if relative not in registered_specs:
                print(f"UNREGISTERED spec {initiative_id} {relative}")
                warnings += 1
        for path in sorted((checkout / "docs/plans").glob("*.json")) if (checkout / "docs/plans").is_dir() else []:
            relative = path.relative_to(checkout).as_posix()
            if relative not in registered_plans:
                print(f"UNREGISTERED plan {initiative_id} {relative}")
                warnings += 1
    print(f"drift: broken={broken} warnings={warnings}")
    if broken:
        raise SystemExit(1)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    register_parser = commands.add_parser("register")
    register_sub = register_parser.add_subparsers(dest="kind", required=True)

    initiative = register_sub.add_parser("initiative")
    initiative.add_argument("--id", required=True)
    initiative.add_argument("--label", required=True)
    initiative.add_argument("--kind", dest="kind_value", choices=["product", "shared-capability", "experimental", "external"], required=True)
    initiative.add_argument("--lifecycle", choices=["active", "dormant", "archived"], default="active")
    initiative.add_argument("--repository", required=True)
    initiative.add_argument("--default-branch", default="main")
    initiative.add_argument("--owner", required=True)
    initiative.set_defaults(handler=register)

    spec = register_sub.add_parser("spec")
    spec.add_argument("--id", required=True)
    spec.add_argument("--initiative-id", required=True)
    spec.add_argument("--label", required=True)
    spec.add_argument("--kind", dest="kind_value", choices=["product-spec", "architecture-spec", "research-spec", "migration-spec"], required=True)
    spec.add_argument("--path", required=True)
    spec.set_defaults(handler=register)

    plan = register_sub.add_parser("plan")
    plan.add_argument("--id", required=True)
    plan.add_argument("--initiative-id", required=True)
    plan.add_argument("--spec-id", required=True)
    plan.add_argument("--label", required=True)
    plan.add_argument("--path", required=True)
    plan.add_argument("--engine", default="zj-roadmap-driven")
    plan.set_defaults(handler=register)

    remove_parser = commands.add_parser("remove")
    remove_sub = remove_parser.add_subparsers(dest="kind", required=True)
    for kind in ("initiative", "spec", "plan"):
        item = remove_sub.add_parser(kind)
        item.add_argument("--id", required=True)
        item.add_argument("--confirm", action="store_true")
        item.set_defaults(handler=remove)

    show_parser = commands.add_parser("show")
    show_parser.add_argument("id")
    show_parser.set_defaults(handler=show)

    diff_parser = commands.add_parser("semantic-diff")
    diff_parser.add_argument("--against", help="path to a generated Registry JSON")
    diff_parser.add_argument("--ref", default="HEAD", help="Git ref containing generated/global-initiative-registry.json")
    diff_parser.add_argument("--commit", default="0000000000000000000000000000000000000000")
    diff_parser.set_defaults(handler=semantic_diff)

    drift_parser = commands.add_parser("check-drift")
    drift_parser.add_argument("--workspace-root", type=Path, default=ROOT.parent)
    drift_parser.set_defaults(handler=check_drift)
    return root


def main() -> int:
    args = parser().parse_args()
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
