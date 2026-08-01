# BIWT Development Progress

Session-level notes and decisions. Unlike the PRD (specification) and README (completion status), this file captures the reasoning behind decisions.

---

## 2026-07-23 (later): data-unit→host-unit scale factor (supersedes the "no conversion" notes below)

The parse-only, no-conversion stance below was intentionally reversed after a
design discussion: recognizing imagerow/imagecol usefully **is** a unit-conversion
problem, so a proper, visible scale factor was added and folded into this branch.

### Design
- **Factor `F` = host units per data unit** (`preferred_domain.units`, microns for
  PhysiCell Studio). Auto-detected only from Visium `.h5ad`
  (`_extract_visium_microns_per_pixel` → `BiwtData.microns_per_data_unit`,
  `55/spot_diameter_fullres`); everything else → `None` (user types it).
- **No unit-name inference.** `infer_domain` reports generic `"data units"` —
  imagerow/imagecol are still recognized + y-flipped but NOT labeled "pixel".
- **Placement scales the data directly**, centered: `placed = raw × F`, centered
  in the domain (`compute_spatial_placement`, `session.effective_scale()`). Pure
  uniform scale + translate — aspect always preserved; the domain is an
  independent host-units container. This replaced the old "auto-scale to fill
  domain" (min-of-ratios fit), which is why `auto_scale_to_domain` was removed in
  favor of `scale_factor` + `apply_scale`.
- **Domain editor** shows two synced bounds columns (data units | host units)
  linked by `F` (no radio — both always visible), a "{host} per data unit" field
  with a reset-to-file button, and one "Apply scale factor to data" checkbox
  (gates cell-scaling only, never the display). "Use Data Domain" fills
  data-units=raw, host=raw×F; host domain is host units verbatim.
- **Why scale the data, not "fit to domain":** the old µm/pixel scaled the domain
  box but never the placed cells (half-baked). Scaling the cells by `F` and
  centering makes the factor actually reach the exported coordinates, and hand-
  editing the domain no longer changes the cell scale.
- **TODO:** when host units ≠ microns (e.g. nm) the seeded Visium µm/pixel factor
  needs converting to host-units/pixel (×1000 for nm). Seeded as-is for now;
  user can override. Also: read a declared unit string if a format ever provides one.

### Files
`core/data_loader.py` (extractor + `microns_per_data_unit`), `core/domain.py`
(units → "data units"; "(image columns)"), `core/positioning.py`
(`compute_spatial_placement`), `gui/walkthrough.py` (`DomainEditorDialog` rewrite,
session `scale_factor`/`apply_scale`/`effective_scale`, `_scale_domain`, import
seeding), `gui/windows/positions.py` (`_default_spatial_pars`, both dialog sites).

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

## 2026-08-01: Discoverable install docs + docs pointer on environment errors

### Why: the reported symptom was not the one the obvious fix addresses

Trigger: a host application that wanted to call BIWT could not find BIWT's docs. The natural
reading is "the `.rds` import error message should link to setup instructions," but that only
reaches someone who already installed BIWT, opened the wizard, and picked an `.rds`. The real
gap was upstream — `pyproject.toml` had no `[project.urls]` at all, so the PyPI page carried
zero outbound links. Work was sequenced to fix the outermost gap first:

1. `[project.urls]` — Homepage / Repository / Documentation / Issues.
2. `docs/installation.md` — the page those links point at.
3. `LoadError.docs_url` — the pointer, decided at the raise site.
4. The dialog — renders the pointer as a clickable link.

Doing 4 before 1–3 would have shipped a link to a section that documented none of what it
promised.

### Docs live here, not in the host

Studio's `bin/ics_tab.py` (`_warn_legacy_biwt_tab`) already showed a rich-text `QMessageBox`
linking to Studio's `doc/BIWT.md` — which is where BIWT's R/Seurat setup was documented. That
runs the dependency backwards: a host-agnostic package's install instructions were maintained
in one host's repo, and host #2 would have duplicated them. The content is now ported to
`docs/installation.md` here (Studio-specific bits generalized: `studio` → `<env>`, no
`bin/studio.py` invocations), and Studio's doc should link here rather than the reverse.

`docs/installation.md` rather than a README anchor: the troubleshooting section is ~10 KB and
would swamp the README, and the URL is baked into shipped releases, so it needs a target that
does not move when the README is reorganized.

### `docs_url` on the exception, not a blanket append in the dialog

The tempting one-liner is to append "see the installation docs" to every `LoadError` in
`_import_cb`. But `str(e)` covers ten distinct raise sites, and telling a user whose CSV
failed to parse to go read the Seurat setup is noise.

