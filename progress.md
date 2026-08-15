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

`docs/assets/screenshots/domain.png` was retaken against the new label.

---

## Open Questions

- **Visium multi-library:** Current code takes the first library's scale factors. Multi-library arrays are uncommon but should be handled eventually.
- **3D spatial data:** Currently padded to z=0. Real 3D data (e.g. MERFISH) would need full 3D domain support.
- **Substrate/gene expression pass-through:** Reserved fields in BiwtResult but not yet implemented.

---

## 2026-08-02: Zero cell counts allowed

The cell-counts screen blocked any type whose count was zero. Allowing it lets a user pull a
PhysiCell template into the generated config without seeding any of those cells — a population
that should appear later by division or differentiation, not at t = 0.

**Why this was mostly a removal.** Cell definitions have never been driven by counts. The
registry is built from `cell_types_list_final` (`load_cell_parameters.py`), and
`build_ic_dataframe` simply iterates each type's coordinate array, so an empty one contributes
no rows. The desired output — definition present, no CSV rows — already fell out of the
existing design. Only the guard had to go.

**What the guard was masking.** Continue only unlocks once *every* cell type's checkbox is
disabled, and a checkbox is disabled only by plotting that type. A zero-count type therefore
stranded the positions step in both dimensionalities, for slightly different reasons:

- **2D** — recoverable but obscure. The user has no reason to select a type with no cells, and
  if they place only the types that have cells, Continue never unlocks. Ticking the empty type
  and pressing Plot *would* have released it, since `_plot_single_2d` disables the checkbox
  unconditionally.
- **3D** — a hard dead-end. `_plot_single_3d` returns on an empty sampler result *before*
  reaching `setEnabled(False)`, so even the workaround above fails.

Verified both by driving the real `PositionsWindow` offscreen: with the fix reverted, all four
scenarios (2D/3D × one-zero/all-zero) leave Continue disabled.

The fix does not add an `N == 0` branch to the plotters. Instead a zero-count type is treated
as **already placed** when the window is built: its checkbox starts disabled, so it can never
be selected and never reaches a plotter. That keeps the existing empty-result return meaning
exactly one thing — the sampler hit its rejection limit and the region is unusable — instead of
conflating "user asked for zero" with "sampling failed". Undo respects the same rule, via
`_is_placeable`.

The Continue gate moved into `_refresh_continue_gate` because of the all-zero case: with
nothing placeable, no plot can ever happen, so the gate has to be evaluated once at window
construction rather than only after a plot.

**Two adjacent bugs fixed while here.** Proportional mode computed
`mult = int(text) / p if p else 0` — editing a row whose share of the data is zero drove the
multiplier to zero and wrote 0 into *every other type*. Zero shares already arose from
`_count_final_cell_types`, so this was reachable before; it just becomes routine once zero is a
legitimate starting state. And `_plot_single_2d` appended a legend entry unconditionally while
`_replot_all_after_undo` skips empty arrays, so a zero-count type appeared in the legend until
the first redraw silently dropped it.

**Empty-frame dtypes.** `pd.DataFrame([], columns=...)` types every column as `object`. That
frame flows into the Studio bridge's `pd.concat` append path, where it would degrade real
coordinate columns, so `build_ic_dataframe` now constructs its empty result with explicit
`float64` x/y/z.

**No floor on the total.** Every type may be zero, giving a definitions-only config and a
header-only CSV. That was a deliberate call rather than an oversight: scaffolding a config now
and placing cells later is a reasonable thing to want.

`CellCountsWindow` had no test coverage at all. The new tests cover `build_ic_dataframe`'s
zero/empty behavior and the placement gate logic (`_is_placeable`, `_refresh_continue_gate`),
following the existing unbound-call-with-stub pattern in `test_positions_plot.py`.

---

## 2026-08-02 (later): Domain editor — OK gating, extents, and honest defaults

Four related changes to `DomainEditorDialog` and `BiwtInput`.

**Nothing validated the bounds.** `DomainSpec` has no `__post_init__`, the dialog had no
`accept()` override, and the shared `QDoubleValidator` had no range — so `xmin > xmax` was
accepted verbatim and flowed into `plot_dx`, the placement scaling, and the emitted
`<x_min>/<x_max>`. An unparseable field silently became `0.0` in `result()`.

OK is now gated: disabled unless all six bounds parse and each minimum is strictly below its
maximum, with the offending fields flagged using `QLineEdit_custom.invalid_style`. Equality
counts as invalid — a zero-width axis divides by zero in the placement scaling and makes the
confluence counts meaningless. Cancel is deliberately left ungated so an unusable domain is
always escapable. With OK gated the `0.0` coercion became unreachable, so it now raises rather
than sitting there as a silent fallback.

**Extents are editable.** Width/height/depth rows, host units only — there is no data-units
counterpart because the factor already relates the two columns and z is never scaled. Editing
an extent moves the axis' **maximum** and anchors the minimum, so `x = [-300, 500]` with the
width set to 1000 becomes `[-300, 700]`.

The first attempt resized about the axis center, reasoning that simulation domains are usually
symmetric about the origin. That was the wrong instinct: centering means an extent edit moves
*both* bounds, so a minimum the user has just typed silently shifts when they then set the
width, and there is no way to specify "left edge here, this wide". Anchoring the minimum moves
exactly one field and makes the two independently settable. A symmetric domain stays symmetric
anyway if the user edits the bounds rather than the extent.

A side effect worth keeping: the maximum is written rather than read, so typing a width repairs
an unparseable maximum instead of refusing to act on it.

Bounds and extents write to each other, so `_syncing` guards against clobbering whichever side
the user is mid-keystroke on. Bound → extent runs off `textChanged` rather than `textEdited`,
because a bound also moves via the presets and the factor sync.

**`domain_accepted` was an override, not a default.** `_import_cb` OR-ed the host value with
the checkbox, and nothing ever seeded the checkbox from it — so a host passing `True` left the
user looking at an *unticked* "Skip domain validation" box that did nothing, with no way to get
the dialog back. The host value now sets the checkbox's initial state and the checkbox alone
decides. Same outcome for a host that sets it, but the user stays in control.

**`preferred_domain` now defaults.** `infer_domain` already falls back to `DomainSpec.default()`
internally, so requiring hosts to supply the same box was ceremony. It is now
`field(default_factory=...)`, which also retired a defensive `preferred is None` branch in
`_import_cb` that the type contract had made unreachable. Passing a real domain remains the
normal thing to do.

Test coverage went from nothing on this dialog to 24 cases in `test_gui_smoke.py`, which
already had the offscreen-QApplication harness. Confirmed load-bearing: neutering the gate
fails 9 of them.

---

## 2026-08-02 (later still): `output_csv_path` removed; two placement bugs fixed

**`BiwtResult.output_csv_path` is gone.** BIWT does not choose where output goes, so carrying
a path was state it had no claim to. `to_csv(path)` remains as a convenience but no longer
records anything. Checked before removing: Studio's `feature/biwt-package` bridge never reads
the field — it calls `result.to_csv(out_path)` with a path it already owns — so nothing on the
host side depends on it.

While tracing it, found `create_biwt_widget`'s module-docstring example still passing
`output_csv_path=` to `BiwtInput`, which has no such field and would raise `TypeError`. That
example renders on the API reference page. Fixed.

**`write_positions.py` deleted.** The 2026-03-29 host-owns-write change (below) unwired
`WritePositionsWindow` from `_step_predicates` and `_factories` and dropped `output_csv_path`
from `BiwtInput`, but left the module on disk and still exported from
`gui/windows/__init__.py`. It had been quietly broken ever since: line 30 read
`s.biwt_input.output_csv_path`, a field removed in that same change, so the window would have
raised `AttributeError` the moment anything constructed it. Nothing did. Beyond being dead, its
entire purpose — asking the user for an output path and writing the file — is the thing that
change existed to remove, so there was nothing to salvage. `s.output_written` went with it; it
had no other reader.

**Deconvolution tie-breaks were biased.** `max(priorities, key=priorities.get)` breaks ties by
dict insertion order, which traces back to `obs` column order. With two genuinely balanced
types and an odd `n_per_spot`, the first-listed type collected the surplus cell in *every*
spot — a tissue-wide population skew, not per-spot noise that averages out. Ties are now broken
at random among the tied set.

Rejected a per-spot rotation, which would also remove the skew and needs no RNG: spots are
usually ordered row-major, so alternating by index would paint a stripe or checkerboard
artifact across the tissue. Trading a population bias for a spatial one is a bad deal in
spatial data. The rest of the placement code already uses unseeded `np.random`, so this is
consistent with it, and tests pin it with `np.random.seed`.

The apportionment moved out of `_plot_spot_deconvolution` into
`core.positioning.apportion_spot_cells`. It was ~10 lines buried in a 90-line Qt method and
therefore untestable; it is the one genuinely non-obvious algorithm in the placement path, and
it belongs in `core` next to the other pure functions. Its docstring explains the shifted
divisor, since that is what stops every reference type getting a free cell in every spot.

**3-D spatial drag wrote into the wrong fields.** `_rect_helper` hard-coded parameter indices
0–3 as `(x0, y0, width, height)`. That is right in 2-D, but the 3-D layout is
`(x0, y0, z0, width, height, depth)` — so a ⇧-drag put the drag's x-span into `z0` and its
y-span into `width`. Only the spatial plotter could hit this, since it is the only one that
wires mouse handling in 3-D (the others are keyboard-only there), which is presumably why it
went unnoticed. The extent slots are now chosen by dimensionality; `z0` and `depth` are left as
typed, a drag being an xy-plane gesture.

---

## 2026-08-02 (release prep): v0.4.0 pre-tag audit

v0.4.0 is the version PhysiCell Studio will depend on, so the release was audited
rather than just tagged. `pyproject.toml` had already carried `version = "0.4.0"`
since the docs-site PR; PyPI's latest published version was still 0.3.1.

Verified before tagging, in order of how badly a failure would have hurt:

- **The built artifact, not just the source tree.** `python -m build` produced the
  wheel and sdist, and the wheel was installed into two clean venvs. Core-only
  install raises the intended docs-aware `ImportError` from `biwt.gui`; the
  `[gui]` extra imports `create_biwt_widget`, constructs
  `BiwtInput(preferred_domain=…, host_name="Studio")`, and loads all 29 templates.
  This is the check that matters most, because `pip install -e` masks
  package-data mistakes — and `cell_templates.toml` plus the seven icons are
  declared via `[tool.setuptools.package-data]` with no `MANIFEST.in` to back
  them up. Both are present in the wheel.
- **The Studio bridge against the *current* API.** `output_csv_path` was removed
  from `BiwtResult` in the previous session, so Studio's `bin/ics_tab.py` was
  re-checked: it never reads the field, and owns the output path itself. No
  host-side breakage.
- **CI on the exact commit that would be tagged**, including all four
  `seurat` / R jobs — not just the pip-only matrix.

**Left out of 0.4.0 deliberately:** PR #8 (parameter variation). It adds a whole
new wizard step and was last touched before the four PRs that landed after it,
so it has never run against current `main`. Shipping the reviewed, CI-green tree
to Studio beats bundling an unexercised step into the release Studio pins to.

**A version floor is a Studio-side gap, not a BIWT one.** Studio installs
`biwt` unpinned. `v0.3.1`'s `BiwtInput` already accepted `preferred_domain` and
`host_name`, so an unpinned install satisfies Studio's `HAVE_BIWT_PACKAGE` import
check with 0.3.1 and silently omits everything in 0.4.0 — the failure mode is a
user on a stale version with no error to show them. Wants `biwt>=0.4.0` in
Studio's docs and install dialog once 0.4.0 is published.

