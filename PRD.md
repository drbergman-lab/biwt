# BIWT Product Requirements Document

The BioInformatics WalkThrough (BIWT) is a guided wizard that imports single-cell bioinformatics data and produces PhysiCell-compatible initial conditions. It is designed as a standalone pip-installable package that can be embedded in any host application (currently: PhysiCell Studio).

---

## Terminology

- **BIWT** is the canonical name. `biwt` and `Biwt` are acceptable variants. Any other acronym (BAWT, VAWT, BAT, BWG) is a typo and should be corrected wherever found.
- **Host**: the application that embeds BIWT (currently: PhysiCell Studio). BIWT must function correctly with PhysiCell Studio as host and must remain host-agnostic at the API boundary (`BiwtInput` / `BiwtResult`).

---

## Target Users

BIWT is intended for academic researchers at all career stages — from high school students and undergraduates through PhD candidates, postdocs, and faculty. The UX assumes:

- A working understanding of PhysiCell and how agent-based simulations are configured.
- Familiarity with common bioinformatics analyses and their outputs (e.g., cell-type clustering, dimensionality reduction, spatial transcriptomics).
- No assumption of software engineering expertise; the wizard guides users step by step.

| Persona | Background | Primary need |
|---------|-----------|--------------|
| **Undergrad / early grad student** | Basic bioinformatics coursework; new to PhysiCell | Step-by-step guidance; clear error messages; sensible defaults at every step |
| **PhD candidate / postdoc** | Active bioinformatics analysis (Seurat, AnnData); moderate PhysiCell experience | Fast, repeatable import with control over cell-type mapping and parameter templates |
| **Faculty / power user** | Deep PhysiCell and bioinformatics expertise | Fine-grained control over domain, counts, coordinate scaling, and XML parameter blocks |

---

## Product Intent and Parity Contract

BIWT must be a seamless, pip-installable replacement for the legacy BIWT tab embedded in PhysiCell Studio, with identical or improved feature utility.

**Must preserve:**
- Studio integration entry point: the `--biwt` flag must continue to enable the BIWT tab in exactly the same way.
- Full feature parity: every feature present in the legacy BIWT implementation must be present in the new package.

**Acceptable changes for this release:**
- UI layout and visual design may differ from the legacy implementation.
- Step order may change as long as the overall outcome and user experience are equivalent.
- Validation may be made stricter than the legacy implementation.
- Performance may be slower than the legacy implementation as long as correctness is preserved.

**Not acceptable:**
- Removing or degrading any core feature of the legacy BIWT workflow.
- Changing the `--biwt` flag interface or the `_biwt_complete` callback contract in ways that require Studio source changes beyond the integration bridge in `bin/ics_tab.py`.

**Out of scope (this and next few releases):** Integration with ABM frameworks other than PhysiCell Studio.

---

## Future Architecture: Framework-Specific Packages

The long-term plan is to split `biwt` into:

- **`biwt`** (this package) — framework-agnostic core: data import, domain inference, cell-type editing, coordinate placement, the Qt walkthrough UI skeleton.
- **`biwt-physicell`** (future) — PhysiCell-specific layer: the 29 cell-parameter templates, PhysiCell XML assembly, `BiwtResult.cell_definitions_xml` population.
- **`biwt-<framework>`** (future) — analogous packages for other ABM frameworks.

The `BiwtInput.extra_cell_template_paths` mechanism (TOML files of `name = """<phenotype>...</phenotype>"""`) is the interim bridge: hosts or users can supply their own template databases without waiting for a `biwt-physicell` package. When `biwt-physicell` is released, the built-in templates will move there and the base `biwt` package will ship with no framework-coupled content.

---

## F1: Data Import

**One-line description:** Load single-cell data from common bioinformatics file formats.

**Behavioral specification:**
- When the user clicks "Import file...", a file dialog offers `.h5ad`, `.rds`, `.rda`, `.rdata`, `.csv`.
- When a `.h5ad` file is selected, BIWT reads it via `anndata.read_h5ad`.
- When a `.rds` / `.rda` / `.rdata` file is selected, BIWT reads it via `rpy2` + `anndata2ri`, supporting Seurat and SingleCellExperiment objects.
- When a `.csv` file is selected, BIWT reads it via `pandas.read_csv`.
- On import failure, a critical error dialog is shown with an actionable message.
- On successful import, the previous session state is fully reset.

**Acceptance criteria:**
- [x] All five extensions load without error on valid files.
- [x] Import failure shows a user-friendly error message.
- [x] Reimport resets all session state cleanly.

