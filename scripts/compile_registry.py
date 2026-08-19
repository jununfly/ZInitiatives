#!/usr/bin/env python3
"""Compile Registry manifests into deterministic JSON, Markdown, and Mermaid views."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "registry" / "registry.config.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def load_directory(path: Path) -> list[dict[str, Any]]:
    return [load_json(item) for item in sorted(path.glob("*.json"))]


def current_commit() -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True
    ).strip()


def build_registry(commit: str) -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    initiative_dir = ROOT / config["manifestDirectories"]["initiatives"]
    spec_root = ROOT / config["manifestDirectories"]["specs"]
    plan_root = ROOT / config["manifestDirectories"]["plans"]

    initiatives = load_directory(initiative_dir)
    specs = [item for directory in sorted(spec_root.iterdir()) if directory.is_dir() for item in load_directory(directory)]
    plans = [item for directory in sorted(plan_root.iterdir()) if directory.is_dir() for item in load_directory(directory)]

    initiative_by_id = {item["id"]: item for item in initiatives}
    spec_by_id = {item["id"]: item for item in specs}
    plan_by_spec = {item["specId"]: item for item in plans}
    if len(initiative_by_id) != len(initiatives):
        raise ValueError("duplicate Initiative id")
    if len(spec_by_id) != len(specs):
        raise ValueError("duplicate Spec id")
    if len(plan_by_spec) != len(plans):
        raise ValueError("multiple Plan manifests for one Spec are not supported by v1 compiler")

    output_initiatives: list[dict[str, Any]] = []
    for initiative in sorted(initiatives, key=lambda item: item["id"]):
        initiative_id = initiative["id"]
        output = dict(initiative)
        output["specs"] = []
        for spec in sorted((item for item in specs if item["initiativeId"] == initiative_id), key=lambda item: item["id"]):
            spec_output = {key: spec[key] for key in ("id", "label", "kind", "path")}
            spec_output["plans"] = []
            for plan in sorted((item for item in plans if item["specId"] == spec["id"]), key=lambda item: item["id"]):
                spec_output["plans"].append({key: plan[key] for key in ("id", "label", "path", "engine")})
            output["specs"].append(spec_output)
        output_initiatives.append(output)

    return {
        "$schema": config["protocolVersion"],
        "generatedFrom": {"repository": config["repository"], "commit": commit},
        "initiatives": output_initiatives,
    }


def render_json(registry: dict[str, Any]) -> str:
    return json.dumps(registry, ensure_ascii=False, indent=2) + "\n"


def render_markdown(registry: dict[str, Any]) -> str:
    lines = [
        "# Global Initiative Registry",
        "",
        f"Generated from `{registry['generatedFrom']['repository']}` at commit `{registry['generatedFrom']['commit']}`.",
        "",
    ]
    for initiative in registry["initiatives"]:
        lines.append(f"## {initiative['label']}")
        lines.append("")
        for spec in initiative["specs"]:
            lines.append(f"- Spec: `{spec['label']}` — `{spec['path']}`")
            for plan in spec["plans"]:
                lines.append(f"  - Plan: `{plan['label']}` — `{plan['path']}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_mermaid(registry: dict[str, Any]) -> str:
    lines = ["flowchart TB"]
    for initiative in registry["initiatives"]:
        initiative_node = initiative["id"].replace("-", "_")
        lines.append(f'  {initiative_node}["{initiative["label"]}"]')
        for spec in initiative["specs"]:
            spec_node = spec["id"].replace("-", "_")
            lines.append(f'  {initiative_node} --> {spec_node}["{spec["label"]}"]')
            for plan in spec["plans"]:
                plan_node = plan["id"].replace("-", "_")
                lines.append(f'  {spec_node} --> {plan_node}["{plan["label"]}"]')
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", help="commit SHA to record; defaults to Registry HEAD")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "generated")
    args = parser.parse_args()
    commit = args.commit or current_commit()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise SystemExit("--commit must be a 40-character lowercase commit SHA")
    registry = build_registry(commit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "global-initiative-registry.json").write_text(render_json(registry), encoding="utf-8")
    (args.output_dir / "global-initiative-registry.md").write_text(render_markdown(registry), encoding="utf-8")
    (args.output_dir / "global-initiative-registry.mmd").write_text(render_mermaid(registry), encoding="utf-8")
    print(f"compiled {len(registry['initiatives'])} initiatives to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
