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
    cell_types.py       — Name-matching heuristics (suggest_name_mappings)
    parameters/
      cell_templates.py — 29 PhysiCell cell-type XML templates
      xml_defaults.py   — Default PhysiCell XML scaffold sections
  gui/
    walkthrough.py      — WalkthroughSession (pure-Python state machine),
                          BiwtWalkthrough (Qt widget), create_biwt_widget,
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
- BIWT returns a `BiwtResult` (coordinates DataFrame, cell type map, XML) via the `on_complete` callback.
- Studio owns all file I/O — BIWT never writes to disk.
- The integration bridge is in `bin/ics_tab.py` of the PhysiCell-Studio repo (`_create_biwt_package_tab` and `_biwt_complete`).
- A legacy fallback (`bin/biwt_tab.py`) is used when the package is not installed.

## Naming Conventions
- **Python files**: `snake_case.py`
- **Classes**: `PascalCase` (e.g. `BiwtWalkthrough`, `WalkthroughSession`)
- **Session fields**: `snake_case` — all state lives on `WalkthroughSession`
- **Step window classes**: named `<Step>Window` (e.g. `EditCellTypesWindow`)
- **Step labels**: PascalCase strings matching the window class prefix (e.g. `"EditCellTypes"`)
- **CSV columns**: `x`, `y`, `z`, `type` (PhysiCell convention; `type` not `cell_type`)
- **Domain units**: `DomainSpec.units` defaults to `"micron"` (PhysiCell convention)
- **Test classes**: `Test<Feature>` (e.g. `TestStepSequencing`)
- **Test files**: `test_<module>.py`

## Publishing a Release

Pushing a version tag triggers CI (`.github/workflows/publish.yml`) to build and publish to PyPI automatically. No manual build or upload needed:

```bash
git tag v<version>
git push origin v<version>
```

## Branching Rules
- Never modify `main` or `development` directly.
- Default base branch is `development` unless the user specifies another base.
- For any task, create a feature branch:
```
git checkout -b feature/<desc> <base-branch>
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
- `WalkthroughSession` is pure Python (no Qt); all Qt logic lives in window classes and `BiwtWalkthrough`.
- `_STEP_ORDER` + `_STEP_FIELDS` + `_invalidate_downstream_of(label)` in `walkthrough.py` centralize downstream session invalidation when the user navigates back and changes an earlier step. Individual window `process_window` callbacks should set `stale_futures = True` when their choice changes something downstream.
- `QLineEdit_custom.focusInEvent` restores the full unformatted value via `QLineEdit.setText(self, self.full_value)` — bypassing the overridden `setText` to avoid re-triggering `format_text` on focus.

## Suggested Reading Order For New Work
1. This file (orientation)
2. [PRD.md](PRD.md) (what BIWT should do)
3. [src/biwt/types.py](src/biwt/types.py) (API boundary)
4. [src/biwt/gui/walkthrough.py](src/biwt/gui/walkthrough.py) (session + widget + step logic)
5. [tests/test_session.py](tests/test_session.py) (how the session is exercised)
