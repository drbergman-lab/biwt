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
from abc import ABC, abstractmethod, ABCMeta
from typing import Optional, Callable

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt

from biwt.gui.widgets import GoBackButton, ContinueButton


# ---------------------------------------------------------------------------
# Metaclass glue
# ---------------------------------------------------------------------------

_WidgetMeta = type(QWidget)


class _WidgetABCMeta(_WidgetMeta, ABCMeta):
    pass


# ---------------------------------------------------------------------------
# Abstract base window
# ---------------------------------------------------------------------------

class BiwinformaticsWalkthroughWindow(QWidget, metaclass=_WidgetABCMeta):
    """Base class for a single BIWT walkthrough step.

    Subclasses must implement ``process_window()``, which reads UI state,
    writes decisions to ``self.walkthrough.session``, and calls
    ``self.walkthrough.advance()`` (or raises ``UserWarning`` to block
    advancing with an error message).

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
        """Wrap *layout* with a centered title, margins, and QLineEdit styling."""
        outer = QVBoxLayout()
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)
        outer.addLayout(layout)
        super().setLayout(outer)
        self.setStyleSheet(
            "QLineEdit { background-color: white; border: 1px solid #555;"
            " border-radius: 2px; padding: 1px 4px; }"
        )

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
