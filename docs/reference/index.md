# API reference

Generated from the source docstrings.

## What is public

| Module | Stability |
|---|---|
| [`biwt.types`](types.md) | **Public API.** `DomainSpec`, `BiwtInput`, `BiwtResult`. Changes here are breaking changes. |
| [`biwt.gui`](gui.md) | **Public entry point:** `create_biwt_widget`. The widget class and step windows are internal. |
| [`biwt.core`](core.md) | **Internal.** Documented because it is useful to read, but not a contract — signatures may change between releases. |

If you are embedding BIWT, you should only need `biwt.types` and `create_biwt_widget`. See
[the API contract](../integration/api-contract.md) for prose covering the same ground.

## Import paths

The three public types are re-exported at the package root, so both of these work:

```python
from biwt import BiwtInput, BiwtResult, DomainSpec      # convenient
from biwt.types import BiwtInput, BiwtResult, DomainSpec  # explicit
```

Same for the factory:

```python
from biwt.gui import create_biwt_widget
from biwt.gui.walkthrough import create_biwt_widget
```

!!! note "Importing `biwt.gui` requires PyQt5"
    `biwt.types` and `biwt.core` are pure Python and import without Qt. Only reach for
    `biwt.gui` when you have installed `biwt[gui]` or the host has supplied Qt.
