# PhysiCell Studio

[PhysiCell Studio](https://github.com/PhysiCell-Tools/PhysiCell-Studio) is BIWT's reference
host. Its bridge lives in `bin/ics_tab.py` and is worth reading as a complete worked example
— it is about sixty lines.

## How Studio detects BIWT

BIWT is an optional dependency. Studio tries the import and falls back if it fails:

```python
try:
    from biwt.gui.walkthrough import create_biwt_widget
    from biwt.types import BiwtInput, DomainSpec
except ImportError:
    from biwt_tab import BioinformaticsWalkthrough   # legacy built-in tab
```

The BIWT tab is enabled with Studio's `--biwt` flag:

```bash
python3 bin/studio.py --biwt
```

When the package is missing, Studio shows its legacy built-in tab and a dialog pointing at
installation instructions.

## Building the input

Studio's BIWT tab is built once at startup and never rebuilt, so it passes a **provider** rather
than a value. BIWT calls it at each import:

```python
def _create_biwt_package_tab(self):
    return create_biwt_widget(self._biwt_input, on_complete=self._biwt_complete)

def _biwt_input(self):
    domain = self._domain_from_config_tab()          # None if unparseable
    return BiwtInput(
        preferred_domain=domain or DomainSpec.default(),
        host_cell_type_names=list(self.xml_creator.celldef_tab.param_d.keys()),
        cell_template_paths=[TEMPLATES],
        host_name="Studio",
    )
```

Worth copying:

- **Guard the domain.** Floats from UI text fields fail in ordinary use: empty, half-typed,
  `xmin == xmax`.
- **Fall back to `DomainSpec.default()`.** A hand-written ±500 box arrives labelled `source=HOST`,
  which tells the user it came from Studio.
- **Set `host_name`.** The domain editor then reads "Use Studio Domain".

## Handling the result

`_biwt_complete` shows a save dialog rather than writing silently. The shape of it:

- A path field pre-filled from Studio's configured output folder and filename, with a
  **Browse…** button.
- **Overwrite** / **Append to existing** radio buttons, shown *only* when the chosen path
  already exists. Append concatenates BIWT's rows onto the existing CSV; extra columns in the
  existing file are left empty for the appended rows.
- Save / Cancel.

Then, separately, if `result.cell_templates` is non-empty, Studio assembles a PhysiCell config
from those templates and offers to save it. Studio also ships the PhysiCell template library
itself and passes it in through `cell_template_paths` — BIWT holds no framework-specific
parameters of its own. That arrangement is not Studio-specific; [templates and name
matching](templates-and-matching.md) describes it for any host.

The lesson generalizes: **BIWT hands you data, and the "where does this go" conversation is
yours to have.** Studio always confirms the path even when the file does not exist, because
silently writing into a user's project directory is not a good default.

## What the package path must match

BIWT replaced a built-in Studio tab, and the replacement has to hold the line on what that tab
already did. From the project's PRD:

- The `--biwt` flag and the `_biwt_complete` callback must keep working without Studio source
  changes beyond the bridge itself.
- No feature of the legacy walkthrough may be removed or degraded.
- UI layout, step order, and stricter validation are all fair game.

If you are integrating BIWT into a different host, none of this binds you — but it explains
why some things are shaped the way they are.
