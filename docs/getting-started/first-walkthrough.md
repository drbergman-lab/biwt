# Your first walkthrough

The fastest way to understand BIWT is to run it once on a file small enough to reason about.
This page does that in about five minutes, with no bioinformatics data required.

## 1. A minimal input file

Save this as `demo.csv`:

```csv
x,y,celltype
-320,140,tumor
-298,155,tumor
-310,122,tumor
40,-260,macrophage
72,-244,macrophage
250,300,tcell
268,281,tcell
```

That is a legitimate BIWT input. One row per cell, coordinate columns BIWT recognizes by
name, and a metadata column holding the cell-type call. Real data has thousands of rows and
dozens of metadata columns, but the shape is identical.

## 2. Launch the wizard

If you are using a host application such as PhysiCell Studio, open its BIWT tab and skip to
step 3.

To run it standalone:

```python
import sys
from PyQt5.QtWidgets import QApplication

from biwt.gui.theme import apply_light_palette
from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, DomainSpec

domain = DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500, units="micron")

def on_complete(result):
    print(result.coordinates)
    result.to_csv("cells.csv")

app = QApplication(sys.argv)
apply_light_palette(app)

widget = create_biwt_widget(BiwtInput(preferred_domain=domain), on_complete=on_complete)
widget.show()
sys.exit(app.exec_())
```

The `DomainSpec` is the box your cells will be placed into — here, a 1000 × 1000 µm square.
Nothing writes to disk unless your `on_complete` says so.

## 3. Walk through it

Click **Import file…** and pick `demo.csv`. What happens next depends on your data, because
BIWT skips steps that do not apply. With this file you will see:

| Step | What you do | Why this file triggers it |
|---|---|---|
| [Cluster column](../guide/cluster-column.md) | Choose `celltype` | The file has metadata columns, so BIWT must be told which one holds the labels |
| [Spatial query](../guide/spatial-query.md) | Choose **yes** | `x` and `y` were recognized, so BIWT asks whether to use them |
| [Edit cell types](../guide/edit-cell-types.md) | Keep all three | Always shown |
| [Rename cell types](../guide/rename-cell-types.md) | Accept the defaults | Always shown |
| [Positions](../guide/positions.md) | Look at the preview, click through | Always shown |
| [Cell parameters](../guide/cell-parameters.md) | Pick any template, or none | Always shown |

Two steps do **not** appear: [spot deconvolution](../guide/spot-deconvolution.md) (this file
has no probability columns) and [cell counts](../guide/cell-counts.md) (you chose to use the
spatial coordinates, which determine the counts). That skipping is the wizard's core
behavior — see [how the wizard flows](../guide/index.md#how-steps-are-chosen).

At the positions step the [domain editor](../guide/domain.md) may open on its own, because
your data spans roughly ±320 µm inside a ±500 µm box. That is BIWT telling you the cells will
sit in the middle of the domain rather than filling it. For this demo, just click OK.

## 4. What you get

`on_complete` receives a [`BiwtResult`][biwt.types.BiwtResult]:

```
        x      y    z        type
0  -320.0  140.0  0.0       tumor
1  -298.0  155.0  0.0       tumor
2  -310.0  122.0  0.0       tumor
3    40.0 -260.0  0.0  macrophage
...
```

Seven rows, one per input cell, with `z` padded to zero because the input was 2D. If you had
merged or renamed types, `result.cell_type_map` would record how each original label maps to
its final name.

## Next

- **[User guide](../guide/index.md)** — every step in detail, including the ones this file
  skipped.
- **[Recipes](../recipes/index.md)** — the same walkthrough with real Visium, scRNA-seq, and
  deconvolution data.
- **[Embedding BIWT](../integration/index.md)** — if you are the one writing `on_complete`
  for other people.
