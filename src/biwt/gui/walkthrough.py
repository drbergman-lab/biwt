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

    def host_input():                      # called at the start of each run
        return BiwtInput(
            preferred_domain=DomainSpec(xmin=-500, xmax=500,
                                        ymin=-500, ymax=500),
            host_cell_type_names=list(my_cell_definitions),
        )

    widget = create_biwt_widget(host_input, on_complete=my_callback)
    widget.show()

A host that embeds the widget for the lifetime of the application passes the
callable, so its domain and cell types are read when a run needs them rather
than when the tab was built.  A ``BiwtInput`` instance also works, and is the
right thing for a one-shot popup.

``my_callback`` receives a ``BiwtResult`` when the user finishes the workflow.

Step selection
--------------
``_step_predicates`` is the single source of truth for which step comes next;
``_STEP_FIELDS`` records which session fields each step owns, so that revisiting
a step can invalidate everything downstream of it.  Anything *derived* rather
than chosen belongs in ``WalkthroughSession.reseed_derived_state`` instead.
"""

from __future__ import annotations

import math
from dataclasses import MISSING, dataclass, field, fields
from html import escape
from typing import Optional, Callable, NamedTuple
import logging

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame,
    QLabel, QPushButton, QLineEdit, QCheckBox, QToolButton,
    QFileDialog, QMessageBox, QDialogButtonBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QDoubleValidator

from biwt import __version__
from biwt.types import (
    DomainSource, DomainSpec, BiwtInput, BiwtInputSource, BiwtResult,
)
from biwt.core import data_loader
from biwt.core.data_loader import (
    INSTALL_DOCS_URL, BiwtData, LoadError, supported_formats,
)
from biwt.core import domain as domain_module
from biwt.core.cell_types import alpha_key, default_name_matches
from biwt.core.positioning import build_ic_dataframe
from biwt.gui.widgets import (
    biwt_icon,
    QHLine, QLineEdit_custom, QVLine, SectionHeader, dropped_local_paths,
)

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


def _scale_domain(d: DomainSpec, factor: float,
                  source: str = DomainSource.DATA, units: str = "micron",
                  scale_z: bool = False) -> DomainSpec:
    """Return *d* with its bounds multiplied by *factor* (host-units per data unit).

    x and y are always scaled.  z only when *scale_z* — see
    ``biwt.core.domain.data_has_z``: a z the file supplied is a real measurement
    and converts like the others, while a synthesized ±10 slab is not in data
    units at all and the factor has nothing to convert.
    """
    z = (d.zmin * factor, d.zmax * factor) if scale_z else (d.zmin, d.zmax)
    return DomainSpec(
        xmin=d.xmin * factor, xmax=d.xmax * factor,
        ymin=d.ymin * factor, ymax=d.ymax * factor,
        zmin=z[0], zmax=z[1], source=source, units=units,
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
    _AXES = (
        _Axis("X", "width",  "xmin", "xmax", True),
        _Axis("Y", "height", "ymin", "ymax", True),
        _Axis("Z", "depth",  "zmin", "zmax", False),
    )
    # Bound attrs the factor applies to, in grid order.  Derived rather than
    # spelled out so it cannot drift from _AXES.
    _XY = tuple(a for ax in _AXES if ax.factor_scaled
                for a in (ax.lo, ax.hi))

    def __init__(
        self,
        parent: QWidget,
        data_domain: DomainSpec,
        preferred_domain: DomainSpec,
        context_message: str = "",
        initial_domain: Optional[DomainSpec] = None,
        initial_preset: str = DomainSource.DATA,
        host_name: str = "Host",
        file_factor: Optional[float] = None,
        current_factor: Optional[float] = None,
        apply_scale: bool = True,
        data_has_z: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Domain Settings")
        # Three paired columns (min | max | size), each holding two fields.
        self.setMinimumWidth(660)

        self._data_domain = data_domain            # raw bounds, data units
        # Whether the file supplied z at all; a synthesized slab is not in data
        # units, so the factor must not be applied to it.
        self._data_has_z = data_has_z
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
        self._factor_edit.setPlaceholderText(self._placeholder_for_empty())
        # Not falling back to file_factor: a factor the user cleared must stay
        # cleared, and the ↺ button is how the file's value comes back.
        F0 = current_factor
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
            # No ndigits: _source_of compares what the fields hold against the
            # host's domain, so rounding here makes a host domain of more than two
            # decimals come back as 'user', with the bounds actually perturbed.
            le = QLineEdit_custom()
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
        if data_domain is None or data_domain.source == DomainSource.DEFAULT:
            # No coordinates in the file, so data_domain is BIWT's fallback box —
            # not the data's anything.  DEFAULT is what marks it as not real.
            data_btn.setEnabled(False)
            data_btn.setToolTip("This file has no spatial coordinates.")
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
        # A revisit shows the domain in force.  Otherwise *initial_preset* decides,
        # and the caller picks it from the session: the data extent is the useful
        # starting point only when the data's own coordinates are being used.
        if initial_domain is not None:
            self._fill_host(initial_domain)   # revisit: host column = active domain
        elif initial_preset == DomainSource.HOST:
            self._fill_preferred()
        else:
            self._fill_data()                 # host = raw×F (or raw)
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
        """Current factor: the field value if valid and positive, else ``None``.

        An empty field means *no factor*, not "fall back to the file value".
        Falling back made the file's value unclearable — the only way to reach it
        was ↺, which then greyed out because the empty field already matched it,
        so three widgets disagreed about what was in effect: a blank field, live
        mirrors, and a disabled restore button. ↺ is now the single way back to
        the file value, which is what it was for.
        """
        text = self._factor_edit.text().strip()
        if not text:
            return None
        try:
            f = float(text)
        except ValueError:
            return None
        return f if f > 0 else None

    def _on_factor_changed(self, _text: str = "") -> None:
        # A changed factor re-derives every data-units cell from the host domain
        # — the extents as well as the bounds.  Syncing only the bounds left the
        # size mirrors showing a span computed with the previous factor.
        self._sync_du_from_host()
        self._sync_du_extents()
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

    def _placeholder_for_empty(self) -> str:
        """What an empty factor field means — including how to undo emptying it.

        With a file value to go back to, the placeholder has to say so: an empty
        field is now genuinely no factor, so without naming ↺ the file's
        calibration would look irrecoverable.
        """
        if self._file_factor is None:
            return "none found in file"
        return f"none — ↺ restores {self._file_factor:g}"

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
        """Mirror the host bounds into data units, clearing them when unusable.

        Bailing out early on a missing factor left the mirrors displaying their
        last values, so a disabled column went on advertising a conversion that
        no longer applied — the same reason an unparseable bound clears its
        mirror rather than keeping the previous number.
        """
        F = self._effective_factor()
        for attr in self._XY:
            host_v = self._parse(self._host_fields[attr])
            self._du_fields[attr].setText(
                "" if F is None or host_v is None else self._fmt(host_v / F)
            )

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

    def _data_host_bounds(self) -> dict:
        """The data extent in host units — what "Use Data Domain" puts in the fields.

        Shared with ``result()``, which needs to recognise these values to report
        an accurate ``DomainSpec.source``.
        """
        d = self._data_domain
        zmin, zmax = d.zmin, d.zmax
        if abs(zmax - zmin) < 1e-6:
            zmin, zmax = -10.0, 10.0
        F = self._effective_factor()
        bounds = {
            attr: (getattr(d, attr) * F if F is not None else getattr(d, attr))
            for attr in self._XY
        }
        # A z the file supplied is a data-unit measurement and converts like x and
        # y; a synthesized slab is not, so the factor has nothing to convert.
        if self._data_has_z and F is not None:
            zmin, zmax = zmin * F, zmax * F
        bounds["zmin"], bounds["zmax"] = zmin, zmax
        return bounds

    def _fill_data(self) -> None:
        """Use Data Domain: data-units = raw bounds; host = raw × factor (or raw)."""
        host_bounds = self._data_host_bounds()
        F = self._effective_factor()
        for attr in self._XY:
            if F is not None:
                self._du_fields[attr].setText(self._fmt(getattr(self._data_domain, attr)))
            self._host_fields[attr].setText(self._fmt(host_bounds[attr]))
        self._host_fields["zmin"].setText(self._fmt(host_bounds["zmin"]))
        self._host_fields["zmax"].setText(self._fmt(host_bounds["zmax"]))

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

    def _source_of(self, bounds: dict) -> str:
        """Which ``DomainSpec.source`` describes *bounds*.

        The dialog used to stamp every accepted domain "user edited", which
        made the field useless: a host is told to check ``source != HOST``
        to see whether its own domain survived, and after this dialog the answer
        was always yes — even when the user pressed Enter on the pre-filled values
        without touching anything.  The bounds themselves say which it is.

        Tolerance covers the round trip through the fields: ``%g`` keeps six
        significant digits, so a value that was only displayed and read back
        differs by at most a relative 5e-7.
        """
        def same_as(reference: dict) -> bool:
            return all(
                math.isclose(bounds[a], reference[a], rel_tol=1e-5, abs_tol=1e-6)
                for a in bounds
            )

        # Host first: if the two coincide, the host's domain did survive — and
        # its own source says whether it was ever really the host's, since an
        # unusable one was replaced by BIWT's box before it got here.
        if same_as({a: getattr(self._preferred_domain, a) for a in bounds}):
            return self._preferred_domain.source
        if same_as(self._data_host_bounds()):
            return DomainSource.DATA
        return DomainSource.USER

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
        bounds = {a: hv(a) for a in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")}
        domain = DomainSpec(**bounds, source=self._source_of(bounds),
                            units=self._host_units)
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

    # ---- domain editor overrides (set by DomainEditorDialog) -------------
    user_domain: Optional[DomainSpec] = None     # user-edited domain (host units); overrides the host's
    data_domain: Optional[DomainSpec] = None     # raw data bounding box (data units) computed at import
    domain_accepted: bool = False                # True once the user has resolved the dialog
    # Scale factor: host-units per one raw data-coordinate unit. Seeded from
    # BiwtData.host_units_per_data_unit; user-editable in the domain editor.
    scale_factor: Optional[float] = None
    apply_scale: bool = True                     # whether the factor scales cell placement

    # ---- spatial data (extracted from data after import) -----------------
    # spatial_data: raw (N, 2-or-3) coordinate array in data units
    # spatial_data_final: post-rename/filter coords, same shape, in data units
    spatial_data: Optional[np.ndarray] = None
    spatial_data_final: Optional[np.ndarray] = None
    # The user's answer at the SpatialQuery step; None = not asked yet.
    # Never read this directly to decide behavior — use the ``use_spatial_data``
    # property, which folds in the cases where there is nothing to ask about.
    spatial_query_answer: Optional[bool] = None

    # ---- spot deconvolution (optional) -----------------------------------
    spot_deconv_asked: bool = False                  # True once the query window is passed
    perform_spot_deconvolution: bool = False
    cell_types_max: Optional[list] = None            # max-prob type per spot
    cell_prob_feature_dicts: Optional[list] = None   # per-spot {type: prob} dicts
    # Post-rename per-spot dicts, aligned row-for-row with spatial_data_final.
    # Kept separate so apply_rename never consumes its own output.
    cell_prob_feature_dicts_final: Optional[list] = None

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

    # ---- cell-parameter library ------------------------------------------
    # Template files currently in play: seeded from BiwtInput.cell_template_paths
    # the first time the step is built, then edited by the user's Add / Remove.
    # Deliberately absent from _STEP_FIELDS — loading a library is an action, not
    # an answer, so changing an earlier step must not silently undo it.  None
    # means "not seeded yet".
    template_library_paths: Optional[list] = None

    # ---- after load-cell-parameters step ---------------------------------
    # final cell-type name → (toml path, template name, template content).
    # Types the user left unassigned are absent; see BiwtResult.cell_templates.
    cell_templates: dict = field(default_factory=dict)
    parameters_loaded: bool = False

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def preferred_domain(self) -> DomainSpec:
        return self.biwt_input.preferred_domain

    @property
    def effective_domain(self) -> DomainSpec:
        """Domain to use for coordinate placement.

        The host's domain until the user accepts an edited one in BIWT's own
        editor.  There is deliberately no third value between them: a second
        latched copy of the host's domain is what let one dialog compute its
        mismatch warning against one box and resolve "Use <host> Domain"
        against another.
        """
        if self.user_domain is not None:
            return self.user_domain
        return self.preferred_domain

    @property
    def data_has_z(self) -> bool:
        """True when the imported file supplied a third coordinate axis.

        Decides whether the scale factor applies to z: a z the file measured
        converts like x and y, a synthesized slab has nothing to convert.
        """
        if self.data is None:
            return False
        return domain_module.data_has_z(obs=self.data.obs, obsm=self.data.obsm)

    def effective_scale(self) -> float:
        """Uniform factor applied to place cells (``1.0`` = no conversion).

        The stored ``scale_factor`` (host-units per data unit) is applied only
        when ``apply_scale`` is on and a positive factor exists; otherwise cells
        are placed at their raw extent, centered.
        """
        if self.apply_scale and self.scale_factor and self.scale_factor > 0:
            return self.scale_factor
        return 1.0

    @property
    def name_matcher(self) -> Callable[[str, str], bool]:
        """The predicate deciding whether two strings name the same cell type.

        The host's ``BiwtInput.name_matches`` if it supplied one — which
        overrides ``name_match_cutoff`` along with the default itself — else
        BIWT's default bound to that cutoff.
        """
        bi = self.biwt_input
        if bi.name_matches is not None:
            return bi.name_matches
        cutoff = bi.name_match_cutoff
        return lambda a, b: default_name_matches(a, b, cutoff=cutoff)

    @property
    def use_spatial_data(self) -> bool:
        """Whether cells are placed at their measured coordinates.

        Derived, never stored, so it is always a real ``bool``:

        * spot deconvolution is on  → True (deconvolution *is* spatial)
        * the data has no coordinates → False (nothing to ask about)
        * otherwise → the user's SpatialQuery answer, False until they answer

        The last case is safe because the SpatialQuery step runs before any
        consumer of this property is reachable.
        """
        if self.perform_spot_deconvolution:
            return True
        if self.data is not None and not self.data.has_spatial:
            return False
        return bool(self.spatial_query_answer)

    # ------------------------------------------------------------------
    # Data-logic helpers (pure Python, no Qt)
    # ------------------------------------------------------------------

    def collect_cell_type_data(self) -> None:
        """Extract unique cell types from the selected obs column."""
        if self.current_column is None:
            raise ValueError(
                "collect_cell_type_data() needs current_column to be set by the "
                "cluster-column step; the spot-deconvolution path derives cell "
                "types from probability columns instead (see "
                "setup_spot_deconvolution_data)."
            )
        col_data = self.data.obs[self.current_column]
        # Stringified per cell as well as in the unique list: the rename mapping
        # is keyed by the unique (string) labels, so a numeric column — integer
        # Leiden/Louvain cluster ids, say — would otherwise match nothing and
        # silently drop every cell in apply_rename.
        self.cell_types_original = [str(ct) for ct in col_data.tolist()]
        self.cell_types_list_original = sorted(set(self.cell_types_original), key=alpha_key)

    def setup_spot_deconvolution_data(self) -> None:
        """Build per-spot probability dicts from probability columns."""
        prob_cols = self.data.probability_columns
        self.cell_types_list_original = sorted((
            {c.replace("_probability", "") for c in prob_cols}
        ), key=alpha_key)
        # Clamped before use, not just when the columns were selected: a raw NaN
        # wins argmax outright, so one bad spot picked its own cell type as the
        # spot's maximum and carried the NaN into the per-spot weights.
        prob_matrix = np.column_stack(
            [data_loader.clamp_probabilities(self.data.obs[c]) for c in prob_cols]
        )
        max_indices = prob_matrix.argmax(axis=1)
        cell_types = [c.replace("_probability", "") for c in prob_cols]
        self.cell_types_max = [cell_types[i] for i in max_indices]
        self.cell_prob_feature_dicts = [
            dict(zip(cell_types, prob_matrix[i]))
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

    def reseed_derived_state(self) -> None:
        """Re-derive the bulk data that follows from the user's answers.

        ``_STEP_FIELDS`` lists the fields whose values a step's user *chose*;
        anything **derived** from those choices belongs here instead, so that a
        downstream invalidation can wipe the choices without destroying what
        follows from the ones still standing.  Called right after that
        invalidation and again before every step-predicate evaluation, so it
        must be idempotent, and it must never overwrite a user decision.

        Not called from ``go_back_to_prev_window``: that path can reuse cached
        windows, and repairing the session behind a live window would leave the
        two disagreeing.

        Spot deconvolution dominates the body because it is the only answer in
        the walkthrough from which *bulk* data follows — three arrays over every
        spot.  Every other step's answer is its own state.  Implications that are
        merely logical, such as "deconvolution means spatial coordinates are in
        use", need no derivation at all: see the ``use_spatial_data`` property.
        """
        if self.data is None:
            return

        if self.perform_spot_deconvolution:
            # One function produces all three, so a single missing one means
            # the whole set has to be rebuilt.
            if (
                self.cell_types_list_original is None
                or self.cell_types_max is None
                or self.cell_prob_feature_dicts is None
            ):
                self.setup_spot_deconvolution_data()
        else:
            # Declining deconvolution after having accepted it must not leave
            # its per-spot artifacts behind.
            self.cell_types_max = None
            self.cell_prob_feature_dicts = None

        if self.data.has_spatial and self.spatial_data is None:
            self.setup_spatial_data()
            if self.spatial_data is None:
                log.warning(
                    "Data reports spatial information in %s, but no coordinates "
                    "could be extracted from it.", self.data.spatial_location,
                )

    def resolved_cell_type_map(self) -> dict:
        """Every original data label → its final name, or ``None`` if deleted.

        Reads the two dicts the walkthrough actually fills: an original absent
        from ``cell_type_dict_on_rename`` was deleted at the edit step, since only
        surviving types have a pre-image there.  Merged originals all resolve to
        the one name their group was given.
        """
        renamed = self.cell_type_dict_on_rename or {}
        return {orig: renamed.get(orig) for orig in (self.cell_types_list_original or [])}

    def compute_intermediate_types(self) -> None:
        """Derive intermediate_types from cell_type_dict_on_edit."""
        self.intermediate_types = []
        self.intermediate_type_pre_image = {}
        for orig in sorted(self.cell_type_dict_on_edit, key=alpha_key):
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
            # Written to a separate field: this method re-runs on every Continue
            # from the rename step, and consuming its own output would rename
            # already-renamed keys and re-zip filtered dicts against the full
            # coordinate array.
            self.cell_prob_feature_dicts_final = updated_dicts
            self.spatial_data_final = np.vstack(spatial_rows) if spatial_rows else np.empty((0, 3))
            self.cell_types_final = sorted(final_set, key=alpha_key)
        else:
            pairs = [
                (mapping[ct], pos)
                for ct, pos in zip(self.cell_types_original,
                                   self.spatial_data if self.use_spatial_data else [None] * len(self.cell_types_original))
                if ct in mapping
            ]
            if self.use_spatial_data:
                self.cell_types_final = [p[0] for p in pairs]
                # Every type deleted leaves nothing to stack, and np.vstack([])
                # raises — from a Qt slot, which aborts the host process.
                self.spatial_data_final = (
                    np.vstack([p[1] for p in pairs]) if pairs
                    else np.empty((0, self.spatial_data.shape[1]))
                )
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

    Predicates read derived state, so ``s.reseed_derived_state()`` must run
    first — ``_build_next_window`` does that for every real evaluation.
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
            # Deconvolution implies spatial, so there is nothing left to ask.
            lambda: s.spatial_query_answer is None
                    and not s.perform_spot_deconvolution
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

# The labels, in order, from the one place that defines them.  The predicates
# are closures, and are not called here.
_STEP_ORDER = [label for _, label in _step_predicates(None)]

_SESSION_FIELDS = {f.name: f for f in fields(WalkthroughSession)}


def _reset_to_default(session, name: str) -> None:
    """Put *name* back to its ``WalkthroughSession`` default.

    Read off the dataclass rather than restated beside the field name: a table of
    reset *values* is a second copy of every default, free to drift from the one
    the session actually starts with.
    """
    spec = _SESSION_FIELDS[name]
    setattr(session, name,
            spec.default_factory() if spec.default_factory is not MISSING
            else spec.default)


# For each step label: (session_field, reset_value) pairs — the fields whose
# values that step's *user* chose.  advance() resets the fields of every step
# AFTER the current one when stale_futures is True, so predicates are
# re-evaluated on fresh state.  State that is *derived* from those choices is
# not listed here; WalkthroughSession.reseed_derived_state owns it and runs
# immediately after the reset.
_STEP_FIELDS: dict[str, list[str]] = {
    "SpotDeconvQuery": ["spot_deconv_asked", "perform_spot_deconvolution"],
    "ClusterColumn": [
        "current_column", "cell_types_original", "cell_types_list_original",
    ],
    "SpatialQuery": ["spatial_query_answer"],
    "EditCellTypes": [
        "cell_type_dict_on_edit", "intermediate_types",
        "intermediate_type_pre_image",
    ],
    "RenameCellTypes": [
        "cell_types_list_final", "cell_type_dict_on_rename", "cell_types_final",
        "spatial_data_final", "cell_prob_feature_dicts_final", "cell_counts",
        "cell_volume",
    ],
    "CellCounts": ["cell_counts_confirmed"],
    "Positions": ["positions_set", "coords_by_type", "plotted_cell_types_per_spot"],
    "LoadCellParameters": ["parameters_loaded", "cell_templates"],
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
        Called once, when the user finishes. There is no cancel callback: closing
        the widget is the host's own event to handle.
    """

    def __init__(
        self,
        biwt_input: BiwtInputSource,
        on_complete: Optional[Callable[[BiwtResult], None]] = None,
    ):
        super().__init__()
        self.setWindowTitle(f"BioInformatics WalkThrough (BIWT) v{__version__}")
        self.setWindowIcon(biwt_icon())
        self.setWindowFlags(Qt.Window)
        self.setAcceptDrops(True)

        if not isinstance(biwt_input, BiwtInput) and not callable(biwt_input):
            raise TypeError(
                "biwt_input must be a BiwtInput or a callable returning one, "
                f"not {type(biwt_input).__name__}"
            )
        self._host_input_source = biwt_input
        self._host_input_error = ""

        self.on_complete = on_complete or (lambda result: None)
        # This first resolution only seeds the home screen and stands in until
        # the first import; nothing derived, placed, or handed back to the host
        # comes out of it.
        self.session = WalkthroughSession(
            biwt_input=self._resolve_host_input() or BiwtInput()
        )

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
    # Host context
    # ------------------------------------------------------------------

    def _resolve_host_input(self) -> Optional[BiwtInput]:
        """Ask the host what its context is now, and freeze the answer.

        Called at exactly two points: widget construction, and the start of every
        run (a successful import).  Nowhere else — not on step-window build, not on
        back/forward, not when the domain editor opens.  That is the whole stability
        guarantee: one snapshot serves a run, so the domain the mismatch warning is
        computed against, the one cells are placed into, and the one reported as
        ``BiwtResult.domain_used`` cannot drift apart.

        A host that supplies a plain ``BiwtInput`` is snapshotted too, so mutating
        the instance it handed over mid-run cannot reach the run either.

        ``None`` if the host could not supply one, which the import path treats as
        "do not start a run" — a walkthrough configured from a previous run's
        settings would be worse than no walkthrough.

        Nothing a host gets wrong here may raise: this is reached from the import
        slot, and PyQt5 turns an exception in a slot into a fatal abort.  Failures are
        logged, and the reason kept for the import path to show; construction is silent.
        """
        source = self._host_input_source
        try:
            resolved = source() if callable(source) else source
            if not isinstance(resolved, BiwtInput):
                raise TypeError(
                    f"host input resolved to {type(resolved).__name__}, not a BiwtInput"
                )
            snapshot = resolved.snapshot()
        except Exception as exc:               # noqa: BLE001 — host code, any failure
            log.error("Could not resolve the host's input.", exc_info=True)
            self._host_input_error = f"{type(exc).__name__}: {exc}"
            return None
        return snapshot

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

        # The home screen is where the version has to live: an embedded host tab
        # never shows a window title, and the step windows come and go.
        version = QLabel(f"version {__version__}")
        version.setAlignment(Qt.AlignCenter)
        version.setStyleSheet("color: #777; font-size: 11px;")
        vbox.addWidget(version)

        # --- Import -----------------------------------------------------------
        vbox.addWidget(SectionHeader("Import"))

        self.import_button = QPushButton("Import file…")
        self.import_button.setStyleSheet(
            "QPushButton {background-color: lightgreen; color: black; padding: 6px 18px;}"
            "QPushButton:disabled {background-color: #d9d9d9; color: #999;}"
        )
        self.import_button.clicked.connect(self._import_cb)

        drop_hint = QLabel("Drop a data file here")
        drop_hint.setAlignment(Qt.AlignCenter)
        drop_hint.setStyleSheet("color: #777; font-size: 13px; border: none;")

        drop_inner = QVBoxLayout()
        drop_inner.addStretch(1)
        drop_inner.addWidget(drop_hint)
        drop_inner.addWidget(self.import_button, alignment=Qt.AlignCenter)
        drop_inner.addStretch(1)

        # The band this fills used to be two empty stretches.  Making it the drop
        # target puts the space to work and gives the button an obvious home.
        self._drop_frame = QFrame()
        self._drop_frame.setLayout(drop_inner)
        self._drop_frame.setMinimumHeight(120)
        self._set_drop_active(False)
        vbox.addWidget(self._drop_frame, 1)

        vbox.addLayout(self._build_format_chips())

        vbox.addStretch(1)

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("color: #777; font-size: 11px; margin-bottom: 4px;")
        label.setWordWrap(True)
        return label

    def _build_format_chips(self) -> QHBoxLayout:
        """A chip per importable format, showing whether this environment has it.

        The alternative is what BIWT did before: the user clicks Import, picks an
        `.rds`, and learns from an error dialog that the R stack is missing.
        """
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel("Supported:"))
        for fmt in supported_formats():
            ok = fmt.available
            chip = QLabel(f"{fmt.label}  {'✓' if ok else '✗'}")
            chip.setStyleSheet(
                "QLabel { border: 1px solid %s; border-radius: 9px;"
                " padding: 2px 8px; color: %s; }"
                % (("#bbb", "#333") if ok else ("#e0b4b4", "#9c4a4a"))
            )
            chip.setToolTip(
                f"{fmt.description}\n\n{fmt.hint}\n\n{INSTALL_DOCS_URL}"
                if not ok else fmt.description
            )
            hbox.addWidget(chip)
        hbox.addStretch(1)
        return hbox

    def _set_drop_active(self, active: bool) -> None:
        """Style the drop frame for its idle or drag-over state."""
        color = "#4c9a4c" if active else "#bbb"
        background = "#f0f7f0" if active else "transparent"
        self._drop_frame.setStyleSheet(
            "QFrame { border: 2px dashed %s; border-radius: 8px;"
            " background-color: %s; }" % (color, background)
        )

    # ------------------------------------------------------------------
    # Drag and drop
    # ------------------------------------------------------------------

    def _dropped_path(self, event) -> Optional[str]:
        """The single local file being dragged, if it is one BIWT can read.

        One file only: importing replaces the whole session, so there is no
        sensible reading of two at once.
        """
        if len(event.mimeData().urls() if event.mimeData().hasUrls() else []) != 1:
            return None
        suffixes = {ext for fmt in supported_formats() for ext in fmt.extensions}
        paths = dropped_local_paths(event, suffixes)
        return paths[0] if paths else None

    def dragEnterEvent(self, event) -> None:      # noqa: N802
        if self.import_button.isEnabled() and self._dropped_path(event) is not None:
            self._set_drop_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:      # noqa: N802
        self._set_drop_active(False)

    def dropEvent(self, event) -> None:           # noqa: N802
        self._set_drop_active(False)
        path = self._dropped_path(event)
        if path is None:
            return
        event.acceptProposedAction()
        self._import_file(path)

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

    def closeEvent(self, event):  # noqa: N802
        """Take the current step window with us; it is parentless by design."""
        if self.window is not None:
            self.window.close()
        super().closeEvent(event)

    def _allow_import(self, allowed: bool) -> None:
        """Importing resets the session, so a run in progress refuses it.

        Ends when the result is emitted, or when the user closes a step window —
        that abandons the run, and the landing screen is then all there is.
        """
        self.import_button.setEnabled(allowed)
        self.import_button.setToolTip(
            "" if allowed else "Finish or close the walkthrough first."
        )

    def _import_cb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import single-cell data",
            "",
            "Supported files (*.h5ad *.rds *.rda *.rdata *.csv);;All files (*)",
        )
        if not path:
            return
        self._import_file(path)

    def _import_file(self, path: str) -> None:
        """Load *path* and start the walkthrough. Shared by the button and drops.

        Refused mid-run: importing resets the session, so a stray click or drop
        would discard the walkthrough in progress.  The button's own enabled state
        is the flag, and it also blocks the drop, which has no button to grey out.
        """
        if not self.import_button.isEnabled():
            return
        try:
            bdata = data_loader.load(path)
        except LoadError as e:
            self._show_import_error(e)
            return
        except Exception as exc:               # noqa: BLE001 — any reader, any file
            # Readers raise their own types on a corrupt file, and this runs in a
            # slot, where an escape aborts the host process.
            log.exception("Import of %s failed.", path)
            self._show_import_error(
                LoadError(f"Could not read '{path}'.\n\n{type(exc).__name__}: {exc}")
            )
            return

        # A run starts here, so this is where the host is asked what its domain
        # and cell types are *now* — the widget may have been built at startup.
        # If it cannot answer, no run starts: the alternative is a walkthrough
        # configured from settings the host has since disowned.
        self._host_input_error = ""
        biwt_input = self._resolve_host_input()
        if biwt_input is None:
            QMessageBox.warning(
                self, "Import cancelled",
                f"{self.session.biwt_input.host_name} could not supply its settings, "
                f"so nothing was imported.\n\n{self._host_input_error}",
            )
            return
        # Reset session so stale state from a previous run doesn't survive reimport.
        self.session = WalkthroughSession(biwt_input=biwt_input)
        self.session.data = bdata

        # Seed the scale factor (host-units per data unit) from what the file
        # supplied (currently only Visium µm/pixel); None → user enters one.
        self.session.scale_factor = bdata.host_units_per_data_unit

        # data_domain = raw coordinate range (data units), used by the editor.
        data_domain = domain_module.infer_domain(
            preferred=None,
            obs=bdata.obs,
            obsm=bdata.obsm,
        )
        self.session.data_domain = data_domain

        log.info(
            "Loaded %d cells from '%s'. Domain source: %s.",
            bdata.n_cells, path, self.session.preferred_domain.source,
        )
        self._start_walkthrough()

    # ------------------------------------------------------------------
    # Step-window management
    # ------------------------------------------------------------------

    def _start_walkthrough(self) -> None:
        """Begin the step-window sequence after successful file import."""
        self._allow_import(False)
        # Drop any window from a previous import: its handlers read the session
        # live, and advance() would otherwise push it onto the fresh history,
        # where Go back would show a window bound to data that no longer exists.
        if self.window is not None:
            self.window.hide()
            self.window.deleteLater()
            self.window = None
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

        Resetting and re-deriving is one operation: the reset clears the user's
        downstream *choices*, then ``reseed_derived_state`` puts back everything
        that follows from the choices still standing upstream.
        """
        try:
            idx = _STEP_ORDER.index(label)
        except ValueError:
            return
        s = self.session
        for step in _STEP_ORDER[idx + 1:]:
            for field_name in _STEP_FIELDS.get(step, []):
                _reset_to_default(s, field_name)
        s.reseed_derived_state()

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
                # Invalidate here, against the step being returned to, rather than
                # leaving the flag set for the next advance(): carried upstream it
                # would fire again from an earlier step and wipe the committed
                # answers of the ones in between.
                self.window_future.clear()
                label = getattr(self.window_history[-1], "_step_label", None)
                if label:
                    self._invalidate_downstream_of(label)
                self.stale_futures = False
            else:
                # Current window is still valid — preserve as next future
                self.window_future.insert(0, self.window)

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
        # Predicates read derived state, so repair it before evaluating them.
        s.reseed_derived_state()

        def _make_edit_cell_types():
            # Only reachable with a chosen column: the deconvolution path always
            # has its cell types derived by reseed_derived_state() already.
            if s.cell_types_list_original is None:
                s.collect_cell_type_data()
            return EditCellTypesWindow(self)

        _factories = {
            "SpotDeconvQuery":    lambda: SpotDeconvolutionQueryWindow(self),
            "ClusterColumn":      lambda: ClusterColumnWindow(self),
            "SpatialQuery":       lambda: SpatialQueryWindow(self),
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
        s = self.session
        result = BiwtResult(
            coordinates=build_ic_dataframe(s.coords_by_type),
            cell_type_map=s.resolved_cell_type_map(),
            domain_used=s.effective_domain,
            cell_templates=s.cell_templates,
        )
        self.on_complete(result)
        self._allow_import(True)


# ---------------------------------------------------------------------------
# Factory function — the primary host entry point
# ---------------------------------------------------------------------------

def create_biwt_widget(
    biwt_input: BiwtInputSource,
    on_complete: Optional[Callable[[BiwtResult], None]] = None,
) -> BioinformaticsWalkthrough:
    """Create and return a BIWT walkthrough widget, suitable for embedding or use as a popup.

    The widget does not close itself on completion — the host is responsible
    for closing or resetting it if desired.

    Parameters
    ----------
    biwt_input:
        A ``BiwtInput``, or a zero-argument callable returning one.  Pass the
        callable when the host outlives one run — BIWT calls it at the start of
        each run, so a domain or cell-type list the user changed after the widget
        was built is picked up without the host having to push an update.  The
        resolved value is snapshotted for the run: nothing the host does mid-run
        can move the domain the cells are being placed into.
    on_complete:
        Callback called with the ``BiwtResult`` when the user finishes the
        workflow.  Not called if the user never finishes.

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

    An embedded, long-lived host passes a callable instead, and BIWT reads it
    at the start of every run::

        def host_input():
            return BiwtInput(preferred_domain=my_app.current_domain(),
                             host_cell_type_names=my_app.cell_type_names(),
                             host_name="My App")

        widget = create_biwt_widget(host_input, on_complete=save)

    BIWT never writes to disk.  To persist the result, do it in
    ``on_complete`` — e.g. ``result.to_csv("cells.csv")``.
    """
    return BioinformaticsWalkthrough(biwt_input=biwt_input, on_complete=on_complete)
