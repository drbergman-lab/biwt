"""
Shared primitive widgets used across BIWT walkthrough windows.

These are small, self-contained Qt widgets with no business logic.
"""

from __future__ import annotations
import os
from typing import Optional, Callable

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PyQt5.QtWidgets import (
    QPushButton, QFrame, QSizePolicy, QCheckBox, QComboBox,
    QCompleter, QDialog, QVBoxLayout, QLineEdit, QShortcut,
)
from PyQt5.QtCore import QSortFilterProxyModel
from PyQt5.QtGui import QValidator, QKeySequence
from PyQt5.QtCore import Qt


_CMD = "\u2318" if os.name != "nt" else "Ctrl"


class GoBackButton(QPushButton):
    """Green '← Go back' button (Cmd+Delete) that calls an optional pre-hook,
    then instructs the walkthrough to return to the previous step."""

    def __init__(
        self,
        parent,
        walkthrough,
        pre_cb: Optional[Callable] = None,
        post_cb: Optional[Callable] = None,
    ):
        super().__init__(parent)
        self.setText(f"\u2190 Go back ({_CMD}\u232b)")
        self.setStyleSheet("QPushButton {background-color: lightgreen; color: black;}")
        if pre_cb is not None:
            self.clicked.connect(pre_cb)
        self.clicked.connect(walkthrough.go_back_to_prev_window)
        if post_cb is not None:
            self.clicked.connect(post_cb)
        self._back_shortcut = QShortcut(QKeySequence("Ctrl+Backspace"), parent)
        self._back_shortcut.activated.connect(walkthrough.go_back_to_prev_window)


class ContinueButton(QPushButton):
    """Green 'Continue →' button (Cmd+Return) that calls *cb* on click."""

    _DEFAULT_STYLE = (
        "QPushButton:enabled  { background-color: lightgreen; color: black; }"
        "QPushButton:disabled { background-color: #b0b0b0;   color: #666;   }"
    )

    def __init__(
        self,
        parent,
        cb: Callable,
        text: str = f"Continue \u2192 ({_CMD}\u21a9)",
        style_sheet: str = _DEFAULT_STYLE,
    ):
        super().__init__(parent)
        self.setText(text)
        self.setStyleSheet(style_sheet)
        self.clicked.connect(cb)
        # Cmd+Return (macOS) / Ctrl+Return (Windows/Linux) triggers Continue
        self._shortcut = QShortcut(QKeySequence("Ctrl+Return"), parent)
        self._shortcut.activated.connect(self._trigger_if_enabled)

    def _trigger_if_enabled(self) -> None:
        if self.isEnabled():
            self.click()


class QHLine(QFrame):
    """Horizontal separator line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.HLine)
        self.setFrameShadow(QFrame.Sunken)


class QVLine(QFrame):
    """Vertical separator line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.VLine)
        self.setFrameShadow(QFrame.Sunken)


# Use the real QRadioButton so isChecked() etc. work correctly.
from PyQt5.QtWidgets import QRadioButton as QRadioButton_custom  # noqa: F401


class QCheckBox_custom(QCheckBox):
    """QCheckBox with a consistent cross-platform indicator style."""

    _STYLE = """
        QCheckBox:disabled { background-color: lightgray; }
    """

    def __init__(self, name: str, **kwargs):
        super().__init__(name, **kwargs)
        self.setStyleSheet(self._STYLE)


