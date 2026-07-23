# BIWT Development Progress

Session-level notes and decisions. Unlike the PRD (specification) and README (completion status), this file captures the reasoning behind decisions.

---

## 2026-07-23: Recognize `imagerow`/`imagecol` spatial coordinates (parse-only)

### What shipped
Recognize 10x Visium `imagerow`/`imagecol` columns as a last-resort spatial
source. The old code *looked* like it supported them but was dead: it called
`_find_coord_col(cols, "imagerow")`, and that function's second argument is an
*axis key* (`x`/`y`/`z`) looked up in `_COORD_CANDIDATES` — so `"imagerow"`
never matched and `has_spatial` was always False for such data.

- `core/domain.py`: added `_PIXEL_COORD_CANDIDATES`, `_find_pixel_coord_col`,
  `resolve_obs_coord_cols()` and `build_obs_coords()` as the single place that
  resolves spatial columns (x/y/z first, then pixel imagecol/imagerow). Wired
  into `infer_domain`, `_detect_spatial_location_from_obs`.
- **Axis mapping:** `imagecol` → x, `imagerow` → y. Image rows increase
  *downward*, so `imagerow` is flipped (`y = rowmax - imagerow`) to a y-up
  system. The flip is a reflection, so it doesn't change the domain-box size —
  only orientation/offset.
- `obsm["spatial"]` is synthesized from obs columns (CSV *and* AnnData/R) so the
  EditCellTypes dim-reduction dropdown offers a Spatial view.
- `setup_spatial_data` uses the same resolver.
- **Units:** imagerow/imagecol data reports its data domain in `"pixel"` units
  (other coords stay `"micron"`). `infer_domain` decides units from the obs
  columns once, so a synthesized `obsm["spatial"]` (which would otherwise take
  the obsm path and lose the signal) still yields `pixel`. Clicking **"Use Data
  Domain"** in the editor fills those bounds *and* the units field.

### No scaling — `microns_per_pixel` removed
No pixels→microns conversion is applied anywhere: whatever coordinates we find
define the data domain, as-is. This removed the pre-existing Visium
`microns_per_pixel` machinery (`_extract_visium_microns_per_pixel`, the
`BiwtData.microns_per_pixel` field, and the `infer_domain` scaling), because it
was half-applied and misleading: it scaled the *domain bounds* to microns but the
cells were still placed at raw coordinates, and the "Auto-scale to fill domain"
checkbox nullified it anyway. A converter also can't prove coordinates are pixels
(an object may carry scalefactors yet store microns), and pixel-vs-micron is
undetectable from an `obsm` array. An earlier draft that added a user-entered
"microns per unit" factor was likewise walked back.

Physical scaling is the user's job — bring data already scaled for the domain, or
scale upstream. The "Auto-scale to fill domain" option below is a *fit-to-domain
placement* convenience, not a unit conversion.

### Auto-scale placement kept (with a fix)
The domain editor keeps the **"Auto-scale data to fill domain (preserving aspect
ratio)"** checkbox (`session.auto_scale_to_domain`, default True). It affects only
spatial *placement*, not the recorded coordinates/units:
- checked → `_default_spatial_pars` scales the data extent to fill the domain
  (aspect preserved), centered;
- unchecked → uses the raw data extent, centered.

The earlier bug — a domain change refused to update the spatial plotter once the
user had hand-edited its parameters — was fixed in `_apply_domain_change_and_redraw`:
instead of only refreshing when the history had a single entry, it now **appends**
the newly-computed default to the plotter's history and points the index at it, so
the plot rescales to the new domain while the user's prior edit remains available
as an undo step. On a domain change the spatial plotter therefore reverts to the
data extent, re-centers in the new domain, and rescales to fill if auto-scale is on.

### Future work: a real pixels→microns scale factor
If revisited, the clean design is to convert coordinates **into microns once, at
load/placement time**, rather than scaling the domain box:
1. Store the factor as data (`BiwtData`) plus a single user-editable session
   value, e.g. `microns_per_unit` (float; `1.0` ⇒ already microns). Seed it from
   any data converter, else `1.0`.
2. Apply it to the **coordinate arrays** (`obsm["spatial"]` / `spatial_data`)
   immediately after load, so everything downstream — plot, domain inference,
   placement, exported ICs — is already in microns and the "Accept" bounds mean
   what they say. This is a unit conversion, distinct from any fit-to-domain
   resizing; do not reintroduce automatic resizing to implement it.
