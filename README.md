# BIWT — BioInformatics WalkThrough

A guided wizard for importing single-cell bioinformatics data and generating initial conditions for agent-based models (ABMs). Designed as a standalone pip-installable package that can be embedded in any host application. Currently integrated with PhysiCell Studio.

## Installation

```bash
pip install -e .                    # core (CSV support only)
pip install -e ".[anndata]"         # + .h5ad support
pip install -e ".[seurat]"          # + .rds/.rda support (requires R + rpy2)
pip install -e ".[dev]"             # + test dependencies
```

## Quick Start

```python
import sys
from PyQt5.QtWidgets import QApplication

from biwt.gui.theme import apply_light_palette
from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, DomainSpec

domain = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500, units="micron")
biwt_input = BiwtInput(preferred_domain=domain)

def on_complete(result):
    # result.coordinates is a DataFrame with columns: x, y, z, type
    result.to_csv("config/cells.csv")

app = QApplication(sys.argv)
apply_light_palette(app) 

widget = create_biwt_widget(biwt_input, on_complete=on_complete)
widget.show()

sys.exit(app.exec_())
```

## Running Tests

```bash
PYTHONPATH=src python -m pytest tests/ -v
```

## Package Structure

```
src/biwt/
  types.py              — Public API: DomainSpec, BiwtInput, BiwtResult
  core/
    data_loader.py      — Unified loader (.h5ad, .rds, .csv) → BiwtData
    domain.py           — Domain inference + coordinate column detection
    positioning.py      — Coordinate scaling + build_ic_dataframe
    cell_types.py       — Name-matching heuristics
    parameters/
      cell_templates.py — 29 PhysiCell cell-type XML templates
      xml_defaults.py   — Default PhysiCell XML scaffold
  gui/
    walkthrough.py      — Session state machine + Qt widget + step logic
    widgets.py          — Shared Qt widgets
    windows/            — One file per walkthrough step
tests/
  test_session.py       — 43 tests covering session logic end-to-end
  fixtures/             — CSV test fixtures
```

## Key Design Decisions

- **No file I/O in BIWT.** The package returns `BiwtResult` in-memory; the host decides how to write.
- **Pure-Python session.** `WalkthroughSession` has no Qt dependencies. All Qt logic is in window classes.
- **Single source of truth for steps.** `_step_predicates(session)` defines step ordering. Tests import it directly.
- **CSV uses `type` header** (not `cell_type`) to match PhysiCell convention.
- **Domain units.** `DomainSpec.units` defaults to `"micron"` but supports other ABM frameworks.

## Implementation Status

### Completed

- [x] Data import: .h5ad, .rds/.rda/.rdata, .csv
- [x] Spatial coordinate detection (obsm, obs columns)
- [x] Pixel-coordinate fallback: recognize `imagecol`→x / `imagerow`→y (row-flipped) as a last-resort spatial source, used as-is with no unit conversion (data domain reported in `pixel` units)
- [x] Spatial synthesis from obs columns (x/y/z or imagerow/imagecol → obsm["spatial"]) for CSV and AnnData/R, so the dim-reduction plot offers a Spatial view
- [x] Domain inference with priority chain (preferred > data_range > default)
- [x] Domain mismatch: two-tier detection (classify_domain_mismatch: "outside" / "small" / None)
- [x] DomainEditorDialog auto-triggered at positions window open (not import time)
- [x] Context-sensitive mismatch header; no header for manual "Domain Settings…" open
- [x] domain_accepted flag prevents re-trigger on back/forward navigation
- [x] BiwtInput.domain_accepted + "Skip domain validation" checkbox bypass auto-check
- [x] Z-fields default to ±10 for 2D data in domain editor
- [x] DomainSpec units field (e.g. `pixel` for imagerow/imagecol data); no unit conversion — coordinates define the data domain as-is
- [x] "Auto-scale data to fill domain" toggle wired into positions step (scale-to-fill vs. raw extent, both centered); off = raw data extent
- [x] "Domain Settings…" button in positions plot window for manual domain editing
- [x] Spot deconvolution query and cell expansion
- [x] Cluster column selection
- [x] Spatial data query (use spatial coords or random placement)
- [x] Edit cell types (keep / merge / delete) with scatter plot and legend
- [x] Rename cell types with Studio name suggestions and duplicate blocking
- [x] Cell counts (data counts, confluence, total count modes)
- [x] Coordinate placement (spatial scaling, random placement)
- [x] 29 cell parameter templates with XML assembly
- [x] BiwtResult assembly (coordinates, cell_type_map, domain, XML)
- [x] Studio bridge (BiwtInput/BiwtResult, _biwt_complete callback)
- [x] Overwrite/Append/Browse/Cancel dialog for CSV output
- [x] Append handles extra columns in existing CSV
- [x] Session reset on reimport
- [x] `tomli` in core dependencies (fixes import crash on Python 3.9/3.10)
- [x] Step predicate extraction for testability
- [x] 57 passing tests

### In Progress

- [ ] End-to-end manual testing with Studio

### Remaining

- [x] pyproject.toml extras for anndata/seurat/dev dependencies
- [x] CI pipeline (GitHub Actions, Python 3.9–3.12)
- [ ] CI: R-dependent tests for `.rds` import (requires provisioning R on CI runners; seurat excluded from `dev` extra for now)
- [ ] User documentation / help text within wizard steps
- [ ] Substrate/gene expression pass-through (reserved fields in BiwtResult)
- [ ] Multi-library Visium support
- [ ] 3D spatial data support beyond z=0 padding

## Related Documents

- [PRD.md](PRD.md) — Product requirements (behavioral specs, acceptance criteria)
- [progress.md](progress.md) — Session decisions and reasoning
- [CLAUDE.md](CLAUDE.md) — Claude agent guide for this repo