**Edge cases:**
- Missing optional dependencies (`anndata`, `rpy2`) produce an install hint, not a traceback.
- Empty CSV files produce a `LoadError`. *(not yet implemented — see [F1 open issue])*
- CSV files with spatial columns (x, y, z) synthesize `obsm["spatial"]` for downstream plotting.

---

## F2: Domain Inference and Mismatch Warning

**One-line description:** Determine spatial domain from data and warn if it conflicts with the host's domain.

**Behavioral specification:**
- When the host provides a preferred domain (via `BiwtInput.preferred_domain`), it always wins for placement.
- After import, BIWT independently computes the data's coordinate range and stores it as `session.data_domain`.
- The `DomainEditorDialog` is shown automatically when the **positions window first opens** (not at import time), using `classify_domain_mismatch()` to detect two-tier mismatches:
  - **"outside"**: any data boundary exceeds the preferred domain (cells would be excluded).
  - **"small"**: data fits inside but covers < 50% of any axis or < 50% of the 2-D area (cells would be sparse).
- The dialog shows a context-sensitive header and allows the user to:
  - Edit xmin/xmax, ymin/ymax, zmin/zmax bounds (auto-populated with data-inferred values; z defaults to ±10 for 2D data).
  - Set units (text field, default from preferred domain).
  - Toggle "auto-scale data to fill domain" (checked by default; preserves aspect ratio).
  - Reset to data domain or preferred domain via preset buttons.
- When OK is clicked, the edited domain becomes `session.user_domain` and overrides the preferred domain for placement.
- When Cancel is clicked, the preferred domain is used unchanged.
- `session.domain_accepted = True` is set after the dialog is dismissed (OK or Cancel) to prevent re-triggering on re-entry.
- `BiwtInput.domain_accepted = True` allows the host to pre-accept the domain and skip the auto-check entirely.
- A "Skip domain validation on import" checkbox on the home screen has the same effect.
- A **"Domain Settings…" button** in the positions plot window allows the user to open the domain editor at any time without a mismatch header.
- `DomainSpec.units` defaults to `"micron"` but can be set by the host for other ABM frameworks.
- The `auto_scale_to_domain` flag is carried forward to the positions step:
  - When True: data coordinates are scaled to fill the simulation domain (aspect ratio preserved); placement origin and size reflect the scaled bounding box centered in the domain.
  - When False: raw data coordinates are used; the bounding box is reported in original units and centered at the domain center.

**Acceptance criteria:**
- [x] `DomainSpec` has a `units` field (default `"micron"`).
- [x] `classify_domain_mismatch()` returns `"outside"`, `"small"`, or `None`.
- [x] `DomainEditorDialog` auto-triggered at positions window open on mismatch.
- [x] Context-sensitive header shown in auto-trigger; no header for manual "Domain Settings…" open.
- [x] `domain_accepted` flag prevents re-triggering on back/forward navigation.
- [x] `BiwtInput.domain_accepted` + "Skip domain validation" checkbox bypass auto-check.
- [x] Z-fields default to ±10 for 2D data in the domain editor.
- [x] User-edited domain stored in `session.user_domain`, overrides preferred.
- [x] Auto-scale checkbox stored in `session.auto_scale_to_domain`.
- [x] Positions step respects `auto_scale_to_domain` flag (scaled vs. raw bounding box centered in domain).
- [x] Tests cover classify_domain_mismatch, units, effective_domain override, auto_scale default, domain_accepted default.

**Edge cases:**
- Data with no spatial coordinates: no data domain to compute, no dialog.
- Data with `microns_per_pixel` (Visium): data domain is in converted microns.
- Default fallback domain (no spatial data): no dialog (source == "default").
- Auto-scale off: spatial plotter uses raw data bounding box (width/height = data extent) centered at domain center.

---

## F3: Spot Deconvolution Query

**One-line description:** Ask whether to use per-spot probability columns for cell-type assignment.

**Behavioral specification:**
- When the imported data has probability columns (e.g. `T_cell_probability`) AND has spatial coordinates, BIWT asks whether to perform spot deconvolution.
- When the user accepts, each spatial spot is expanded into individual cells proportional to the probability distribution.
- When the user declines, BIWT proceeds to the cluster column selector.
- This step is skipped entirely if the data lacks probability columns or spatial coordinates.

**Acceptance criteria:**
- [x] Step shown only when both probability columns and spatial data exist.
- [x] Accepting sets up deconvolution data structures.
- [x] Declining moves to cluster column selection.

---

## F4: Cluster Column Selection

**One-line description:** Let the user choose which metadata column contains cell-type labels.

