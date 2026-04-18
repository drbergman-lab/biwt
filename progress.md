# BIWT Development Progress

Session-level notes and decisions. Unlike the PRD (specification) and README (completion status), this file captures the reasoning behind decisions.

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
