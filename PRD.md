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
- When a `.rds` / `.rda` / `.rdata` file is selected, BIWT reads it via `rpy2` + `anndata2ri`, supporting Seurat, SingleCellExperiment, and SpatialExperiment objects.
- When a `.csv` file is selected, BIWT reads it via `pandas.read_csv`.
- On import failure, a critical error dialog is shown with an actionable message.
- When the failure is fixed by changing the environment rather than the file, the dialog additionally shows a clickable link to the setup docs. `LoadError.docs_url` carries the pointer (`None` when absent), so the decision lives at the raise site in `core/data_loader.py` and any host — GUI, notebook, CLI — can surface it. Two targets, matching the two fixes: `INSTALL_DOCS_URL` for dependencies that were never installed (missing `anndata`, missing `rpy2`/`anndata2ri`), and `TROUBLESHOOTING_DOCS_URL` for an R stack that is present but misbehaving (`anndata2ri` activation failure from the 2.0+ API removal; R-object read failures from a missing `SeuratObject` or an ABI-mismatched R). It is **not** set for unsupported extensions, malformed CSVs, or unsupported R classes.
- On successful import, the previous session state is fully reset.

**Acceptance criteria:**
- [x] All five extensions load without error on valid files.
- [x] Import failure shows a user-friendly error message.
- [x] Environment-related import failures link to the installation docs; file-related failures do not.
- [x] Reimport resets all session state cleanly.

**Edge cases:**
- Missing optional dependencies (`anndata`, `rpy2`) produce an install hint, not a traceback.
- Empty CSV files produce a `LoadError`. *(not yet implemented — see [F1 open issue])*
- CSV files with spatial columns (x, y, z) synthesize `obsm["spatial"]` for downstream plotting.
- Spatial coordinates are resolved from obs/CSV columns in priority order (`resolve_obs_coord_cols`): `x`/`y`/`z` candidates first, then — as a last resort — 10x Visium pixel columns `imagecol`/`imagerow`. `imagecol` maps to x and `imagerow` maps to y; because image rows increase downward, `imagerow` is flipped (`y = rowmax - imagerow`) to give a y-up coordinate system. The data domain is reported in a generic `"data unit"` — BIWT infers no unit name from the data. Like every other unit name, it is stored singular (`DomainSpec.units` holds `"micron"`, not `"microns"`), so it reads correctly both as a bounds-column header and as the denominator of the scale-factor label. A data→host-units **scale factor** (see F2) converts the coordinates, applied visibly in the domain editor; the only auto-detected factor is 10x Visium's µm/pixel (`BiwtData.microns_per_data_unit`).
- When spatial coordinates are found in obs columns (rather than an `obsm` array), `obsm["spatial"]` is synthesized from them (with the pixel flip applied) for both CSV and AnnData/R, so the EditCellTypes dim-reduction plotter offers a Spatial view.

---

## F2: Domain Inference and Mismatch Warning

**One-line description:** Determine spatial domain from data and warn if it conflicts with the host's domain.

**Behavioral specification:**
- When the host provides a preferred domain (via `BiwtInput.preferred_domain`), it always wins for placement.
- After import, BIWT independently computes the data's coordinate range and stores it as `session.data_domain`.
- The `DomainEditorDialog` is shown automatically when the **positions window first opens** (not at import time), using `classify_domain_mismatch()` to detect two-tier mismatches:
  - **"outside"**: any data boundary exceeds the preferred domain (cells would be excluded).
  - **"small"**: data fits inside but covers < 50% of any axis or < 50% of the 2-D area (cells would be sparse).
- The dialog edits the domain in the **host's units** (`preferred_domain.units`, e.g. `micron`) and exposes a data-unit→host-unit **scale factor**:
  - A **`{host-unit}/data unit`** field (e.g. `micron/data unit`) — ratio notation, so the denominator stays singular whatever the host unit is — seeded from `BiwtData.microns_per_data_unit` (Visium), or a `"none found in file"` placeholder. A reset button (enabled only when the field differs from the file value) restores the file value.
  - **Two bounds columns** shown side by side, headed with the two unit names — `{data unit}` and `{host unit}` — kept in sync by the factor (edit either, the other updates via ×/÷ F). With no factor, the data-units column is disabled and only the host-units column (the stored domain) is editable.
  - **"Use Data Domain"**: fills data-units = raw data bounds and host-units = raw × factor (or, with no factor, host-units = raw). **"Use {host} Domain"**: fills host-units = the host bounds verbatim. Z is host-units only and never scaled.
  - **"Apply scale factor to data"** checkbox (on by default) — when on, placement scales the cells by the factor; when off, cells are placed at their raw extent (centered). It never disables the factor field or the column sync.