**Behavioral specification:**
- When the user has not yet selected a column, a dropdown lists all columns in `obs`.
- The default cell-type column name can be pre-set from the launch widget.
- When a column is selected, BIWT extracts unique cell types and per-cell labels.
- A "Go Back" button is available if the spot deconvolution query was shown.

**Acceptance criteria:**
- [x] All obs columns listed in the dropdown.
- [x] Selection populates `cell_types_list_original` and `cell_types_original`.
- [x] Go Back available after spot deconv query.

---

## F5: Spatial Data Query

**One-line description:** Ask whether to use the data's spatial coordinates for cell placement.

**Behavioral specification:**
- When the data has spatial coordinates, BIWT asks whether to use them.
- Choosing "yes" means cells are placed at their data coordinates (scaled to domain).
- Choosing "no" means cells are placed randomly within the domain.
- This step is skipped when data has no spatial information.

**Acceptance criteria:**
- [x] Step shown only when `data.has_spatial` is True.
- [x] Choice is recorded in `session.use_spatial_data`.

---

## F6: Edit Cell Types (Keep / Merge / Delete)

**One-line description:** Allow the user to keep, merge, or delete each cell type from the imported data.

**Behavioral specification:**
- Each cell type is shown with Keep/Merge/Delete options.
- Merging combines two or more types into one (the merge target).
- Deleting removes a type from the output entirely.
- A scatter plot of spatial coordinates (colored by type) is shown when spatial data exists.
- A "Show Legend" button opens a popup legend for the scatter plot.
- Cell types are displayed in alphabetical order.
- When a merge target is left as the sole partner, it auto-dissolves back to "keep".

**Acceptance criteria:**
- [x] All three operations (keep, merge, delete) correctly modify intermediate types.
- [x] Spatial scatter plot shown when spatial data exists.
- [x] Legend popup works.
- [x] Alphabetical ordering.

**Edge cases:**
- Deleting all cell types: blocked (at least one must be kept).
- Merging with only one partner: dissolves back to keep.

---

## F7: Rename Cell Types

**One-line description:** Rename each intermediate cell type before output.

**Behavioral specification:**
- Each intermediate cell type gets a text field pre-populated with the first original name.
- If Studio cell type names were provided, placeholder text suggests the closest match.
- Exact duplicate names are blocked with a warning (case-sensitive).

**Acceptance criteria:**
- [x] Pre-populated with original names.
- [x] Studio name suggestions shown as placeholder text.
- [x] Duplicate names blocked.

**Edge cases:**
- Names that differ only by case (e.g. "CD8" vs "cd8") are allowed (PhysiCell treats them as distinct).

---

## F8: Cell Counts

**One-line description:** Let the user specify how many cells of each type to place.

**Behavioral specification:**
- Shown only when NOT using spatial data (spatial data determines counts from the data itself).
- Four modes: (1) use data counts as-is, (2) proportional to the counts data, (3) specify by confluence percentage, (4) specify by total cell count.
- Confluence mode pre-populates from current counts.
- Zero-count types are blocked with a warning.

**Acceptance criteria:**
- [x] Step skipped when using spatial data.
- [x] All four modes produce valid counts.
- [x] Zero counts blocked.
- [x] Confluence fields auto-populated.

---

## F9: Positions (Coordinate Placement)

**One-line description:** Place cells in the simulation domain using specified or data-derived coordinates.

**Behavioral specification:**
- When using spatial data: scales data coordinates to fit the simulation domain.
- When not using spatial data: distributes cells randomly within the domain.
- Shows a preview plot of placed cells.

**Acceptance criteria:**
- [x] Spatial placement preserves relative cell positions.
- [x] Random placement respects domain boundaries.
- [x] Preview plot displayed.

---

## F10: Load Cell Parameters

**One-line description:** Assign PhysiCell phenotype parameters to each cell type.

**Behavioral specification:**
- Each cell type can be assigned a parameter template from the 29 built-in templates.
- Templates are PhysiCell XML phenotype blocks (motility, mechanics, secretion, etc.).
- Selected templates are stored in `session.cell_definitions_registry`.

**Acceptance criteria:**
- [x] 29 cell templates available.
- [x] Template assignment stored per cell type.

---

## F11: Result Assembly and Return

**One-line description:** Assemble final output and return to the host application.

**Behavioral specification:**
- BIWT assembles a `BiwtResult` containing:
  - `coordinates`: DataFrame with columns `["x", "y", "z", "type"]`.
  - `cell_type_map`: dict mapping original labels to final names (or `None` for deleted types).
  - `domain_used`: the DomainSpec used for placement.
  - `cell_definitions_xml`: optional serialized PhysiCell cell-defs XML.
