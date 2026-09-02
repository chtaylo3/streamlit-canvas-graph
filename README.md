# Streamlit Graph Canvas dependency explorer

A Streamlit application for browsing GitHub accounts, repositories, manifests,
direct dependencies, and transitive dependencies without rendering an entire
software portfolio at once.

The app reads local, snapshot-oriented DuckDB/Parquet data. GitHub access is
isolated in separate command-line tools, so the UI never receives or stores a
GitHub credential.

## Quick start

```bash
uv sync
uv run scg demo
uv run streamlit-canvas-graph
```

The demo command writes two deterministic snapshots, Parquet tables, and UUID
ring thumbnails under the gitignored `data/demo/` directory. The app opens at
`http://localhost:8501` and uses that dataset by default.

To open another compatible database:

```bash
SCG_DATA_DIR=/path/to/data \
SCG_DATABASE=/path/to/data/dependency-explorer.duckdb \
uv run streamlit-canvas-graph
```

The thumbnail directory must be `${SCG_DATA_DIR}/thumbnails`, with files named
`<node_uuid>.png`.

## Configuration and secrets

Configuration is managed by Dynaconf through the typed
`streamlit_canvas_graph.settings.AppConfig` interface. Values are loaded in
this order:

1. Tracked, non-secret defaults from `settings.toml`.
2. Local secrets from `.secrets.toml`.
3. `SCG_*` environment variables, which have the highest priority.

Create a local secrets file from the safe template:

```bash
install -m 600 .secrets.toml.example .secrets.toml
```

Then edit `.secrets.toml`:

```toml
github_read_token = "github_pat_..."
github_provision_token = "github_pat_..."
```

Use a read-only fine-grained PAT for `github_read_token` and a separate,
write-enabled PAT for `github_provision_token`. The real `.secrets.toml` is
ignored by Git; `.secrets.toml.example` contains placeholders only.

Environment variables remain useful for CI and temporary terminal sessions:

```bash
export SCG_GITHUB_READ_TOKEN='github_pat_...'
export SCG_GITHUB_PROVISION_TOKEN='github_pat_...'
export SCG_DATA_DIR='/path/to/data'
export SCG_DATABASE='/path/to/data/dependency-explorer.duckdb'
```

The original `GITHUB_READ_TOKEN` and `GITHUB_PROVISION_TOKEN` names are accepted
as compatibility fallbacks, but new configuration should use the `SCG_` prefix.
Never place a real PAT in `settings.toml`, the repository catalog, or the
example secrets file.

## User experience

- Account → repository → manifest → shared dependency navigation.
- Two ancestor levels and one descendant level around the focused node.
- Ancestors outside the active breadcrumb trail are dimmed while the active
  lineage and immediate descendant edges remain emphasized.
- A hard 500-node canvas limit with explicit truncation messaging.
- The reusable `streamlit-graph-canvas==0.1.0rc1` component supplies the typed
  graph contract, React Flow canvas, ELK layout, pan/zoom, controls, minimap,
  keyboard navigation, and validated selection state.
- `streamlit-graph-canvas-contrib==0.1.0rc1` supplies explicitly enabled
  connection-count badges without application-owned JavaScript.
- Node metadata or enlarged ring details in the right panel.
- Snapshot history, global node search, manual refresh, severity cards, and a
  filterable vulnerability table.

The concentric rings use fixed semantics: direct/transitive on the inner ring,
major/minor/patch updates in the middle, and critical/high/medium/low findings
on the outer ring. Segment size represents count.

## Read-only GitHub ingestion

Create a fine-grained PAT with read-only access to repository metadata and
contents, grant it only to the repositories you intend to inspect, and expose
it through the environment:

```bash
export SCG_GITHUB_READ_TOKEN='...'
uv run scg ingest github --output data/github
```

The command discovers the authenticated account at runtime, lists only
non-archived repositories owned by that account, and prompts for a selection.
For a noninteractive but still explicit run:

```bash
uv run scg ingest github \
  --repo authenticated-owner/repository-one \
  --repo authenticated-owner/repository-two \
  --yes
```

Each run writes an immutable snapshot. GitHub SPDX SBOM data is augmented from
npm, PyPI, and NuGet lockfiles, then enriched through batched OSV requests and
ecosystem registry metadata. Unsupported or partial inputs are recorded in the
`ingestion_issues` table instead of being silently discarded.

Tokens are never accepted as CLI arguments and are not written to logs,
DuckDB, Parquet, thumbnails, or Streamlit state.

## Private-data boundary

Snapshots contain GitHub account names, repository names and URLs, manifest
paths, dependency relationships, and vulnerability findings. The entire `data/`
tree is ignored by Git and must never be committed, attached to an issue, or
published as a build artifact. This application does not provide authentication;
serve private-derived datasets only on a trusted local machine or behind an
independently authenticated access layer.

## Optional private test copies

[`config/test-repositories.toml`](config/test-repositories.toml) contains four
dependency-rich public sources for each of npm, PyPI, and NuGet. All twelve are
selected by default. The catalog belongs only to the provisioning tool; the
Streamlit app and ingestion library do not import it.

Public GitHub forks cannot be made private. The provisioner therefore creates
independent private repositories containing only each source's current default
branch. It does not copy issues, pull requests, releases, Actions secrets,
tags, or full history.

Use a separate token authorized to create, push, and delete repositories:

```bash
export SCG_GITHUB_PROVISION_TOKEN='...'
uv run scg provision create
```

The command validates current visibility, license, default-branch SHA,
repository size, and expected manifests before displaying a complete preview.
Nothing is created until confirmation. Override the default set by repeating
`--source owner/repository`.

Every created repository is recorded by immutable GitHub repository ID in
`data/provisioning/repositories.json`. Cleanup is allowlisted to active records
in that local manifest and has a separate destructive confirmation:

```bash
uv run scg provision cleanup
```

Review upstream licenses before provisioning. License and attribution files
from the default branch are retained in each private copy.

## Contributing and security

Pull requests are accepted from approved repository collaborators. Other users
should open an issue to discuss a proposed change. See
[`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md), and the
maintainer list in [`.github/MAINTAINERS.md`](.github/MAINTAINERS.md).

This project is licensed under the Apache License 2.0.

## Development

Python checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The application consumes the pinned `streamlit-graph-canvas` and
`streamlit-graph-canvas-contrib` wheels from PyPI. Their packaged frontend and
renderer assets mean this example requires no local Node.js build. Update both
pins together because the prerelease renderer contract is versioned as a pair.

## Data model

The normalized contract contains `snapshots`, `nodes`, `edges`,
`ring_metrics`, `vulnerabilities`, `package_versions`, and `ingestion_issues`.
Dependency identity is stable across repositories within a snapshot by
ecosystem, normalized package name, and resolved version. Each snapshot is also
exported as table-oriented Parquet under `parquet/<snapshot_uuid>/`.

Manifest-to-package `depends_on` edges identify declared direct dependencies.
The separate `resolves` edge anchors a parsed dependency component to its source
manifest when the parser cannot identify a direct declaration; it conveys
provenance, not direct-dependency status. Ingestion resolves each repository's
default branch to an immutable commit SHA and stores SHA-256 hashes for parsed
manifest and SBOM content. A snapshot is rolled back if any dependency remains
unreachable from a manifest before metrics and exports are finalized.