- When OK is clicked, the **host-units** bounds become `session.user_domain`; the factor and checkbox persist to `session.scale_factor` / `session.apply_scale`.
- When Cancel is clicked, the preferred domain is used unchanged.
- `session.domain_accepted`, `BiwtInput.domain_accepted`, the "Skip domain validation" checkbox, and the "Domain Settings…" button behave as before.
- **Placement (`_default_spatial_pars` via `compute_spatial_placement`):** cells are scaled by `session.effective_scale()` (`scale_factor` when `apply_scale` and a positive factor exist, else `1.0`) and **centered** in the domain — a pure uniform scale + translate. Aspect ratio is always preserved; editing the domain resizes the container without changing the cell scale. On a domain change the spatial default is recomputed and any user edit is preserved as an undo step (`_apply_domain_change_and_redraw`).

**Acceptance criteria:**
- [x] `classify_domain_mismatch()` returns `"outside"`, `"small"`, or `None`; auto-triggered at positions window open on mismatch (data extent compared in host units).
- [x] Data domain reported in a generic singular `"data unit"` (no inferred unit name); imagerow/imagecol still recognized + y-flipped.
- [x] Visium µm/pixel factor extracted (`_extract_visium_microns_per_pixel`) into `BiwtData.microns_per_data_unit`; CSV/R → `None`.
- [x] Domain editor: factor field (placeholder when none) + reset-to-file button; dual data-units/host-units columns synced by the factor; disabled data-units column when no factor.
- [x] `session.effective_scale()` truth table (factor × apply); `compute_spatial_placement` scales data by F and centers (uniform → exact F× when domain = data×F).
- [x] User-edited **host-units** domain stored in `session.user_domain`; `scale_factor`/`apply_scale` persisted.
- [x] Tests cover extractor, `_scale_domain`, units label, `effective_scale`, and `compute_spatial_placement` invariant.

**Edge cases:**
- No factor (CSV / imagerow/imagecol / non-Visium): data-units column disabled; work in host units; placement scale `1.0` (raw extent, centered). Out-of-domain cells → existing `_check_out_of_bounds_cells` warning/undo.
- Domain edited to a different aspect than the data: cells still uniform-scale by F and center (no distortion); they simply do not fill the box.
- Default fallback domain (no spatial data): no dialog (source == "default").
- **TODO:** when host units ≠ microns (e.g. nm), the auto-seeded Visium factor (µm/pixel) must be converted to host-units-per-pixel (×1000 for nm). For now it is seeded as-is; the user can override.

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
- A count of zero is **allowed**, and means "define this cell type in the output config but place none of it". The type keeps its `<cell_definition>` — definitions are driven by `cell_types_list_final`, never by counts — and contributes no rows to the coordinates DataFrame. Deleting the type at the edit step (F6) remains the way to remove it from the config entirely. There is no floor on the total either: every type may be zero, yielding a definitions-only config and a header-only CSV.
- A zero-count type is treated as already placed at the positions step (F9): its checkbox is disabled so it cannot be selected and does not hold up the Continue gate.
- Proportional mode leaves the other types untouched when the edited type's share of the data is zero, rather than scaling them all by a zero multiplier.

**Acceptance criteria:**
- [x] Step skipped when using spatial data.
- [x] All four modes produce valid counts.
- [x] Zero counts allowed; the type is absent from `BiwtResult.coordinates` but still present in `cell_definitions_xml`.
- [x] All-zero counts produce an empty coordinates DataFrame that keeps `float64` x/y/z dtypes.
- [x] A zero-count type does not block Continue at the positions step, in 2D or 3D.
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
- Failures whose fix is an installation or environment change must also carry a link to the installation docs (`LoadError.docs_url`); failures about the file itself must not, so the pointer stays meaningful.

---

## Packaging and Environment

- Python >= 3.9 required.
- `anndata >= 0.12.2` required for `.h5ad` support (optional pip extra: `biwt[anndata]`).
- `rpy2` + `anndata2ri` required for R object support (optional pip extra: `biwt[seurat]`), plus a working R with `Seurat` and `SingleCellExperiment`. Setup recipe and troubleshooting live in the docs site (`docs/getting-started/`).
- `[project.urls]` in `pyproject.toml` publishes Homepage / Repository / Documentation / Issues so the PyPI page links back to the repo and docs.
- Documentation is a MkDocs Material site under `docs/`, built and deployed to GitHub Pages by `.github/workflows/docs.yml` on push to `main`. The build runs with `--strict`, so a broken internal link or a nav entry pointing at a missing file fails CI. The API reference is generated from docstrings by mkdocstrings, which means docstring formatting errors are build failures too. Optional pip extra: `biwt[docs]`.
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
