"""
biwt.gui — PyQt5 walkthrough UI.

This subpackage requires PyQt5 (and matplotlib).  Install with:
    pip install biwt[gui]

Importing this module without PyQt5 raises a clear ImportError rather than
a cryptic AttributeError deep in Qt internals.

Public surface
--------------
    create_biwt_widget(biwt_input, on_complete) → BioinformaticsWalkthrough
"""

try:
    from PyQt5.QtWidgets import QWidget  # noqa: F401 — import check only
except ImportError as _err:
    raise ImportError(
        "biwt.gui requires PyQt5.\n"
        "Install with:  pip install biwt[gui]"
    ) from _err

from biwt.gui.walkthrough import BioinformaticsWalkthrough, create_biwt_widget

__all__ = ["BioinformaticsWalkthrough", "create_biwt_widget"]
