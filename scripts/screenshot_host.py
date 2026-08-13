#!/usr/bin/env python3
"""Launch BIWT standalone with the host settings the documentation pictures use.

    PYTHONPATH=src python scripts/screenshot_host.py

Run ``make_screenshot_data.py`` first; this opens the window you then walk and
capture.  The companion checklist lives with the docs work, not here.

Why a dedicated launcher
------------------------
``scratch_biwt.py`` is built for adversarial testing: it passes
``host_name="Scratch"``, host cell types and a template library, and every one of
those is visible in a screenshot — as "Use Scratch Domain", as extra rows on the
cell-parameters screen.  The published images show a plain host, so this passes
nothing but a domain and lets ``host_name`` default to "Host".

Studio is the wrong launcher for the same reason: it embeds the widget in a tab,
and the published images are of a standalone window.

The ±500 µm domain is load-bearing.  The synthetic tissue is ~2000 µm across, so
against ±500 it classifies as "outside" and the domain editor opens by itself at
the positions step — which is the state ``docs/guide/domain.md`` pictures.  Widen
this and that screenshot becomes unreachable.
"""

from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication, QMainWindow

from biwt.gui.theme import apply_light_palette
from biwt.gui.walkthrough import create_biwt_widget
from biwt.types import BiwtInput, DomainSpec


def on_complete(result) -> None:
    """Print what the host would have received, so a pass can be sanity-checked."""
    print(f"\n{len(result.coordinates)} cells, "
          f"{result.coordinates['type'].nunique()} types")
    print("domain:", result.domain_used)
    for cell_type, (path, name, content) in result.cell_templates.items():
        print(f"  {cell_type:20s} -> {name:20s} "
              f"[{path.split('/')[-1]}] {len(content)} chars")


def main(argv=None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    apply_light_palette(app)

    biwt_input = BiwtInput(
        # Deliberately nothing else: no host_name, no host_cell_type_names, no
        # cell_template_paths.  Load the .toml libraries through "Add templates
        # from file…" instead, which is what the cell-parameters picture shows.
        preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500,
                                    units="micron"),
    )

    window = QMainWindow()
    window.setCentralWidget(create_biwt_widget(biwt_input, on_complete=on_complete))
    window.resize(1100, 820)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
