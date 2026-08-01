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
audit trail: it records every decision you made at the edit and rename steps, so a reviewer
can trace an output population back to the clusters it came from.

### `domain_used`

The [`DomainSpec`][biwt.types.DomainSpec] actually applied when placing cells — which may
differ from what the host passed in, if you changed it in
[the domain editor](domain.md). Its `source` field says where it came from (`preferred`,
`data_range`, `anndata_metadata`, or `default`), so the host can tell whether its own domain
was overridden.

### `cell_definitions_xml`

A complete PhysiCell settings XML string, if you assigned
[phenotype templates](cell-parameters.md). It contains the standard scaffold sections, your
domain, and a `<cell_definitions>` block with one entry per cell type.

`None` if you assigned no templates.

## What the host does with it

That is up to the host. BIWT's contract ends at the callback.

PhysiCell Studio, for example, offers Overwrite / Append / Browse / Cancel when the target
`cells.csv` already exists, and separately offers to save the XML as a new config file. A
notebook host might just call `result.to_csv(...)` or work with the DataFrame directly.

If you are writing a host, see [embedding BIWT](../integration/index.md).

## Writing it yourself

From a script, the convenience method does the obvious thing:

```python
def on_complete(result):
    result.to_csv("config/cells.csv")
```

That writes only the four PhysiCell columns, without the DataFrame index. To save the XML:

```python
def on_complete(result):
    result.to_csv("config/cells.csv")
    if result.cell_definitions_xml:
        with open("config/PhysiCell_settings.xml", "w") as f:
            f.write(result.cell_definitions_xml)
```

## Starting over

The widget does not close itself when the workflow finishes — that is the host's call.
Importing a new file resets the session completely, so the same widget can be reused for
another dataset without restarting anything.