Which failures warrant the pointer is a property of the raise site, so `LoadError` grew an
optional `docs_url` (default `None`) and the GUI renders a link only when one is present.
Four sites set it: missing `anndata`, missing `rpy2`/`anndata2ri`, `anndata2ri activation
failed` (the 2.0+ `activate()` removal), and `Failed to read ... as R object` (missing
`SeuratObject`, or an ABI-mismatched R — the segfault case). Six do not: unsupported
extension, unreadable `.h5ad`, empty R workspace, unsupported R class, unreadable CSV,
unreadable obs/obsm.

Keeping the decision in `core/data_loader.py` also means a notebook or CLI host calling
`data_loader.load()` gets the same pointer — putting the URL in the Qt callback would have
made it GUI-only, against the package's pure-Python-core rule.

### Verified rather than assumed: QMessageBox opens external links itself

Qt sets `openExternalLinks=True` on the message box's text label (`qt_msgbox_label`), so an
`<a href>` in rich-text mode opens in the default browser with no `linkActivated` →
`QDesktopServices` wiring. Confirmed by introspecting the label under
`QT_QPA_PLATFORM=offscreen`; no handler was added.

`str(err)` is HTML-escaped before interpolation, since messages embed file paths and R error
text that can contain `<`, `>`, and `&`.

### Tests

`TestLoadErrorDocsPointer` (`test_session.py`) asserts the pointer is present on dependency
failures and absent on file failures; missing dependencies are simulated with
`monkeypatch.setitem(sys.modules, "anndata2ri", None)`, which makes `import` raise
`ImportError` without touching the real environment. One test resolves `DOCS_URL` back to a
file in the repo, so renaming the docs page fails the suite instead of shipping a dead link.

`test_gui_smoke.py` covers the dialog itself with `QMessageBox.exec_` monkeypatched to record
the box instead of blocking: rich text plus anchor for dependency errors, plain text for file
errors, and HTML escaping of the message.

---

## 2026-08-01: Documentation site (MkDocs Material → GitHub Pages)

### Why a site rather than more markdown files

The previous session added `docs/installation.md` and pointed the "Import failed" dialog at
it via a `/blob/main/` GitHub URL. Two problems with stopping there. The URL is baked into
released wheels but always resolves to tip-of-main, so an 0.3.2 user reads 0.5 docs. And the
troubleshooting content alone is ~10 KB — a single flat file was already at the limit of what
is navigable, and the three sections still missing (user guide, recipes, integration) are
several times larger.

Chose MkDocs Material over Sphinx: the source stays plain markdown that renders fine on
GitHub, the setup is a single config file, and mkdocstrings covers the autodoc requirement
without committing to reStructuredText.

### Structure

Four audiences, four top-level sections, because they want different things:

- `getting-started/` — install, first walkthrough, R troubleshooting
- `guide/` — one page per wizard step, written as user-facing prose rather than the PRD's
  spec language, plus the domain editor (a dialog, not a step)
- `recipes/` — Visium, non-spatial scRNA-seq, spot deconvolution; task-shaped, each naming
  the traps specific to that data
- `integration/` — the audience whose failure to find the docs started all of this
- `reference/` — mkdocstrings

The PRD stays the internal spec. It is not user documentation and was not linked into the
nav; the guide pages were written *from* it, not as a copy of it.

### Build is strict, and that is load-bearing

`mkdocs build --strict` fails on broken internal links and nav entries pointing at missing
files, so the docs cannot silently rot as pages are renamed. Because mkdocstrings imports the
package to read docstrings, malformed docstrings are also build failures — the first strict
run caught a real one (see below). CI runs the build on PRs and only deploys on push to
`main`.

### Two docs URLs, not one

Splitting the guide into install and troubleshooting pages made the single `DOCS_URL` too
coarse, so `data_loader` now exposes `INSTALL_DOCS_URL` and `TROUBLESHOOTING_DOCS_URL`:

- Never-installed dependency (missing `anndata`, missing `rpy2`/`anndata2ri`) → install page.
- R stack present but misbehaving (`anndata2ri` activation failure, R-object read failure) →
  troubleshooting page, which has numbered entries for exactly those symptoms.

The dialog's link text went from "BIWT installation docs" to "BIWT setup docs" so it reads
correctly for both.

The URL-resolution test was reworked: it now maps a published Pages path back to its source
file under `docs/`, so renaming a page still fails the suite. A second test asserts
`DOCS_BASE_URL` equals pyproject's `Documentation` entry, so the PyPI link and the in-app
links cannot drift apart.

