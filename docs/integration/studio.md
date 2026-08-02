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

Studio reads the domain straight off its own config tab, with a fallback if the fields are
empty or unparseable:

```python
def _create_biwt_package_tab(self):
    ct = self.config_tab
    try:
        domain = DomainSpec(
            xmin=float(ct.xmin.text()), xmax=float(ct.xmax.text()),
            ymin=float(ct.ymin.text()), ymax=float(ct.ymax.text()),
        )
    except (ValueError, AttributeError):
        domain = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)

    biwt_input = BiwtInput(preferred_domain=domain, host_name="Studio")
    return create_biwt_widget(biwt_input, on_complete=self._biwt_complete)
```

Two things to copy from this:

**Guard the domain construction.** Pulling floats out of UI text fields fails in ordinary use
— empty fields, a partially typed value. A `DomainSpec` you cannot build is not a reason to
fail to open the tab.

**Set `host_name`.** Studio passes `"Studio"`, so the domain editor reads "Use Studio Domain"
rather than "Use Host Domain".

## Handling the result

`_biwt_complete` shows a save dialog rather than writing silently. The shape of it:

- A path field pre-filled from Studio's configured output folder and filename, with a
  **Browse…** button.
- **Overwrite** / **Append to existing** radio buttons, shown *only* when the chosen path
  already exists. Append concatenates BIWT's rows onto the existing CSV; extra columns in the
  existing file are left empty for the appended rows.
- Save / Cancel.

Then, separately, if `result.cell_definitions_xml` is present, Studio offers to save it as a
new config file.

The lesson generalizes: **BIWT hands you data, and the "where does this go" conversation is
yours to have.** Studio always confirms the path even when the file does not exist, because
silently writing into a user's project directory is not a good default.

## What Studio does not do

Studio does not pass `host_cell_type_names`, so BIWT cannot suggest matches against Studio's
existing cell definitions at the [rename step](../guide/rename-cell-types.md). Wiring that up
is a straightforward improvement for any host with a cell-type list to hand.

## What the package path must match

BIWT replaced a built-in Studio tab, and the replacement has to hold the line on what that tab
already did. From the project's PRD:

- The `--biwt` flag and the `_biwt_complete` callback must keep working without Studio source
  changes beyond the bridge itself.
- No feature of the legacy walkthrough may be removed or degraded.
- UI layout, step order, and stricter validation are all fair game.

If you are integrating BIWT into a different host, none of this binds you — but it explains
why some things are shaped the way they are.
