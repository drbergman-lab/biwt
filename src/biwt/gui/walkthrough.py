"""
BioinformaticsWalkthrough — top-level popup widget (new package interface).

This is the main controller for the BIWT workflow.  It owns:
  - The step-window stack (windows are built lazily on demand).
  - A ``WalkthroughSession`` dataclass that accumulates all data decisions
    (no Qt objects stored there — purely plain data).
  - The ``BiwtResult`` that is handed back to the host via ``on_complete``.

Host usage (e.g. from Studio's ICs tab):
-----------------------------------------
    from biwt import BiwtInput, DomainSpec
    from biwt.gui import create_biwt_widget

    biwt_input = BiwtInput(
        preferred_domain=DomainSpec(xmin=-500, xmax=500, ymin=-500, ymax=500),
        host_cell_type_names=celldef_tab.get_cell_type_names(),
    )
    widget = create_biwt_widget(biwt_input, on_complete=my_callback)
    widget.show()

``my_callback`` receives a ``BiwtResult`` when the user finishes the workflow.

Migration status
----------------
The step windows listed in ``_WINDOW_SEQUENCE`` are progressively migrated
from ``bin/biwt_tab.py``.  Windows not yet migrated fall back to the legacy
implementation via ``_legacy_window_fallback``.  Each migrated window is
removed from the fallback list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Optional, Callable, NamedTuple, Type
import logging

import numpy as np
import pandas as pd

from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QCheckBox, QToolButton,
    QFileDialog, QMessageBox, QDialogButtonBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDoubleValidator

from biwt.types import DomainSpec, BiwtInput, BiwtResult
from biwt.core import data_loader
from biwt.core.data_loader import BiwtData, LoadError
from biwt.core import domain as domain_module
from biwt.core.cell_types import CellTypeConfig, CellTypeAction, suggest_name_mappings
from biwt.core.positioning import build_ic_dataframe
from biwt.gui.widgets import QHLine, QLineEdit_custom, QVLine, SectionHeader

log = logging.getLogger(__name__)

_LE_STYLE = (
    "background-color: white; border: 1px solid #555;"
    " border-radius: 2px; padding: 1px 4px;"
)

# For fields that are present but switched off.  A disabled QLineEdit carrying
# _LE_STYLE keeps its white background, so it reads as empty-and-editable rather
# than inert — which matters for the domain editor's z row, where the widgets
# exist only so the row matches x and y.
_LE_STYLE_INERT = (
    "background-color: #ececec; border: 1px solid #bbb; color: #999;"
    " border-radius: 2px; padding: 1px 4px;"
)


# ---------------------------------------------------------------------------
# Domain editor dialog
# ---------------------------------------------------------------------------

class _Axis(NamedTuple):
    """One axis of the domain: its label, its two bounds, and its extent.

    Bundling them in a single record is what keeps "width belongs to x" true by
    construction.  Everything that walks the domain — the grid layout, the
    extent derivation, and the bounds validation — iterates this one table, so
    no caller has to know that ``width`` is the span of ``xmin``…``xmax``, and
    nothing addresses a bound or an extent by position.
    """
    label: str            # "X" — the axis, shown as the row label
    extent: str           # "width" — both the dict key and the displayed word
    lo: str               # "xmin" — DomainSpec attribute for the minimum
    hi: str               # "xmax" — DomainSpec attribute for the maximum
    factor_scaled: bool   # does the data-unit ⇄ host-unit factor apply?


# z is not ``factor_scaled``: it is a 2-D slab / synthetic depth rather than a
# measurement in data units, so the factor has nothing to convert.  Its
# data-units cells are still built, so the Z row matches the others and wiring
# them up later is a matter of flipping this flag.
_DOMAIN_AXES = (
    _Axis("X", "width",  "xmin", "xmax", True),
    _Axis("Y", "height", "ymin", "ymax", True),
    _Axis("Z", "depth",  "zmin", "zmax", False),
)


def _scale_domain(d: DomainSpec, factor: float,
                  source: str = "data_range", units: str = "micron") -> DomainSpec:
    """Return *d* with its x/y bounds multiplied by *factor* (host-units per data unit).

    Z bounds are left untouched (a 2-D slab / synthetic depth, not a data-unit
    measurement). Used to convert a raw data-range domain into host units.
    """
    return DomainSpec(
        xmin=d.xmin * factor, xmax=d.xmax * factor,
        ymin=d.ymin * factor, ymax=d.ymax * factor,
        zmin=d.zmin, zmax=d.zmax, source=source, units=units,
    )


class DomainEditorDialog(QDialog):
    """Pop-up for reviewing / editing domain bounds after data import.

    The domain is edited in the **host's units** (``preferred_domain.units``,
    e.g. microns).  A conversion factor (host-units per data unit) is shown
    alongside a mirrored **data-units** column; editing either column keeps the
    other in sync via the factor.  When "Apply scale factor to data" is checked,
    the factor is used to scale the placed cells (``raw × factor``, centered in
    the domain).

    ``result()`` returns ``(DomainSpec, scale_factor, apply_scale)`` after
    ``exec_()`` returns ``QDialog.Accepted``.
    """

    # The grid is laid out one row per axis, so an axis' extent sits on the same
    # row as the two bounds that define it.  Editing an extent moves the
    # **maximum** and anchors the minimum, so exactly one bound changes: set the
    # left edge, then set the width, and the width does not shift the left edge
    # back.
    _AXES = _DOMAIN_AXES
    # Bound attrs the factor applies to, in grid order.  Derived rather than
    # spelled out so it cannot drift from _AXES.
    _XY = tuple(a for ax in _DOMAIN_AXES if ax.factor_scaled
                for a in (ax.lo, ax.hi))

    def __init__(
        self,
        parent: QWidget,
        data_domain: DomainSpec,
        preferred_domain: DomainSpec,
        context_message: str = "",
        initial_domain: Optional[DomainSpec] = None,
        host_name: str = "Host",
        file_factor: Optional[float] = None,
        current_factor: Optional[float] = None,
        apply_scale: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle("Domain Settings")
        # Three paired columns (min | max | size), each holding two fields.
        self.setMinimumWidth(660)

        self._data_domain = data_domain            # raw bounds, data units
        self._preferred_domain = preferred_domain  # host bounds, host units
        self._file_factor = file_factor
        # Re-entrancy guard: bounds and extents write to each other, so whichever
        # side the user is editing must not be overwritten mid-keystroke.
        self._syncing = False
        # Both are singular unit *names* ("micron", "data unit"), so they read
        # correctly both as a column header and as a ratio denominator.
        self._host_units = (preferred_domain.units or "micron")
        self._data_units = (data_domain.units if data_domain else None) or "data unit"

        layout = QVBoxLayout(self)

        if context_message:
            lbl = QLabel(context_message)
            lbl.setWordWrap(True)
            layout.addWidget(lbl)

        # --- conversion factor row ---
        factor_hbox = QHBoxLayout()
        # Ratio notation ("micron/data unit") rather than prose ("micron per
        # data unit"): a ratio denominator is singular by convention, which
        # sidesteps pluralising either unit name.  Reads straight off the two
        # DomainSpecs, so a data domain that ever carries a real unit name
        # renders as e.g. "micron/pixel" with no further change here.
        factor_hbox.addWidget(QLabel(f"{self._host_units}/{self._data_units}:"))
        self._factor_edit = QLineEdit()
        fv = QDoubleValidator()
        fv.setBottom(0.0)
        self._factor_edit.setValidator(fv)
        self._factor_edit.setStyleSheet(_LE_STYLE)
        self._factor_edit.setMaximumWidth(120)
        self._factor_edit.setPlaceholderText("none found in file")
        F0 = current_factor if current_factor is not None else file_factor
        if F0 is not None:
            self._factor_edit.setText(f"{F0:g}")
        factor_hbox.addWidget(self._factor_edit)
        self._reset_btn = QToolButton()
        self._reset_btn.setText("↺")  # ↺ restore
        self._reset_btn.clicked.connect(self._on_reset)
        factor_hbox.addWidget(self._reset_btn)
        factor_hbox.addStretch()
        layout.addLayout(factor_hbox)

        # --- axis grid: one row per axis, columns min | max | size ---
        # Each cell pairs the host-units field with its data-units mirror in
        # parentheses.  Host units lead because that is what the domain is
        # stored in and what placement and BiwtResult consume; the data-units
        # value is the annotation.  Laying it out per axis rather than per field
        # is what puts "width" on the X row instead of six rows below it.
        legend = QLabel(
            f"<b>{escape(self._host_units)}</b> "
            f"<span style='color:#666;'>({escape(self._data_units)})</span>"
        )
        layout.addWidget(legend)

        # Ruled like a table: separators sit in their own grid tracks, so the
        # data columns keep odd indices and the axis rows keep even ones.  Six
        # paired fields in a row is too many to delimit by whitespace alone —
        # without rules it is not obvious where "min" stops and "max" starts.
        _LABEL_COL, _DATA_COLS, _STRETCH_COL = 0, (2, 4, 6), 7
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        for col, head in zip(_DATA_COLS, ("min", "max", "size")):
            lbl = QLabel(f"<b>{head}</b>")
            lbl.setAlignment(Qt.AlignCenter)
            grid.addWidget(lbl, 0, col)

        self._du_fields: dict[str, QLineEdit] = {}     # every bound; z stays inert
        self._host_fields: dict[str, QLineEdit] = {}   # x/y/z (the stored domain)
        self._extent_fields: dict[str, QLineEdit] = {}
        self._du_extent_fields: dict[str, QLineEdit] = {}
        dv = QDoubleValidator()

        def edit(width: int) -> QLineEdit_custom:
            le = QLineEdit_custom(ndigits=2)
            le.setValidator(dv)
            le.setStyleSheet(_LE_STYLE)
            # Fixed rather than expanding: a stretched field drags its closing
            # parenthesis away from the number it is supposed to be wrapping.
            le.setFixedWidth(width)
            return le

        # Axis rows are 2, 4, 6 — the odd rows in between hold the rules.
        for row, ax in zip(range(2, 2 * len(self._AXES) + 1, 2), self._AXES):
            grid.addWidget(QLabel(f"{ax.label} ({ax.extent})"), row, _LABEL_COL)
            for col, attr in zip(_DATA_COLS, (ax.lo, ax.hi)):
                self._host_fields[attr] = edit(86)
                self._du_fields[attr] = edit(74)
                grid.addWidget(
                    self._pair_cell(self._host_fields[attr], self._du_fields[attr]),
                    row, col,
                )
            self._extent_fields[ax.extent] = edit(86)
            self._du_extent_fields[ax.extent] = edit(74)
            grid.addWidget(
                self._pair_cell(self._extent_fields[ax.extent],
                                self._du_extent_fields[ax.extent]),
                row, _DATA_COLS[-1],
            )

        last_row = 2 * len(self._AXES)
        # Rules last, so they span tracks whose sizes are already established.
        for col in (1, 3, 5):
            grid.addWidget(QVLine(), 0, col, last_row + 1, 1)
        for row in range(1, last_row, 2):
            grid.addWidget(QHLine(), row, _LABEL_COL, 1, _STRETCH_COL)
        # Soak up the leftover width here rather than letting the cells stretch.
        grid.setColumnStretch(_STRETCH_COL, 1)
        # Kept so the axis-major invariant is assertable: an extent must share a
        # grid row with the two bounds it spans.
        self._grid = grid
        layout.addLayout(grid)

        # --- preset buttons ---
        preset_hbox = QHBoxLayout()
        data_btn = QPushButton("Use Data Domain")
        data_btn.clicked.connect(self._fill_data)
        preferred_btn = QPushButton(f"Use {host_name} Domain")
        preferred_btn.clicked.connect(self._fill_preferred)
        preset_hbox.addWidget(data_btn)
        preset_hbox.addWidget(preferred_btn)
        layout.addLayout(preset_hbox)

        # --- apply checkbox ---
        self._apply_cb = QCheckBox("Apply scale factor to data")
        self._apply_cb.setChecked(apply_scale)
        layout.addWidget(self._apply_cb)

        # --- OK / Cancel ---
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        # Kept so _validate can gate it; Cancel stays enabled unconditionally, so
        # an unusable domain is always escapable.
        self._ok_btn = btn_box.button(QDialogButtonBox.Ok)
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

        # --- initial population (before signals are connected) ---
        if initial_domain is not None:
            self._fill_host(initial_domain)   # revisit: host column = active domain
        else:
            self._fill_data()                 # first open: host = raw×F (or raw)
        self._update_data_units_enabled()
        self._update_reset_enabled()
        self._sync_extents_from_host()
        self._validate()

        # --- wire signals (after population, so programmatic fills don't loop) ---
        # textEdited fires only on user input (not setText) → no sync loops.
        self._factor_edit.textChanged.connect(self._on_factor_changed)
        # Only the factor-scaled axes are wired on the data-units side; z owns
        # the widgets purely so its row matches the others.
        for attr in self._XY:
            self._du_fields[attr].textEdited.connect(
                lambda _t, a=attr: self._on_du_edited(a))
            self._host_fields[attr].textEdited.connect(
                lambda _t, a=attr: self._on_host_edited(a))
        # textChanged, not textEdited: a bound also moves via the presets and the
        # factor sync, and the extents and the OK gate must follow every time.
        for le in self._host_fields.values():
            le.textChanged.connect(self._on_host_changed)
        for key, le in self._extent_fields.items():
            le.textEdited.connect(lambda _t, k=key: self._on_extent_edited(k))
        for ax in self._AXES:
            if ax.factor_scaled:
                self._du_extent_fields[ax.extent].textEdited.connect(
                    lambda _t, k=ax.extent: self._on_du_extent_edited(k))

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pair_cell(host_le: QLineEdit, du_le: QLineEdit) -> QWidget:
        """One grid cell: *host_le*, with *du_le* beside it in parentheses.

        Wrapped in its own widget rather than spread across four grid columns,
        which would leave the grid 13 columns wide and reintroduce exactly the
        positional addressing this layout exists to remove.
        """
        cell = QWidget()
        hbox = QHBoxLayout(cell)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(2)
        hbox.addWidget(host_le)
        for text, widget in (("(", None), (None, du_le), (")", None)):
            hbox.addWidget(QLabel(text) if widget is None else widget)
        return cell

    # ------------------------------------------------------------------
    # Factor
    # ------------------------------------------------------------------

    def _effective_factor(self) -> Optional[float]:
        """Current factor: the field value if valid (>0), else the file value."""
        text = self._factor_edit.text().strip()
        if not text:
            return self._file_factor
        try:
            f = float(text)
        except ValueError:
            return None
        return f if f > 0 else None

    def _on_factor_changed(self, _text: str = "") -> None:
        # A changed factor re-derives the data-units column from the host domain.
        if self._effective_factor() is not None:
            self._sync_du_from_host()
        self._update_data_units_enabled()
        self._update_reset_enabled()

    def _on_reset(self) -> None:
        if self._file_factor is not None:
            self._factor_edit.setText(f"{self._file_factor:g}")

    def _update_reset_enabled(self) -> None:
        if self._file_factor is None:
            self._reset_btn.setEnabled(False)
            self._reset_btn.setToolTip("")
            return
        cur = self._effective_factor()
        differs = cur is None or abs(cur - self._file_factor) > 1e-12
        self._reset_btn.setEnabled(differs)
        self._reset_btn.setToolTip(f"restore value from file: {self._file_factor:g}")

    def _update_data_units_enabled(self) -> None:
        """Enable the data-units cells that the factor can actually convert.

        Without a factor there is nothing to convert, so the whole column goes
        inert; z stays inert either way — it carries the widgets so its row
        matches the others, not because the factor applies to it.
        """
        enabled = self._effective_factor() is not None
        inert_tip = f"z is not scaled by the {self._host_units}/{self._data_units} factor"
        for ax in self._AXES:
            live = enabled and ax.factor_scaled
            for le in (self._du_fields[ax.lo], self._du_fields[ax.hi],
                       self._du_extent_fields[ax.extent]):
                le.setEnabled(live)
                le.setStyleSheet(_LE_STYLE if live else _LE_STYLE_INERT)
                if not ax.factor_scaled:
                    le.setToolTip(inert_tip)

    # ------------------------------------------------------------------
    # Column sync
    # ------------------------------------------------------------------

    @staticmethod
    def _parse(le: QLineEdit) -> Optional[float]:
        try:
            return float(le.text())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _fmt(v: float) -> str:
        return f"{v:g}"

    def _sync_du_from_host(self) -> None:
        F = self._effective_factor()
        if F is None:
            return
        for attr in self._XY:
            host_v = self._parse(self._host_fields[attr])
            if host_v is not None:
                self._du_fields[attr].setText(self._fmt(host_v / F))

    def _on_du_edited(self, attr: str) -> None:
        F = self._effective_factor()
        v = self._parse(self._du_fields[attr])
        if F is None or v is None:
            return
        self._host_fields[attr].setText(self._fmt(v * F))

    def _on_host_edited(self, attr: str) -> None:
        F = self._effective_factor()
        v = self._parse(self._host_fields[attr])
        if F is None or v is None:
            return
        self._du_fields[attr].setText(self._fmt(v / F))

    # ------------------------------------------------------------------
    # Preset fills
    # ------------------------------------------------------------------

    def _fill_host(self, d: DomainSpec) -> None:
        """Fill the host column from *d* (host units); derive the data-units column."""
        for attr in self._host_fields:
            self._host_fields[attr].setText(self._fmt(getattr(d, attr)))
        self._sync_du_from_host()

    def _fill_data(self) -> None:
        """Use Data Domain: data-units = raw bounds; host = raw × factor (or raw)."""
        d = self._data_domain
        zmin, zmax = d.zmin, d.zmax
        if abs(zmax - zmin) < 1e-6:
            zmin, zmax = -10.0, 10.0
        F = self._effective_factor()
        for attr in self._XY:
            raw = getattr(d, attr)
            if F is not None:
                self._du_fields[attr].setText(self._fmt(raw))
                self._host_fields[attr].setText(self._fmt(raw * F))
            else:
                self._host_fields[attr].setText(self._fmt(raw))
        # Z is never scaled by the factor.
        self._host_fields["zmin"].setText(self._fmt(zmin))
        self._host_fields["zmax"].setText(self._fmt(zmax))

    def _fill_preferred(self) -> None:
        """Use Host Domain: host = host bounds verbatim; derive data-units."""
        for attr in self._host_fields:
            self._host_fields[attr].setText(self._fmt(getattr(self._preferred_domain, attr)))
        self._sync_du_from_host()

    # ------------------------------------------------------------------
    # Extents
    # ------------------------------------------------------------------

    def _on_host_changed(self, _text: str = "") -> None:
        self._sync_extents_from_host()
        self._validate()

    def _sync_extents_from_host(self) -> None:
        """Re-derive width/height/depth, both unit columns, from the bounds."""
        if self._syncing:
            return
        self._syncing = True
        try:
            for ax in self._AXES:
                a = self._parse(self._host_fields[ax.lo])
                b = self._parse(self._host_fields[ax.hi])
                self._extent_fields[ax.extent].setText(
                    "" if a is None or b is None else self._fmt(b - a)
                )
            self._sync_du_extents()
        finally:
            self._syncing = False

    def _sync_du_extents(self, skip: Optional[str] = None) -> None:
        """Mirror each extent into data units, leaving *skip* alone.

        Derived from the host bounds (span ÷ factor) rather than by subtracting
        the data-units bounds: a bound edit fires both textEdited and
        textChanged, and only the host column is guaranteed to have been written
        by the time this runs, so reading the data-units column could lag a
        keystroke behind.  *skip* is the field the user is typing in, which must
        not be rewritten underneath them.
        """
        F = self._effective_factor()
        for ax in self._AXES:
            if ax.extent == skip:
                continue
            a = self._parse(self._host_fields[ax.lo])
            b = self._parse(self._host_fields[ax.hi])
            usable = F is not None and ax.factor_scaled and a is not None and b is not None
            self._du_extent_fields[ax.extent].setText(
                self._fmt((b - a) / F) if usable else ""
            )

    def _on_extent_edited(self, key: str, _du_source: Optional[str] = None) -> None:
        """Move that axis' maximum, anchoring the minimum where the user put it.

        Exactly one bound moves, which is what makes the minimum and the extent
        independently settable — type the left edge, then type the width, and
        the width does not drag the left edge with it.  The other axes are
        untouched either way.

        *_du_source* names the data-units extent the edit originated from, if
        any, so the mirror does not overwrite the field being typed in.
        """
        if self._syncing:
            return
        ax = next(a for a in self._AXES if a.extent == key)
        size = self._parse(self._extent_fields[key])
        a = self._parse(self._host_fields[ax.lo])
        if size is None or a is None:
            self._validate()
            return
        self._syncing = True
        try:
            self._host_fields[ax.hi].setText(self._fmt(a + size))
        finally:
            self._syncing = False
        self._sync_du_from_host()
        self._sync_du_extents(skip=_du_source)
        self._validate()

    def _on_du_extent_edited(self, key: str) -> None:
        """A data-units extent edit is the host rule expressed in data units.

        Converted to host units and handed to ``_on_extent_edited`` rather than
        reimplemented, so "move the maximum, anchor the minimum" has exactly one
        implementation and cannot drift between the two columns.
        """
        if self._syncing:
            return
        F = self._effective_factor()
        size = self._parse(self._du_extent_fields[key])
        if F is None or size is None:
            self._validate()
            return
        self._syncing = True
        try:
            self._extent_fields[key].setText(self._fmt(size * F))
        finally:
            self._syncing = False
        self._on_extent_edited(key, _du_source=key)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _invalid_bounds(self) -> set[str]:
        """Host-bound attrs that make the domain unusable.

        A bound is flagged when it is not a number, or when it is on the wrong
        side of its partner.  Equal bounds count as wrong: a zero-width axis
        divides by zero in the placement scaling, and a zero-area domain makes
        the confluence counts meaningless.
        """
        bad: set[str] = set()
        vals: dict[str, Optional[float]] = {}
        for attr, le in self._host_fields.items():
            v = self._parse(le)
            vals[attr] = v
            if v is None:
                bad.add(attr)
        for ax in self._AXES:
            if (vals[ax.lo] is not None and vals[ax.hi] is not None
                    and vals[ax.lo] >= vals[ax.hi]):
                bad.update((ax.lo, ax.hi))
        return bad

    def _validate(self) -> None:
        """Flag the offending bounds and gate OK on there being none."""
        bad = self._invalid_bounds()
        for attr, le in self._host_fields.items():
            le.setStyleSheet(le.invalid_style if attr in bad else _LE_STYLE)
        self._ok_btn.setEnabled(not bad)
        self._ok_btn.setToolTip(
            "" if not bad else
            "Every bound must be a number, and each minimum must be "
            "below its maximum."
        )

    # ------------------------------------------------------------------

    def result(self) -> tuple[DomainSpec, Optional[float], bool]:
        """Return ``(host-units DomainSpec, scale_factor, apply_scale)``.

        Only meaningful after ``exec_()`` returned ``Accepted``; OK is disabled
        while any bound is unparseable, so every field reads as a float here.
        """
        def hv(attr):
            v = self._parse(self._host_fields[attr])
            if v is None:                      # unreachable while OK is gated
                raise ValueError(f"domain bound {attr!r} is not a number")
            return v
        domain = DomainSpec(
            xmin=hv("xmin"), xmax=hv("xmax"),
            ymin=hv("ymin"), ymax=hv("ymax"),
            zmin=hv("zmin"), zmax=hv("zmax"),
            source="user_edited", units=self._host_units,
        )
        return domain, self._effective_factor(), self._apply_cb.isChecked()


def _build_mismatch_message(
    kind: str, data: DomainSpec, preferred: DomainSpec, host_name: str = "Host"
) -> str:
    """Return a human-readable header for DomainEditorDialog based on mismatch kind."""
    data_str = (
        f"Data range: [{data.xmin:.1f}, {data.xmax:.1f}] \u00d7 "
        f"[{data.ymin:.1f}, {data.ymax:.1f}]"
    )
    pref_str = (
        f"{host_name}: [{preferred.xmin:.1f}, {preferred.xmax:.1f}] \u00d7 "
        f"[{preferred.ymin:.1f}, {preferred.ymax:.1f}]"
    )
    if kind == "outside":
        return (
            f"<b>Warning:</b> Some data coordinates fall outside the {host_name} domain "
            "\u2014 those cells would be excluded from the simulation.\n\n"
            f"{data_str}\n{pref_str}"
        )
    if kind == "small":
        return (
            f"<b>Note:</b> The data covers a significantly smaller area than the {host_name} "
            "domain \u2014 cells may appear very sparse.\n\n"
            f"{data_str}\n{pref_str}"
        )
    return ""


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _patch_domain_xml(root, domain: "DomainSpec") -> None:
    """Overwrite the <domain> child of *root* with values from *domain*."""
    domain_elem = root.find("domain")
    if domain_elem is None:
        return
    _set_text(domain_elem, "x_min", domain.xmin)
    _set_text(domain_elem, "x_max", domain.xmax)
    _set_text(domain_elem, "y_min", domain.ymin)
    _set_text(domain_elem, "y_max", domain.ymax)
    _set_text(domain_elem, "z_min", domain.zmin)
    _set_text(domain_elem, "z_max", domain.zmax)
    use_2d = domain_elem.find("use_2D")
    dz_elem = domain_elem.find("dz")
    if use_2d is not None and dz_elem is not None:
        try:
            dz = float(dz_elem.text)
        except (TypeError, ValueError):
            dz = 20.0
        use_2d.text = "true" if (domain.zmax - domain.zmin) <= dz else "false"


def _set_text(parent, tag: str, value) -> None:
    el = parent.find(tag)
    if el is not None:
        el.text = str(value)


# ---------------------------------------------------------------------------
# Session — plain-data accumulator (no Qt)
# ---------------------------------------------------------------------------

@dataclass
class WalkthroughSession:
    """Accumulates all data decisions made during the BIWT workflow.

    This object is the single source of truth shared between the walkthrough
    controller and all step windows.  No Qt objects are stored here.

    Fields are populated progressively as the user advances through steps.
    ``None`` means "not yet determined".
    """
    biwt_input: BiwtInput

    # ---- after file import -----------------------------------------------
    data: Optional[BiwtData] = None
    inferred_domain: Optional[DomainSpec] = None

    # ---- domain editor overrides (set by DomainEditorDialog) -------------
    user_domain: Optional[DomainSpec] = None     # user-edited domain (host units); overrides inferred
    data_domain: Optional[DomainSpec] = None     # raw data bounding box (data units) computed at import
    domain_accepted: bool = False                # True once user has resolved domain dialog
    # Scale factor: host-units per one raw data-coordinate unit. Seeded from
    # BiwtData.microns_per_data_unit; user-editable in the domain editor.
    scale_factor: Optional[float] = None
    apply_scale: bool = True                     # whether the factor scales cell placement

    # ---- spatial data (extracted from data after import) -----------------
    # spatial_data: raw (N, 2-or-3) coordinate array in data units
    # spatial_data_final: post-rename/filter coords, same shape, in data units
    spatial_data: Optional[np.ndarray] = None
    spatial_data_final: Optional[np.ndarray] = None
    use_spatial_data: Optional[bool] = None   # None = not yet asked

    # ---- spot deconvolution (optional) -----------------------------------
    spot_deconv_asked: bool = False                  # True once the query window is passed
    perform_spot_deconvolution: bool = False
    cell_types_max: Optional[list] = None            # max-prob type per spot
    cell_prob_feature_dicts: Optional[list] = None   # per-spot {type: prob} dicts

    # ---- after cluster-column selection ----------------------------------
    current_column: Optional[str] = None             # obs column chosen by user
    cell_types_original: Optional[list] = None       # per-cell type labels
    cell_types_list_original: Optional[list] = None  # unique sorted labels

    # ---- after edit-cell-types step --------------------------------------
    # Mirrors the original biwt_tab intermediate representation
    cell_type_dict_on_edit: Optional[dict] = None    # original → intermediate | None
    intermediate_types: Optional[list] = None        # post-edit type names
    intermediate_type_pre_image: Optional[dict] = None   # intermediate → [originals]

    # ---- after rename step -----------------------------------------------
    cell_types_list_final: Optional[list] = None     # final display names
    cell_type_dict_on_rename: Optional[dict] = None  # original → final
    cell_types_final: Optional[list] = None          # per-cell final types
    cell_counts: Optional[dict] = None               # type → int count
    cell_counts_confirmed: bool = False              # True after CellCountsWindow
    cell_volume: Optional[dict] = None               # type → float µm³

    # ---- after positions step --------------------------------------------
    coords_by_type: dict = field(default_factory=dict)  # type → (N,3) ndarray
    plotted_cell_types_per_spot: list = field(default_factory=list)  # spot-deconv records
    positions_set: bool = False

    # ---- XML built in _finish() ------------------------------------------
    cell_definitions_xml: Optional[str] = None   # in-memory XML; passed to BiwtResult

    # ---- after load-cell-parameters step ---------------------------------
    cell_definitions_registry: dict = field(default_factory=dict)
    parameters_loaded: bool = False

    # ---- legacy CellTypeConfig (new-style, not yet fully wired) ----------
    cell_type_config: CellTypeConfig = field(default_factory=CellTypeConfig)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def preferred_domain(self) -> DomainSpec:
        return self.biwt_input.preferred_domain

    @property
    def effective_domain(self) -> DomainSpec:
        """Domain to use for coordinate placement.

        Priority: user_domain (from editor) > inferred_domain > preferred_domain.
        """
        if self.user_domain is not None:
            return self.user_domain
        return self.inferred_domain or self.preferred_domain

    def effective_scale(self) -> float:
        """Uniform factor applied to place cells (``1.0`` = no conversion).

        The stored ``scale_factor`` (host-units per data unit) is applied only
        when ``apply_scale`` is on and a positive factor exists; otherwise cells
        are placed at their raw extent, centered.
        """
        if self.apply_scale and self.scale_factor and self.scale_factor > 0:
            return self.scale_factor
        return 1.0

    # ------------------------------------------------------------------
    # Data-logic helpers (pure Python, no Qt)
    # ------------------------------------------------------------------

    def collect_cell_type_data(self) -> None:
        """Extract unique cell types from the selected obs column."""
        col_data = self.data.obs[self.current_column]
        self.cell_types_original = col_data.tolist()
        self.cell_types_list_original = sorted(set(str(ct) for ct in self.cell_types_original))

    def setup_spot_deconvolution_data(self) -> None:
        """Build per-spot probability dicts from probability columns."""
        prob_cols = self.data.probability_columns
        self.cell_types_list_original = sorted(set(
            c.replace("_probability", "") for c in prob_cols
        ))
        prob_matrix = self.data.obs[prob_cols].values
        max_indices = prob_matrix.argmax(axis=1)
        cell_types = [c.replace("_probability", "") for c in prob_cols]
        self.cell_types_max = [cell_types[i] for i in max_indices]
        self.cell_prob_feature_dicts = [
            {c.replace("_probability", ""): self.data.obs[c].iloc[i]
             for c in prob_cols}
            for i in range(len(self.data.obs))
        ]

    def setup_spatial_data(self) -> None:
        """Extract raw spatial coordinates into self.spatial_data."""
        from biwt.core.domain import (
            _find_spatial_key, resolve_obs_coord_cols, build_obs_coords,
        )
        if self.data.obsm:
            key = _find_spatial_key(self.data.obsm)
            if key:
                arr = np.asarray(self.data.obsm[key])
                if arr.ndim == 2 and arr.shape[1] == 2:
                    arr = np.column_stack([arr, np.zeros(len(arr))])
                self.spatial_data = arr
                return
        cols = list(self.data.obs.columns)
        x_col, y_col, z_col, is_image_coords = resolve_obs_coord_cols(cols)
        if x_col and y_col:
            xy = build_obs_coords(self.data.obs, x_col, y_col, z_col, is_image_coords)
            if xy.shape[1] == 2:
                xy = np.column_stack([xy, np.zeros(len(xy))])
            self.spatial_data = xy

    def compute_intermediate_types(self) -> None:
        """Derive intermediate_types from cell_type_dict_on_edit."""
        self.intermediate_types = []
        self.intermediate_type_pre_image = {}
        for orig in sorted(self.cell_type_dict_on_edit):
            intermed = self.cell_type_dict_on_edit[orig]
            if intermed is None:
                continue
            if intermed not in self.intermediate_types:
                self.intermediate_types.append(intermed)
                self.intermediate_type_pre_image[intermed] = [orig]
            else:
                self.intermediate_type_pre_image[intermed].append(orig)

    def apply_rename(self) -> None:
        """Build cell_types_final, spatial_data_final, counts, and volumes."""
        mapping = self.cell_type_dict_on_rename
        if self.perform_spot_deconvolution:
            updated_dicts, spatial_rows = [], []
            final_set = set()
            for prob_dict, sp in zip(self.cell_prob_feature_dicts, self.spatial_data):
                new_dict = {}
                for orig, prob in prob_dict.items():
                    if orig not in mapping:
                        continue
                    renamed = mapping[orig]
                    new_dict[renamed] = new_dict.get(renamed, 0.0) + prob
                    final_set.add(renamed)
                if sum(new_dict.values()) > 0:
                    updated_dicts.append(new_dict)
                    spatial_rows.append(sp)
            self.cell_prob_feature_dicts = updated_dicts
            self.spatial_data_final = np.vstack(spatial_rows) if spatial_rows else np.empty((0, 3))
            self.cell_types_final = sorted(final_set)
        else:
            pairs = [
                (mapping[ct], pos)
                for ct, pos in zip(self.cell_types_original,
                                   self.spatial_data if self.use_spatial_data else [None] * len(self.cell_types_original))
                if ct in mapping
            ]
            if self.use_spatial_data:
                self.cell_types_final = [p[0] for p in pairs]
                self.spatial_data_final = np.vstack([p[1] for p in pairs])
            else:
                self.cell_types_final = [mapping[ct] for ct in self.cell_types_original if ct in mapping]

        self._count_final_cell_types()
        self._compute_cell_volumes()

    def _count_final_cell_types(self) -> None:
        self.cell_counts = {ct: 0 for ct in self.cell_types_list_final}
        for ct in self.cell_types_final:
            if ct in self.cell_counts:
                self.cell_counts[ct] += 1

    def _compute_cell_volumes(self) -> None:
        """Default volume 2494 µm³ (PhysiCell default).
        TODO: accept host cell volumes via BiwtInput."""
        self.cell_volume = {ct: 2494.0 for ct in self.cell_types_list_final}


# ---------------------------------------------------------------------------
# Step-predicate table (pure Python, no Qt — importable by tests)
# ---------------------------------------------------------------------------

def _step_predicates(s: "WalkthroughSession") -> list:
    """Return ``[(predicate, label), ...]`` in walkthrough order.

    Each *predicate* is a zero-arg callable returning ``bool``.
    Each *label* is a stable string identifier for the step.

    This function is the single source of truth for step-selection logic.
    ``BioinformaticsWalkthrough._build_next_window`` maps each label to its
    factory; tests import this function directly so they never duplicate the
    predicate logic.
    """
    return [
        (
            lambda: not s.spot_deconv_asked
                    and bool(s.data and s.data.probability_columns)
                    and bool(s.data and s.data.has_spatial),
            "SpotDeconvQuery",
        ),
        (
            lambda: s.current_column is None and not s.perform_spot_deconvolution,
            "ClusterColumn",
        ),
        (
            lambda: s.use_spatial_data is None
                    and s.data is not None and s.data.has_spatial,
            "SpatialQuery",
        ),
        (
            lambda: s.cell_type_dict_on_edit is None,
            "EditCellTypes",
        ),
        (
            lambda: s.cell_types_list_final is None,
            "RenameCellTypes",
        ),
        (
            lambda: not s.use_spatial_data and not s.cell_counts_confirmed,
            "CellCounts",
        ),
        (
            lambda: not s.positions_set,
            "Positions",
        ),
        (
            lambda: not s.parameters_loaded,
            "LoadCellParameters",
        ),
    ]


# ---------------------------------------------------------------------------
# Downstream-invalidation tables (used by advance() to centralize resets)
# ---------------------------------------------------------------------------

_STEP_ORDER = [
    "SpotDeconvQuery", "ClusterColumn", "SpatialQuery",
    "EditCellTypes", "RenameCellTypes", "CellCounts",
    "Positions", "LoadCellParameters",
]

# For each step label: (session_field, reset_value) pairs.
# advance() resets the fields of every step AFTER the current one when
# stale_futures is True, so predicates are re-evaluated on fresh state.
_STEP_FIELDS: dict[str, list] = {
    "SpotDeconvQuery": [
        ("spot_deconv_asked", False),
        ("perform_spot_deconvolution", False),
        ("cell_types_max", None),
        ("cell_prob_feature_dicts", None),
    ],
    "ClusterColumn": [
        ("current_column", None),
        ("cell_types_original", None),
        ("cell_types_list_original", None),
    ],
    "SpatialQuery": [
        ("use_spatial_data", None),
    ],
    "EditCellTypes": [
        ("cell_type_dict_on_edit", None),
        ("intermediate_types", None),
        ("intermediate_type_pre_image", None),
    ],
    "RenameCellTypes": [
        ("cell_types_list_final", None),
        ("cell_type_dict_on_rename", None),
        ("cell_types_final", None),
        ("cell_counts", None),
        ("cell_volume", None),
    ],
    "CellCounts": [
        ("cell_counts_confirmed", False),
    ],
    "Positions": [
        ("positions_set", False),
        ("coords_by_type", {}),
        ("plotted_cell_types_per_spot", []),
    ],
    "LoadCellParameters": [
        ("parameters_loaded", False),
        ("cell_definitions_registry", {}),
        ("cell_definitions_xml", None),
    ],
}


# ---------------------------------------------------------------------------
# Main walkthrough widget
# ---------------------------------------------------------------------------

class BioinformaticsWalkthrough(QWidget):
    """Top-level BIWT popup controller.

    Parameters
    ----------
    biwt_input:
        Everything the host supplies at launch (domain, cell-type names, etc.)
    on_complete:
        Callback receiving a ``BiwtResult`` when the user finishes.
        Called with ``None`` if the user cancels.
    """

    def __init__(
        self,
        biwt_input: BiwtInput,
        on_complete: Optional[Callable[[Optional[BiwtResult]], None]] = None,
    ):
        super().__init__()
        self.setWindowTitle("BioInformatics WalkThrough (BIWT)")
        self.setWindowFlags(Qt.Window)

        self.on_complete = on_complete or (lambda result: None)
        self.session = WalkthroughSession(biwt_input=biwt_input)

        # Window stack management.
        # Two-list model mirrors the original biwt_tab.py design:
        #
        #   window_history — windows already visited (most-recent last).
        #                    Going back pops from the end of this list.
        #   window_future  — windows that were visited but are still valid
        #                    (not stale).  Going forward reuses these instead
        #                    of rebuilding, so a back→forward without any
        #                    user change preserves window state.
        #   stale_futures  — set to True by any widget that changes session
        #                    state.  When True, going forward discards
        #                    window_future and builds fresh windows instead.
        self.window_history: list[QWidget] = []
        self.window_future: list[QWidget] = []
        self.stale_futures: bool = False
        self.current_window_idx: int = -1
        self.window: Optional[QWidget] = None

        self._build_home_ui()

    # ------------------------------------------------------------------
    # Home screen
    # ------------------------------------------------------------------

    def _build_home_ui(self) -> None:
        vbox = QVBoxLayout(self)

        # Title
        title = QLabel(
            '<p style="font-size:28px; text-decoration:underline;">'
            '<b>B</b>io<b>I</b>nformatics <b>W</b>alk<b>T</b>hrough (BIWT)'
            "</p>"
        )
        title.setAlignment(Qt.AlignCenter)
        vbox.addWidget(title)
        vbox.addStretch(1)

        # Import section
        vbox.addWidget(SectionHeader("Import"))
        hbox_import = QHBoxLayout()

        self.import_button = QPushButton("Import file…")
        self.import_button.setStyleSheet("QPushButton {background-color: lightgreen; color: black;}")
        self.import_button.clicked.connect(self._import_cb)
        hbox_import.addWidget(self.import_button)

        hbox_import.addWidget(QLabel("Default cell-type column:"))
        self.column_line_edit = QLineEdit("type")
        self.column_line_edit.setStyleSheet(_LE_STYLE)
        hbox_import.addWidget(self.column_line_edit)
        vbox.addLayout(hbox_import)

        vbox.addWidget(QLabel(
            "Supported formats: .h5ad (AnnData), .rds / .rda / .rdata (Seurat / SCE), .csv"
        ))

        self._domain_accepted_cb = QCheckBox("Skip domain validation on import")
        self._domain_accepted_cb.setToolTip(
            "When checked, the domain editor will not appear automatically at the positions step."
        )
        # The host sets the *default* for this box, not the outcome — the user
        # stays able to turn domain validation back on.
        self._domain_accepted_cb.setChecked(self.session.biwt_input.domain_accepted)
        vbox.addWidget(self._domain_accepted_cb)

        vbox.addWidget(QHLine())

        vbox.addStretch(1)

    # ------------------------------------------------------------------
    # File import
    # ------------------------------------------------------------------

    def _show_import_error(self, err: LoadError) -> None:
        """Show the modal error for a failed import.

        Errors that carry a ``docs_url`` — a missing optional dependency or a
        broken R stack — are rendered as rich text with a clickable pointer to
        the setup guide.  Errors about the file itself stay plain text, so the
        pointer only appears where it is actually the fix.
        """
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("Import failed")
        box.setStandardButtons(QMessageBox.Ok)

        if err.docs_url:
            # QMessageBox's text label sets openExternalLinks itself, so the
            # anchor opens in the default browser with no extra wiring.
            box.setTextFormat(Qt.RichText)
            box.setTextInteractionFlags(Qt.TextBrowserInteraction)
            box.setText(
                escape(str(err)).replace("\n", "<br>")
                + f'<br><br>See the <a href="{escape(err.docs_url, quote=True)}">'
                "BIWT setup docs</a> for how to fix this."
            )
        else:
            box.setTextFormat(Qt.PlainText)
            box.setText(str(err))
        box.exec_()

    def _import_cb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import single-cell data",
            "",
            "Supported files (*.h5ad *.rds *.rda *.rdata *.csv);;All files (*)",
        )
        if not path:
            return
        try:
            bdata = data_loader.load(path)
        except LoadError as e:
            self._show_import_error(e)
            return

        # Reset session so stale state from a previous run doesn't survive reimport.
        self.session = WalkthroughSession(biwt_input=self.session.biwt_input)
        self.session.data = bdata
        # If the input has no spatial coordinates, force non-spatial mode so that
        # downstream Qt widgets never receive a None for a boolean.
        self.session.use_spatial_data = None if bdata.has_spatial else False


        # Seed the scale factor (host-units per data unit) from what the file
        # supplied (currently only Visium µm/pixel); None → user enters one.
        self.session.scale_factor = bdata.microns_per_data_unit

        # data_domain = raw coordinate range (data units), used by the editor.
        data_domain = domain_module.infer_domain(
            preferred=None,
            obs=bdata.obs,
            obsm=bdata.obsm,
        )
        self.session.data_domain = data_domain

        # Default effective domain (host units): the host's preferred domain,
        # which always exists — BiwtInput defaults it to DomainSpec.default().
        self.session.inferred_domain = self.session.biwt_input.preferred_domain

        # The checkbox is the single source of truth; BiwtInput.domain_accepted
        # only seeded its initial state (see _build_home_ui).
        self.session.domain_accepted = self._domain_accepted_cb.isChecked()

        log.info(
            "Loaded %d cells from '%s'. Domain source: %s.",
            bdata.n_cells, path, self.session.inferred_domain.source,
        )
        self._start_walkthrough()

    # ------------------------------------------------------------------
    # Step-window management
    # ------------------------------------------------------------------

    def _start_walkthrough(self) -> None:
        """Begin the step-window sequence after successful file import."""
        self.window_history.clear()
        self.window_future.clear()
        self.current_window_idx = -1
        self.stale_futures = True   # first advance always builds fresh
        self.advance()

    def _invalidate_downstream_of(self, label: str) -> None:
        """Reset all session fields for every step strictly after *label*.

        Called by ``advance()`` when ``stale_futures`` is True so that
        step predicates are re-evaluated against a clean state.  Individual
        window classes no longer need to maintain their own invalidation lists.
        """
        import copy as _copy
        try:
            idx = _STEP_ORDER.index(label)
        except ValueError:
            return
        s = self.session
        for step in _STEP_ORDER[idx + 1:]:
            if (
                step == "SpatialQuery"
                and s.data is not None
                and not s.data.has_spatial
            ):
                continue

            for field_name, default in _STEP_FIELDS.get(step, []):
                setattr(s, field_name, _copy.copy(default))

    def advance(self) -> None:
        """Move forward one step.

        If ``stale_futures`` is True (user changed something on the current
        step), reset all downstream session fields and build a fresh window.
        If ``stale_futures`` is False and cached future windows exist, reuse
        the next one so that back→forward without changes preserves state.
        """
        if self.window is not None:
            self.window_history.append(self.window)
            self.window.hide()

        if self.stale_futures or not self.window_future:
            if self.stale_futures:
                label = getattr(self.window, "_step_label", None)
                if label:
                    self._invalidate_downstream_of(label)
                self.window_future.clear()
            next_win = self._build_next_window()
            if next_win is None:
                self._finish()
                return
        else:
            # Reuse cached future — user went back without changing anything
            next_win = self.window_future.pop(0)

        self.stale_futures = False
        self.current_window_idx += 1
        self.window = next_win
        self.window.show()

    def go_back_to_prev_window(self) -> None:
        """Return to the previous step.

        If the current window has been marked stale (user changed something),
        discard all future windows — they must be rebuilt when the user
        advances again.  Otherwise, save the current window to the front of
        ``window_future`` so it can be reused on the next forward step.
        """
        if not self.window_history:
            return

        if self.window is not None:
            self.window.hide()
            if self.stale_futures:
                self.window_future.clear()
            else:
                # Current window is still valid — preserve as next future
                self.window_future.insert(0, self.window)

        self.stale_futures = False   # future list (if any) is now clean
        self.current_window_idx -= 1
        self.window = self.window_history.pop()
        self.window.show()

    def _build_next_window(self) -> Optional[QWidget]:
        """Return the next step window determined by current session state.

        Steps are checked in order; the first whose predicate is True is built
        and returned.  Predicates are re-evaluated on every advance so that
        optional steps (SpatialQuery, CellCounts) are included or skipped based
        on the data and earlier user choices.

        Flow:
          import → [SpotDeconvQuery?] → ClusterColumn → [SpatialQuery?]
               → EditCellTypes → RenameCellTypes → [CellCounts?]
               → Positions → LoadCellParameters → done (host writes output)
        """
        # Lazy imports keep startup fast and avoid circular imports at module level.
        from biwt.gui.windows.spot_deconvolution import SpotDeconvolutionQueryWindow
        from biwt.gui.windows.cluster_column import ClusterColumnWindow
        from biwt.gui.windows.spatial_query import SpatialQueryWindow
        from biwt.gui.windows.edit_cell_types import EditCellTypesWindow
        from biwt.gui.windows.rename_cell_types import RenameCellTypesWindow
        from biwt.gui.windows.cell_counts import CellCountsWindow
        from biwt.gui.windows.positions import PositionsWindow
        from biwt.gui.windows.load_cell_parameters import LoadCellParametersWindow

        s = self.session

        def _make_spatial_query():
            s.setup_spatial_data()
            return SpatialQueryWindow(self)

        def _make_edit_cell_types():
            if s.cell_types_list_original is None:
                s.collect_cell_type_data()
            return EditCellTypesWindow(self)

        _factories = {
            "SpotDeconvQuery":    lambda: SpotDeconvolutionQueryWindow(self),
            "ClusterColumn":      lambda: ClusterColumnWindow(self),
            "SpatialQuery":       _make_spatial_query,
            "EditCellTypes":      _make_edit_cell_types,
            "RenameCellTypes":    lambda: RenameCellTypesWindow(self),
            "CellCounts":         lambda: CellCountsWindow(self),
            "Positions":          lambda: PositionsWindow(self),
            "LoadCellParameters": lambda: LoadCellParametersWindow(self),

        }

        for predicate, label in _step_predicates(s):
            if predicate():
                win = _factories[label]()
                win._step_label = label
                return win
        return None

    # ------------------------------------------------------------------
    # Finish
    # ------------------------------------------------------------------

    def _finish(self) -> None:
        """Assemble BiwtResult and call on_complete. The host writes all output."""
        import copy
        import xml.etree.ElementTree as ET
        from biwt.core.parameters.xml_defaults import xml_defaults

        coords_df = build_ic_dataframe(self.session.coords_by_type)
        mapping = self.session.cell_type_config.resolve()
        s = self.session

        # Build cell-definitions XML if the parameters step populated the registry.
        if s.cell_definitions_registry:
            root = ET.Element("PhysiCell_settings", version="devel-version")
            for key, xml_str in xml_defaults.items():
                wrapped = f"<{key}>{xml_str.strip()}</{key}>"
                root.append(ET.fromstring(wrapped))
            _patch_domain_xml(root, s.effective_domain)
            cell_defs = ET.SubElement(root, "cell_definitions")
            for template_elem in s.cell_definitions_registry.values():
                cell_defs.append(copy.deepcopy(template_elem))
            s.cell_definitions_xml = ET.tostring(
                root, encoding="unicode", xml_declaration=False
            )

        result = BiwtResult(
            coordinates=coords_df,
            cell_type_map=mapping,
            domain_used=s.effective_domain,
            cell_definitions_xml=s.cell_definitions_xml,
        )

        self.on_complete(result)


# ---------------------------------------------------------------------------
# Factory function — the primary host entry point
# ---------------------------------------------------------------------------

def create_biwt_widget(
    biwt_input: BiwtInput,
    on_complete: Optional[Callable[[Optional[BiwtResult]], None]] = None,
) -> BioinformaticsWalkthrough:
    """Create and return a BIWT walkthrough widget, suitable for embedding or use as a popup.

    The widget does not close itself on completion — the host is responsible
    for closing or resetting it if desired.

    Parameters
    ----------
    biwt_input:
        Constructed by the host with domain and optional cell-type hints.
    on_complete:
        Callback called with ``BiwtResult`` (or ``None`` on cancel) when the
        user finishes the workflow.

    Example
    -------
    ::

        from biwt import BiwtInput, DomainSpec
        from biwt.gui import create_biwt_widget

        widget = create_biwt_widget(
            BiwtInput(
                preferred_domain=DomainSpec(xmin=-500, xmax=500,
                                            ymin=-500, ymax=500),
                host_cell_type_names=["default", "tumor", "immune"],
                host_name="My App",
            ),
            on_complete=lambda result: print(result.coordinates.head()),
        )
        widget.show()

    BIWT never writes to disk.  To persist the result, do it in
    ``on_complete`` — e.g. ``result.to_csv("./config/cells.csv")``.
    """
    return BioinformaticsWalkthrough(biwt_input=biwt_input, on_complete=on_complete)
