# Embedding BIWT

BIWT is designed to be embedded. It ships a Qt widget and a two-type data contract, and
deliberately knows nothing about the application hosting it.

If you maintain an ABM tool and want a single-cell import path, this section is for you.

## The whole interface

```python
from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, BiwtResult, DomainSpec

widget = create_biwt_widget(
    BiwtInput(preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500)),
    on_complete=my_handler,      # called with a BiwtResult
)
```

That is the entire surface. One factory function, one input type, one result type. Everything
else in `biwt` is internal and free to change.

## Three rules

### 1. The host owns all file I/O

BIWT never writes to disk. It hands you a `BiwtResult` in memory and your `on_complete` does
whatever your application does with output — write it, show a save dialog, keep it in memory,
push it to a server.

This is not an oversight to work around. It keeps BIWT usable from a notebook or a headless
script, and it means BIWT never has to know about your project layout, your file-overwrite
policy, or your undo system.

### 2. The widget does not close itself

When the workflow finishes, BIWT calls `on_complete` and stops. It does not hide, close, or
reset. If your application should dismiss the tab, do it in your handler.

Importing a new file resets the session, so the same widget instance can be reused for
another dataset.

### 3. `on_complete` can receive `None`

The callback signature is `Callable[[Optional[BiwtResult]], None]`. Handle the cancel case.

## Optional inputs worth wiring up

`BiwtInput` has three fields beyond the domain that meaningfully improve the experience if
your application can supply them:

| Field | Effect |
|---|---|
| `host_cell_type_names` | Cell types your app already defines. BIWT suggests the closest match as placeholder text at the [rename step](../guide/rename-cell-types.md), so imported types line up with existing definitions instead of duplicating them. |
| `host_name` | Your application's name, used in the [domain editor](../guide/domain.md) UI ("Use Studio Domain"). Defaults to `"Host"`, which looks unfinished. |
| `extra_cell_template_paths` | TOML files of your own phenotype templates, which appear alongside the 29 built-ins at the [cell parameters step](../guide/cell-parameters.md). |

`domain_accepted=True` suppresses the automatic domain-mismatch dialog, if your application
already validates the domain itself.

## Degrading gracefully when BIWT is absent

BIWT is an optional dependency for most hosts. The conventional pattern:

```python
try:
    from biwt.gui.walkthrough import create_biwt_widget
    from biwt.types import BiwtInput, DomainSpec
    HAVE_BIWT = True
except ImportError:
    HAVE_BIWT = False
```

...then branch on `HAVE_BIWT` when building the UI, and tell the user how to install it if
they reach for the feature.

## Read next

- **[The API contract](api-contract.md)** — `BiwtInput` and `BiwtResult` field by field,
  including what is reserved for future use.
- **[PhysiCell Studio](studio.md)** — a complete worked bridge, and the conventions it
  established.
- **[API reference](../reference/index.md)** — generated signatures and docstrings.
