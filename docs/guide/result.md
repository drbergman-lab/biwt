# Finishing up

When the last step is done, BIWT assembles a [`BiwtResult`][biwt.types.BiwtResult] and hands
it to the host. Nothing is written to disk by BIWT itself.

## What is in the result

### `coordinates`

A DataFrame with one row per placed cell:

| x | y | z | type |
|---|---|---|------|
| -320.0 | 140.0 | 0.0 | tumor |
| 40.0 | -260.0 | 0.0 | macrophage |

The column names follow the PhysiCell convention — note **`type`**, not `cell_type`. For 2D
data, `z` is padded with zeros.

### `cell_type_map`

How every original label in your data maps to its final name:

```python
{
    "CD8_effector": "CD8_T_cell",   # merged and renamed
    "CD8_memory":   "CD8_T_cell",   # merged into the same target
    "doublet":      None,           # deleted
    "Tumor":        "tumor",        # renamed only
}
```

`None` means the type was [deleted](edit-cell-types.md) and contributes no cells. This is your
audit trail: it records every decision you made at the edit and rename steps.

### `domain_used`

The [`DomainSpec`][biwt.types.DomainSpec] actually applied when placing cells — which may
differ from what the host passed in, if you changed it in
[the domain editor](domain.md). Its `source` field says where it came from — `host`, `data`,
`user` or `default` — so the host can tell whether its own domain was overridden.

### `cell_templates`

The [cell templates](cell-templates.md) you assigned, as a mapping from final cell-type
name to `(path, name, content)` — the `.toml` file the template came from, its name in that
file, and its content **verbatim**.

BIWT never parses that content, so a PhysiCell host receives exactly the `<phenotype>` block
its own template file holds, and owns every decision about assembling a config from it — see
[templates and name matching](../integration/templates-and-matching.md) if you are writing a
host.

Where you picked one of the host's own cell types, `path` is
[`HOST_SOURCE`][biwt.types.HOST_SOURCE] and the content is empty — the host already holds that
definition.

Types you left unassigned are **absent** from the mapping, so `{}` is a normal result — that is
what Skip produces. Hosts have two more rules to follow here; see
[the API contract](../integration/api-contract.md#biwtresult-biwt-to-host).

## What the host does with it

That is up to the host. BIWT's contract ends at the callback.

PhysiCell Studio, for example, offers Overwrite / Append / Browse / Cancel when the target
`cells.csv` already exists, and separately assembles a PhysiCell config from the templates. A
notebook host might just call `result.to_csv(...)` or work with the DataFrame directly.

If you are writing a host, see [embedding BIWT](../integration/index.md).

## Writing it yourself

From a script, the convenience method does the obvious thing:

```python
def on_complete(result):
    result.to_csv("config/cells.csv")
```

That writes only the four columns, without the DataFrame index. The templates are yours to
assemble — for a PhysiCell host, one `<cell_definition>` per type wrapping the content BIWT
handed back:

```python
import xml.etree.ElementTree as ET

from biwt.types import HOST_SOURCE

def on_complete(result):
    result.to_csv("config/cells.csv")
    cell_defs = ET.Element("cell_definitions")
    for i, (cell_type, (path, name, content)) in enumerate(result.cell_templates.items()):
        if path == HOST_SOURCE:
            continue                     # you already define this type; no content to parse
        cd = ET.SubElement(cell_defs, "cell_definition", name=cell_type, ID=str(i))
        cd.append(ET.fromstring(content))
```

## Starting over

The widget does not close itself when the workflow finishes — that is the host's call.
Importing a new file resets the session completely, so the same widget can be reused for
another dataset without restarting anything.