**Stale docs corrected.** The README claimed 98 tests (155), and listed
R-dependent `.rds` CI under *Remaining* even though `ci.yml` has run that conda-R
job across Python 3.9–3.12 for two sessions. The matching `TODO` in
`pyproject.toml` asked for the job that already exists; it is now a note
explaining why `seurat` is absent from the `dev` extra (pip cannot install R)
rather than a task. The README's *Completed* list had also not been backfilled
for the OK-gating, extents, apportionment tie-break, no-output-path, and 3-D
drag-slot work — the PRD had all of it, the README had none of it. Two `[x]`
items were sitting under a *Remaining* heading; moved.

`End-to-end manual testing with Studio` stays unchecked in both the README and
PRD F12. It is a genuine manual GUI test and nothing in this pass performed it.

---

## 2026-08-02 (later still, cont.): domain editor laid out per axis

Shipping in v0.4.0 — caught before the tag rather than after.

**The complaint was that width, height and depth looked misplaced, and they were.**
The grid was field-major: six label/value rows for the bounds, then the three
extents appended after all of them. `Width` therefore sat six rows below the
`X min` / `X max` that produce it, with the whole of Y and Z in between, and the
data-units column went empty for the last five rows so the bottom third was a
ragged L that read as unrelated trailing fields.

The values were right the whole time — this was purely placement.

**Root cause: nothing in the widget knew that width belonged to x.** `_ROWS` and
`_EXTENTS` were two independent flat lists, and the only place the pairing
existed was the `("Width", "width", "xmin", "xmax")` tuple, consumed by the
extent sync and never by the layout, which walked the two lists back-to-back
with `start=len(self._ROWS) + 1`. That offset is precisely how the extents ended
up stranded. Replaced by one `_DOMAIN_AXES` table of `_Axis` records that the
layout, the extent derivation and the bounds validation all iterate — the same
single-source-of-truth shape as `_step_predicates`. `_XY` is now derived from it
instead of spelled out, so it cannot drift.

**Layout is now axis-major**: one row per axis against ruled min / max / size
columns. Rejected keeping one row per field and merely moving each extent under
its own axis block — it puts width adjacent to X, but the dialog stays nine rows
tall and the data-units column keeps its five holes. Axis-major collapses it to
three rows and makes the pairing structural rather than adjacent, which is the
difference between "the reader can see the relationship" and "the code knows it".

**Both unit systems now live inside each cell**, host units leading with the
data-units mirror in parentheses, rather than as two separate column groups.
Host leads because it is the stored domain and what placement and `BiwtResult`
consume; the parenthetical is the annotation. This also filled the holes: the
extents gained a data-units mirror, which they never had.

Editing a data-units extent converts to host units and calls the existing
`_on_extent_edited` rather than reimplementing the rule. Worth the indirection:
"move the maximum, anchor the minimum" now has exactly one implementation and
cannot drift between the two columns. The new `_sync_du_extents(skip=...)` takes
the field being typed in, because the mirror must not rewrite it mid-keystroke —
the same hazard the `_syncing` guard already existed for. Data-units extents are
derived from the host span ÷ factor rather than by subtracting the data-units
bounds: a bound edit fires both `textEdited` and `textChanged`, and only the host
column is guaranteed written by then, so reading the mirror could lag a keystroke.

**Z keeps the widgets even though the factor does not apply to it.** First pass
omitted them, which is honest but left the Z row visibly shorter; z may well
become editable later, so the cells are built and disabled instead, and enabling
them is a matter of flipping `factor_scaled`. They needed `_LE_STYLE_INERT`: a
disabled `QLineEdit` carrying `_LE_STYLE` keeps its white background and reads as
empty-and-editable rather than switched off.

**Fixed field widths, not expanding.** A stretched field drags its closing
parenthesis away from the number it is wrapping; a stretch column at the end
soaks up the slack instead. That also brought the dialog back from 1067px to
694px.

**Rules were added after looking at it.** Six paired fields in a row cannot be
delimited by whitespace — without vertical and horizontal rules it was not
obvious where `min` stopped and `max` started. Separators live in their own grid
tracks, so data columns keep even indices and axis rows keep even rows.

The 25 existing tests needed no changes: they address widgets by dict key, never
by grid position. One `test_gui_smoke` assertion did change, because the two
column headers became a single legend. The guard worth having is the new
`test_extent_shares_its_axis_row` — it asserts the axis-major invariant against
the real `QGridLayout`, so "width goes with x" is enforced rather than incidental.
That is the check the 3-D `_rect_helper` slot bug never had.

The docs screenshot was regenerated. It had been stale for two features — it
still showed the dialog with no extent rows at all.

### Screenshot handling, and a trap in it

The docs screenshots are normalized with `sips -Z 1600 <files>`, which caps the
longest side at 1600. That is why exactly four of them are 1600 px wide and
carry a compact ~344-byte sRGB `iCCP` — sips re-encodes on resize. The other
five were already under the cap and were left as raw captures.

**`-Z` scales up as well as down.** It sets the maximum dimension rather than
capping it, so running it on a capture already below 1600 *inflates* the image:
the new 1582×1016 domain screenshot went to 1600×1027 and **338 KB → 405 KB**,
with the text interpolated and softened. Only run it on captures wider than
1600.

**A marginal overshoot is not worth the cap either.** The same re-encode that
inflates an under-cap image also inflates one barely over it, and there is no
pixel saving to pay for it: `cell-counts-confluence` at 1604×808 went **296 KB
→ 349 KB** for a four-pixel trim, text interpolated. It is committed at its
native 1604 and will read as over the cap to anything that checks — that is
deliberate. The cap earns its keep on a real overshoot, where the two positions
captures came down 38% and 41% from 2528.

For a capture already under the cap, the win is metadata, not pixels. A raw
`screencapture` PNG carries a ~3 KB Display-P3 ICC profile plus `cICP`, `eXIf`,
`pHYs`, an XMP packet and Apple's `iDOT` chunk, and writes IDAT in 16 KB pieces.
Stripping those and converting P3 → sRGB took the domain screenshot to 216 KB
with dimensions and alpha untouched. Converting rather than relabelling is the
point: these are shots of a Qt UI specified in sRGB, so a P3-tagged file that
browsers render as sRGB is the one case where the pixels are genuinely wrong.

A script for that was written and then dropped — `sips` is the established tool
here and a second one competing with it is worse than a note. If it is ever
needed again, beware that littleCMS stamps wall-clock time into the ICC header,
so the profile must have its creation timestamp zeroed or every re-run churns
the file with identical pixels.

### Follow-up: the factor field had three defects behind it

Found by looking at the real dialog on the test dataset, plus a Copilot review
note on PR #16. The paired layout did not cause all of these — it made them
visible, which is a point in its favor.

**1. Size mirrors ignored the factor.** `_on_factor_changed` synced the bound
mirrors and not the extent mirrors, so changing the factor updated `min` and
`max` on the data-units side while `size` kept a span computed with the previous
factor. Introduced with the mirrors themselves in this branch. The screenshots
show it plainly: bounds at ±2000 for a factor of 0.1, size still reading the old
value.

**2. Mirrors kept stale values when the factor went away.** `_sync_du_from_host`
returned early on `F is None`, leaving whatever was last written. Disabling a
field does not unsay its contents — a greyed cell showing `-400` still claims a
conversion that no longer exists. It now clears, and so does the case of an
unparseable *bound*, for the same reason.

**3. An empty factor field silently fell back to the file value.** This one was
pre-existing and deliberate — `_effective_factor`'s docstring said "the field
value if valid, else the file value" — but it made a file factor unclearable.
↺ was the only route back to the file value, and ↺ *disabled itself* when the
field was empty because empty already matched the file. So three widgets
disagreed at once: a blank field, live mirrors, and a greyed-out restore button.
There was no way to say "do not scale this data" about a Visium file.

Empty now means none. ↺ is the single way back to the file value and is enabled
whenever the field differs from it, empty included. The placeholder had been
lying — it read `none found in file` unconditionally, even when the file
*did* supply one and that value was in effect — and now states what empty means
and how to undo it: `none — ↺ restores 0.5`.

Rejected the smaller fix of keeping the fallback and only correcting the
placeholder to name the value in effect. It removes the lie but keeps the gap:
a factor that came from a file would still be permanent. `result()` now reports
`None` once cleared, so `session.scale_factor` is `None` and
`effective_scale()` returns 1.0 — placement falls back to the raw extent,
centered, which is what clearing the factor ought to mean.

Eight of the ten new tests were confirmed to fail against the pre-fix widget, so
they are guards rather than descriptions.

---

## 2026-08-11 — Host-owned cell templates, skippable parameters step, step-sequencing fix (v0.5.0)

Five requests in one branch, four of them pushing the same direction: BIWT should not know
about PhysiCell.

### The reported crash (and what it really was)

Repro: a Visium `.h5ad` with `*_probability` columns → answer **No** to spot deconvolution →
**Back** at the cluster-column step → answer **Yes** → a "Spatial Data" window appears that
should not exist on that path → Continue → `KeyError: None` in `collect_cell_type_data`.

Root cause was an ordering bug, not a predicate bug. `advance()` invalidates downstream session
state *after* the leaving window's `process_window` has already committed. The deconvolution
window committed three fields that `_STEP_FIELDS` assigns to *later* steps — `current_column`,
`cell_types_list_original`, `use_spatial_data` — so the invalidation wiped them the instant they
were written. Back was never required: toggling No→Yes on the first window (which sets
`stale_futures`) and clicking Continue reproduced it.

The fix draws a line that did not exist before:

- **`_STEP_FIELDS` = what the user chose. `reseed_derived_state()` = everything that follows
  from those choices.** Reseed is idempotent and total, runs at the end of
  `_invalidate_downstream_of` and again before every predicate evaluation, and must never
  overwrite a user decision. `cell_types_max` / `cell_prob_feature_dicts` moved out of
  `_STEP_FIELDS` into reseed's care; the "skip SpatialQuery fields when the data is
  non-spatial" special case in `_invalidate_downstream_of` was deleted, since reseed subsumes it.
- **`use_spatial_data` is now a derived property**, not a stored tri-state.
  `spatial_query_answer` holds the user's answer; the property folds in "deconvolution implies
  spatial" and "no coordinates means no". It therefore always returns a real `bool`, which also
  kills a latent `setChecked(None)` TypeError at `positions.py:352`. Three writers became one
  answer plus one derivation.
- The SpatialQuery predicate gained `not perform_spot_deconvolution`, so the spurious window is
  now unreachable rather than merely unlikely. The `"__spot_deconv__"` sentinel is gone — the
  ClusterColumn predicate already tested the flag, so the sentinel only ever existed to be
  wiped and then dereferenced.

Rejected: a per-window `commit()` hook called after invalidation. It does not fix the reported
symptom, because `use_spatial_data` was also written in the deconvolution window's constructor
and toggle handler, and it would need a two-phase `validate()`/`commit()` protocol across all
eight windows (two of them block advancing on validation failure).

### Three more bugs the work surfaced

