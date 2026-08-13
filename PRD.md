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
- **`biwt-physicell`** (future) — a PhysiCell-specific layer, should one prove useful: curated template libraries, config assembly, framework-aware validation.
- **`biwt-<framework>`** (future) — analogous packages for other ABM frameworks.

The framework-coupled content is **already out** of this package: BIWT ships no cell-parameter templates and generates no XML. Templates arrive as opaque TOML content through `BiwtInput.cell_template_paths` (from the host) or the cell-parameters step's file loader (from the user), and come back as `BiwtResult.cell_templates` for the host to assemble. PhysiCell Studio owns the PhysiCell templates and the config assembly. A future `biwt-physicell` would be a convenience layer over that boundary, not a prerequisite for it.

---

## F1: Data Import

**One-line description:** Load single-cell data from common bioinformatics file formats.

**Behavioral specification:**
- When the user clicks "Import file...", a file dialog offers `.h5ad`, `.rds`, `.rda`, `.rdata`, `.csv`. Dropping a single file of one of those extensions onto the landing screen's drop area takes the same path; anything else is ignored rather than reported, since a rejected drag never highlights the target in the first place.
- The landing screen shows a chip per supported format with its **availability in this environment**, probed via `importlib.util.find_spec` (no import, no startup cost) by `core.data_loader.supported_formats`. An unavailable format's tooltip names the missing module, the pip extra that installs it, and the install docs. Without this, a missing optional dependency is discovered only by picking a file and reading the error dialog.
- The landing screen's **Shortcuts** group holds the two settings that pre-answer a later step — the cell-type column hint and the domain check — each captioned with what it skips. They are grouped because as loose controls they read as stray settings and their effect is invisible: the column hint silently skips a whole step.
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
- Spatial coordinates are resolved from obs/CSV columns in priority order (`resolve_obs_coord_cols`): `x`/`y`/`z` candidates first, then — as a last resort — 10x Visium pixel columns `imagecol`/`imagerow`. `imagecol` maps to x and `imagerow` maps to y; because image rows increase downward, `imagerow` is flipped (`y = rowmax - imagerow`) to give a y-up coordinate system. The data domain is reported in a generic `"data unit"` — BIWT infers no unit name from the data. Like every other unit name, it is stored singular (`DomainSpec.units` holds `"micron"`, not `"microns"`), so it reads correctly both as a bounds-column header and as the denominator of the scale-factor label. A data→host-units **scale factor** (see F2) converts the coordinates, applied visibly in the domain editor; the only auto-detected factor is 10x Visium's µm/pixel (`BiwtData.host_units_per_data_unit`).
- When spatial coordinates are found in obs columns (rather than an `obsm` array), `obsm["spatial"]` is synthesized from them (with the pixel flip applied) for both CSV and AnnData/R, so the EditCellTypes dim-reduction plotter offers a Spatial view.

---

## F2: Domain Inference and Mismatch Warning

**One-line description:** Determine spatial domain from data and warn if it conflicts with the host's domain.

**Behavioral specification:**
- The host's preferred domain (`BiwtInput.preferred_domain`) always wins for placement. The field defaults to `DomainSpec.default()` (±500 µm × ±10 µm), the same fallback `infer_domain` already used, so a host may omit it and `BiwtInput()` is valid.
- **The host's input is resolved at the start of each run and frozen for it.** `create_biwt_widget` accepts a `BiwtInput` *or* a zero-argument callable returning one (`BiwtInputSource`), because a host that embeds the widget for the life of the application would otherwise be pinned to whatever its domain and cell definitions were when the tab was built. BIWT calls the provider at exactly two points — widget construction, which only seeds the domain-check checkbox, and each successful import — and holds a `snapshot()` of the result: `preferred_domain` and both list fields are copied, so a host mutating its own objects cannot rewrite a domain cells were already placed into. A provider that raises or returns the wrong type leaves the previous context in place and logs.
- There is exactly **one** name for the host's domain on the session (`preferred_domain`); `effective_domain` is `user_domain or preferred_domain`. A second latched copy is what allowed one `DomainEditorDialog` invocation to compute its mismatch warning against one box while resolving "Use <host> Domain" and `_source_of` against another.
- A host edit *during* a run is deliberately invisible until the next import, and `domain_accepted` is read only at construction (the checkbox is on screen and authoritative from then on).
- After import, BIWT independently computes the data's coordinate range and stores it as `session.data_domain`.
- The `DomainEditorDialog` is shown automatically when the **positions window first opens** (not at import time), using `classify_domain_mismatch()` to detect two-tier mismatches:
  - **"outside"**: any data boundary exceeds the preferred domain (cells would be excluded).
  - **"small"**: data fits inside but covers < 50% of any axis or < 50% of the 2-D area (cells would be sparse).
