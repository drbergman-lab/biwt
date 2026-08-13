"""
Shared primitive widgets used across BIWT walkthrough windows.

These are small, self-contained Qt widgets with no business logic.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Optional, Callable

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PyQt5.QtWidgets import (
    QPushButton, QFrame, QSizePolicy, QCheckBox, QComboBox,
    QCompleter, QDialog, QStyle, QStyleOptionComboBox, QStylePainter,
    QVBoxLayout, QLabel, QLineEdit, QShortcut,
)
from PyQt5.QtCore import QSortFilterProxyModel
from PyQt5.QtGui import QColor, QIcon, QPalette, QValidator, QKeySequence
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


# Widest a generated row label may get before it wraps.  Roughly 30 characters
# at the default font — enough for any single cell-type name on one line.
ROW_LABEL_MAX_WIDTH = 240


def set_elided_text(widget, text: str, suffix: str = "",
                    max_width: int = ROW_LABEL_MAX_WIDTH) -> None:
    """Put *text* on *widget*, clipped to *max_width* px, full text in the tooltip.

    The companion to :func:`row_label`, for widgets whose text cannot wrap — a
    ``QCheckBox`` above all.  Cell-type names arrive from the data and survive
    merging and renaming, so any of them can be arbitrarily long; unchecked, one
    such name sets the width of the panel it sits in.

    *suffix* is appended after clipping, so a trailing annotation (``⇒ Merge Gp.
    #2``) is never eaten by the ellipsis — and stays readable by code that keys
    off it.
    """
    fm = widget.fontMetrics()
    shown = fm.elidedText(text, Qt.ElideRight, max_width)
    widget.setText(shown + suffix)
    widget.setToolTip((text + suffix) if shown != text else "")


def dropped_local_paths(event, suffixes) -> list:
    """Local file paths carried by a drag event whose suffix is in *suffixes*.

    Note what a drop can and cannot do: it hands over a **path on this machine**.
    In a streamed remote session — a Galaxy interactive tool, say — the app runs
    in a container and the user's own files never reach it, so no drop event
    arrives at all.  Drag-and-drop is therefore always an accelerator, never the
    only way to get a file in.
    """
    if not event.mimeData().hasUrls():
        return []
    paths = []
    for url in event.mimeData().urls():
        if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in suffixes:
            paths.append(url.toLocalFile())
    return paths


ICON_DIR = Path(__file__).parent / "icons"


def action_icon(name: str) -> QIcon:
    """A packaged action icon by stem, e.g. ``action_icon("auto_match")``.

    Drawn rather than typed: a text glyph is rendered by whatever font the host's
    fallback chain supplies, so the three action marks came out at visibly
    different sizes and weights — and differently again inside an embedding
    application.  An SVG looks the same everywhere and stays crisp on a HiDPI
    screen, which a PNG would not without a second asset.
    """
    return QIcon(str(ICON_DIR / f"action_{name}.svg"))


ROW_ARROW = "\u21d2"


def row_arrow() -> QLabel:
    """The ``⇒`` between a row's label and its field.

    Its own widget, in its own column, so it stays beside the field it points at
    and vertically centered on it.  Appended to the label instead, it would drift
    to the end of the last line whenever the label wrapped.
    """
    arrow = QLabel(ROW_ARROW)
    arrow.setAlignment(Qt.AlignCenter)
    return arrow


def row_label(text: str, max_width: int = ROW_LABEL_MAX_WIDTH) -> QLabel:
    """A right-aligned row label that wraps rather than widening its column.

    Some row labels are *generated* rather than typed: a merged cell type is
    labeled with every original name that fed it, so its natural width is
    unbounded.  Left to size itself, one such row dictates the width of the whole
    window and squeezes the fields on every other row.

    Capping the width and wrapping keeps every name readable — the row simply
    grows taller — where clipping would have hidden most of them behind a
    tooltip.  The tooltip is still set when the text does not fit on one line, for
    the case wrapping cannot help: a single unbreakable name wider than the cap.

    The row's ``⇒`` is *not* part of this label; see :func:`row_arrow`.
    """
    label = QLabel(text)
    label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if label.fontMetrics().horizontalAdvance(text) <= max_width:
        return label            # fits on one line; nothing to wrap

    # Wrapping only for the labels that need it.  A wrapped QLabel will happily
    # shrink to its longest *word*, which would break a short label across lines
    # for no reason and let the column collapse — so pin the width to the cap.
    label.setWordWrap(True)
    label.setFixedWidth(max_width)
    label.setToolTip(text)
    fm = label.fontMetrics()
    pieces = text.replace("-", " ").replace("/", " ").split()   # where Qt may break
    if max((fm.horizontalAdvance(w) for w in pieces), default=0) > max_width:
        # Nothing to wrap at, and a right-aligned QLabel clips an over-wide word
        # at its *start* — reading backwards. Elide it ourselves instead.
        label.setText(fm.elidedText(text, Qt.ElideRight, max_width))
    return label


class RelabelledComboBox(QComboBox):
    """A combo box that can draw something other than its current item's text.

    Qt paints a closed combo box from ``currentText()``, so an item that reads
    correctly inside the popup — under a group header, say — can lose its context
    the moment the list closes.  There is no per-widget display override, and the
    model may be shared between several combo boxes, so neither the item text nor
    the model can carry the difference.  Intercepting the paint can.

    Assign a callable to ``display_for_index``: given the current index it returns
    ``None`` to fall back to the item's own text, a string to draw instead, or a
    ``(primary, secondary)`` pair — *primary* left-aligned, *secondary* right-
    aligned and muted, which lines the secondaries up down a column of boxes.

    Nothing else changes: the popup, the signals and ``currentText()`` all behave
    exactly as before, so selection logic is unaffected.
    """

    #: Gap kept between the two halves, and the floor below which the primary is
    #: considered too squeezed to be worth qualifying.
    _GAP_EMS = 2
    _PRIMARY_FLOOR_CHARS = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.display_for_index = None

    # ------------------------------------------------------------------
    # What to draw
    # ------------------------------------------------------------------

    def displayed_parts(self) -> tuple:
        """``(primary, secondary)`` for the current index; secondary may be ""."""
        shown = None
        if self.display_for_index is not None:
            shown = self.display_for_index(self.currentIndex())
        if shown is None:
            return self.currentText(), ""
        if isinstance(shown, str):
            return shown, ""
        primary, secondary = shown
        return primary, secondary or ""

    def displayed_text(self) -> str:
        """The two halves as one string, for tests and logs."""
        primary, secondary = self.displayed_parts()
        return f"{primary} ({secondary})" if secondary else primary

    def text_layout(self, width: int) -> tuple:
        """What actually fits in *width*: ``(primary, secondary)``, either elided.

        The rule when both do not fit: **the secondary goes**. The primary names
        the thing chosen, so it is what the box must always say; a half-elided
        file path qualifies nothing. Only once the primary has room to stay
        legible is the qualifier worth its space.
        """
        primary, secondary = self.displayed_parts()
        fm = self.fontMetrics()
        if secondary:
            gap = self._GAP_EMS * fm.horizontalAdvance(" ")
            for_primary = width - fm.horizontalAdvance(secondary) - gap
            if for_primary >= self._PRIMARY_FLOOR_CHARS * fm.averageCharWidth():
                return fm.elidedText(primary, Qt.ElideRight, for_primary), secondary
        return fm.elidedText(primary, Qt.ElideRight, width), ""

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:      # noqa: N802
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)

        # Frame and arrow from the style; the label is ours, so it is drawn
        # without CE_ComboBoxLabel rather than through it.
        option.currentText = ""
        painter.drawComplexControl(QStyle.CC_ComboBox, option)

        field = self.style().subControlRect(
            QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self
        ).adjusted(2, 0, -2, 0)
        primary, secondary = self.text_layout(field.width())

        enabled = self.isEnabled()
        painter.setPen(self.palette().color(
            QPalette.Active if enabled else QPalette.Disabled, QPalette.Text
        ) if enabled else QColor("#9a9a9a"))
        painter.drawText(field, Qt.AlignLeft | Qt.AlignVCenter, primary)
        if secondary:
            painter.setPen(QColor("#8a8a8a") if enabled else QColor("#c4c4c4"))
            painter.drawText(field, Qt.AlignRight | Qt.AlignVCenter, secondary)