1. **`apply_rename` was not idempotent under deconvolution** — silent data corruption. It
   rewrote `cell_prob_feature_dicts` in place while zipping against the *unfiltered*
   `spatial_data`, and the rename window calls it on every Continue. Second pass after a rename
   dropped every cell (`ValueError: zero-size array to reduction` downstream); second pass after
   any spot had been filtered paired every probability profile with the *wrong* coordinate, with
   no error at all. Now writes `cell_prob_feature_dicts_final` and never consumes its own
   output. `spatial_data_final` was also owned by no step; both are now in the RenameCellTypes
   bucket.
2. **Re-import left a dead window in the fresh history.** `_start_walkthrough` cleared the
   stacks but not `self.window`, so `advance()` pushed a window bound to the discarded session
   onto the new history — Go back would then show it reading the new session live.
3. **A numeric cell-type column silently dropped every cell.** `collect_cell_type_data`
   stringified the unique-label list but not the per-cell list, and the rename mapping is keyed
   by the former. Integer Leiden/Louvain cluster ids are a completely ordinary thing to select,
   and selecting one produced either an empty output or a crash. Found by the new ownership
   test walking a fixture with no categorical column.

The last one is a good argument for the test that found it: `TestStepFieldOwnership` drives the
real controller, snapshots `dataclasses.fields(session)` around each commit, and asserts no step
writes a field owned by a later step. The comparison window is deliberately narrow — from just
before `process_window` to the moment `advance()` is entered — so it excludes the *next* window's
constructor, which legitimately initializes its own fields after the invalidation. That
distinction cost two iterations to get right: a wider window flags `PositionsWindow`
initializing `coords_by_type`, and a rule of "≤ max(leaving, arriving) step" would have let the
original bug through.

### Cell parameters: names out, provenance in

`BiwtResult.cell_definitions_xml` is **removed**. `BiwtResult.cell_templates` maps each final
cell-type name to `(path, name, content)`. The shape was chosen over the two simpler
alternatives for one reason: the user can load their own template file mid-walkthrough, so a
bare template *name* is meaningless to a host that has never seen it, while content alone loses
which template was picked. Unassigned types are absent, so `{}` is normal — that is what Skip
produces.

- **BIWT ships no templates.** `cell_templates.toml` (2,902 lines, 29 PhysiCell phenotype
  blocks) and `xml_defaults.py` are deleted along with the whole `core/parameters/` subpackage,
  whose `__init__` docstring promised a template registry this change repudiates. A copy of the
  TOML went to `bin/BIWT_parameters/cell_templates.toml` in the Studio repo (untracked; the
  Studio session commits it). `load_templates_from_file` survives in the new
  `core/templates.py`, now rejecting non-string values — a stray `[section]` header nests
  everything after it, and that would have surfaced in the host long after the file left sight.
- All XML generation is gone: `_patch_domain_xml`, `_set_text`, the `_finish` assembly block and
  its three function-local imports, `_make_cell_definition` and its never-resetting
  `_cell_id_counter`. Worth noting what left with the last one: `except ET.ParseError: pass`
  silently emitted an empty `<cell_definition>` for a malformed template.
- The step is **always shown** (a user can always supply their own templates) and **always
  skippable**: a Skip button, a `(none)` row at the top of every dropdown, and no must-assign
  gate. Skip drives the dropdowns to `(none)` rather than writing `{}` directly — this is the
  last step, so Back-then-forward can bring the cached window back, and it must not display
  selections that contradict what was returned.
- `(none)` carries a distinct sentinel object, deliberately **not** `None`: `None` already means
  "section header, or a combo mid-rebuild", and conflating the two would make an explicit
  unassignment indistinguishable from no information — it would be dropped on every sort-mode
  switch. Pinning that row at index 0 in both modes also fixed a pre-existing wart, where By
  Source mode put a bold non-selectable header in row 0 that Qt auto-selected into every combo.
- Three session write sites collapsed to one `_sync_session()` that *rebuilds* the mapping from
  the dropdowns, guarded by a `_rebuilding` flag: `setCurrentIndex` does not signal when the
  index is unchanged, so an incremental writer can be left holding whatever the transient
  `clear()` produced.
- By Name labels now show the bare template name while one file is loaded and tag every entry
  with its source once two or more are — per the request, because with several libraries in play
  even a unique name leaves you asking which file supplied `TREM2+ M1 Macrophages` versus
  `TREM2+ Macrophages`.

### Name matching is the host's decision

Studio is implementing a `difflib` similarity check, and duplicating that rule here would be a
standing desync risk. So: `BiwtInput.name_matches` takes a `(str, str) -> bool` predicate and
**replaces BIWT's rule and its cutoff entirely**; `name_match_cutoff` (0.85) tunes only the
default. A predicate rather than a scorer, because "are these the same cell type?" is the
question the host actually answers.

One policy, both call sites: rename suggestions and template pre-selection now share
`best_match`, which replaces the old exact-then-bidirectional-substring rule at the rename step
(a short host name no longer matches everything containing it). Nothing tested
`suggest_name_mappings`, so that cost no test churn — only new tests.

The default gates on **equal digit runs** before scoring similarity, and that gate is
load-bearing rather than a refinement. At 0.85, similarity alone accepts `M1`/`M2 Macrophage`
(0.92), `CD4`/`CD8 T Cell` (0.90), `M0`/`M1 Macrophage` (0.87) and `Layer 2`/`Layer 6` (0.86),
while still admitting `Fibroblast`/`Fibroblasts` (0.95) and `Tumor`/`tumour` (0.91).

Known gap, documented rather than papered over: `PD-1hi CD137lo CD8 T Cell` and
`PD-1lo CD137lo CD8 T Cell` hold the *same* digits (1, 137, 8) and score 0.92, so they match.
The plan claimed the digit gate caught that pair; writing the test proved otherwise. Widening
the rule to hi/lo qualifiers was the wrong move — it would diverge from Studio's — so the gap is
named in the docstring, in a test, and in the handoff doc, where a host is pointed at
`name_matches` and told to import `default_name_matches` rather than copy it.

### Also

- `BiwtInput.extra_cell_template_paths` → `cell_template_paths` (it is not "extra" when it is
  the only source). `BiwtData.microns_per_data_unit` → `host_units_per_data_unit`; the Visium
  extractor keeps its name, since 55 µm/spot is an assay fact rather than a host convention.
- Numeric constants stayed out of scope by decision: `is_2d`'s 20 µm voxel, the ±10 µm z-slab,
  2494 µm³ cell volume, the hardcoded µm axis labels, and "PhysiCell" in the pyproject keywords.
- `docs/assets/screenshots/cell-parameters.png` deleted: it showed the removed experimental
  banner, `(built-in)` suffixes and a populated dropdown. Needs regenerating against the new
  window — `mkdocs build --strict` will not catch a stale image.
- `docs/integration/templates-and-matching.md` is the durable host-facing guide for the two
  jobs BIWT now declines: supplying a template library and owning the name-match rule. It
  carries the worked assembly example, the digit-rule table, and a short 0.4→0.5 delta for any
  host, not just Studio.
- The Studio-specific migration note lives at `host-migration-v0.5.md` in the repo root and is
  **gitignored** — it is an artifact to hand to the Studio session, not documentation. Anything
  in it worth keeping was folded into the page above.

### Not verified here

`mkdocs build --strict` could not run — mkdocs is not installed in this environment. The two
failure modes it would have caught were checked statically instead: every mkdocstrings target in
`docs/reference/` resolves against the real modules, every relative link under `docs/` points at
a file that exists, and every nav entry exists.

### Follow-up: matching against a library loaded mid-step

The first cut deliberately did *not* re-resolve defaults after a runtime file add, on the
grounds that a selection might be deliberate. That was too blunt — it meant a user who loaded
their own library got no matching against it at all, which is most of the value of loading one.

Now the window distinguishes rows the user **picked** from rows merely **showing a computed
value**, and a file load re-auto-matches only the latter. The distinction is free in Qt:
`QComboBox.activated` fires only for a real user pick, while `currentIndexChanged` also fires
for every programmatic one — so a sort-mode switch or a model rebuild cannot be mistaken for a
decision. Bulk **All to default** / **All to (none)** count as decisions; **Auto-match** clears
the record, because afterwards every row holds exactly what auto-matching computes and there is
nothing left to protect.

All three actions exist at both scopes: a "Set all:" row, and a compact `QToolButton` beside
each dropdown. I initially dropped the per-row buttons on a horizontal-space argument, which
was not mine to make — they were asked for explicitly, and the retraction case they cover
(*forget my pick on this row, follow the library*) has no other affordance, since a per-row
Auto-match is what removes that row from `_touched`.

Each pair shares a glyph — ⟳ recompute, ⌂ the `default` template, ∅ no template — defined once at
module level and used in both the bulk button and the row button, so the correspondence is
visible rather than only asserted in a tooltip. A test pins that pairing, because it is the kind
of thing that silently drifts when one label is reworded. Per-row tooltips name both the cell
type and the bulk button they mirror.

The middle action started as a star, which was wrong: both readings of ★ miss. "Favourite"
implies a user preference, but the button assigns a library template the user never marked;
"best" is nearly backwards, since `default` is the plainest fallback — what you get when nothing
matched. Rendered, it was also the heaviest mark in the row, drawing the eye to the least
consequential action. Candidates were mocked up side by side in the real widget (⟳ ★ ∅ / word /
⌂ / all-words / ✱ / ◉) and ⌂ was chosen: home reads as the baseline you return to. Worth noting
for future edits that ✱ reads as a wildcard and ◉ as "selected", so neither is a safe substitute.

While in that layout: the rows had been spread over the full height of the scroll area, so a
trailing `addStretch(1)` now packs them at the top.

Two earlier tests encoded the old never-re-resolve rule and were removed rather than adapted:
one asserted the whole mapping was unchanged after an add, and one used a programmatic
`setCurrentIndex` where it meant a user pick — which is now precisely the case the window
treats differently. `TestReMatchOnFileAdd` is the authoritative place for the merge semantics.

### Follow-up: library files come and go, and an ambiguous `default` is no default

Two decisions from review, both instances of the same principle — when the evidence is
ambiguous, withdraw rather than guess.

**A `default` defined by two loaded files means there is no default.** Previously
`_first_key_for_name` resolved it path-alphabetically, so the ⌂ action and the auto-match
fallback tier silently picked one library's baseline over the other's by a rule no user could
predict — the same silent-fallback shape that was just removed from the Studio config path. Now
the ⌂ buttons disable and the fallback tier drops. Two implementation notes worth keeping:

- The core function needed no signature change. `default_template_choices` already receives the
  template names as a *multiset* (`[name for name, _ in self._template_db]`), so
  `names.count(DEFAULT_TEMPLATE_NAME) == 1` is the whole test.