- The dialog edits the domain in the **host's units** (`preferred_domain.units`, e.g. `micron`) and exposes a data-unit→host-unit **scale factor**:
  - A **`{host-unit}/data unit`** field (e.g. `micron/data unit`) — ratio notation, so the denominator stays singular whatever the host unit is — seeded from `BiwtData.host_units_per_data_unit` (Visium). A reset (↺) button restores the file value and is enabled whenever the field differs from it, **including when the field is empty**.
  - **An empty, unparseable, or non-positive factor means no factor** — not "fall back to the file value". Falling back made a file factor unclearable: ↺ was the only route to it, and ↺ then greyed out because the empty field already matched it, so a blank field, live mirrors and a disabled restore button all disagreed about what was in effect. The placeholder states what empty means and how to undo it: `none — ↺ restores {file value}`, or `none found in file` when there is nothing to restore.
  - **Every data-units cell is re-derived when the factor changes**, extents included. Syncing only the bounds left the size mirrors showing a span computed with the previous factor. When the factor is unusable the mirrors are **cleared**, not merely disabled — a disabled field holding its last value advertises a conversion that no longer applies.
  - **An axis-major grid**: one row per axis (`X (width)`, `Y (height)`, `Z (depth)`) against three ruled columns — **min**, **max**, **size** — so an axis' extent sits beside the two bounds that span it rather than in a separate block below them. Vertical and horizontal rules delimit the tracks; six paired fields per row cannot be delimited by whitespace alone.
  - **Each value appears in both unit systems within its own cell**: the host-units field leads (it is the stored domain and what placement consumes) and its data-units mirror follows in parentheses, kept in sync by the factor (edit either, the other updates via ×/÷ F). With no factor every parenthesized field is disabled, and only the host-units fields are editable.
  - **"Use Data Domain"**: fills data-units = raw data bounds and host-units = raw × factor (or, with no factor, host-units = raw). **"Use {host} Domain"**: fills host-units = the host bounds verbatim. Z is host-units only and never scaled.
  - **"Apply scale factor to data"** checkbox (on by default) — when on, placement scales the cells by the factor; when off, cells are placed at their raw extent (centered). It never disables the factor field or the column sync.
  - **The size column** (width / height / depth) is two-way with the bounds in **either** unit system: a bound edit re-derives the extent, and an extent edit moves that axis' **maximum**, anchoring the minimum (`x = [-300, 500]`, width set to 1000 → `[-300, 700]`). Only one bound moves, so a minimum and an extent can be set independently; other axes are untouched. A data-units extent edit is converted to host units and routed through the same rule, so the anchoring behavior has one implementation and cannot drift between the columns.
  - **Z carries the same cells as x and y but they are inert** on the data-units side: the factor converts a measurement in data units and z is a slab depth BIWT supplies, so there is nothing to convert. The widgets exist so the row reads uniformly and so enabling them later is a matter of flipping `factor_scaled` on the axis record; they render greyed rather than empty-and-white, which would read as editable.
  - **One axis table (`_DOMAIN_AXES`) is the single source of truth** for the layout, the extent derivation, and the bounds validation, so a bound and its extent cannot disagree about which pair of numbers they span.
