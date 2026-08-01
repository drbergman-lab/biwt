# BIWT — BioInformatics WalkThrough

A guided wizard for importing single-cell bioinformatics data and generating initial conditions for agent-based models (ABMs). Designed as a standalone pip-installable package that can be embedded in any host application. Currently integrated with PhysiCell Studio.

## Installation

```bash
pip install biwt                    # core (CSV support only)
pip install "biwt[anndata]"         # + .h5ad support
pip install "biwt[seurat]"          # + .rds/.rda support (also needs R — see below)
pip install "biwt[gui]"             # + PyQt5 walkthrough UI
pip install "biwt[all]"             # everything
```

Development install (from a clone):

```bash
pip install -e ".[dev]"             # editable + test dependencies
```

`.rds` / `.rda` import needs a working R with `Seurat` and `SingleCellExperiment` in addition
to the pip extra. See the
**[installation guide](https://drbergman-lab.github.io/biwt/getting-started/installation/)**
for the conda recipe and a
[troubleshooting guide](https://drbergman-lab.github.io/biwt/getting-started/troubleshooting/)
for the R stack.

## Documentation

Full docs: **[drbergman-lab.github.io/biwt](https://drbergman-lab.github.io/biwt/)** — user
guide for every wizard step, worked recipes for Visium / scRNA-seq / spot-deconvolution data,
the host-integration contract, and a generated API reference.

Build them locally with:

```bash
pip install -e ".[docs]"
mkdocs serve
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
  test_session.py       — 78 tests covering session logic end-to-end
  test_gui_smoke.py     — Headless Qt import-path and error-dialog tests
  test_positions_plot.py — Spatial placement / plot scaling tests
  fixtures/             — CSV test fixtures
docs/                   — MkDocs Material site (published to GitHub Pages)
  index.md
  getting-started/      — Install matrix, first walkthrough, R/Seurat troubleshooting
  guide/                — One page per wizard step, plus the domain editor
  recipes/              — Visium, non-spatial scRNA-seq, spot deconvolution
  integration/          — Host embedding: API contract + Studio bridge
  reference/            — mkdocstrings API reference
mkdocs.yml
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
- [x] Pixel-coordinate fallback: recognize `imagecol`→x / `imagerow`→y (row-flipped) as a last-resort spatial source; domain reported in generic `data units` (no inferred unit name)
- [x] Spatial synthesis from obs columns (x/y/z or imagerow/imagecol → obsm["spatial"]) for CSV and AnnData/R, so the dim-reduction plot offers a Spatial view
- [x] Domain inference with priority chain (preferred > data_range > default)
- [x] Domain mismatch: two-tier detection (classify_domain_mismatch: "outside" / "small" / None)
- [x] DomainEditorDialog auto-triggered at positions window open (not import time)
- [x] Context-sensitive mismatch header; no header for manual "Domain Settings…" open
- [x] domain_accepted flag prevents re-trigger on back/forward navigation
- [x] BiwtInput.domain_accepted + "Skip domain validation" checkbox bypass auto-check
- [x] Z-fields default to ±10 for 2D data in domain editor
- [x] Data-unit→host-unit scale factor in the domain editor: auto-detected Visium µm/pixel (`_extract_visium_microns_per_pixel`), editable, with dual data-units/host-units bounds columns synced by the factor and a reset-to-file button
- [x] Placement scales cells by the factor and centers them in the domain (`compute_spatial_placement`; `session.effective_scale()`) — uniform, aspect-preserving; the domain is an independent host-units container
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
- [x] `[project.urls]` metadata so the PyPI page links to the repo, docs, and issues
- [x] MkDocs Material documentation site published to GitHub Pages by `.github/workflows/docs.yml`
- [x] Docs: user guide (all wizard steps), recipes (Visium / non-spatial / spot deconvolution), host-integration guide, mkdocstrings API reference
- [x] `LoadError.docs_url`: environment-related import failures link to the setup docs from the "Import failed" dialog; file-related failures stay plain text. Missing dependencies point at the install page, broken R stacks at troubleshooting
- [x] 96 passing tests

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

- [Documentation site](https://drbergman-lab.github.io/biwt/) — user guide, recipes, integration guide, API reference (source in [docs/](docs/))
- [PRD.md](PRD.md) — Product requirements (behavioral specs, acceptance criteria)
- [progress.md](progress.md) — Session decisions and reasoning
- [CLAUDE.md](CLAUDE.md) — Claude agent guide for this repo
