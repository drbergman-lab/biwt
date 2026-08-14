# Claude Agent Guide (BIWT)

## About the User
Assistant professor working on computational modeling of cancer-immune interactions, mechanistic modeling, and agent-based modeling frameworks. Lead developer of this package.

## Repository Overview

BIWT is a standalone pip-installable Python package that provides a guided walkthrough ("wizard") for importing single-cell bioinformatics data and generating initial conditions for agent-based models (ABMs). The primary host application is PhysiCell Studio, but the package is designed to be host-agnostic at the `BiwtInput` / `BiwtResult` API boundary.

The package lives at `~/biwt/` locally and `github.com/drbergman-lab/biwt` remotely.

## How To Run

### Install (development)
```
pip install -e ".[dev]"
```

### Run tests
```
PYTHONPATH=src python -m pytest tests/ -v
```

### Launch embedded in Studio (integration check)
```
python3 ~/PhysiCell-Studio_git/bin/studio.py --biwt
```

## Package Structure

```
src/biwt/
  types.py              — Public API: DomainSpec, BiwtInput, BiwtResult
  core/
    data_loader.py      — Unified loader (.h5ad, .rds, .csv) → BiwtData
    domain.py           — Domain inference + coordinate column detection
    positioning.py      — Coordinate scaling + build_ic_dataframe
    cell_types.py       — Name matching (default_name_matches, best_match,
                          suggest_name_mappings) + keep/merge/delete
    templates.py        — Reading host/user cell-parameter template files
  gui/
    walkthrough.py      — WalkthroughSession (pure-Python state machine),
                          BioinformaticsWalkthrough (Qt widget), create_biwt_widget,
                          _step_predicates (importable by tests)
    widgets.py          — QLineEdit_custom, QHLine, SectionHeader, etc.
    windows/
      base.py           — BiwinformaticsWalkthroughWindow base class
      spot_deconvolution.py
      cluster_column.py
      spatial_query.py
      edit_cell_types.py
      rename_cell_types.py
      cell_counts.py
      positions.py
      load_cell_parameters.py
tests/
  test_session.py       — Tests covering session logic end-to-end
  fixtures/             — CSV test fixtures
```

## Studio Integration

BIWT integrates with PhysiCell Studio as an optional installed dependency:

- Studio detects the package via `try: from biwt.gui.walkthrough import create_biwt_widget`.
- Studio constructs a `BiwtInput` (domain bounds, host name) and passes it to `create_biwt_widget`.
- BIWT returns a `BiwtResult` (coordinates DataFrame, cell type map, chosen cell templates) via the `on_complete` callback.
- Studio owns all file I/O — BIWT never writes to disk.
- The integration bridge is in `bin/ics_tab.py` of the PhysiCell-Studio repo (`_create_biwt_package_tab` and `_biwt_complete`).
- A legacy fallback (`bin/biwt_tab.py`) is used when the package is not installed.

## Naming Conventions
- **Python files**: `snake_case.py`
- **Classes**: `PascalCase` (e.g. `BioinformaticsWalkthrough`, `WalkthroughSession`)
- **Session fields**: `snake_case` — all state lives on `WalkthroughSession`
- **Step window classes**: named `<Step>Window` (e.g. `EditCellTypesWindow`)
- **Step labels**: PascalCase strings matching the window class prefix (e.g. `"EditCellTypes"`)
- **CSV columns**: `x`, `y`, `z`, `type` (PhysiCell convention; `type` not `cell_type`)
- **Domain units**: `DomainSpec.units` defaults to `"micron"` (PhysiCell convention)
- **Test classes**: `Test<Feature>` (e.g. `TestStepSequencing`)
- **Test files**: `test_<module>.py`

## Project Icon

The two masters are gitignored (`/biwt_icon*.png`) — ~7000 px and ~3 MB each, which would more
than double the sdist and sit in every clone to buy nothing the derivatives do not. Keep them
with the artwork; re-run `python scripts/make_icons.py` when they change.

| Master | Feeds |
|---|---|
| `biwt_icon.png` — full sticker, "BIWT" over "BioInformatics WalkThrough" | `docs/assets/biwt-sticker.png`, the README header only |
| `biwt_icon_mini.png` — same hex, subtitle dropped | `src/biwt/gui/icons/biwt.png`, `docs/assets/logo.png`, `docs/assets/favicon.png` |

