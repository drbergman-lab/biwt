# The API contract

Three dataclasses in `biwt.types` define everything that crosses the host boundary. They live
in one file specifically so the interface can be audited at a glance.

For generated signatures see the [API reference](../reference/types.md); this page is about
what the fields *mean* and how to use them well.

## `DomainSpec` — the simulation box

```python
DomainSpec(
    xmin=-500.0, xmax=500.0,
    ymin=-500.0, ymax=500.0,
    zmin=-10.0,  zmax=10.0,
    source="preferred",
    units="micron",
)
```

Passed **in** as `BiwtInput.preferred_domain` and returned **out** as
`BiwtResult.domain_used`.

### `units`

Defaults to `"micron"`, the PhysiCell convention. BIWT uses this for two things: labelling
the [domain editor](../guide/domain.md) fields (`micron/data unit`), and flagging
potential mismatches.

!!! warning "Non-micron hosts: a known gap"
    The Visium scale factor BIWT auto-detects is in **µm per pixel**. If your `units` is
    something else, that seeded value is not converted and will be wrong. Users can override
    it manually. Until this is fixed, consider setting `domain_accepted=True` and validating
    the domain yourself if you work in other units.

### `source`

Records how the spec was determined, so you can tell whether your domain survived:

| Value | Meaning |
|---|---|
| `"preferred"` | Passed in by the host |
| `"anndata_metadata"` | Read from AnnData/Seurat spatial metadata |
| `"data_range"` | Computed from the coordinate min/max |
| `"default"` | Fallback (±500 µm × ±10 µm) |

Check `result.domain_used.source` in your handler. If it is not `"preferred"`, the user
changed the domain during the walkthrough and your application's configured domain no longer
matches the initial conditions you just received.

### Convenience members

`width`, `height`, `depth` are derived properties. `is_2d` is true when the z extent is at
most one default PhysiCell voxel (20 µm). `DomainSpec.default()` builds the fallback.

## `BiwtInput` — host to BIWT

```python
BiwtInput(
    preferred_domain=domain,              # required
    host_cell_type_names=[],              # optional
    domain_accepted=False,                # optional
    host_name="Host",                     # optional
    extra_cell_template_paths=[],         # optional
)
```

**`preferred_domain`** is the only required field. BIWT uses it for placement unless the user
overrides it.

**`host_cell_type_names`** — a list of the cell types your application already defines. Used
only for rename suggestions; BIWT does not require them and does not constrain the user to
them.

**`domain_accepted`** — set `True` to suppress the automatic domain-mismatch dialog for every
session.

**`host_name`** — appears in the domain editor as "Use \<host_name\> Domain". Set it; the
default `"Host"` reads like a placeholder because it is one.

**`extra_cell_template_paths`** — paths to TOML files, each mapping a template name to a
PhysiCell phenotype XML block:

```toml
"My Cell Type" = """
<phenotype>
  ...
</phenotype>
"""
```

These merge with the 29 built-ins in the parameter dropdowns. This is the supported extension
point for framework- or lab-specific parameter databases — and the interim bridge until the
PhysiCell-specific templates move into a separate `biwt-physicell` package.

## `BiwtResult` — BIWT to host

```python
BiwtResult(
    coordinates=df,                  # DataFrame: x, y, z, type
    cell_type_map={...},             # original label -> final name | None
    domain_used=domain,              # DomainSpec actually applied
    output_csv_path=None,            # set by to_csv(); BIWT never writes on its own
    cell_definitions_xml=None,       # PhysiCell XML string, or None
)
```

**`coordinates`** — one row per placed cell, columns `["x", "y", "z", "type"]`. The header is
`type`, not `cell_type`, matching PhysiCell's CSV convention. 2D data has `z = 0.0`.

**`cell_type_map`** — every original label mapped to its final name, with `None` for deleted
types. Use it to reconcile the output against your own cell definitions, or to report to the
user what happened to each input cluster.

**`domain_used`** — see `source` above.

**`cell_definitions_xml`** — a complete PhysiCell settings XML string when the user assigned
[phenotype templates](../guide/cell-parameters.md), `None` otherwise. Always check before
using it.

**`output_csv_path`** — `None` unless something called `to_csv()`, which sets it as a side
effect. BIWT itself never populates this.

### `to_csv(path)`

A convenience for hosts that just want the file written:

```python
result.to_csv("config/cells.csv")
```

Writes only the four PhysiCell columns, no index, and records the path in `output_csv_path`.
Using it is optional — the DataFrame is yours.

### Reserved fields

`substrate_data`, `gene_expression`, and `spatial_metadata` are named in the docstring as
future expansion but are **not populated and not currently attributes**. Do not code against
them yet.

## A complete minimal host

```python
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow

from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, DomainSpec


def on_complete(result):
    if result is None:
        print("user cancelled")
        return

    print(f"{len(result.coordinates)} cells, "
          f"{result.coordinates['type'].nunique()} types")

    if result.domain_used.source != "preferred":
        print(f"note: domain changed to {result.domain_used.source}")

    result.to_csv("cells.csv")
    if result.cell_definitions_xml:
        with open("PhysiCell_settings.xml", "w") as f:
            f.write(result.cell_definitions_xml)


app = QApplication(sys.argv)
window = QMainWindow()
window.setCentralWidget(create_biwt_widget(
    BiwtInput(
        preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500),
        host_cell_type_names=["default", "tumor", "immune"],
        host_name="My App",
    ),
    on_complete=on_complete,
))
window.show()
sys.exit(app.exec_())
```

## Stability

`biwt.types` and `create_biwt_widget` are the public API and changes to them will be treated
as breaking. Everything under `biwt.core` and `biwt.gui.windows` is internal — useful to read,
but not a contract.