3. Ask for the factor once, up front (at the spatial-confirmation step), with a
   sensible default and a note that it can be revised — but only if step 2 is
   done so it isn't silently overridden.
4. Because pixel-vs-micron can't be auto-detected, keep the factor visible and
   user-confirmable; never apply a data-derived factor silently.

## 2026-07-09: Fix `tomli` dependency classification (v0.3.2)

### Bug: `ModuleNotFoundError` on import under Python 3.9/3.10
`core/parameters/cell_templates.py` parses the built-in `cell_templates.toml`
at *import time* (`CELL_TEMPLATES = load_templates_from_file(...)`). On Python
< 3.11 there is no stdlib `tomllib`, so it falls back to the `tomli` backport.
But `tomli` was declared only in the `[gui]` optional extra — even though the
code that needs it lives in `biwt.core`, not the GUI.

As a result, any non-`gui` install path (`pip install biwt`, `biwt[anndata]`,
`biwt[seurat]`) crashed on import under 3.9/3.10. Only combinations that
happened to pull in `gui` (e.g. `biwt[all]`) worked. This surfaced when
launching in PhysiCell Studio on a Python 3.9 venv.

**Fix:** moved `tomli>=1.2; python_version < '3.11'` from the `[gui]` extra
into the base `dependencies`. The environment marker means 3.11+ still skips
it (stdlib `tomllib` is used there). Version bumped to 0.3.2.

Also updated `CLAUDE.md` Branching Rules: base branch is `main` (there is no
`development` branch in this repo).

## 2026-07-03: Fix stale marker sizes after domain change

### Bug: spot/cell markers wrong size after switching domain settings
`PositionsWindow._recompute_scatter_sizes` converts each cell type's true
micron^2 area into a matplotlib scatter `s` value (points^2) using the
axes' current data-to-pixel transform (`ax0.transData`). For 2D plots the
axes use `set_aspect(1.0)`, but matplotlib only recomputes the axes' pixel
bounding box for that aspect constraint during a draw pass
(`Axes.apply_aspect()`, normally invoked inside `canvas.draw()`).

`_apply_domain_change_and_redraw` (triggered by the "Domain Settings…"
dialog) called `_recompute_scatter_sizes()` *before* `canvas.draw()`, so it
read a stale/unadjusted axes box whenever the new domain had a different
aspect ratio than the old one — producing incorrectly sized spot markers.
`_create_figure` (initial setup) happened to get the order right by luck
(`draw()` before the first `_recompute_scatter_sizes()` call), which is
why the bug only showed up after changing domain settings, not on first
load.

**Fix:** `format_axis()` now calls `self.ax0.apply_aspect()` immediately
after `set_aspect(1.0)`, so the axes box is always correct right after
`format_axis()` returns — regardless of whether a `canvas.draw()` has run
yet. This removes the fragile ordering dependency between `format_axis()`,
`_recompute_scatter_sizes()`, and `canvas.draw()` across all call sites.

Circle-based markers for already-placed cells (`self.circles(...)`) were
never affected — their radius is in data units, so they scale
automatically with axis limits.

Regression test added in `tests/test_positions_plot.py`, exercising
`format_axis()` directly against a bare `matplotlib.figure.Figure`/`Axes`
(no `QApplication` needed, since the method only touches `self.ax0` and
the `plot_x/y/zmin/max` bounds).