### Two real docstring bugs, found by writing the docs

Both were invisible until docstrings became rendered output:

1. `create_biwt_widget`'s example passed `output_csv_path=` to `BiwtInput`, which has no such
   field — the documented example raised `TypeError`. Replaced with `host_name` and a note
   that persistence belongs in `on_complete`.
2. `BiwtResult`'s "Future expansion" block sat inside its numpydoc `Parameters` section, so
   griffe parsed it as a parameter named `Future`. Moved to a `Notes` section, explicitly
   flagged as not-currently-attributes.

### Deployment prerequisite

GitHub Pages must be enabled with **Settings → Pages → Source: GitHub Actions** before the
workflow can deploy. Until then the in-app links 404. Nothing in the repo can do this step.
*(Done 2026-08-01; the site goes live on the first push to `main`.)*

### Screenshot data generator

`scripts/make_screenshot_data.py` builds a synthetic Visium-like `.h5ad` for documentation
screenshots. Synthetic rather than a public 10x dataset because raw Visium carries no
cell-type annotation — a real file would need a full clustering pass before BIWT's
cluster-column dropdown showed anything worth photographing — and because the composition can
be tuned to read clearly at screenshot resolution.

It is built backwards from what each screen needs:

- `uns["spatial"][lib]["scalefactors"]["spot_diameter_fullres"] = 110.0`. BIWT computes
  `55.0 / spot_diameter_fullres`, so this yields exactly 0.5 µm/pixel and the domain editor's
  factor field appears pre-filled — the entire point of that screenshot.
- A ~2500 µm tissue extent, which `classify_domain_mismatch` calls `"outside"` against a
  ±500 µm domain, so the domain editor auto-opens at the positions step instead of having to
  be summoned.
- Six cell types with two obvious merges (`Tumor_Core`/`Tumor_Edge`, `M1`/`M2 Macrophage`), so
  edit-cell-types demonstrates merging rather than just listing.
- Decoy obs columns (`orig.ident`, `nCount_RNA`, `percent.mt`, `seurat_clusters`, …) so the
  cluster-column dropdown looks like a real object.
- `--deconv` adds `*_probability` columns. Opt-in, because their presence changes the wizard's
  path: BIWT asks the deconvolution question and then skips the cluster-column step.

**Two passes over the same file** are needed for full coverage — verified by driving
`_step_predicates` headlessly. Answering *yes* at the spatial query reaches ClusterColumn,
EditCellTypes, RenameCellTypes, Positions, LoadCellParameters; answering *no* is the only way
to reach CellCounts, which is skipped whenever spatial data is used.

---

## 2026-08-01: Scale-factor label as a ratio; data unit name made singular

The domain editor's factor field read `micron per data unit`, which is wrong for a singular
unit name — nobody says "0.5 micron per data unit". Pluralising needs a rule for an arbitrary
host unit string, so the label is now a **ratio**: `micron/data unit`. A ratio denominator is
singular by convention (km/h, mg/L), so no pluralisation logic is needed at all.

That exposed an inconsistency in what `DomainSpec.units` holds. The host side stored a
singular unit *name* (`"micron"`), but `_domain_from_coords` defaulted to the plural
`"data units"`. Now both are singular names, so the same value reads correctly in both places
it appears: as a bounds-column header, and as a term in the ratio.

Both sides of the label are read from the two `DomainSpec`s rather than hardcoded, which
means a data domain that ever carries a real unit name renders as `micron/pixel` with no
further change to the dialog. Nothing sets one today — `_domain_from_coords` still passes the
generic default even on the `imagerow`/`imagecol` path, where pixel-ness *is* known — so
that remains an available follow-up rather than something implemented.

`DomainSpec.units` on the host side is untouched: still `"micron"`, still the PhysiCell
convention, still what rides out on `BiwtResult.domain_used`.

Two tests pin this: one asserts the ratio format and the absence of the old prose, the other
constructs the dialog with `nanometer`/`pixel` to prove neither side is hardcoded.

`docs/assets/screenshots/domain.png` still shows the old prose label and needs a retake.

---

## Open Questions

- **Visium multi-library:** Current code takes the first library's scale factors. Multi-library arrays are uncommon but should be handled eventually.
- **3D spatial data:** Currently padded to z=0. Real 3D data (e.g. MERFISH) would need full 3D domain support.
- **Substrate/gene expression pass-through:** Reserved fields in BiwtResult but not yet implemented.
