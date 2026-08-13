"""
Abstract base class for all BIWT walkthrough step windows.

Each step is a ``BiwinformaticsWalkthroughWindow`` subclass.  The walkthrough
controller (``BioinformaticsWalkthrough``) owns a stack of windows and calls
``process_window()`` when the user clicks Continue.

Design notes
------------
- Windows hold only UI state; data decisions are written back to the
  walkthrough's ``session`` object (a plain dataclass, no Qt).
- The ABC metaclass trick is required because QWidget uses a custom sip
  metaclass that is incompatible with ABCMeta by default.
"""

from __future__ import annotations
from abc import abstractmethod, ABCMeta
from typing import Optional, Callable

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout

from biwt.gui.widgets import GoBackButton, ContinueButton


# ---------------------------------------------------------------------------
# Metaclass glue
# ---------------------------------------------------------------------------

_WidgetMeta = type(QWidget)


class _WidgetABCMeta(_WidgetMeta, ABCMeta):
    pass


# Styling BIWT cannot leave to the host.
#
# A disabled control has to *look* disabled — BIWT uses that state to say "this
# action has nothing to do here", from a merged cell type's checkbox to the
# "assign default" button when no library defines one.  Qt normally paints it
# from the palette's Disabled group, which an embedding application can flatten
# without meaning to: ``QPalette.setColor(role, color)`` with no ColorGroup sets
# *every* group, disabled included, so a host that does that for ButtonText or
# WindowText makes disabled and enabled identical.  PhysiCell Studio does exactly
# this.  A stylesheet on our own window overrides palette-derived rendering, so
# these rules put the distinction back under BIWT's control; widgets that set
# their own stylesheet (the green nav buttons, the keep/merge/delete colors)
# still win over it, as they should.
_DISABLED_FG = "#9a9a9a"

_WINDOW_STYLE = (
    "QLineEdit { background-color: white; border: 1px solid #555;"
    " border-radius: 2px; padding: 1px 4px; }"
    f"QLineEdit:disabled {{ color: {_DISABLED_FG}; background-color: #f2f2f2; }}"
    "QPushButton:disabled, QToolButton:disabled, QCheckBox:disabled,"
    f" QRadioButton:disabled, QComboBox:disabled, QLabel:disabled {{ color: {_DISABLED_FG}; }}"
)


# ---------------------------------------------------------------------------
# Abstract base window
# ---------------------------------------------------------------------------

class BiwinformaticsWalkthroughWindow(QWidget, metaclass=_WidgetABCMeta):
    """Base class for a single BIWT walkthrough step.

    Subclasses must implement ``process_window()``, which reads UI state,
    writes decisions to ``self.walkthrough.session``, and calls
    ``self.walkthrough.advance()``.  To block progress instead — after showing
    a validation dialog, say — return without calling ``advance()``; nothing
    catches exceptions raised out of this method.

    The ``create_nav_bar`` helper builds the standard ← Go back / Continue →
    button row so subclasses don't repeat that layout.
    """

    def __init__(self, walkthrough):
        super().__init__()
        self.walkthrough = walkthrough
        # Marking futures stale ensures later windows are re-built when a
        # user revisits this step and changes something.
        self.walkthrough.stale_futures = True
        # current_window_idx is pre-increment at build time; +2 gives the
        # correct 1-based step number that will be shown to the user.
        self._step_number = walkthrough.current_window_idx + 2
        self.setWindowTitle(f"BioInformatics WalkThrough — Step {self._step_number}")

    def setLayout(self, layout) -> None:  # noqa: N802
        """Wrap *layout* with margins and the styling BIWT relies on."""
        outer = QVBoxLayout()
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)
        outer.addLayout(layout)
        super().setLayout(outer)
        self.setStyleSheet(_WINDOW_STYLE)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def create_continue_button(
        self,
        cb: Optional[Callable] = None,
        **kwargs,
    ) -> ContinueButton:
        if cb is None:
            cb = self.process_window
        return ContinueButton(self, cb, **kwargs)

    def create_nav_bar(
        self,
        include_back: bool = True,
        continue_cb: Optional[Callable] = None,
        **continue_kwargs,
    ) -> QHBoxLayout:
        """Return an HBoxLayout with [Go back] [Continue →]."""
        hbox = QHBoxLayout()
        if include_back:
            hbox.addWidget(GoBackButton(self, self.walkthrough))
        hbox.addWidget(self.create_continue_button(continue_cb, **continue_kwargs))
        return hbox

    # ------------------------------------------------------------------
    # Subclass contract
    # ------------------------------------------------------------------

    @abstractmethod
    def process_window(self) -> None:
        """Read UI state, commit decisions, and advance the walkthrough."""