Render size decides, not preference: the subtitle is illegible below ~200 px, and
mkdocs-material draws a header logo ~24 px tall and a favicon at 16–32. Anything small takes the
mini. The full sticker is only used where it renders large.

`docs/assets/social-preview.png` is GitHub's repo card, 1280×640 with the sticker inside an 80 px
margin — double the 40 pt border GitHub asks for. Nothing picks it up automatically: upload it
under **Settings → Social preview**.

Social cards for the docs site come from the `social` plugin, gated `enabled: !ENV [CI, false]`.
The renderer needs a native libcairo that pip does not install, so ungated it would break
`mkdocs serve` for anyone without it; CI sets `CI=true` and installs the system libraries. That
also means a local build never produces cards — the PR's Docs check is where they are verified.

The README header must stay an absolute `raw.githubusercontent.com/.../main/...` URL — a relative
path does not render on PyPI. It 404s on a branch until the change reaches `main`.

Never call `QApplication.setWindowIcon` from the package: that is one icon per process and
embedding would take the host's. Standalone launchers do it themselves. On macOS the per-window
icons BIWT does set are invisible, since the Dock has no per-window entry.

## Publishing a Release

Pushing a version tag triggers CI (`.github/workflows/publish.yml`) to build and publish to PyPI automatically. No manual build or upload needed:

```bash
git tag v<version>
git push origin v<version>
```

## Branching Rules
- Never modify `main` directly.
- The base branch is always `main` unless the user specifies another base.
- For any task, create a feature branch:
```
git checkout -b feature/<desc> main
```

## Definition of Done
A feature or fix is complete when ALL of the following are satisfied:

1. **Code**: Implementation is clean, minimal, and follows existing conventions.
2. **Edge cases**: Known edge cases are handled (empty data, missing columns, duplicate names, unit mismatches, etc.).
3. **Tests**: New or modified behavior has corresponding tests in `tests/`. All tests pass (`PYTHONPATH=src python -m pytest tests/ -v`).
4. **Documentation**: PRD.md updated with behavioral spec and acceptance criteria. README.md implementation status updated. progress.md updated with session decisions.
5. **No regressions**: Existing tests still pass. Studio can still launch with `--biwt` flag.

## Key Documents
- [PRD.md](PRD.md) — Product Requirements Document (what BIWT should do)
- [README.md](README.md) — Package overview and implementation status
- [progress.md](progress.md) — Session-level decisions and reasoning

## Common Pitfalls
- BIWT never writes to disk — the host is responsible for all file I/O.
- `_step_predicates` is the single source of truth for step ordering; `_build_next_window` and tests both use it.
- `WalkthroughSession` is pure Python (no Qt); all Qt logic lives in window classes and `BioinformaticsWalkthrough`.
- `_STEP_ORDER` + `_STEP_FIELDS` + `_invalidate_downstream_of(label)` in `walkthrough.py` centralize downstream session invalidation when the user navigates back and changes an earlier step. Individual window `process_window` callbacks should set `stale_futures = True` when their choice changes something downstream.
- Host context (`BiwtInput`) is resolved in `_resolve_host_input` at two points only — widget construction and each import — and snapshotted, so a run cannot see the host change under it. `create_biwt_widget` accepts a provider callable for exactly this reason. Do not add a third read point.
- `session.preferred_domain` is the only name for the host's domain; `effective_domain` falls back to it directly. Do not reintroduce a latched copy.
- `QLineEdit_custom.focusInEvent` restores the full unformatted value via `QLineEdit.setText(self, self.full_value)` — bypassing the overridden `setText` to avoid re-triggering `format_text` on focus.

## Suggested Reading Order For New Work
1. This file (orientation)
2. [PRD.md](PRD.md) (what BIWT should do)
3. [src/biwt/types.py](src/biwt/types.py) (API boundary)
4. [src/biwt/gui/walkthrough.py](src/biwt/gui/walkthrough.py) (session + widget + step logic)
5. [tests/test_session.py](tests/test_session.py) (how the session is exercised)
