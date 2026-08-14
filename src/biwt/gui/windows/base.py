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

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QButtonGroup, QRadioButton,
)
from PyQt5.QtCore import Qt

from biwt.gui.widgets import GoBackButton, ContinueButton, biwt_icon


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
        # current_window_idx is pre-increment at build time; +2 gives the
        # correct 1-based step number that will be shown to the user.
        self._step_number = walkthrough.current_window_idx + 2
        self.setWindowTitle(f"BioInformatics WalkThrough — Step {self._step_number}")
        # Each step is its own top-level window, so each needs the icon: without
        # it they appear in the dock or taskbar under whatever generic mark the
        # host application's interpreter carries.
        self.setWindowIcon(biwt_icon())

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


    def closeEvent(self, event):  # noqa: N802
        """Closing a step abandons the run, so let the landing screen import again."""
        self.walkthrough._allow_import(True)
        super().closeEvent(event)


class YesNoQueryWindow(BiwinformaticsWalkthroughWindow):
    """A step that asks one yes/no question and writes one session field.

    Two steps are exactly this, and the shape is fiddly enough to get subtly
    wrong twice: ``idToggled`` fires for the button being *unchecked* as well, and
    the default has to be set explicitly rather than left to the toggle that
    ``setChecked`` emits, or it depends on statement order.

    Subclasses give ``title``, ``field``, and a ``message(session)``.
    """

    title: str = ""
    field: str = ""
    include_back: bool = True

    def message(self, session) -> str:
        raise NotImplementedError

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        header = QLabel(self.title)
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 18pt; font-weight: bold; margin-bottom: 10px;")

        self.yes_no_group = QButtonGroup()
        self.yes_rb = QRadioButton("Yes")
        self.no_rb = QRadioButton("No")
        self.yes_no_group.addButton(self.yes_rb, 0)
        self.yes_no_group.addButton(self.no_rb, 1)
        self.yes_no_group.idToggled.connect(self._toggled)
        self.yes_rb.setChecked(True)
        setattr(walkthrough.session, self.field, True)

        hbox_yn = QHBoxLayout()
        hbox_yn.addWidget(self.yes_rb)
        hbox_yn.addWidget(self.no_rb)

        vbox = QVBoxLayout()
        vbox.addWidget(header)
        vbox.addWidget(QLabel(self.message(walkthrough.session)))
        vbox.addLayout(hbox_yn)
        vbox.addLayout(self.create_nav_bar(include_back=self.include_back))
        self.setLayout(vbox)

    def _toggled(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return                    # the button being unchecked; not an answer
        self.walkthrough.stale_futures = True
        setattr(self.walkthrough.session, self.field, btn_id == 0)

    def process_window(self) -> None:
        self.walkthrough.advance()
