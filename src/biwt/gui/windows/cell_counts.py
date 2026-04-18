"""Step: Set how many cells of each type to place (non-spatial path)."""

from __future__ import annotations
import numpy as np
from PyQt5 import QtGui
from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QWidget,
    QButtonGroup, QRadioButton, QMessageBox,
)
from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import QVLine, QLineEdit_custom


class CellCountsWindow(BiwinformaticsWalkthroughWindow):
    """Let the user set per-cell-type counts by one of four methods:

    1. Use data counts as-is
    2. Scale by proportion (keeping relative ratios)
    3. Set total confluence (% area coverage)
    4. Set counts manually
    """

    _COL_W = {"name": 100, "count": 120, "prop": 120, "conf": 150, "manual": 120}

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session
        d = walkthrough.session.effective_domain

        self._cell_types = s.cell_types_list_final
        n_cells_total = sum(s.cell_counts.values()) or 1

        # Per-type original proportions  (fraction of total)
        self._orig_props = {
            ct: s.cell_counts[ct] / n_cells_total
            for ct in self._cell_types
        }

        # Confluence: area of one cell / total domain area
        domain_area = d.width * d.height
        self._area_per_cell: dict[str, float] = {}
        self._prop_dot_ratios = 0.0
        for ct in self._cell_types:
            vol = s.cell_volume.get(ct, 2494.0)
            area_one = ((9 * np.pi * vol ** 2) / 16) ** (1.0 / 3.0) / domain_area
            self._area_per_cell[ct] = area_one
            self._prop_dot_ratios += self._orig_props[ct] * area_one

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(
            "Set how many of each cell type to place.\n"
            "Use data counts, scale by proportion, set confluence, or set manually."
        ))

        int_validator = QtGui.QIntValidator()
        int_validator.setBottom(0)

        # Column header row
        cols = [QVBoxLayout() for _ in range(5)]
        for c, lbl in zip(cols, ["Cell Type", "Count", "Proportion", "Confluence (%)", "Manual"]):
            header = QLabel(lbl)
            header.setFixedWidth(list(self._COL_W.values())[list(self._COL_W.keys()).index(
                ["name", "count", "prop", "conf", "manual"][cols.index(c)])])
            cols[cols.index(c)].addWidget(header)

        # Radio buttons
        self._mode_group = QButtonGroup()
        self._rb_counts     = QRadioButton("Use counts");      self._rb_counts.setChecked(True)
        self._rb_props      = QRadioButton("Use proportions")
        self._rb_confluence = QRadioButton("Set confluence (%)")
        self._rb_manual     = QRadioButton("Set manually")
        for i, rb in enumerate([self._rb_counts, self._rb_props, self._rb_confluence, self._rb_manual]):
            self._mode_group.addButton(rb, i)
        self._mode_group.idToggled.connect(self._mode_changed)

        cols[0].addWidget(QLabel(""))  # spacer under "Cell Type"
        cols[1].addWidget(self._rb_counts)
        cols[2].addWidget(self._rb_props)
        cols[3].addWidget(self._rb_confluence)
        cols[4].addWidget(self._rb_manual)

        # Per-type row widgets
        self._w_count:      dict[str, QLineEdit_custom] = {}
        self._w_prop:       dict[str, QLineEdit_custom] = {}
        self._w_confluence: dict[str, QLineEdit_custom] = {}
        self._w_manual:     dict[str, QLineEdit_custom] = {}

        for idx, ct in enumerate(self._cell_types):
            cols[0].addWidget(QLabel(ct))

            wc = QLineEdit_custom(enabled=False)
            wc.setText(str(s.cell_counts[ct]))
            wc.setFixedWidth(self._COL_W["count"])
            self._w_count[ct] = wc

            wp = QLineEdit_custom(enabled=False)
            wp.setText(str(s.cell_counts[ct]))
            wp.setObjectName(str(idx))
            wp.setFixedWidth(self._COL_W["prop"])
            wp.setValidator(int_validator)
            wp.textEdited.connect(self._prop_edited)
            self._w_prop[ct] = wp

            wconf = QLineEdit_custom(enabled=False)
            wconf.setObjectName(str(idx))
            wconf.setFixedWidth(self._COL_W["conf"])
            wconf.setValidator(QtGui.QDoubleValidator(bottom=0))
            wconf.textEdited.connect(self._conf_edited)
            wconf.set_formatter(ndigits=2)
            self._w_confluence[ct] = wconf

            wm = QLineEdit_custom(enabled=False)
            wm.setText(str(s.cell_counts[ct]))
            wm.setObjectName(str(idx))
            wm.setFixedWidth(self._COL_W["manual"])
            wm.setValidator(int_validator)
            wm.textEdited.connect(self._manual_edited)
            self._w_manual[ct] = wm

            for col, w in zip(cols[1:], [wc, wp, wconf, wm]):
                col.addWidget(w)

        # Total row
        cols[0].addWidget(QLabel("Total"))
        wc_total = QLineEdit_custom(enabled=False)
        wc_total.setText(str(n_cells_total))
        wc_total.setFixedWidth(self._COL_W["count"])
        cols[1].addWidget(wc_total)

        self._total_prop = QLineEdit_custom(enabled=False)
        self._total_prop.setText(str(n_cells_total))
        self._total_prop.setFixedWidth(self._COL_W["prop"])
        self._total_prop.setValidator(int_validator)
        self._total_prop.setObjectName("total_prop")
        self._total_prop.textEdited.connect(self._prop_edited)
        cols[2].addWidget(self._total_prop)

        self._total_conf = QLineEdit_custom(enabled=False)
        self._total_conf.setObjectName("total_conf")
        self._total_conf.setFixedWidth(self._COL_W["conf"])
        self._total_conf.setValidator(QtGui.QDoubleValidator(bottom=0))
        self._total_conf.textEdited.connect(self._conf_edited)
        self._total_conf.set_formatter(ndigits=2)
        self._total_conf.setText("100")
        cols[3].addWidget(self._total_conf)

        self._total_manual = QLineEdit_custom(enabled=False)
        self._total_manual.setText(str(n_cells_total))
        self._total_manual.setFixedWidth(self._COL_W["manual"])
        cols[4].addWidget(self._total_manual)

        self._update_confluence_from_counts()  # initialize confluence values from counts

        hbox_cols = QHBoxLayout()
        for i, c in enumerate(cols):
            hbox_cols.addLayout(c)
            if i < len(cols) - 1:
                hbox_cols.addWidget(QVLine())
        vbox.addLayout(hbox_cols)

        # Scroll if many cell types
        if len(self._cell_types) > 8:
            w = QWidget(); w.setLayout(vbox)
            sa = QScrollArea(); sa.setWidget(w)
            outer = QVBoxLayout()
            outer.addWidget(sa)
            vbox = outer

        vbox.addLayout(self.create_nav_bar())
        self.setLayout(vbox)

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def _mode_changed(self, mode_id: int) -> None:
        self.walkthrough.stale_futures = True
        enable = [False, False, False, False]
        enable[mode_id] = True
        _, ep, ec, em = enable
        for w in self._w_prop.values():      w.setEnabled(ep)
        self._total_prop.setEnabled(ep)
        for w in self._w_confluence.values(): w.setEnabled(ec)
        self._total_conf.setEnabled(ec)
        for w in self._w_manual.values():    w.setEnabled(em)

        if mode_id == 0:   # use data counts — reset manual to original data counts
            for ct in self._cell_types:
                self._w_manual[ct].setText(self._w_count[ct].text())
            self._update_total_manual()
            self._update_confluence_from_counts()
        elif mode_id == 1:  # proportions → sync manual to current proportion values
            for ct in self._cell_types:
                self._w_manual[ct].setText(self._w_prop[ct].text())
            self._update_total_manual()
            self._update_confluence_from_counts()
        elif mode_id == 2:  # confluence → count values will be synced from confluence values in _conf_edited callback, so just trigger that
            counts, _ = self._confluence_to_counts()
            for ct, n in counts.items():
                self._w_manual[ct].setText(str(n))
            self._update_total_manual()
        elif mode_id == 3: # manual → sync confluence to current manual values
            self._update_confluence_from_counts()

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _update_confluence_from_counts(self) -> None:
        """Recalculate confluence column from current manual-column counts."""
        total = 0.0
        for ct in self._cell_types:
            try:
                n = int(self._w_manual[ct].text() or 0)
            except ValueError:
                n = 0
            conf = n * self._area_per_cell[ct] * 100
            self._w_confluence[ct].setText(str(conf))
            total += conf
        self._total_conf.setText(str(total))
        self._warn_confluence(total)

    # ------------------------------------------------------------------
    # Proportion callbacks
    # ------------------------------------------------------------------

    def _prop_edited(self, text: str) -> None:
        self.walkthrough.stale_futures = True
        sender = self.sender()
        if not sender.hasAcceptableInput():
            return
        name = sender.objectName()
        if name == "total_prop":
            mult = int(text)
            self._total_manual.setText(text)
        else:
            idx = int(name)
            p = self._orig_props[self._cell_types[idx]]
            mult = int(text) / p if p else 0
            self._total_prop.setText(str(round(mult)))
            self._total_manual.setText(str(round(mult)))
        for i, ct in enumerate(self._cell_types):
            if name == str(i):
                continue
            self._w_prop[ct].setText(str(round(mult * self._orig_props[ct])))
            self._w_manual[ct].setText(str(round(mult * self._orig_props[ct])))
        self._update_total_manual()
        self._update_confluence_from_counts()

    # ------------------------------------------------------------------
    # Confluence callbacks
    # ------------------------------------------------------------------

    def _conf_edited(self, text: str) -> None:
        self.walkthrough.stale_futures = True
        sender = self.sender()
        if not sender.hasAcceptableInput():
            return
        sender.full_value = text
        current_name = sender.objectName()
        current_conf = float(text)
        if current_name == "total_conf":
            mult = current_conf / (self._prop_dot_ratios * 100 or 1)
        else:
            idx = int(current_name)
            ct = self._cell_types[idx]
            mult = (current_conf / 100) / (self._area_per_cell[ct] * self._orig_props[ct] or 1)
        total_conf = 0.0
        for i, ct in enumerate(self._cell_types):
            if current_name == str(i):
                total_conf += current_conf
                continue
            new_conf = mult * self._orig_props[ct] * self._area_per_cell[ct] * 100
            total_conf += new_conf
            self._w_confluence[ct].setText(str(new_conf))
        if current_name != "total_conf":
            self._total_conf.setText(f"{total_conf:.2f}")
        self._warn_confluence(total_conf)
        counts, total = self._confluence_to_counts()
        for ct, n in counts.items():
            self._w_manual[ct].setText(str(n))
        self._total_manual.setText(str(total))

    def _warn_confluence(self, total_conf: float) -> None:
        if total_conf > 100:
            self._total_conf.setStyleSheet(self._total_conf.invalid_style)
        else:
            self._total_conf.setStyleSheet(self._total_conf.valid_style)

    def _confluence_to_counts(self) -> tuple[dict, int]:
        counts, total = {}, 0
        for ct in self._cell_types:
            try:
                conf_pct = float(self._w_confluence[ct].get_full_value())
            except (ValueError, AttributeError):
                conf_pct = 0.0
            n = round((conf_pct / 100) / (self._area_per_cell[ct] or 1))
            counts[ct] = n
            total += n
        return counts, total

    # ------------------------------------------------------------------
    # Manual callbacks
    # ------------------------------------------------------------------

    def _manual_edited(self, _) -> None:
        self.walkthrough.stale_futures = True
        self._update_total_manual()
        self._update_confluence_from_counts()

    def _update_total_manual(self) -> None:
        total = sum(
            int(w.text()) for w in self._w_manual.values()
            if w.hasAcceptableInput()
        )
        self._total_manual.setText(str(total))

    # ------------------------------------------------------------------
    # process_window
    # ------------------------------------------------------------------

    def process_window(self) -> None:
        s = self.walkthrough.session
        mode = self._mode_group.checkedId()
        if mode == 1:   # proportion
            for ct in self._cell_types:
                s.cell_counts[ct] = int(self._w_prop[ct].text() or 0)
        elif mode == 2:  # confluence
            s.cell_counts, _ = self._confluence_to_counts()
        elif mode == 3:  # manual
            for ct in self._cell_types:
                s.cell_counts[ct] = int(self._w_manual[ct].text() or 0)
        # mode == 0: use data counts as-is (already set in session.cell_counts)

        zero_types = [ct for ct in self._cell_types if s.cell_counts.get(ct, 0) == 0]
        if zero_types:
            QMessageBox.warning(
                self,
                "Zero cell count",
                "The following cell types have a count of 0 and will place no cells:\n\n"
                + "\n".join(f"  \u2022 {ct}" for ct in zero_types)
                + "\n\nPlease set a non-zero count for each type before continuing.",
            )
            return

        s.cell_counts_confirmed = True
        self.walkthrough.advance()