- A disabled control with no explanation reads as a bug, so the tooltip is swapped for the reason
  ("more than one loaded file defines a 'default' template — pick the one you want from the
  dropdown"). A test asserts the explanation, not just the disabled state.

Both templates stay individually selectable, labeled with their source, so nothing is lost —
which is what makes withdrawing the shortcut acceptable rather than obstructive.

**Template files can now be removed**, the host's own library included: what the host passes is a
starting point, not a fixture the user is stuck with. Removal shares one merge path with loading
(`_remerge`), so the touched rule governs both: untouched rows re-auto-match against whatever the
library now holds, picked rows keep their choice. The one case removal adds is a row whose
template just ceased to exist — there is no choice left to preserve, so it is dropped from
`_touched` and rejoins the re-matched rows rather than silently inheriting some other template
from the surviving files. A test pins that specifically, since "quietly substitutes a different
template" is the failure mode that would be hardest to notice.

Nice interaction between the two: removing one of two conflicting libraries resolves the
ambiguity and the ⌂ action comes back on its own.

### Follow-up: `reseed_derived_state` was half dead code

Review flagged the method as suspiciously specialized to spot deconvolution. Two of its branches
turned out to be dead, and both were the ones that made it look like it was policing spatial
policy in general:

- **`spatial_query_answer = False` for data with no coordinates.** Redundant. The
  `use_spatial_data` property short-circuits on `not data.has_spatial` *before* it ever reads the
  answer, and the SpatialQuery predicate requires `has_spatial` too — so the stored False changed
  nothing. The only other reference in `src/` is a comment.
- **Forcing `perform_spot_deconvolution` off when the data has no coordinates.** Unreachable. The
  flag is only written by `SpotDeconvolutionQueryWindow`, and that window is only built when the
  SpotDeconvQuery predicate fires, which requires `has_spatial`. The state it repaired cannot
  occur, so the repair was defensive code guarding an invariant the predicate already holds — and
  the test covering it was really testing the branch's own existence. Replaced with a test that
  the predicate never offers the step for non-spatial data.

What is left is the derivation that genuinely has to happen — the three probability-derived arrays
and the raw coordinates — and the reason it reads as deconvolution-heavy is that deconvolution is
the only answer in the walkthrough from which *bulk* data follows. That is now stated in the
docstring, so the next reader has the same question answered without re-deriving it.

The general lesson, worth remembering the next time this mechanism grows: a *logical* implication
("deconvolution means spatial is in use") wants a derived property, not stored state plus a
repair pass. Only a *computed* one — arrays over N spots — needs the repair pass at all.

A deeper refactor is available if this ever grows again, but it is blocked on one field rather
than on general effort, which is worth writing down.

`reseed_derived_state` derives **four** values. Three — `cell_types_max`,
`cell_prob_feature_dicts`, `spatial_data` — are pure functions of `data` (true of the first two
only since `apply_rename` stopped mutating its input), so each could be a `cached_property` keyed
on nothing: a new import builds a new session, so the cache can never go stale.

The fourth, `cell_types_list_original`, is not. It is computed two different ways —
from the probability *column names* when deconvolution is on, and from
`data.obs[current_column]` when it is off — so it depends on `current_column`, a user choice. A
data-keyed cache is simply wrong for it: change the column and the cached value is stale. And it
is the field the original crash was about, the one `EditCellTypesWindow` needs, so it is the
reason the repair pass exists at all. Converting the other three would therefore be 3/4 of the
work for none of the payoff: `reseed_derived_state` would still have to run to rebuild this one.

Converting it too means an uncached branching property, which drags `cell_types_original` along
(`[str(x) for x in data.obs[current_column]]`, O(N) per read and read in a loop by
`apply_rename`, so it wants caching keyed on `current_column`) — i.e. the repair pass is replaced
by a cache-key mechanism rather than by nothing. `collect_cell_type_data()` disappears with it,
and 23 call sites go: 20 in tests, plus `ClusterColumnWindow.process_window` and the
`_make_edit_cell_types` factory. Worth it only if a third concern lands in the repair pass.

### The version is now visible

`biwt.__version__` already existed, reading the installed distribution metadata so `pyproject.toml`
stays the single source. What was missing was anywhere a *person* could see it.

It now appears on the walkthrough's home screen, under the title. That is the surface that
matters: a host embeds BIWT as a tab, where the window title is never drawn, and the step windows
come and go — the home screen is the one thing that stays put. The window title carries it too,
which only helps standalone use. A test asserts both, because "the version label quietly stopped
rendering" is invisible until someone asks what version they are running.

Note the fallback: an uninstalled source tree reports `0.0.0+unknown` rather than guessing. That is
honest, and it is the ecosystem-standard behavior for metadata-derived versions.

### Checkpoint: row layout, library persistence, tied names, and an empty `cell_type_map`

**Row layouts were per-row HBoxes, so nothing lined up.** Reported from the rename step, where a
merged type is labeled with *every* original name that fed it: five merged Epithelial subtypes
produced a label wide enough to force a horizontal scrollbar, leaving that row's own field a stub
and every other row's field starting at a different x. Both the rename and cell-parameters steps
are now `QGridLayout`, so labels share a column, and generated labels go through a new
`elided_row_label` helper (`widgets.py`) that clips to a cap and puts the full text in the
tooltip. The cap is what bounds the window: it is now sized for the cap rather than for the text,
and the label column can no longer be dictated by one outlier. A trailing row stretch packs rows
at the top instead of spreading them down the viewport.

**A user-loaded template library was collateral damage of step invalidation.** It lived on the
window, and the window is rebuilt whenever the user goes back and changes an earlier step — so a
file they loaded silently vanished. The library now lives on the session
(`template_library_paths`), seeded once from `BiwtInput.cell_template_paths`, and is deliberately
*not* in `_STEP_FIELDS`: loading a library is an action, not an answer to a step. Only *Remove
templates from file…* takes a file out. Files are re-read on each rebuild, which also picks up
on-disk edits and drops a file that has become unreadable — `_load_template_file` returns the
absolute path or `None` so an unreadable one leaves the library rather than re-warning on every
rebuild.

**Tied template names are flagged rather than silently resolved.** Two libraries can both define
`Tumor`; matching then has two equally good candidates and breaks the tie by path order, which is
arbitrary from the user's side. The row's dropdown now carries a tooltip naming the file the shown
template came from and the others that define the name. A tooltip because it costs no layout, and
the dropdown label already shows *which* file won — only the existence of a contest had to be
added. This is the softer sibling of the `default` rule: a tie on `default` withdraws the action
entirely, because there the whole point is an unambiguous baseline; a tie on a matched name still
has a defensible answer, so it is annotated instead of withdrawn.

**`BiwtResult.cell_type_map` came back `{}` on every single run.** `_finish` read
`session.cell_type_config.resolve()`, and `cell_type_config` was a `CellTypeConfig` that nothing
ever populated — the session comment admitted as much ("new-style, not yet fully wired") while the
real decisions sat in `cell_type_dict_on_rename`. The docs promised an audit trail from every
original label to its final name; the code returned an empty dict. Now
`WalkthroughSession.resolved_cell_type_map()` builds it from the decisions the walkthrough
actually records, and the never-populated field is deleted so the same trap cannot be re-set.
`CellTypeConfig` / `CellTypeAction` survive in `core/cell_types.py`, tested and documented, but
are now used by nothing — worth either wiring into the edit step or dropping.

Two lessons from how this one was found: it was visible in the `BiwtResult` repr I printed during
my own end-to-end verification and I read straight past it, and no test asserted on
`cell_type_map` at all — `_finish` was covered for coordinates and templates only. There are now
tests at both levels.

**The Qt test suite was segfaulting.** Not one bad module: dropping *any* of three made it go
away, which is the signature of a cumulative resource problem. Qt keeps every top-level widget
alive until something destroys it, and these tests build walkthrough windows (with matplotlib
canvases) per test and never destroyed theirs. Past a few hundred, the offscreen platform faults —
in whichever module happens to run next, which is what made it look like an unrelated regression
in the navigation tests. Fixed once, in `conftest.py`: an autouse `_reap_widgets` fixture destroys
leftover top-level widgets after every test. Autouse so no module has to remember and adding one
cannot reintroduce it. Suite verified stable across repeated runs.

### Small corrections from review

- Per-row button tooltips were verbose ("Auto-match Tumor — same as Set all: Auto-match, for this
  type only"). They now say only what the button does: **Auto-match**, **Assign default**,
  **Assign (none)**. The "Set all" row directly above pairs the same three glyphs with words, so a
  row tooltip does not have to re-explain the pairing or repeat which cell type it sits beside. The
  third reads "Assign (none)" rather than "No template" to stay parallel with "Assign default" and
  to name the dropdown entry it actually selects. The *disabled* default tooltip stays long — an
  explanation of why a control is unavailable earns its length.
- The Studio handoff note claimed a host might have "worked around" the empty `cell_type_map` and
  that such a workaround would now be wrong. Invented: Studio's `_biwt_complete` only ever read
  `coordinates`, `to_csv` and the XML field. Corrected to say plainly that nothing breaks and the
  field is simply worth using now.

### The tie notice became a dismissible marker

The tooltip-only version was invisible until hovered, which is a poor flag. Rows whose template
name is shared now carry an **ⓘ** in a narrow column of their own, with the same text as the
dropdown's tooltip. Informational rather than a warning glyph: the selection is perfectly valid,
there simply happened to be more than one candidate.

Clicking it hides it, and that is deliberately not remembered. `_refresh_row_flags` recomputes
every row's flag from scratch on each call — any selection change, library change or sort switch —
so a dismissed marker returns if the row is still ambiguous, and disappears for good once it is
not. Per-row "already silenced for this selection" state would cost more than the notice is worth.

One layout snag on the way: `row_label` set `wordWrap` on every label, and a wrapped QLabel will
shrink to its longest *word*, so short labels started breaking before the ⇒ once the marker column
took its 20 px. Wrapping is now applied only to labels that actually exceed the cap, and those get
a fixed width so the column cannot collapse under them.

The notice text then went through two more passes, both cutting:

- It said "'Tumor' is defined by more than one loaded file. This is the one from templates_a.toml;
  also available from templates_b.toml." Everything before the last clause is on screen already —
  the dropdown label reads `Tumor (templates_a.toml)`. Now: `'Tumor' also defined by
  templates_b.toml.`
- It lived on both the dropdown and the marker. The marker *is* the notice — visible without
  hovering anything — so the dropdown's copy was one sentence too many and is gone.

The `⇒` then had to leave the label. Appended as a suffix it rode along to the end of the last
wrapped line, so on a merged row it sat several lines below the field it points at. It is now
`row_arrow()` in a column of its own between label and field, vertically centered — which also
means the label helper no longer takes a `suffix`, and the two windows gained a column each. A
geometry test pins the arrow to the vertical center of its field and to the left of it.

### Long names, everywhere they land

Reported from the positions window: a cell type renamed to a 100-character string ran its
checkbox off the edge of the panel. The question raised was whether to build a scrollable label.

**No** — a scroll area per row means a dozen tiny scrollbars nobody thinks to drag, and it still
hides the text. Two shared primitives instead, both in `widgets.py`, chosen by whether the widget
can wrap:

- `row_label(text)` — wraps within a capped column, so every character stays on screen and the row
  grows taller rather than the window growing wider. For `QLabel`s in a grid or column layout: the
  rename step, the cell-parameters step, and now the cell-counts name column.
- `set_elided_text(widget, text, suffix="")` — clips and puts the full name in the tooltip, for
  widgets whose text **cannot** wrap. `QCheckBox` is the whole reason it exists: the positions
  step's cell-type list and the edit step's keep/merge/delete list.

The `suffix` argument is not decoration. The edit step appends `⇒ Merge Gp. #2` to a checkbox and
later reads that annotation *back off the label* to decide whether dissolving a merge partner is
needed, so clipping had to be applied to the name and the annotation appended after — otherwise a
long name would have silently eaten the suffix and changed behavior. (That code reading display
text as state is fragile independent of this change and worth revisiting.)

Also confirmed while here: the arrow-column fix from the previous entry did apply to the
cell-parameters step. A 100-character name there wraps and the ⇒ sits beside the dropdown with
matching vertical centers — the screenshot that prompted the question predated the change.

### Display text as state, in the edit step

`_set_keep` decided whether a type was leaving a merge group by asking its checkbox:
`if "⇒ Merge Gp." in old_text`. That is why the elision work had to append the annotation *after*
clipping — the label had quietly become load-bearing.

The reason it was written that way is more interesting than the smell: **the session dict cannot
express group membership.** `cell_type_dict_on_edit` maps original → intermediate, and a group's
first member maps to *itself* — byte for byte what a kept type looks like. So state alone genuinely
could not tell "kept" from "leader of a merge group", and the label was the only place that
distinction was recorded. Fixed by recording it: `self._merge_group: dict[str, int]`, cell type →
group id, window state rather than session state. The label is now write-only.

Two things worth recording about the fix itself:

**I chased a case that cannot happen, twice.** With group ids in hand, re-merging an
already-merged type looked like it needed handling: first as "dissolve the partner it strands"
(wrong — the old mapping had all three merged the whole time, so that would have ejected a type from
a merge the user made), then as "absorb the old group" (harmless, but pointless). Both were dead
code. `_merge_cb` disables a merged type's checkbox, and the only way out of a group is that type's
own Keep button, which removes it from the group first — so a type can never belong to two groups,
and the reconciliation had no reachable trigger. My tests only reached it because
`setChecked(True)` works on a disabled widget when called from code.

The mistake underneath was a level confusion: I reasoned about a transition of the *mapping* while
the *GUI* already made that transition unreachable. Same lesson as the reseed branches earlier in
this branch — check what guards the state before writing code to repair it. The absorption block is
gone, and the tests that replaced it assert the guard instead: merging disables the checkbox, Keep
is the only way back and re-enables it, and no type ever holds two group ids.

**The reversion check on the new tests was not evidence.** Stashing the source and re-running them
produced eight failures, but on `AttributeError: _merge_group` — they fail because they reference the
new attribute, not because they caught the old behavior. The one honest claim about the old label
read is narrower than it looks, too: a cell type *named* "Tumor ⇒ Merge Gp. #1" would have been
misread as merged, but `_dissolve_solo_merge_partner` then finds no partners and no-ops, so the
misreading was harmless. The real argument for this change is the coupling, not a live bug.

### The landing window

Three changes, from a review of a screen that was mostly empty space and a sentence.

**Format chips that carry information.** The static "Supported formats: …" line is now a chip per
format showing whether *this environment* can read it, from
`core.data_loader.supported_formats()` — `FormatSupport` probes with
`importlib.util.find_spec`, so asking costs nothing and imports nothing. An unavailable format's
tooltip names the missing module, the pip extra, and the install docs. This matters because the
alternative is what BIWT did before: click Import, pick an `.rds`, and learn from an error dialog
that the R stack is missing. The dev environment this was written in is itself an example —
`anndata2ri` is absent, so the `.rds` chip renders red.

**The dead space became a drop target.** The screen reserved a large empty band between two
stretches; it is now a dashed frame holding the Import button, accepting a dragged file. A drag is
only accepted for a single local file with a supported extension, so an unusable drag never
highlights the target. `_import_cb` was split so the button and the drop share one `_import_file`.

**The two pre-answers are grouped and honest.** "Skip domain validation **on import**" was
factually wrong — `domain_accepted` is read at the *positions* step, nowhere near import. And it
was not the only pre-answer: the cell-type column hint silently makes the cluster-column step
auto-continue, skipping a step with no indication. Both now sit under a **Shortcuts** header with a
caption naming what each one skips.

**Rejected: more pre-answers to speed-run the wizard.** Every remaining question is
*data-dependent* — has this file coordinates, probability columns, which column holds the labels —
so answering before the file is open means guessing, and a wrong guess silently changes behavior.
The real bottleneck is getting the file in, which is what the drop zone addresses.

### Dropping template libraries, and what that means off the desktop

The cell-parameters step now takes dropped `.toml` files, several at once, and the Add dialog
became multi-select to match. Both go through one `_add_template_files`, which loads everything and
then re-matches **once** — not per file, or a type could be decided by the first library and left
there when a better match arrives in the same drop. A test covers exactly that.

Unlike the landing screen's data-file drop, several at a time is the point here: libraries
accumulate, where a second data file would replace the session.

**The Galaxy question, checked rather than assumed.** Studio already runs there, and its
`bin/galaxy_functions.py` shows the model: the user gives a dataset id, `galaxy_ie_helpers.get()`
pulls that dataset from the history *into the container's working directory* (which is why the
Galaxy panel prints `pwd:`), and the app then opens it by path. `put()` sends results back. So:

- The GUI is streamed from a container. A drag from the user's own desktop never reaches it —
  no drop event arrives at all. Not broken, just inert.
- `QFileDialog` still works, but browses the **server's** filesystem: the container, where
  `get()` deposits datasets. That makes the button the only route there, which is why the drop
  is strictly additive and the button was never replaced by a drop zone.
- The cleanest Galaxy path is the one the API already supports: the host stages the file and
  passes it in `cell_template_paths`.

One wrinkle worth remembering: staged Galaxy datasets have opaque names, so the source labels BIWT
derives from basenames (`dataset_47.dat`) would be unhelpful there. A host-supplied display name
per library would fix it — not built, not needed until someone runs this in Galaxy for real.

### Disabled controls stopped looking disabled inside Studio

Reported from a real Studio run: the ⌂ button does not grey out when it is disabled, and the row
buttons generally look like the host's, not BIWT's.

The cause is not the host stylesheet, which is what it looked like. `bin/studio.py` calls

```python
palette.setColor(QPalette.ButtonText, Qt.black)
palette.setColor(QPalette.WindowText, Qt.black)
studio_app.setPalette(palette)
```

and `QPalette.setColor(role, color)` with **no ColorGroup argument sets every group** — `Active`,
`Inactive` *and* `Disabled`. So disabled button and checkbox text is painted the same black as
enabled, and Qt's usual way of showing "you cannot use this" is gone for every widget in the
application. BIWT relies on that state in several places: a merged cell type's checkbox, the
`Remove templates` button with nothing loaded, and the ⌂ actions when no library defines a
`default` (or two do).

Fixed by not depending on the ambient palette. `base.py` now carries a `_WINDOW_STYLE` with
explicit `:disabled` rules, applied to every step window, and the per-row buttons set their own
stylesheet — which outranks both the window rule and anything the host installed. Widgets that
already style themselves (the green nav buttons, the keep/merge/delete colors) still win, as they
should.

Two things worth recording:

- **Studio's app stylesheet is also malformed**: `"QLineEdit { background-color: white };"` has a
  stray `;` after the closing brace, which is what prints *"Could not parse application
  stylesheet"* at startup — visible in the screenshot that opened this whole branch. It is likely
  discarded wholesale, which is why the palette was the culprit rather than the stylesheet.
- **The test that proves this is a pixel comparison**, not a stylesheet-string assertion: render
  the button enabled and disabled under a Studio-like palette and require the images to differ.
  Stripping the fix fails exactly one of the three — the row `QToolButton`. The two `QPushButton`
  cases pass either way on this platform style, so they are guards on what the user must see
  rather than evidence the rules are load-bearing.

### The row glyphs, measured instead of guessed

The house was unidentifiable at row scale — it reads as a small triangle. Replaced with a **gear**,
which is both distinctive and apt: a template *is* a parameter set. (Third glyph for this action;
the star before it was wrong for meaning, the house for legibility.)

Two things came out of making them bigger without letting the rows grow:

- **The buttons are pinned to their dropdown's height** (`dd.sizeHint().height()`, passed into
  `_row_action`), so the glyph can be set as large as fits without the row expanding to
  accommodate it. Row pitch is unchanged at 34 px, verified by rendering.