class QLineEdit_custom(QLineEdit):
    """QLineEdit with validity-color feedback and a disabled-background color.

    Mirrors ``studio_classes.QLineEdit_custom`` so that all existing window
    code that relies on ``check_validity()``, ``get_full_value()``,
    ``set_formatter()``, ``full_value``, ``valid_style``, ``invalid_style``
    continues to work unchanged.
    """

    def __init__(self, disabled_color: str = "gray", ndigits: Optional[int] = None, **kwargs):
        super().__init__(**kwargs)
        self.validator = None
        self.full_value: Optional[str] = None
        self._disabled_color = disabled_color
        self._ndigits: Optional[int] = ndigits
        if ndigits is not None:
            self.editingFinished.connect(self.format_text)
        self._create_styles()
        self.textChanged.connect(self.check_validity)
        self.check_validity(self.text())

    def setText(self, text: str) -> None:  # noqa: N802
        super().setText(text)
        if self._ndigits is not None and not self.signalsBlocked():
            self.format_text()

    def setValidator(self, validator):  # noqa: N802
        super().setValidator(validator)
        self.validator = validator

    def check_validity(self, text: str = None) -> bool:
        if text is None:
            text = self.text()
        if self.validator and self.validator.validate(text, 0)[0] != QValidator.Acceptable:
            self.setStyleSheet(self.invalid_style)
            return False
        self.setStyleSheet(self.valid_style)
        return True

    def _create_styles(self):
        self.valid_style = f"""
            QLineEdit {{ color: black; background-color: white; }}
            QLineEdit:disabled {{ color: black; background-color: {self._disabled_color}; }}
        """
        self.invalid_style = f"""
            QLineEdit {{ color: black; background-color: rgba(255, 0, 0, 0.5); }}
            QLineEdit:disabled {{ color: black; background-color: {self._disabled_color}; }}
        """

    def set_formatter(self, bval: bool = True, ndigits: int = 5):
        if bval:
            self._ndigits = ndigits
            self.editingFinished.connect(self.format_text)
        else:
            self._ndigits = None
            try:
                self.editingFinished.disconnect()
            except TypeError:
                pass

    def format_text(self):
        ndigits = self._ndigits
        if ndigits is None:
            return
        try:
            self.full_value = self.text()
            value = float(self.full_value)
            if value == 0:
                formatted = "0"
            elif abs(value) < 10 ** -ndigits:
                formatted = f"{value:.{ndigits}e}"
            else:
                formatted = f"{value:.{ndigits}f}".rstrip("0").rstrip(".")
            self.blockSignals(True)
            self.setText(formatted)
            self.blockSignals(False)
        except ValueError:
            pass

    def get_full_value(self) -> Optional[float]:
        try:
            return float(self.full_value or self.text())
        except (ValueError, TypeError):
            return None

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self.full_value is not None:
            # Bypass the overridden setText so format_text is NOT called here.
            QLineEdit.setText(self, self.full_value)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Re-apply rounding when focus leaves (covers tab-away without editing).
        self.format_text()


class LegendWindow(QDialog):
    """Floating legend window for the scatter plot."""

    def __init__(self, parent=None, legend_artists=None, legend_labels=None,
                 legend_title=None):
        super().__init__(parent)
        self.setWindowTitle(f"Legend: {legend_title}")
        self.setGeometry(100, 100, 300, 200)
        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        ax = self.figure.add_subplot(111)
        ax.legend(legend_artists or [], legend_labels or [])
        ax.axis("off")
        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.setLayout(layout)

    def closeEvent(self, event):  # noqa: N802
        self.figure.clear()
        super().closeEvent(event)


class ExtendedCombo(QComboBox):
    """QComboBox with case-insensitive filter-as-you-type completion."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setEditable(True)
        self.completer = QCompleter(self)
        self.completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)
        self._filter_model = QSortFilterProxyModel(self)
        self._filter_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setPopup(self.view())
        self.setCompleter(self.completer)
        self.lineEdit().textEdited[str].connect(self._filter_model.setFilterFixedString)
        self.completer.activated.connect(self._set_text_if_completer_clicked)

    def setModel(self, model):  # noqa: N802
        super().setModel(model)
        self._filter_model.setSourceModel(model)
        self.completer.setModel(self._filter_model)

    def setModelColumn(self, column):  # noqa: N802
        self.completer.setCompletionColumn(column)
        self._filter_model.setFilterKeyColumn(column)
        super().setModelColumn(column)

    def view(self):
        return self.completer.popup()

    def _set_text_if_completer_clicked(self, text: str):
        if self.currentText() != text:
            index = self.findText(text)
            if index >= 0:
                self.setCurrentIndex(index)
            else:
                self.setCurrentIndex(0)


class SectionHeader(QPushButton):
    """Non-interactive orange section-label bar (matches Studio style)."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setEnabled(False)
        self.setMaximumHeight(20)
        self.setStyleSheet(
            "QPushButton {background-color: orange; color: black; font-weight: bold;}"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