- **OK is gated on a usable domain.** It is disabled unless all six bounds parse as numbers and `xmin < xmax`, `ymin < ymax`, `zmin < zmax`; equal bounds are invalid, since a zero-width axis divides by zero in the placement scaling. Offending fields are highlighted. Cancel is never gated. Because OK is gated, `result()` no longer coerces an unparseable field to `0.0` — it raises instead.
- `DomainSpec.source` takes one of four values, named by `types.DomainSource`: `host`, `data`, `user`, `default`. Three answers matter to a host — its domain, the data's, or the user's — and `default` is the fourth because "nobody supplied one" is neither, and it also marks a data domain as not real, which is how the positions step knows there is no mismatch worth raising. The earlier vocabulary (`preferred` / `anndata_metadata` / `data_range` / `user_edited` / `default`) distinguished *how* a data domain was found, which nothing ever branched on.
- The accepted domain's `source` is **derived from the bounds**, not asserted: `host` if they equal the domain the host passed, `data` if they equal the data extent in host units, else `user`. Stamping `user_edited` unconditionally made the field useless — a host is told to check `source != host` to see whether its own domain survived, and the answer was always yes. Where the two coincide, `host` wins: the host's domain did survive.
- The dialog's initial fill is the caller's choice (`initial_preset`), taken from the session: the data extent when the data's own coordinates are in use, the host's domain otherwise. A revisit always shows the domain currently in force. The data extent is only a useful starting point when the data is what positions the cells.
- When OK is clicked, the **host-units** bounds become `session.user_domain`; the factor and checkbox persist to `session.scale_factor` / `session.apply_scale`.
- When Cancel is clicked, nothing is written: whatever domain was already in effect stays — the host's on first open, a previous user edit thereafter.
- `BiwtInput.domain_accepted` **seeds** the "Skip domain validation" checkbox rather than overriding it; the checkbox alone determines `session.domain_accepted`, so the user can turn validation back on. The "Domain Settings…" button behaves as before.
- **Placement (`_default_spatial_pars` via `compute_spatial_placement`):** cells are scaled by `session.effective_scale()` (`scale_factor` when `apply_scale` and a positive factor exist, else `1.0`) and **centered** in the domain — a pure uniform scale + translate. Aspect ratio is always preserved; editing the domain resizes the container without changing the cell scale. On a domain change the spatial default is recomputed and any user edit is preserved as an undo step (`_apply_domain_change_and_redraw`).

**Acceptance criteria:**
- [x] `classify_domain_mismatch()` returns `"outside"`, `"small"`, or `None`; auto-triggered at positions window open on mismatch (data extent compared in host units).
- [x] Data domain reported in a generic singular `"data unit"` (no inferred unit name); imagerow/imagecol still recognized + y-flipped.
- [x] Visium µm/pixel factor extracted (`_extract_visium_microns_per_pixel`) into `BiwtData.host_units_per_data_unit`; CSV/R → `None`. The field name is host-neutral; the value it carries is µm/pixel, so it is only literally "host units" for a host measuring in microns.
- [x] Domain editor: factor field (placeholder when none) + reset-to-file button; host-units values paired with parenthesized data-units mirrors synced by the factor; parenthesized fields disabled when no factor.
- [x] Axis-major grid: each extent shares a grid row with its own axis' bounds (asserted, so it cannot silently regress); each axis gets its own row; `_XY` is derived from `_DOMAIN_AXES` rather than spelled out.
- [x] Data-units extent mirrors derived on open and after a bound edit; editing one moves that axis' maximum without rewriting the field being typed in; other axes untouched.
- [x] Z's data-units cells exist, stay disabled and empty even with a factor, and carry a tooltip explaining why.
- [x] A factor change re-derives the bound **and** size mirrors; an empty / unparseable / non-positive factor yields `None`, clears and disables every mirror, leaves the host bounds and the OK gate untouched, and is reported as `None` by `result()`.
- [x] ↺ is enabled on an empty field and restores the file value; the placeholder names the restore path when a file factor exists and says `none found in file` when it does not.
- [x] `session.effective_scale()` truth table (factor × apply); `compute_spatial_placement` scales data by F and centers (uniform → exact F× when domain = data×F).
- [x] User-edited **host-units** domain stored in `session.user_domain`; `scale_factor`/`apply_scale` persisted.
- [x] Tests cover extractor, `_scale_domain`, units label, `effective_scale`, and `compute_spatial_placement` invariant.
- [x] OK disabled on an inverted, zero-width, or unparseable bound, per axis, with the offending fields flagged; Cancel always enabled.
- [x] Extent rows derive from the bounds; editing one moves that axis' maximum and anchors its minimum, leaving the other axes unaffected.
- [x] `BiwtInput.domain_accepted` seeds the checkbox and the user can override it either way; `BiwtInput()` constructs with the default domain.
- [x] A host value changed after the widget was built reaches the next run: the provider is called at each import, and the resolved context does not move for the duration of that run.
- [x] `session.effective_domain is session.preferred_domain` while the user has not edited the domain; no third domain field exists.
- [x] A provider that raises, or returns something other than a `BiwtInput`, does not fail the import.

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
- [x] Per-spot cells are apportioned by `apportion_spot_cells` (`core/positioning.py`): equal-proportions (Huntington–Hill) with a **shifted divisor**, so the first cell is contested like any other and a trivially-probable type wins none. Scale-invariant, so filtering the mixture to the kept types needs no renormalizing. **Ties are broken at random** — breaking them by dict order awarded the surplus to the first-listed `obs` column in every spot, skewing the whole tissue.
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
- Cell types are displayed in alphabetical order, case-insensitively (`AaBbCc`, not `ABCabc`) — see *Displaying Cell-Type Names*.
- When a merge group is left with a single member, it auto-dissolves back to "keep" — a group of one is not a merge.
- A merged type's checkbox is **disabled** until its Keep button pulls it back out, so a type can never be in two groups at once and nothing has to reconcile that case.
- Group membership is tracked as window state (`_merge_group`: cell type → group id), **not** read back from the checkbox label. It cannot be derived from `cell_type_dict_on_edit`: a group's first member maps to itself, which is byte-for-byte what a kept type looks like. The label showing the group is display only.