- **The first font bump did nothing at all.** `font-size: 17px` produced pixel-identical output to
  the inherited size — measured by counting ink pixels, not by looking. Measuring each candidate
  size gave the real answer: 24px is the largest that keeps a margin inside a 30x28 button, with
  the widest glyph (∅) reaching 18x19 px. There is now a test comparing rendered ink against a
  button styled identically *minus* the font rule, so a future no-op change cannot pass unnoticed.

### From glyphs to packaged icons

Enlarging the text glyphs fixed legibility and exposed the deeper problem: the three marks are
drawn by *different fonts*. Whatever the fallback chain hands back for ⟳, ⚙ and ∅ has its own
metrics, so at one nominal size they rendered 13x11, 14x15 and 18x19 — visibly mismatched, and
liable to differ again inside an embedding application, which is where it was reported from.

They are now three packaged SVGs (`gui/icons/action_*.svg`), loaded through a new
`widgets.action_icon()`. SVG rather than PNG for two reasons: it stays crisp on a HiDPI screen
without a second @2x asset, and it is already the house convention — the positions step's plotter
buttons load `gui/icons/*.svg` the same way, and `pyproject.toml` already ships that directory.

Both scopes use the same icon, so the row button and its "Set all" counterpart still pair visibly.
The size is one constant (20 px inside the 30x28 button, still pinned to the dropdown height, row
pitch unchanged at 34).

The `default` action's icon is a **house inside a ring**. The ring is the point: it gives this icon
the same circular silhouette as the circular arrow and the slashed circle, so the three read as one
set. The house is deliberately small — a first attempt filled the ring and turned into a dark blob
at 20 px, which is the size it is actually used at. Chosen by rendering candidates at real size next
to a 5x magnification and comparing, not by eyeballing the source.

Three tests replaced the ones that asserted on glyph text: every action icon loads (a missing SVG
gives a null QIcon and a *blank* button, which nothing else here would notice), the three render
differently from each other (the copy-paste failure), and each row button's icon renders
pixel-identically to its bulk counterpart's. The disabled-state pixel test needed no change and
still passes, which was the open question in moving from styled text to icons — Qt's generated
disabled pixmap stays distinguishable under Studio's flattened palette.

The guide embeds the icons in its action table rather than naming them in words, so the page shows
what the button shows. Two details worth keeping in mind:

- **Markdown image syntax, not raw `<img>`.** mkdocs rewrites relative paths in markdown links and
  images to suit directory URLs; it passes raw HTML `src` through verbatim, so an `<img>` needs the
  path the *served* page will use (`../../assets/...`) while the markdown form takes the path the
  *source tree* uses (`../assets/...`). The latter is what a source-tree link checker can verify, and
  `attr_list` is already enabled so `{ width="20" }` sizes it.
- **The docs keep their own copy** under `docs/assets/icons/`, because mkdocs only serves files
  inside `docs/`. A test asserts the copies are byte-identical to the packaged originals and names
  the `cp` that fixes it, so editing an icon cannot leave the guide showing the old one.

  Two copies is not ideal and the alternatives were weighed. A `on_files` mkdocs **hook** could
  register the packaged icons into the build, giving one source of truth — but the icons have to end
  up in the `Files` collection rather than merely copied, or `mkdocs build --strict` fails link
  validation on the markdown references, and mkdocs is not installed in this environment so that
  cannot be verified here. `pymdownx.snippets` (already enabled) could inline the SVG source, but a
  table cell must stay on one line, so the SVGs would have to be single-line files — unreadable and
  uncommentable. A symlink is fragile and worse on Windows. Three ~500-byte files with a hard test
  beats an unverifiable build hook; worth revisiting when someone has a docs build in front of them.

### Two fixes from a Studio run

**The ambiguous-`default` tooltip was too wordy.** Now: "Multiple 'default' templates found.
Manually select which template to apply." The long version explained the mechanism; the short one
says what happened and what to do.