### Follow-up: spot preview markers still stale after the above fix
The `apply_aspect()` fix corrected `_recompute_scatter_sizes()`'s own math,
but user testing (loading `tests/fixtures/spatial.csv`, opening "Domain
Settings…", switching to the data domain) showed the spatial-plotter's
gray "spot" preview markers still didn't resize until clicking "Select
Remaining" or plotting cells.

Root cause: `_apply_domain_change_and_redraw` called
`self._replot_all_after_undo()` *before* `self._recompute_scatter_sizes()`.
But `_replot_all_after_undo()` ends by calling `self.sync_par_area()`,
which re-invokes `self.current_plotter` — for the spatial plotter, that's
`spatial_plotter()`, which reads `self.scatter_sizes` to size the preview
scatter it (re)creates. So the preview got redrawn using `scatter_sizes`
from *before* the domain change, and `_recompute_scatter_sizes()` ran too
late to matter — it updated `self.scatter_sizes` for next time, but never
touched the already-created scatter artist. Clicking "Select Remaining"
called `sync_par_area()` again, by which point `scatter_sizes` was
already fresh, so it looked "fixed" once you interacted with the window.

**Fix:** moved `self._recompute_scatter_sizes()` into
`_replot_all_after_undo()`, right after `format_axis()` and before the
per-cell-type replot loop / `sync_par_area()` call, and removed the
now-redundant standalone call from `_apply_domain_change_and_redraw`.
This guarantees scatter/marker sizes are always current *before* anything
that might redraw a size-dependent preview.

Verified the regression test (`TestReplotOrdering` in
`tests/test_positions_plot.py`, asserting `_recompute_scatter_sizes` is
called before `sync_par_area` inside `_replot_all_after_undo`) fails
against the pre-fix code and passes against the fix.

---

## 2026-03-29: Domain editor dialog, CSV column rename, documentation

### Domain editor dialog (replaces plain warning)
On mismatch between data-inferred domain and preferred domain, BIWT now shows a `DomainEditorDialog` instead of a plain warning. The dialog auto-populates with the data-inferred domain and lets the user:
- Edit xmin/xmax, ymin/ymax, zmin/zmax bounds.
- Set units (text field).
- Toggle "auto-scale data to fill domain" (preserves aspect ratio).
- Reset to data domain or preferred domain.

The edited domain is stored as `session.user_domain` and overrides the preferred domain in `effective_domain`. The `auto_scale_to_domain` flag is carried to the positions step: when False, `_default_spatial_pars` uses raw coordinates with identity transform.

**Why a dialog instead of a warning:** A warning says "there's a problem" but doesn't let the user fix it mid-BIWT. The editor gives them control without leaving the walkthrough.

**Why no separate preserve-aspect-ratio checkbox:** Auto-scaling always preserves aspect ratio. A second checkbox would clutter the interface and confuse more users than it helps.

**Why approximate matching (5% relative / 1 unit absolute):** Strict equality would fire on minor rounding differences or cells that sit near but don't cross the boundary. The tolerance suppresses false positives while catching genuine scale mismatches (e.g. pixel coordinates in the thousands vs a micron domain of +/-500).

### CSV column rename: cell_type -> type
PhysiCell's cells.csv convention uses `type` as the header, not `cell_type`. Renamed throughout: `positioning.build_ic_dataframe`, `BiwtResult.to_csv`, `BiwtResult.coordinates` docstrings, and all tests.

### Append logic for extra columns
When Studio appends BIWT output to an existing CSV that has extra columns (e.g. `volume`), `pd.concat` naturally fills missing columns with NaN, which renders as empty in CSV output. This matches the user's expectation: appended rows have `x,y,z,type` populated and extra columns empty.

---

## 2026-03-29 (earlier): Host-owns-write architecture

### Decision: Remove all file I/O from BIWT
Previously BIWT had a `WritePositionsWindow` step and wrote cells.csv directly. This was removed:
- `WritePositionsWindow` removed from `_step_predicates` and `_factories`.
- `output_csv_path` removed from `BiwtInput`.
- `_finish()` now assembles `BiwtResult` in-memory and calls `on_complete`.
- Studio's `_biwt_complete` now shows Overwrite/Append/Browse/Cancel dialog.

**Why:** BIWT is a package that may be embedded in different hosts. The host knows where files should go; BIWT should not. This also eliminates the need for BIWT to know about Studio's `csv_folder` / `output_file` fields.

### Session reset on reimport
When the user imports a new file, the session is now fully reset: `self.session = WalkthroughSession(biwt_input=self.session.biwt_input)`. This prevents stale state from a previous run (e.g. spatial data, cell counts) from leaking into a new walkthrough.

---

## 2026-03-29 (earlier): Step predicate extraction

### Decision: _step_predicates as module-level function
Previously `_next_step` logic was duplicated between `walkthrough.py` and `test_session.py`. Extracted `_step_predicates(session)` as a pure-Python module-level function that returns `[(predicate, label)]`. Both `_build_next_window` (production) and tests import it directly.

**Why:** Single source of truth. If steps change, tests automatically reflect it. Tests no longer need to re-implement the predicate logic.

---

## 2026-03-29 (earlier): CSV spatial synthesis

### Decision: Synthesize obsm["spatial"] for CSV files
CSV files with x/y columns had spatial coordinates in `obs` but not `obsm`. The `EditCellTypesWindow` scatter plotter looks for `obsm["spatial"]`. Rather than changing the plotter, `_load_csv` now synthesizes `obsm["spatial"]` from coordinate columns. `setup_spatial_data` then pads z=0 when the array is 2D.

**Why:** Minimal change — the plotter's `obsm`-based approach works for all formats (.h5ad, .rds, .csv) without special-casing.

---

## 2026-03-29 (earlier): Case-sensitive duplicate check in rename

### Decision: Allow names that differ only by case
The rename step originally blocked case-insensitive duplicates (e.g. "CD8" and "cd8"). Changed to exact (case-sensitive) match only.

**Why:** PhysiCell treats "CD8" and "cd8" as distinct cell types. Blocking them would be incorrect.

---

## 2026-03-29 (earlier): Cell counts step visibility

### Bug: CellCountsWindow never shown
`apply_rename()` always populates `cell_counts`, so the predicate `cell_counts is None` was always False after the rename step. Fixed by adding a `cell_counts_confirmed: bool = False` flag that is only set to True when the user explicitly confirms counts in the CellCountsWindow.

---

## 2026-03-30: Domain editor overhaul + positions auto-trigger + spatial pars fix

### Two-tier domain mismatch detection (replaces bounds_match)

`DomainSpec.bounds_match()` was removed. It was a symmetric, tolerance-based comparison that treated all mismatches identically. Replaced with `classify_domain_mismatch(data, preferred) -> str | None` in `core/domain.py`:
- **"outside"**: any data boundary exceeds preferred (cells would be excluded).
- **"small"**: data fits inside but covers < 50% of any axis or < 50% of 2-D area (cells would be sparse).
- **None**: no significant mismatch.

50% threshold chosen after testing: a typical spatial dataset of [-278, 285] × [-497, 499] in a [-500, 500] × [-500, 500] domain covers ~56% of each axis and ~56% of the area — correctly returns None (no dialog needed).

### Dialog moved to positions window open (not import time)

The domain editor used to show at import time, before the user even reaches the spatial placement step. It now auto-triggers when the **positions window first opens** via `_maybe_show_domain_editor()`. This is more UX-relevant: the domain directly affects cell placement, so it should be reviewed at that point.

`session.domain_accepted = True` is set after the dialog is dismissed (OK or Cancel) to prevent re-triggering when the user navigates back and forward. `BiwtInput.domain_accepted` and a "Skip domain validation" checkbox on the home screen also bypass the auto-check.

### "Domain Settings…" button for manual access

Added to `BiwinformaticsWalkthroughPlotWindow` (below "Show Legend"). Opens the domain editor without a mismatch header. On OK: updates `session.user_domain`, refreshes domain dims, clears the plot, and calls `_undo_all_cb()` to reset placed cells.

### Auto-scale off: bounding box centered in domain (not identity transform)

Previously `auto_scale_to_domain = False` returned `[0.0, 0.0, 1.0, 1.0]` (1×1 box at the origin), which was incorrect. Now `_default_spatial_pars` computes the raw data bounding box and centers it at the domain center:
- `x0 = domain_center_x - data_dx / 2`, `y0 = domain_center_y - data_dy / 2`
- `width = data_dx`, `height = data_dy` (original data extent)

Both auto-scale modes share the same normalized base coords (0→1 relative to data bounding box), so the spatial plotter formula `x0 + base_x * width` is consistent.

**Why centered at domain center (not at data's original position):** The domain center is the natural reference point for PhysiCell simulations (typically 0,0). Centering there avoids cells appearing at an unexpected offset, especially when data coordinates are in pixel space (thousands of pixels) while the domain is in microns (±500).

---

## Open Questions

- **Visium multi-library:** Current code takes the first library's scale factors. Multi-library arrays are uncommon but should be handled eventually.
- **3D spatial data:** Currently padded to z=0. Real 3D data (e.g. MERFISH) would need full 3D domain support.
- **Substrate/gene expression pass-through:** Reserved fields in BiwtResult but not yet implemented.