**Acceptance criteria:**
- [x] All three operations (keep, merge, delete) correctly modify intermediate types.
- [x] A group reduced to one member dissolves; a merged type stays locked until Keep releases it.
- [x] No behavior is driven by widget text.
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
- A count of zero is **allowed**, and means "define this cell type in the output config but place none of it". The type still reaches the host — definitions are driven by `cell_types_list_final`, never by counts — and contributes no rows to the coordinates DataFrame. Deleting the type at the edit step (F6) remains the way to remove it from the config entirely. There is no floor on the total either: every type may be zero, yielding a definitions-only config and a header-only CSV.
- A zero-count type is treated as already placed at the positions step (F9): its checkbox is disabled so it cannot be selected and does not hold up the Continue gate.
- Proportional mode leaves the other types untouched when the edited type's share of the data is zero, rather than scaling them all by a zero multiplier.

**Acceptance criteria:**
- [x] Step skipped when using spatial data.
- [x] All four modes produce valid counts.
- [x] Zero counts allowed; the type is absent from `BiwtResult.coordinates` but still reaches the host in `cell_type_map` and `cell_templates`.
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

**One-line description:** Assign each cell type a parameter template, or none.

**Behavioral specification:**
- BIWT ships **no** templates. The library offered is the union of the TOML files in `BiwtInput.cell_template_paths` and any the user loads at this step via **Add templates from file…**.
- A template file maps `template_name = "content"`. The content is **opaque**: read as text, never parsed, validated or wrapped, and returned to the host verbatim. A non-string value (a `[section]` header, a number) is rejected with a message naming the key, since the content would otherwise fail in the host long after the file left sight.
- Template identity is `(name, path)`, so identically named templates from two files coexist. Entries show the bare name while one file is loaded, and are tagged with the shortest distinguishing path suffix once two or more are — with several libraries in play, provenance matters even for a unique name. A closed combo box displays only the current *item's* text, never the group header it sat under, so under **By Source** the popup keeps bare names while the box paints the qualified label itself — `gui.widgets.RelabelledComboBox` overrides `paintEvent` for that. Neither the item text nor the model can carry the difference: one model is shared by every dropdown. The two halves are laid out rather than concatenated — template name left, source file right-aligned and muted, so sources align down the column — and when the box is too narrow for both, the **source is dropped rather than truncated**: the name identifies the choice, a half-elided path qualifies nothing. `text_layout(width)` is a pure function so that rule is tested without pixels.
- Every dropdown offers **(none)** as its first row in both modes. A **Skip** button unassigns every type and continues. Neither the step nor any individual assignment is ever required; nothing blocks Continue.
- Default per type: a template whose name matches the type (see F13), else one literally named `default` if the library has one, else `(none)`. Where a name exists in several files, the path-sorted first wins, so the pre-selection does not depend on load order or display mode.
- Template files are added by dialog (multi-select) or by dropping `.toml` files on the window, and both routes go through one code path that loads every file and then re-matches **once**, so an untouched cell type matches against the library as it finally stands rather than being decided by whichever file was read first. A drop only ever carries a path on the machine running BIWT, so it is an accelerator and never the only route: in a streamed remote session (a Galaxy interactive tool, say) no drop arrives and the file dialog browses the server's filesystem — there the host should stage the file and pass it in `cell_template_paths`.
- Template files can be added **and removed** at this step, the host's own library included; the library it presents is a starting point rather than a fixture. The set of files in play is **session state** (`template_library_paths`), seeded once from `BiwtInput.cell_template_paths`: loading a library is an action, not an answer to a step, so revisiting an earlier step must not undo it. It is therefore absent from `_STEP_FIELDS`, and only *Remove templates from file…* takes a file out. Files are re-read on each rebuild, so an edit on disk is picked up and a file that has become unreadable drops out rather than warning again on every rebuild. Removing a file drops its templates; rows that were using one lose their assignment and re-match with the untouched rows, since the template they named no longer exists.
- Two loaded files may define a template of the same name. Matching then has two equally good candidates and resolves the tie by path order, which is arbitrary from the user's side, so the row is marked with a dismissible **ⓘ** whose tooltip reads `'Tumor' also defined by templates_b.toml.` — and nothing else carries that text, since the marker is already visible without hovering. The dropdown label names the file the shown template came from, so the note adds only the part the screen does not: which *other* files define the name. Clicking the marker hides it and that is **not** remembered — flags are recomputed from scratch on every refresh, so a dismissed marker returns while the row is still ambiguous. Per-row "already silenced" state would be more machinery than the notice is worth.
- A template named `default` in **two** loaded files, with no host `default` to outrank them, is ambiguous: both the `default` actions and the auto-match fallback tier are withdrawn rather than resolved by file order — the point of that tier is the obvious baseline, and two libraries disagreeing means there is not one. The disabled control says so in its tooltip, and both templates stay individually selectable, labeled with their source.
- Three actions — **Auto-match** (recompute the default per type), **default**, **(none)** — exist at two scopes: a **Set all** row that applies them to every cell type, and a compact button beside each dropdown that applies them to that type alone. Each pair shares an **icon** (a circular arrow, a house in a ring, a slashed circle — packaged SVGs under `gui/icons/`) so the correspondence is visible rather than only stated in the tooltips. Icons rather than text glyphs because a glyph is drawn by whatever font the host's fallback chain supplies: the three marks came out at visibly different sizes and weights on one screen, and differently again inside an embedding application, and every per-row tooltip names both its cell type and its bulk counterpart. The **default** actions are disabled unless a template named `default` exists; the **Auto-match** actions are disabled when no templates are loaded at all.
- The window tracks which cell types the user has **picked for themselves** — a real dropdown activation, or any **default**/**(none)** action at either scope, as distinct from programmatic changes such as a sort-mode switch. Loading a further template file re-auto-matches only the *other* types, so a library loaded mid-step takes effect without overwriting decisions already made. **Auto-match** clears that record for the rows it touches — all of them from the **Set all** row, one from a per-row button — since those rows then hold exactly the computed value. A per-row **Auto-match** is therefore also how a user retracts a pick.
- Selections are stored in `session.cell_templates` as `{cell_type: (path, name, content)}`, rebuilt from the dropdowns on every change so a type switched to `(none)` leaves no stale entry. Unassigned types are absent.
- **The host's own cell types are candidates too.** Every name in `BiwtInput.host_cell_type_names` joins the dropdown under a reserved source, `types.HOST_SOURCE` (`"<host>"`), and matches on **equal footing** with templates from files. Assigning one means "the host already defines this cell type", and it comes back as `(HOST_SOURCE, host_type_name, "")` — no content, because there is nothing for BIWT to hand back: the host holds the definition. What to do with that signal is the host's decision (alias the names, copy its own definition, skip the type); BIWT only reports the match. The sentinel is deliberately unusable as a path, so a host that neglects to check it fails immediately rather than reading some file that happens to exist.
  - Displayed as `Tumor (Studio)` — the host's `host_name` (blank is replaced with `Host`), never the sentinel, which is an API signal and not something to show a user. Unlike a file qualifier, a host qualifier is **never** suppressed when only one source is loaded: it is what distinguishes "a type you already have" from "a template", which is information at any count.
  - **A host cell type named `default` is the baseline**, outranking any library's. `default` from a library is a generic starting point; the host's is that host's actual default cell type, which is what the action asks for. It also settles the case that otherwise has no answer: two libraries each defining `default` leaves neither as *the* baseline and withdraws the action, but a host `default` outranks both, so the buttons stay enabled and point at it. One rule serves the `default` actions and the auto-match fallback tier, so the two controls cannot disagree about what `default` means.
  - Not removable: *Remove templates from file…* offers files only, since the host's cell types are not something BIWT loaded.
  - **The host outranks the libraries at every match tier.** `matched_candidates` tries the host's names before the templates at the exact tier, then again at the similarity tier — so the host wins where both name a type equally well (`tumor` from the host beats `Tumor` from a file), while match *quality* still comes first (an exact template match beats a merely similar host name). Where the two spell a name identically, `_first_key_for_name` breaks the tie the same way, sorting by `(name, source is not the host, path)`. The file entry stays listed and selectable, and the row carries the usual **ⓘ** naming it as the alternative. Source display order in **By Source** mode follows the same preference, so the group that wins a tie is the group listed first.
  - **Deferred: a full source ranking.** The intended order is host cell types, then libraries the *user* loaded (they went to the trouble), then libraries the *host* supplied (a generic framework library is the weakest answer). Only the first tier exists today. The obstacle is not mechanism but classification: a host may well let users pre-register their own libraries, which would then arrive through `cell_template_paths` indistinguishable from the framework's own — so "host-supplied" would silently demote a user's library. Getting that wrong is worse than not ranking, and the distinction needs settling at the API boundary first.
- The step is shown on **every** run: a user can always supply their own templates, so there is no host flag to hide it.

**Acceptance criteria:**
- [x] No templates ship with the package; `cell_template_paths` and the runtime loader are the only sources.
- [x] Content round-trips verbatim, including surrounding whitespace.
- [x] Non-string template values are rejected, naming the offending key.
- [x] Skip yields an empty mapping and advances; `(none)` per type omits just that type.
- [x] Name-matched, `default`-fallback and unassigned pre-selection all behave as specified.
- [x] Same-named templates from two files stay distinguishable, and a runtime file add preserves existing selections.
- [x] The window builds and Continue works with no templates available at all.
- [x] Loading a template file re-matches untouched types and leaves user-picked ones — including an explicit `(none)` — alone.
- [x] Bulk and per-row actions behave as specified, pair up by glyph, and are disabled when they would have nothing to do.
- [x] Host cell types appear as candidates, match on equal footing with file templates, and come back as `(HOST_SOURCE, name, "")`.
- [x] A host cell type named `default` neither supplies the `default` fallback nor makes it ambiguous.
- [x] Host entries are labelled with `host_name` at any source count, and cannot be removed.
- [x] Removing a library file re-matches the rows that used it and leaves other picks intact; a cancelled dialog changes nothing.
- [x] A `default` defined by two files withdraws the default actions, with a tooltip explaining why.

---

## F11: Result Assembly and Return

**One-line description:** Assemble final output and return to the host application.

**Behavioral specification:**
- BIWT assembles a `BiwtResult` containing:
  - `coordinates`: DataFrame with columns `["x", "y", "z", "type"]`.
  - `cell_type_map`: dict mapping every original label to its final name, or `None` where the type was deleted. Built by `WalkthroughSession.resolved_cell_type_map()` from the decisions the walkthrough actually records (`cell_types_list_original` and `cell_type_dict_on_rename`); merged originals all resolve to the one name their group was given.
  - `domain_used`: the DomainSpec used for placement.
  - `cell_templates`: `{final_cell_type: (path, name, content)}` for the templates the user assigned; unassigned types are absent, so `{}` is a normal result.
- BIWT never writes to disk. The host decides how to persist the result — and **where**: the result carries no output-path field. `to_csv(path)` is a convenience that writes and returns nothing; it records no state, because BIWT does not choose the output location and so has no business remembering one.
- The `on_complete` callback is invoked with the `BiwtResult`.

**Acceptance criteria:**
- [x] `BiwtResult.coordinates` has correct columns.
- [x] `cell_type_map` is populated: merged originals resolve to their group's final name, deleted types to `None`, and every original label appears.
- [x] `BiwtResult.to_csv()` writes with `type` header (not `cell_type`).
- [x] No file I/O in BIWT; host owns writing, and owns the path.
- [x] `BiwtResult.cell_templates` carries the assigned templates with their provenance; BIWT assembles no framework config of its own.

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
- If `cell_templates` is non-empty, Studio assembles a PhysiCell config from the template contents and offers to save it. Studio also ships the PhysiCell template library and passes it in through `cell_template_paths`.

**Acceptance criteria:**
- [x] Overwrite/Append/Browse/Cancel dialog shown when file exists.
- [x] Append preserves extra columns from existing CSV.
- [ ] Studio assembles and saves a config from `cell_templates` (host-side work; the host contract is `docs/integration/templates-and-matching.md`).
- [ ] Integration tested end-to-end with Studio (manual test).

---

## F13: Name Matching (Host-Owned)

**One-line description:** Deciding whether two strings name the same cell type.

**Behavioral specification:**
- The decision belongs to the host: `BiwtInput.name_matches` takes a `Callable[[str, str], bool]`, and supplying it replaces BIWT's rule **and** `BiwtInput.name_match_cutoff` entirely.
- BIWT's default, `core.cell_types.default_name_matches`, applies two rules in order:
  1. **Digit runs must be equal.** A number distinguishes cell types rather than spelling them differently: `M1`/`M2 Macrophage` (similarity 0.92), `CD4`/`CD8 T Cell` (0.90) and `Layer 2`/`Layer 6` (0.86) all clear any useful cutoff, so digits are compared first and any difference is disqualifying.
  2. **Then similarity**: `difflib.SequenceMatcher` ratio on the casefolded strings must reach the cutoff (default `0.85`). This admits `Fibroblast`/`Fibroblasts` (0.95) and `Tumor`/`tumour` (0.91).
- Known limitation: pairs distinguished by a non-numeric qualifier are not caught — `PD-1hi …`/`PD-1lo …` hold the same digits and score 0.92. A host curating names of that shape supplies its own predicate.
- Selection (`core.cell_types.best_match`) is shared by both callers: a case-insensitive exact match wins outright, else the first accepted candidate in sorted order. A boolean predicate admits no ranking, and sorting keeps the outcome independent of file or dict order.
- Both call sites use one policy: rename suggestions (F7) and cell-parameter pre-selection (F10).

**Acceptance criteria:**
- [x] Every digit-differing pair in a realistic library is rejected; spelling variants are accepted.
- [x] A host predicate fully replaces the default, cutoff included; exact matches still win.
- [x] Results are independent of candidate order.

---

## F14: Derived State and Step Invalidation

**One-line description:** Revisiting a step invalidates what came after it without destroying what follows from the answers still standing.

**Behavioral specification:**
- `_STEP_FIELDS` records, per step, the fields whose values that step's **user** chose. On advancing from a step whose answer changed, every field of every later step is reset.
- Anything **derived** from those answers belongs to `WalkthroughSession.reseed_derived_state()`, which runs immediately after that reset and again before every step-predicate evaluation. It is idempotent, total, and must never overwrite a user decision.
- Derived state is only what has to be *computed*: the probability-derived cell types, per-spot dicts and max-probability labels are rebuilt when deconvolution is on and cleared when it is off, and raw coordinates are extracted when missing. Spot deconvolution dominates that list because it is the only answer in the walkthrough from which bulk data follows; every other step's answer is its own state.
- An implication that is merely *logical* is **derived on read instead** — never stored, so never in need of repair. `use_spatial_data` is a property rather than a field for exactly this reason: True under deconvolution, False when the data has no coordinates, else the user's answer. It is therefore always a real boolean, and no step is ever asked a question the data has already answered.
- A step must not commit a field owned by a later step. Doing so is invisible at the time and destructive on the next advance, because the invalidation runs after the step has written.

**Acceptance criteria:**
- [x] Declining then accepting spot deconvolution (with or without a Back in between) reaches the edit step with its derived cell types intact, and never shows the spatial-data question.
- [x] Non-spatial data never reaches the spatial question, and `use_spatial_data` reads False throughout rather than ever being unset.
- [x] Re-import drops every window belonging to the previous session.
- [x] A test drives the real controller and asserts no step commits a downstream-owned field.

---

## Step Ordering (Single Source of Truth)

The walkthrough step sequence is defined in `_step_predicates(session)` in `walkthrough.py`:

| # | Step | Condition to show |
|---|------|-------------------|
| 1 | SpotDeconvQuery | Data has probability columns AND spatial coordinates, not yet asked |
| 2 | ClusterColumn | No column selected and spot deconv not chosen |
| 3 | SpatialQuery | Data has spatial coordinates, spot deconv not chosen, not yet answered |
| 4 | EditCellTypes | Cell type edit dict not yet built |
| 5 | RenameCellTypes | Final names not yet assigned |
| 6 | CellCounts | Not using spatial data AND counts not confirmed |
| 7 | Positions | Positions not yet set |
| 8 | LoadCellParameters | Parameters not yet loaded (always reached; skippable) |

Predicates read derived state, so `reseed_derived_state()` runs before each evaluation (see F14). After all predicates are False, `_finish()` assembles the result and calls `on_complete`.

---

## Appearance Inside a Host

BIWT is embedded, so an application-wide palette or stylesheet from the host reaches its widgets.
Anything BIWT uses to *convey information* must therefore be styled by BIWT rather than inherited.

The case that forced this: a disabled control has to look disabled — BIWT disables the merge
checkboxes, the Remove-library button, and the "assign default" actions to say the action has
nothing to do. Qt paints that from the palette's `Disabled` colour group, and a host can flatten it
without meaning to, since `QPalette.setColor(role, colour)` with no `ColorGroup` sets **every**
group. PhysiCell Studio does this for `ButtonText` and `WindowText`.

`gui/windows/base.py` therefore applies `_WINDOW_STYLE` to every step window with explicit
`:disabled` rules, and controls whose appearance matters most set their own stylesheet, which
outranks both. Regression tests compare rendered pixels of the enabled and disabled states under a
Studio-like palette; asserting on stylesheet strings would not have caught it.

---

## Displaying Cell-Type Names

**Ordering.** Anywhere names are shown to a user they sort case-insensitively, via
`core.cell_types.alpha_key` — `AaBbCc`, not `ABCabc`. Plain `sorted` orders by code point, which
files every capitalized name ahead of every lowercase one, stranding `iCAF` and `myCAF` after
`Stellate` instead of beside their alphabetical neighbours. The exact name is the tie-break, so two
names differing only in case still have a stable order. This governs the cell-type lists at every
step, the template dropdowns, and the loaded-file lists.

**Width.** Cell-type names arrive from the data and survive merging and renaming, so any of them can be
arbitrarily long — and a merged type's row label lists every original name that fed it. One such
name must never set the width of the panel it sits in. Two shared helpers in `biwt/gui/widgets.py`,
chosen by whether the widget's text can wrap:

- `row_label` wraps within a capped column, keeping every character on screen: the row grows taller
  instead of the window growing wider. Used for `QLabel` rows — rename, cell parameters, cell counts.
- `set_elided_text` clips and puts the full name in the tooltip, for widgets that cannot wrap
  (`QCheckBox` in the edit and positions steps). Its `suffix` is appended *after* clipping, so an
  annotation such as `⇒ Merge Gp. #2` is never eaten by the ellipsis.

A row's `⇒` is a separate widget in its own column rather than a suffix on the label, so it stays
beside the field it points at instead of drifting to the end of the last wrapped line.

**Acceptance criteria:**
- [x] A 100-character cell-type name leaves every field aligned and the window no wider.
- [x] Wrapped labels keep every character; elided ones carry the full name in a tooltip.
- [x] An appended annotation survives clipping, including for code that reads it back.

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
- `biwt.__version__` reads the installed distribution metadata, so `pyproject.toml` stays the single source of the version (a source tree that was never installed reports `0.0.0+unknown`). It is public API: a host may display or record it. BIWT surfaces it itself on the walkthrough's home screen — the one place it is visible when BIWT is embedded as a host tab, since an embedded widget's window title is never drawn — and in the window title for standalone use.
- The wheel ships **no framework-specific data**: no cell-parameter templates, no XML scaffold. The only package data is the GUI's icons. `tomli` remains a hard dependency on 3.9/3.10 because template files supplied by the host or the user are read at runtime (stdlib `tomllib` is 3.11+).
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
| `tests/fixtures/templates_a.toml` | TOML | Cell-parameter templates, including a `default`; values deliberately non-XML so content round-trips prove BIWT never parses them |
| `tests/fixtures/templates_b.toml` | TOML | A second library: one name colliding with `templates_a`, one differing from a fixture cell type only by case |

CSV fixtures should reside in `biwt/tests/fixtures/`. The `.h5ad` and `.rds` fixtures are to be created programmatically if possible; otherwise provided manually before release.