**By Source mode lost the source.** Its items were bare names under per-file headers, which reads
fine while the list is open and loses everything the moment it closes: a `QComboBox` displays only
the current *item's* text, never the group header it sat under. So a template picked in By Source
mode showed as plain `default`, with no way to tell which of two libraries it came from — visible in
the two screenshots side by side.

First fix was to suffix the By Source items too, which works but clutters a list whose headers
already name the file. The better answer was suggested in review: let the popup and the closed box
say different things. Qt paints a closed combo from `currentText()`, but `paintEvent` is
overridable, so `gui.widgets.RelabelledComboBox` takes a `display_for_index` callable and swaps
`QStyleOptionComboBox.currentText` before drawing. The popup keeps `Tumor` under a
`templates_a.toml` header; the box reads `Tumor (templates_a.toml)`. Nothing else changes — the
model, the signals and `currentText()` are untouched, so no slot had to be disconnected and the
selection logic is unaffected. (The other route, `setEditable(True)` with a read-only line edit,
also works but changes the widget's whole appearance on macOS.)

A test compares the rendered pixels against a plain combo holding the *item's* text, because
`displayed_text()` could return the right string while `paintEvent` still drew the model's.

Worth noting how nearly this went wrong: the first patch attempt silently did nothing, because the
indent in `QStandardItem(f"\u2003{name}")` is an em-space and my match pattern used a regular one.
`str.replace` does not complain about a pattern it never finds. The behavior test caught it, then
the *same* mistake appeared in the test's own assertion — an argument for asserting on behavior
(`currentText()`) rather than on markup whenever there is a choice.

The em-space in `QStandardItem(f"\u2003{name}")` defeated `str.replace` **three times** in a row
while editing that line — a literal em-space in a search pattern is invisible next to a regular
one, and `str.replace` reports success when it matches nothing. Matching on the surrounding
expression with a regex, and asserting on behavior rather than markup, are the two habits that
caught it each time.

### Right-aligning the source

Asked for in review, and once the paint is already ours it is only a layout: draw the frame from the
style with an empty label, take the `SC_ComboBoxEditField` rect, then the template name
left-aligned and the source right-aligned in grey. The sources then line up down the column, which
is what makes two libraries comparable at a glance.

The interesting part is the question that came with it — what happens when the box is too narrow.
The rule: **the source goes, the name stays.** The name identifies the choice; a path elided to
`templ…` qualifies nothing, so spending the last pixels on it is worse than dropping it. The
qualifier only earns its place while the name still has room to be legible (a six-character floor),
and below that the name itself elides and takes the whole field.

That decision lives in `text_layout(width)`, a pure function returning the two strings that will be
drawn, so the rule is tested at four widths without rendering anything. The painting then has no
logic left in it worth testing beyond "it draws what text_layout said", which one pixel comparison
covers.

### `domain_used.source` was lying

Reported from a Studio run: the emitted domain came back as `user_edited` with the *data* extent,
after the user had merely pressed Enter on the domain dialog without touching anything. Two
separate defects, and the report caught both at once.

**`result()` hardcoded `source="user_edited"`.** Every accepted domain claimed the user had edited
it. That is not a cosmetic mislabel: `docs/integration/api-contract.md` tells a host to check
`source != "preferred"` to learn whether its own domain survived the walkthrough, and after this
dialog the answer was unconditionally yes. The field was unfalsifiable. It is now derived from the
bounds — `"preferred"` if they match the host's domain, `"data_range"` if they match the data extent
in host units, `"user_edited"` only if neither. `"preferred"` takes precedence where the two
coincide, since the host's domain did in fact survive. The comparison tolerance covers the round
trip through the fields: `%g` keeps six significant digits, so a value merely displayed and read
back differs by at most a relative 5e-7.

**`user_edited` was never documented.** It appears in neither `DomainSpec`'s docstring nor the
api-contract table, both of which listed only preferred / anndata_metadata / data_range / default.
A host reading the docs had no reason to expect the value it was actually receiving. Added to both.

The remaining question is a product decision, not a bug: on first open the dialog pre-fills from the
data, and `QDialogButtonBox.Ok` is the default button, so **Enter adopts the data extent**. That is
defensible — the dialog only appears when the domains mismatch, and the data extent is usually the
fix — but it means dismissing an unread dialog silently replaces the host's configured domain. With
the source now honest, a host can at least see that it happened; whether Enter should instead be a
no-op (pre-fill the host domain, make "Use Data Domain" the deliberate act) is left to the
maintainer.

### Three answers, three words: `host` / `data` / `user`

That open question got answered, and the vocabulary got cut down with it.

**The pre-fill now depends on whether the data has a say.** Spatial coordinates in use → the dialog
opens on the data extent, because that is the domain the cells actually occupy and adopting it is
almost always the fix. No spatial data → it opens on the host's domain, because a computed extent
from scaled non-spatial layout is not a meaningful box to hand someone as a default. Enter is still
Ok, so in both cases pressing it accepts something sensible rather than something arbitrary — which
was the actual complaint, not the label. Carried by a new `initial_preset` argument, so the auto-open
on domain mismatch and the manual open from the button can differ if they ever need to.

**Four source values, one of them redundant.** `anndata_metadata` and `data_range` are both "the
data's own extent" — they differ only in *how* BIWT found it, which no host has a decision to make
about. Collapsed to `data`. `preferred` named the field it arrived in rather than who supplied it;
`user_edited` was a verb phrase where the other three were nouns. The vocabulary is now `host` /
`data` / `user`, plus `default` for the fallback box when nobody supplied anything — and
`biwt.types.DomainSource` names them so no host has to type the strings.

Three values because there are exactly three answers a host can act on: your domain survived, the
user took the data's instead, or the user typed something else. Two spellings of the second one is a
distinction that exists in BIWT's implementation and nowhere in the host's decision.

### A `NameError` that 473 passing tests could not see

Caught in a live Studio run, not by the suite: `positions.py` used `DomainSource` in
`_maybe_show_domain_editor` without importing it. Fixed by the obvious one-line import — the
interesting part is why the suite was blind to it.

`PositionsWindow.__init__` can open a modal dialog, so **every test deliberately stops short of
building it** (`test_walkthrough_nav.py` names the reason in a comment). That exemption made an
entire module's method bodies unreachable, and an undefined name inside them is a runtime error with
no test to trip it. The gap was in the harness, not the coverage count.

Two guards, because the two failure modes are different sizes:

**`tests/test_static_checks.py`** runs pyflakes' name resolution over every module in the package
and fails on `UndefinedName` / `UndefinedLocal` / `UndefinedExport` only. Style messages are
excluded on purpose — unused imports are an opinion, an undefined name is a crash. This is the
general fix: it does not care which lines tests can reach, so it covers every method body BIWT will
ever have, including the ones no harness can construct. Verified against the actual defect: all four
call sites reported.

**`TestPositionsDomainAutoShow`** in `test_walkthrough_nav.py` removes the exemption instead of
working around it. Patching `DomainEditorDialog.exec_` to return `Rejected` costs one line and makes
the modal harmless, so the step is now walked for real — and while there, it pins the behavior from
the previous entry: the auto-shown editor pre-fills the data extent and reports `DATA`.

Writing the paired negative test surfaced a rule worth restating: a domain mismatch is not only
"the data escapes the box". `classify_domain_mismatch` also flags `"small"`, so 400 µm of cells in a
±500 µm domain opens the dialog — sparse is a mismatch too. My first attempt at "no dialog when the
data fits" asserted against that and failed correctly.

### The host boundary had one entry point and no clock

Asked directly: is `create_biwt_widget` the only thing a host calls, given the domain it takes can
change between building the tab and running the walkthrough? Yes — and the answer turned out to be
about *when* a value is read, not which values exist.

**The failure is structural on the host side.** Studio builds the BIWT tab in `ICs.__init__`,
which runs from `PhysiCellXMLCreator.__init__` before the main window is ever shown, and nothing
rebuilds it for the life of the process — not File>Open, not a sample-model load. On `development`
the `BiwtInput` is a *local variable*, so it is not merely unrefreshed, it is unrefreshable. Fifteen
seconds of ordinary use reaches it: launch, type `xmax = 2000` on Config Basics, go to ICs → BIWT,
import. Six domain `QLineEdit`s with no change signals, an `xml_root` that holds the on-disk bounds
until a save, and no hook that means "the user is about to run BIWT."

**Six of seven fields were already read lazily**, off `session.biwt_input` at the point of use, so
the plumbing was nearly there. What was missing was a sanctioned way to change the object — and a
guarantee about what happens when someone does.

**Chosen: a provider callable, pulled once per run.** `create_biwt_widget` now takes a `BiwtInput`
*or* a zero-argument callable returning one. Pull rather than push, because push asks the host a
question it cannot answer here — there is no event that means "now" — while BIWT knows exactly one
moment when a fresh answer is both needed and safe to take: the import. Two resolution points
(construction, which only seeds the domain-check checkbox; and each successful import), and nothing
in between. The Studio delta is negative: the companion session's `refresh_biwt_input`, its six
`textChanged` connects, its stored input and its `reset_info` hook all delete, and with them the
torn-read defense their own comment describes (pairing a new `xmin` with an old `xmax`) — a pull at
import has no torn read to defend against.

**The snapshot is the other half, and it closed a live bug.** `BiwtInput.snapshot()` copies
`preferred_domain` and both lists, so a host editing its own `DomainSpec` in place cannot rewrite a
domain the run already placed cells into. Demonstrated before fixing: mutating the host's spec set
`domain_used.xmax` to 9999 *after* the coordinates were computed, so the result asserted that
domain and coordinates agreed when they did not.

**And it removed a second name for the same thing.** `session.inferred_domain` latched the host's
domain at import while `session.preferred_domain` read it live — and `_maybe_show_domain_editor`
feeds *one* dialog invocation from both, the mismatch warning from the latched copy and the
"Use <host> Domain" preset and `_source_of` from the live one. Any host refresh made them disagree:

    after import:       preferred=(-500, 500)   effective=(-500, 500)
    after host refresh: preferred=(-2000, 2000) effective=(-500, 500)

That is the same class of lie in `domain_used.source` as the previous entry, re-entering through the
refresh path. `inferred_domain` was a pure duplicate — one writer, two readers — so it is gone and
`effective_domain` is `user_domain or preferred_domain`. Note the test that had been setting it
passed anyway: a plain dataclass accepts an unknown attribute without complaint, so the assertion
was exercising a field that no longer existed. The replacement asserts `hasattr` is false.

**What freezing costs, stated rather than hidden:** a host edit during a run is invisible until the
next import, and `domain_accepted` is honored only at construction. Both are deliberate — the first
is what makes the warning, the placement and `domain_used` describe one box; the second keeps the
checkbox authoritative, since it is on screen by then.

**One correction shipped with it.** `celldef_tab.get_cell_type_names()` appeared in BIWT's own
module docstring and in the handoff doc as the way a host reads its cell types. It does not exist in
Studio — it never did. The real accessor is `celldef_tab.param_d.keys()`. An illustrative example
invented an API and then got quoted as though it were one.

### The host's own cell types are answers too

Asked for: `BiwtInput.host_cell_type_names` should feed the cell-parameters step, not just rename
suggestions — and where the user picks one, the returned tuple's first element must be something
obviously *not* a filepath that says "this cell type already exists in the host", leaving the host
to decide what to do about it.

**The signal.** `biwt.types.HOST_SOURCE = "<host>"`, and the value is `(HOST_SOURCE, host_name, "")`.
Angle brackets because no filesystem accepts them: a host that forgets the check fails at once
rather than reading some file that happens to exist. Content is the empty string because there is
genuinely nothing to hand back — the host holds the definition. That does mean an unguarded
`ET.fromstring(content)` raises, which is the loud failure the sentinel is chosen to produce, and it
is now the one item on the Studio checklist marked as able to crash the host if ignored.

**Matching.** Host names pool with template names and go through the same `best_match`, so the same
`name_matches` predicate decides rename suggestions and parameter pre-selection — one rule, three
call sites. Per the request they tie rather than outrank, and it is worth recording which way a tie
currently falls: `_first_key_for_name` sorts by `(name, path)`, and `/abs/path` sorts before
`<host>`, so a same-named file template wins. Upweighting the host is deferred and noted in the PRD;
it needs a ranking notion, and `name_matches` is a boolean by design.

**Two places where "the same as a library" would have been wrong.**

*The `default` tier.* `default` is a common cell-type name — conventional in PhysiCell models,
though not guaranteed by anything. Pooling a host cell type of that name into the fallback tier
would make `default` ambiguous whenever it happened to appear, and the response to an ambiguous
`default` is to withdraw the shortcut, so the feature would have disabled the button on a collision
that says nothing about which template is the baseline. Host names are therefore candidates for
*matching* but never eligible to *be* the baseline, which the
`default_template_choices(host_names=...)` signature now encodes rather than leaves to the caller.

*The source qualifier.* A file qualifier is suppressed while only one file is loaded, on the
grounds that it is noise. A host qualifier is not, at any count: it is what distinguishes "a type
you already have" from "a template". Without it, a host that passes cell types and no library would
show a dropdown that reads exactly like a template list and means something else entirely.

The reserved source also stays out of *Remove templates from file…* — the host's cell types are not
something BIWT loaded, so they are not something it can unload — and is never shown to the user:
rows read `Tumor (Studio)`, using `host_name`. The sentinel is an API signal, not UI text.

One synergy worth noting with the previous entry: this feature reads `host_cell_type_names` at
window-build time, so it is only trustworthy because the input is now resolved per run. Before
that, a Studio user who added a cell type after launch would have been offered the list as it stood
when the application started.

### The host wins the tie, and it needed no scoring

I had filed "upweight the host" as deferred work needing a ranking notion. That was wrong, and the
question that corrected it was the right one: the two candidates already score *equally*, so the
winner is decided by source order — and there is only ever one host source to hoist. The fix is the
sort key in `_first_key_for_name`: `(name, path != HOST_SOURCE, alpha_key(path))`. False sorts before
True, so the host's entry heads its name group and `setdefault` takes it.

What stays deferred is narrower than I first described, and worth stating precisely: preference
applies to **identical** names. Where the host offers `Tumor` and a file offers `Tumour` and both
match a data type, the winner is still first-in-name-order, because `best_match` ranks candidates by
name and a boolean predicate gives nothing to rank sources by. That case does need scoring. An exact
collision never did.

`_source_paths` now orders the host first as well, so the group that wins a tie is also the group
listed first in **By Source** mode. One test flipped — it had encoded the old outcome in both its
assertion and its comment — and two were added: the host winning a collision, and a file template
still winning a name the host does not define.

### pyflakes found two tests that had never run

Added as a guard against unreachable-line `NameError`s, the static check earned its place on a
different failure the same day. Widened to cover `tests/` and to treat `RedefinedWhileUnused` as
fatal, it reported:

    tests/test_session.py:1171: redefinition of unused 'TestCollectCellTypeData' from line 325

Two classes, one name. Python keeps the second, so `test_extracts_unique_types_sorted` and
`test_per_cell_labels_match_obs` had been silently absent from every run — pytest collected 3 tests
where the file defines 5. Nothing failed, which is exactly why it survived: a dropped test is
indistinguishable from a passing one in the summary line. Renamed to
`TestCollectCellTypeDataEdgeCases`, and the count went 508 → 510.

The other two reports were benign but real: a duplicated `_labels` helper in `test_gui_smoke.py`
(identical behavior, so nothing was testing the wrong thing — the first definition was simply dead)
and one unused import.

Also cleaned the 14 unused imports and one unused local pyflakes had been reporting all along.
Two were worth a check rather than a delete: `biwt.gui.__init__`'s `QWidget` is a deliberate PyQt5
availability probe carrying its own `# noqa` and comment, and stays — which is why `UnusedImport` is
not in the fatal set. `widgets.py`'s `QRadioButton as QRadioButton_custom` looked like a re-export,
but nothing in BIWT or Studio imports it: Studio has its own `QRadioButton_custom` in
`studio_classes.py`, and BIWT's was an alias to the plain widget, i.e. a name left behind by the
copy from Studio that never did anything. Deleted.

### Matching gets tiers, and the host's `default` becomes the baseline

Three reports from a live run, and the third reversed a decision from the entry above.

**The host lost a tie it was supposed to win.** Naming a data type `tumor` picked templates_a's
`Tumor` over the host's `tumor`. The preference I had added lived in `_first_key_for_name`, which is
keyed on the name *string* — so it only fired when the two sources spelled a name identically. But
`best_match` short-circuits on a case-insensitive exact match, and `tumor` and `Tumor` are both
exact matches, so the name that came back was already the library's and the source preference never
got a say.

Fixed by tiering in core instead: `best_match` gained `exact_only`, and the candidate pools are now
tried host-then-library at the exact tier, then host-then-library at the similarity tier. Provenance
breaks ties *within* a tier; quality still comes first, so an exact template match beats a merely
similar host name. `default_template_choices` became `matched_candidates` — it answers only "which
name names this cell type", which is the part that is pure.

**The ⓘ marker only fired on identical spellings.** Same root cause, different symptom: `tumor` and
`Tumor` in two sources are one contest, and the row said nothing. It now compares candidates with
the matching rule rather than `==`, and names the rival's spelling when it differs, since the
dropdown does not show it: `'tumor' also defined by templates_a.toml (as 'Tumor').`

**A third defect nobody had reported.** Fixing the first two made me trace the fallback path, where
a type that matched nothing takes the template named `default`. The resolution went through
`_first_key_for_name`, which prefers the host — so a host cell type called `default` won the lookup
and became the baseline it was explicitly barred from being. Both my tests missed it: one used a
library with no `default`, the other went through the button rather than auto-match.

**And then the bar came off entirely.** The report: "the 'set to default' button seems to ignore the
host's `default` cell type. if anything, it should prefer this." Correct, and it makes the design
simpler rather than more complex. A library `default` is a generic starting point; the host's is
that host's *actual* default cell type, which is what the action asks for. So the host's outranks
any library's — and it settles the case that previously had no answer at all: two libraries each
defining `default` used to withdraw the action, and a host `default` now outranks both and keeps the
buttons working.

That collapsed a duplication I had been carrying. The "which `default` is the baseline" rule was
expressed twice — once in core counting names, once in the window counting keys — because core knew
about `host_names` but not about sources. It is now `_baseline_key()` in the window, once, where
sources are known; core is out of the fallback business; and the `TemplateChoice(name, matched)`
flag I had just added to carry the distinction across that boundary was deleted with it. The same
key serves the `default` buttons and the auto-match fallback tier, so the two controls cannot
disagree about what `default` means — which they briefly did.

Also gone: the rule suppressing a host rival on the ⓘ marker for a fallback selection. It existed
because host entries were ineligible for that tier; now they are eligible, so the case cannot arise.

**Still deferred, with the reason recorded.** The full ranking is host cell types, then libraries the
user loaded, then libraries the host supplied — a generic framework library being the weakest answer.
Only the first tier exists. The obstacle is classification, not mechanism: a host may let users
pre-register their own libraries, which then arrive through `cell_template_paths` indistinguishable
from the framework's own, so a "host-supplied" tier would silently demote a user's library. That
distinction has to be settled at the API boundary before the ranking is worth building.

### A review pass, and what it found that I could not

Ran a five-dimension review over the staged branch — correctness, docs-vs-code accuracy, whether
the new tests bite, lifecycle interactions, hostile host input — each dimension's findings then put
to a skeptic told to refute them. 22 reported, 21 confirmed with a concrete repro, 1 refuted.

**The crash class was the real find: four ways a host mistake took down the host's whole process.**
An exception raised in a Qt slot is not caught by anything — PyQt5 calls `qFatal`, so the process
aborts. Every one of these was a `SIGABRT` in a live probe, mid-session, in Studio:

- `_resolve_host_input`'s guard did not cover `snapshot()`, so a `BiwtInput` of the right *type*
  carrying `None` in a list field aborted the import. The guard now wraps the whole resolution,
  including the non-callable branch, which had the same hole.
- A non-string in `host_cell_type_names` — an integer id, one stray `None` — reached `casefold()`
  while sorting and aborted at the rename step. Dropped in `snapshot()` now, the one point both
  entry paths pass through. The cell-parameters step already filtered them, so the two consumers
  had disagreed.
- `cell_template_paths="/path/x.toml"` (a bare string where a list belongs) was iterated into
  characters, opening one modal "could not load" dialog *per character* — 106 of them for a
  106-character path, each blocking. `__post_init__` now rejects a string for either list field, so
  it fails at the host's own construction site.
- A degenerate host domain — zero width, NaN, inf — was accepted unchecked and died several steps
  later dividing by zero in the counts step or inside matplotlib. `_usable_domain` now repairs
  inverted bounds by swapping (the intent is unambiguous, and it silently stacked every cell on one
  line) and substitutes BIWT's own box for a non-finite or flat extent, reported as `DEFAULT`. Flat
  *z* is left alone: a 2-D host domain is legitimate.

**Two genuine behavior bugs, neither in code this branch wrote.** Keeping or deleting a merge
group's *leader* left the other members still pointing at it, so they were folded into a type the
user had just removed from the group — or, after Delete, into a type absent from the output
entirely. Only the group-of-two case had been handled. And `_maybe_show_domain_editor` latched
`domain_accepted = True` on its non-spatial shortcut, so answering No at the spatial query and then
going back to Yes permanently suppressed the mismatch dialog — the one prompt that lets a user adopt
the data extent or set a µm/pixel factor. The shortcut is read-only now; nothing else reads the flag
on that path.

**The test-bite dimension was the most uncomfortable, and the most useful.** It mutated the source
and reported which of my tests still passed:

- The spot-deconvolution fix from this very branch — `cell_prob_feature_dicts_final` — had *no*
  test. Restoring the pre-branch expression left the whole suite green, while a renamed cell type
  silently lost its probability mass and placed nothing. `_plot_spot_deconvolution` is its only
  reader and no test reached the positions step, the same gap that let the `DomainSource` NameError
  ship. Covered now, and verified to fail against the reverted line.
- `initial_preset` was never passed by any test, so both the branch and its caller could be deleted
  with 541 passing — and a non-spatial run would have offered ±500 in place of a host's ±2000.
- The wrong-type provider test could not tell "kept the previous context" from "reset to defaults",
  because the context it kept *was* the default. It now starts from a distinctive one.
- `test_duplicate_and_empty_host_names_are_ignored` filtered its assertion to rows containing
  "Tumor", so the blank rows it was named for were invisible to it — and they were reaching the
  model as selectable rows handing the host `(HOST_SOURCE, "", "")`.
- The `RelabelledComboBox` paint test passed with *either* `drawText` deleted, including the
  secondary the class exists for: comparing one widget's pixels to another's only proves something
  differs. It changes one half at a time now and requires the pixels to move; verified against both
  mutants.
- Two tests used repo-root-relative fixture paths, so from any other cwd the missing file opened a
  blocking modal inside the constructor: the suite **hung** instead of failing.

**Docs drift, again in the direction of claims nobody checked.** `on_complete(None)` on cancel was
documented in four places and has never happened — a host clearing a "running" flag in that branch
would wait forever; deleted, and pinned by a test. `studio.md` asserted both that Studio passes
`host_cell_type_names` and that it does not. `docs/reference/gui.md` asked mkdocstrings for a
`closeEvent` that does not exist. The rename page still said the names land in "generated PhysiCell
cell-definitions XML", which this branch deleted. And the README's "300 passing tests" was replaced
with no number at all: a count is re-verified on every branch or it rots, which is how `155`
survived four releases.

**One refutation worth keeping.** A finder re-reported the host-`default` fallback bug I had fixed
mid-review; the skeptic checked the current tree, found it already resolved *in the opposite
direction*, and explicitly warned that applying the suggested patch would recreate the disagreement
in mirror image. That is the check earning its place — a stale finding applied faithfully is a new
bug.

### A simplification pass, run as seven reviews

With the branch committed, seven agents read the whole diff at once — reuse, simplification,
altitude, efficiency, prose, tests, docs structure. Net **−300 lines** with nothing lost, and four
findings that were defects rather than debt.

**A CI break I had shipped.** I renamed `default_template_choices` to `matched_candidates` mid-branch
and never updated `docs/reference/core.md`. `mkdocs build --strict` runs in CI and mkdocs is not
installed locally, so nothing here could catch it. Fixed, and `test_static_checks.py` now resolves
every `:::` target and every `members:` entry in the docs against the real module — verified to fail
on exactly that stale name.

**The autouse widget reaper had made every test Qt-dependent.** It requested the `qapp` fixture,
whose `importorskip` therefore ran ahead of every test in the suite — so with PyQt5 absent the 64
Qt-free tests reported as *skipped* rather than run, and a Qt-less CI leg would have gone green
while testing nothing. It now reaches for `QApplication.instance()` directly and returns if there is
none. Confirmed by running the two pure-Python modules with PyQt5 blocked at the import hook: 64
passed.

**A pixel-test class that passed with the feature deleted.** `TestDisabledLooksDisabledUnderAHostPalette`
compared grabs of enabled vs disabled widgets; deleting *both* of BIWT's `:disabled` stylesheet
rules left all three tests green, because the difference it measured was Qt's own disabled-icon
rendering. 76 lines, replaced by nothing: `isEnabled()` assertions elsewhere already cover the
behavior.

**41 redundant refresh passes per window build.** `__init__` populated the model without the
`_rebuilding` guard the rest of the file uses, so each of the shared model's `appendRow` calls
signalled every combo, and each signal re-derived the whole tie relation — 2n+1 passes, 42% of
construction, quadratic in cell types × templates. Construction now routes through the same
`_rebuild_and_restore` everything else uses: **41 calls → 1**.

**What got simpler.** `CellTypeConfig`/`CellTypeAction` were dead — 84 lines still exported and
documented, superseded by `resolved_cell_type_map()`. The four-call host-first tiering in
`matched_candidates` became one `best_match` with a rank comparator, which also deleted the
`exact_only` parameter it needed; the deferred third source tier is now a change to one lambda.
`_STEP_ORDER` is derived from `_step_predicates` instead of restating its eight labels, and
`_STEP_FIELDS` holds names only — its 22 reset *values* were a second copy of the dataclass
defaults, free to drift, and `_reset_to_default` reads them off the dataclass instead. I checked
both derivations against the committed tables: identical, including every reset value.

Four host-input guards became one: `__post_init__` normalizes lists, host name and domain, and
`snapshot()` is a copy again rather than also being the sanitizer — which fixed a real seam, since
the caller had been reaching back into the object `snapshot()` had just produced to finish
validating it. `host_label` went with it: a property guarding a field nobody should read, replaced
by normalizing the field.

The two yes/no query steps became one base class. They had ~35 identical lines, and this branch had
already fixed the same `idToggled` arity bug in both — independently, with the same comment, which
is the evidence you want before merging. 121 lines → 44 across the two, one copy of the guard.

In the cell-parameters window: the label rule was implemented twice, once on the paint path;
computing it with the model deleted a method and took the allocation out of `paintEvent`. Nine
action wrappers for three actions at two scopes became three methods taking the cell types they
apply to. `_first_key_for_name` stored the key it was keyed by. 901 lines → 806.

**Prose.** The docs said the same thing in up to six places — the "unassigned types are absent"
rule in four, the `HOST_SOURCE` example verbatim in both a docstring and a page, the digit-gate
derivation in six. Each now has one owner and the rest link. A comment block stated its point twice
and then described the icon as a gear, which it has not been since the house replaced it.

### One copy of "what the windows do to the session"

Four test modules each wrote out the step sequence — pick a column, keep every type, rename,
`apply_rename` — and `test_session.py` wrote it fifteen more times inline. That is not just
duplication: a session-field rename has to be chased through every copy, and a missed one builds a
window against a stale session rather than failing, which is exactly what happened when
`use_spatial_data` became `spatial_query_answer` mid-branch.

`tests/helpers.py` now holds it once, split at the seams the windows themselves have —
`pick_column`, `keep_all`, `rename_to`, and `session_through_rename` composing the three — plus
`walkthrough_with_data` and `window_at_rename`. Plain functions rather than fixtures, because most
callers need them inside a module-level factory rather than as a test argument. `FIXTURES` and
`DOMAIN` live there too, deleted from the seven modules that each re-declared them.

`test_gui_smoke` had re-declared `make_widget` and `drive_import`, which conftest already provides —
and its copies did not register widgets for teardown, which is what the autouse reaper exists for.
`test_load_cell_parameters` had three copies of the same five-line "add a template file" helper plus
four inline duplicates of it; one now, hoisted above its first use.

Net −129 lines across the modules against +78 for the shared file. The number is not the point:
there is now one place to edit when a step's contract changes.

### The legend outlived its window

Reported from a live run: the Positions legend stays on screen after leaving that step, including
after going back and invalidating it.

It is its own top-level window, so it does not follow the step window unless told to — and it was
being told in two specific places: `process_window`, and the Go back *button*'s `pre_cb`. Both are
exits, but neither is *the* exit. Probing all four routes out:

    after Continue:                  hidden
    after go_back_to_prev_window():  VISIBLE   <- the controller's own route
    after invalidating it:           VISIBLE   <- reported
    after re-import:                 VISIBLE

The Back button is one caller of `go_back_to_prev_window`; the controller calls it directly too, and
neither discarding a stale cached window nor re-importing goes anywhere near that button. What all
four share is `self.window.hide()` — so the legend now follows a `hideEvent` on the window it
belongs to, and the two explicit calls are gone. One rule where there were two special cases, and it
covers the exits nobody has written yet.

`showEvent` brings it back, because back-then-forward without changes deliberately reuses the window
and its plot; the legend is that plot's key, so it belongs to the same preserved state.

### The last step had nowhere to go

Reported after Skip: "biwt exits and there's nothing left. I can't go back." Not Skip's doing —
plain Continue from the cell-parameters step did the same, and Skip only made it easy to reach.

`advance()` hid the current window *first*, then looked for a next one. On the last step there is
none, so `_finish()` fired against a widget with nothing visible in it. The window was also pushed
onto the history while still being `self.window`, so Go back would have popped the step the user was
already standing on.

Now nothing is put away until there is a replacement to put in its place. The last step stays on
screen after the result is emitted, and Go back reaches the step before it.

BIWT still does not decide what happens after completion — the docs are explicit that the widget
does not close or reset itself, because the host owns that. What changed is only that "the host
decides" no longer means "the user is looking at a blank panel while it does".

### The audit's leftovers

Two published examples assembled a host XML document straight from `cell_templates` values without
checking for `HOST_SOURCE`. That sentinel is not a path and its content is empty, so a host copying
either example hit `ParseError` on the ordinary case where a type matched one of the host's own cell
types. Both now skip it, which is also the correct behavior: the host already has that definition.

`data_loader.py` raised its "no obs columns" `LoadError` from inside the `try` that wraps AnnData
access, so it came back out re-wrapped as a read failure — a file BIWT understood perfectly well was
reported as one it could not read. Moved out.

The rest were tests for behavior nothing exercised. The one that mattered: every domain-editor test
rejected the dialog, so the branch that writes the user's domain to the session — the one deciding
where cells land and what `domain_used` reports — had never run. Four more cover the invalidation on
a second Go back, the import lockout's two release paths, library-path deduplication, and Positions
declining to latch `domain_accepted` on a non-spatial pass. Each was confirmed by breaking the code
it guards and watching exactly that test fail.

### The triage, and what the loader now decides

Five calls came back on the coverage audit, and they were all about the same question: when the
file's numbers are wrong or ambiguous, does BIWT guess, refuse, or carry on?

An obsm entry now has to be 2 or 3 columns wide to count as coordinates. The name was doing all
the work before, so `spatial_connectivities` — an N×N adjacency matrix — matched on "spatial" and
its first three columns became x/y/z. Worse, it outranked the real `imagerow`/`imagecol` columns
sitting in obs. The check went into `_find_spatial_key`, which `infer_domain`,
`setup_spatial_data` and the location description all share, so one guard covers every reader.

The y-flip needed no change at all. It belongs to `imagerow`/`imagecol` and fires wherever those
are read; an obsm array has no column names, so it is taken as given. The audit had read the
disagreement between a file's two routes as a bug, but a file offering both is simply not
expected to agree with itself. Both directions are pinned now.

z is scaled when the file supplies z. A synthesized ±10 slab is not a measurement in data units,
so the factor has nothing to convert — but a real z column is, and leaving it alone shipped two
of three axes converted. `data_has_z` mirrors `infer_domain`'s resolution order exactly, because
a flag that describes different coordinates than the domain would be worse than no flag.

A probability outside `[0, inf)` is worth zero rather than deleting its cell type. One NaN used
to fail `(obs[col] >= 0).all()` for the whole column and the type vanished with no error. The
clamp had to go where the weights are built, not only where the columns are chosen: a raw NaN
wins `argmax`, so a single bad spot nominated its own type as that spot's maximum.

An `.rda` workspace is searched by class instead of taking `base::ls()`'s first name, which is
sorted — so a workspace holding `annotations` and `seurat_obj` imported `annotations`. Several
datasets or none is refused rather than guessed at. Which one the user meant is genuinely
unknowable, it would have to be asked somewhere, and a one-object file keeps the run
reproducible from the file alone.

Four findings were left alone on the same reasoning in reverse: the signal to the user is already
clear, so a warning would only be noise. And one was not a bug — the domain editor defaulting to
the data extent is the intent.

---

## 2026-08-15: "Skip domain validation" removed from the home screen

Nothing on that screen validated anything. The checkbox let the user pre-answer a question the
positions step asks against data that has not been imported yet — and phrased it as turning off
a check, which is not a decision anyone can make before seeing the mismatch. The mismatch dialog
itself remains the place where the domain is judged, and it is worth keeping precisely because it
is the one moment the data's extent and the host's domain are visible together.

`BiwtInput.domain_accepted` is now the only way to suppress the auto-opened dialog, so it is read
at each import like the rest of the host's input rather than only at construction. The old
read-once rule existed to stop a later host value contradicting a box already on screen; with no
box, a run simply sees what the host currently says.

The cluster-column shortcut stays. It answers a question whose cost the user can predict — a long
column list to scroll — without needing to see the file first.