- BIWT never writes to disk. The host decides how to persist the result.
- The `on_complete` callback is invoked with the `BiwtResult`.

**Acceptance criteria:**
- [x] `BiwtResult.coordinates` has correct columns.
- [x] `BiwtResult.to_csv()` writes with `type` header (not `cell_type`).
- [x] No file I/O in BIWT; host owns writing.
- [x] XML assembly includes all selected cell templates.

---

## F12: Studio Integration (Host Bridge)

**One-line description:** Studio embeds BIWT and handles file output from the result.

**Behavioral specification:**
- When `_biwt_complete` is called with a `BiwtResult`:
  - If the target CSV already exists, Studio shows an Overwrite / Append / Browse / Cancel dialog.
  - Overwrite: writes BIWT coordinates, replacing the file.
  - Append: reads existing CSV, concatenates BIWT rows (extra columns in existing file become empty for appended rows).
  - Browse: lets the user pick a new save location.
  - Cancel: discards the result.
- If `cell_definitions_xml` is present, Studio offers to save it as a new config file.

**Acceptance criteria:**
- [x] Overwrite/Append/Browse/Cancel dialog shown when file exists.
- [x] Append preserves extra columns from existing CSV.
- [x] Cell definitions XML save dialog works.
- [ ] Integration tested end-to-end with Studio (manual test).

---

## Step Ordering (Single Source of Truth)

The walkthrough step sequence is defined in `_step_predicates(session)` in `walkthrough.py`:

| # | Step | Condition to show |
|---|------|-------------------|
| 1 | SpotDeconvQuery | Data has probability columns AND spatial coordinates, not yet asked |
| 2 | ClusterColumn | No column selected and spot deconv not chosen |
| 3 | SpatialQuery | Data has spatial coordinates, not yet answered |
| 4 | EditCellTypes | Cell type edit dict not yet built |
| 5 | RenameCellTypes | Final names not yet assigned |
| 6 | CellCounts | Not using spatial data AND counts not confirmed |
| 7 | Positions | Positions not yet set |
| 8 | LoadCellParameters | Parameters not yet loaded |

After all predicates are False, `_finish()` assembles the result and calls `on_complete`.

---

## Error and Recovery Policy

When BIWT cannot complete a step:
- A clear, modal warning dialog is shown containing: (1) what failed, (2) why it failed, and (3) how to fix it.
- If the failure is recoverable (e.g., bad file format, missing optional dependency), the user remains in the wizard at the current step.
- If session state is unrecoverable, the wizard is closed and control returns to the host application.
- Missing optional dependencies (`anndata`, `rpy2`) must produce an actionable install hint (e.g., `pip install biwt[anndata]`) rather than a raw traceback.

---

## Packaging and Environment

- Python >= 3.9 required.
- `anndata >= 0.12.2` required for `.h5ad` support (optional pip extra: `biwt[anndata]`).
- `rpy2` + `anndata2ri` required for R object support (optional pip extra: `biwt[seurat]`).
- Performance targets are non-blocking for this release; no specific throughput constraints are defined.

---

## Release Gates (Definition of Done)

All of the following must be satisfied before a release is published:

1. Studio launches successfully with the `--biwt` flag and the BIWT tab opens without error.
2. All BIWT unit tests pass: `PYTHONPATH=src python -m pytest tests/ -v` from `biwt/`.
3. A manual end-to-end run from data import through to CSV output completes without error.
4. A legacy behavior parity checklist is verified against the original BIWT implementation.
5. No regressions in non-BIWT Studio workflows (Studio operates normally without `--biwt`).
6. Documentation updated: this PRD, `biwt/README.md`, and `biwt/progress.md`.

---

## Test Fixtures

The following fixture files are required for end-to-end and integration testing:

| File | Format | Purpose |
|------|--------|---------|
| `tests/fixtures/cells.csv` | CSV | Non-spatial cell types; baseline import and walkthrough test |
| `tests/fixtures/spatial_cells.csv` | CSV | Cells with `x`/`y`/`z` columns; spatial placement test |
| `tests/fixtures/test_adata.h5ad` | AnnData `.h5ad` | Full walkthrough with spatial coordinates and probability columns |
| `tests/fixtures/test_object.rds` | R `.rds` | One of: Seurat, SingleCellExperiment, or SpatialExperiment object |

CSV fixtures should reside in `biwt/tests/fixtures/`. The `.h5ad` and `.rds` fixtures are to be created programmatically if possible; otherwise provided manually before release.
