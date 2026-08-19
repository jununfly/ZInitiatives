# ZInitiatives

ZInitiatives is the GitHub-hosted registry for cross-repository Initiative navigation. Its stable hierarchy is `Initiative → Spec → Plan`; the registry indexes documents owned by Initiative repositories and does not copy their contents.

## Repository layout

- `registry/` contains the manifest inputs.
- `generated/` contains deterministic registry projections.
- `schemas/` contains protocol schemas.
- `docs/prds/` contains the Registry Protocol specification.

The first protocol fixture indexes the `zj-initiative-registry` Spec and Plan in ZAgentic. The compiler and validator are implementation work tracked by the ZAgentic Plan referenced by that fixture.

## Compile generated views

Run `python scripts/compile_registry.py` from this repository. The compiler reads `registry/` manifests, sorts every collection by stable ID, and writes `generated/global-initiative-registry.json`, `generated/global-initiative-registry.md`, and `generated/global-initiative-registry.mmd`. Use `--commit <40-character-sha>` when reproducing a historical generated view; otherwise the current Registry `HEAD` is recorded.

Run `python scripts/validate_registry.py` to check manifest relations, local checkout references, generated JSON freshness, and every indexed `zj-roadmap-driven` Plan. Use `--workspace-root <directory>` when Initiative repositories are checked out outside the parent directory of ZInitiatives.

Use `python scripts/registry_admin.py show <id>` to inspect an entity. Registering uses `register initiative`, `register spec`, or `register plan` with explicit identity and path fields; removal requires `remove <kind> --id <id> --confirm`. `semantic-diff` compares the current manifests with a generated Registry file or a Git ref and reports added, changed, and removed IDs.

Use `python scripts/git_workflow.py publish-plan <scope>` to print the scoped branch, commit, push, and pull-request commands without executing them. `sync --execute` fetches a remote and stops when the remote branch has moved; `create-branch --execute` creates a scoped branch only from a clean tree. Device-local Initiative checkout paths are managed with `checkout-map set|get|list` and are stored outside this repository by default.
