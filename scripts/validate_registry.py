#!/usr/bin/env python3
"""Validate Registry manifests, local references, generated projections, and Plan files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from compile_registry import ROOT, build_registry, render_json


ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
KINDS = {"product", "shared-capability", "experimental", "external"}
LIFECYCLES = {"active", "dormant", "archived"}
SPEC_KINDS = {"product-spec", "architecture-spec", "research-spec", "migration-spec"}


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def require_text(value: object, field: str, path: Path, errors: list[str]) -> None:
    if not isinstance(value, str) or not value:
        fail(errors, f"{path}: {field} must be a non-empty string")


def check_id(value: object, field: str, path: Path, errors: list[str]) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        fail(errors, f"{path}: {field} must be kebab-case")


def load_manifests(root: Path, errors: list[str]) -> tuple[list[dict], list[dict], list[dict]]:
    config = load(root / "registry/registry.config.json")
    directories = config.get("manifestDirectories", {})
    try:
        initiative_dir = root / directories["initiatives"]
        spec_dir = root / directories["specs"]
        plan_dir = root / directories["plans"]
    except KeyError as exc:
        fail(errors, f"registry.config.json missing manifest directory: {exc}")
        return [], [], []

    initiatives = [load(path) for path in sorted(initiative_dir.glob("*.json"))]
    specs = [load(path) for directory in sorted(spec_dir.iterdir()) if directory.is_dir() for path in sorted(directory.glob("*.json"))]
    plans = [load(path) for directory in sorted(plan_dir.iterdir()) if directory.is_dir() for path in sorted(directory.glob("*.json"))]
    return initiatives, specs, plans


def validate_manifests(initiatives: list[dict], specs: list[dict], plans: list[dict], errors: list[str]) -> None:
    ids: set[str] = set()
    initiative_ids: set[str] = set()
    for item in initiatives:
        path = Path(f"registry/initiatives/{item.get('id', '<unknown>')}.json")
        if item.get("$schema") != "zj-initiative/v1":
            fail(errors, f"{path}: invalid $schema")
        check_id(item.get("id"), "id", path, errors)
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in ids:
                fail(errors, f"duplicate id: {item_id}")
            ids.add(item_id)
            initiative_ids.add(item_id)
        require_text(item.get("label"), "label", path, errors)
        require_text(item.get("repository"), "repository", path, errors)
        require_text(item.get("defaultBranch"), "defaultBranch", path, errors)
        require_text(item.get("owner"), "owner", path, errors)
        if item.get("kind") not in KINDS:
            fail(errors, f"{path}: invalid kind")
        if item.get("lifecycle") not in LIFECYCLES:
            fail(errors, f"{path}: invalid lifecycle")

    spec_ids: set[str] = set()
    for item in specs:
        path = Path(f"registry/specs/{item.get('initiativeId', '<unknown>')}/{item.get('id', '<unknown>')}.json")
        if item.get("$schema") != "zj-initiative-spec/v1":
            fail(errors, f"{path}: invalid $schema")
        check_id(item.get("id"), "id", path, errors)
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in ids:
                fail(errors, f"duplicate id: {item_id}")
            ids.add(item_id)
            spec_ids.add(item_id)
        if item.get("initiativeId") not in initiative_ids:
            fail(errors, f"{path}: unknown initiativeId")
        require_text(item.get("label"), "label", path, errors)
        if item.get("kind") not in SPEC_KINDS:
            fail(errors, f"{path}: invalid kind")
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.startswith("docs/prds/") or not path_value.endswith(".md"):
            fail(errors, f"{path}: path must target docs/prds/*.md")

    plan_ids: set[str] = set()
    for item in plans:
        path = Path(f"registry/plans/{item.get('initiativeId', '<unknown>')}/{item.get('id', '<unknown>')}.json")
        if item.get("$schema") != "zj-initiative-plan/v1":
            fail(errors, f"{path}: invalid $schema")
        check_id(item.get("id"), "id", path, errors)
        item_id = item.get("id")
        if isinstance(item_id, str):
            if item_id in ids:
                fail(errors, f"duplicate id: {item_id}")
            ids.add(item_id)
            plan_ids.add(item_id)
        if item.get("initiativeId") not in initiative_ids:
            fail(errors, f"{path}: unknown initiativeId")
        if item.get("specId") not in spec_ids:
            fail(errors, f"{path}: unknown specId")
        if item.get("engine") != "zj-roadmap-driven":
            fail(errors, f"{path}: unsupported engine")
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.startswith("docs/plans/") or not path_value.endswith(".json"):
            fail(errors, f"{path}: path must target docs/plans/*.json")


def repository_dir(repository: str, workspace_root: Path) -> Path | None:
    parsed = urlparse(repository)
    name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    candidate = workspace_root / name
    return candidate if candidate.is_dir() else None


def validate_local_references(initiatives: list[dict], specs: list[dict], plans: list[dict], workspace_root: Path, roadmap_cli: Path, errors: list[str], warnings: list[str]) -> None:
    roots = {item["id"]: repository_dir(item["repository"], workspace_root) for item in initiatives if isinstance(item.get("id"), str) and isinstance(item.get("repository"), str)}
    for item in specs:
        root = roots.get(item.get("initiativeId"))
        if root is None:
            warnings.append(f"remote checkout unavailable for Spec {item.get('id')}")
            continue
        if not (root / item["path"]).is_file():
            fail(errors, f"missing Spec reference: {root / item['path']}")
    for item in plans:
        root = roots.get(item.get("initiativeId"))
        if root is None:
            warnings.append(f"remote checkout unavailable for Plan {item.get('id')}")
            continue
        plan_path = root / item["path"]
        if not plan_path.is_file():
            fail(errors, f"missing Plan reference: {plan_path}")
            continue
        try:
            plan = load(plan_path)
            if not isinstance(plan.get("nodes"), dict) or "1" not in plan["nodes"]:
                fail(errors, f"Plan is not a zj-roadmap-driven JSON: {plan_path}")
            else:
                subprocess.run(
                    ["python", str(roadmap_cli), "validate", str(plan_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                )
        except (json.JSONDecodeError, subprocess.CalledProcessError, OSError) as exc:
            fail(errors, f"Plan validation failed for {plan_path}: {exc}")


def validate_generated(root: Path, errors: list[str]) -> None:
    generated_path = root / "generated/global-initiative-registry.json"
    if not generated_path.is_file():
        fail(errors, "generated/global-initiative-registry.json is missing")
        return
    generated = load(generated_path)
    commit = generated.get("generatedFrom", {}).get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        fail(errors, "generated registry has invalid generatedFrom.commit")
        return
    expected = build_registry(commit)
    if generated != expected:
        fail(errors, "generated/global-initiative-registry.json is stale; run compile_registry.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, default=ROOT.parent)
    parser.add_argument("--roadmap-cli", type=Path, default=Path.home() / ".codex/skills/zj-roadmap-driven/roadmap_cli.py")
    args = parser.parse_args()
    errors: list[str] = []
    warnings: list[str] = []
    initiatives, specs, plans = load_manifests(ROOT, errors)
    validate_manifests(initiatives, specs, plans, errors)
    if not errors:
        validate_local_references(initiatives, specs, plans, args.workspace_root, args.roadmap_cli, errors, warnings)
        validate_generated(ROOT, errors)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"valid: {len(initiatives)} initiatives, {len(specs)} specs, {len(plans)} plans")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
