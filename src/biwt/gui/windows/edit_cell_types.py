"""Step: Keep, merge, or delete cell types found in the data."""

from __future__ import annotations
import os
import numpy as np
from PyQt5 import QtCore, QtGui
from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPushButton,
    QScrollArea, QWidget, QButtonGroup, QComboBox,
    QLineEdit, QSplitter,
)
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import QHLine, GoBackButton, LegendWindow


_KEEP_COLOR   = "lightgreen"
_MERGE_COLOR  = "yellow"
_DELETE_COLOR = "#FFCCCB"

_BTN_STYLE = lambda color: f"""
    QPushButton {{ color: black; font-weight: bold; }}
    QPushButton:enabled  {{ background-color: {color}; }}
    QPushButton:disabled {{ background-color: grey; }}
"""
_CB_STYLE = lambda color: f"""
    QCheckBox {{
        color: black; font-weight: bold;
        background-color: {color};
        padding: 2px 4px;
    }}
"""


class EditCellTypesWindow(BiwinformaticsWalkthroughWindow):
    """Let the user keep, merge, or delete discovered cell types.

    Displays a scrollable list of checkboxes (one per cell type) and
    Keep / Merge / Delete action buttons.  Optionally shows a dimensionality-
    reduction scatter plot when one is available in obsm.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        # --- initialise edit dict (all kept by default) -------------------
        s.cell_type_dict_on_edit = {ct: ct for ct in sorted(s.cell_types_list_original)}

        self._merge_id = 0
        self._checkbox: dict[str, QCheckBox] = {}
        self._keep_btn: dict[str, QPushButton] = {}

        label = QLabel(
            f"The following cell types were found.<br>"
            f"Choose which to "
            f"<b style='background-color:{_KEEP_COLOR};'>KEEP</b>, "
            f"<b style='background-color:{_MERGE_COLOR};'>MERGE</b>, and "
            f"<b style='background-color:{_DELETE_COLOR};'>DELETE</b>.<br>"
            f"By default, all are kept."
        )

        vbox = QVBoxLayout()
        vbox.addWidget(label)

        # Scrollable cell-type list
        inner_vbox = QVBoxLayout()
        self._checkbox_group = QButtonGroup(exclusive=False)
        self._checkbox_group.buttonToggled.connect(self._on_toggle)
        for ct in sorted(s.cell_types_list_original):
            hbox = QHBoxLayout()
            cb = QCheckBox(ct)
            cb.setStyleSheet(_CB_STYLE(_KEEP_COLOR))
            cb.setFixedHeight(30)
            self._checkbox_group.addButton(cb)
            self._checkbox[ct] = cb

            keep_b = QPushButton("Keep", enabled=False, objectName=ct)
            keep_b.setStyleSheet(_BTN_STYLE(_KEEP_COLOR))
            keep_b.setFixedHeight(30)
            keep_b.clicked.connect(self._keep_cb)
            self._keep_btn[ct] = keep_b

            hbox.addWidget(cb)
            hbox.addStretch(1)
            hbox.addWidget(keep_b)
            inner_vbox.addLayout(hbox)

        scroll_widget = QWidget()
        scroll_widget.setLayout(inner_vbox)
        scroll_area = QScrollArea()
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        vbox.addWidget(scroll_area)

        # Merge / Delete buttons
        self._merge_btn = QPushButton("Merge", enabled=False,
                                      styleSheet=_BTN_STYLE(_MERGE_COLOR))
        self._delete_btn = QPushButton("Delete", enabled=False,
                                       styleSheet=_BTN_STYLE(_DELETE_COLOR))
        self._merge_btn.clicked.connect(self._merge_cb)
        self._delete_btn.clicked.connect(self._delete_cb)
        hbox_md = QHBoxLayout()
        hbox_md.addWidget(self._merge_btn)
        hbox_md.addWidget(self._delete_btn)
        vbox.addLayout(hbox_md)
        vbox.addWidget(QHLine())

        # Back button closes the legend before returning to the previous step
        back_btn = GoBackButton(self, walkthrough, pre_cb=self._close_legend)
        nav_hbox = QHBoxLayout()
        nav_hbox.addWidget(back_btn)
        nav_hbox.addWidget(self.create_continue_button())
        vbox.addLayout(nav_hbox)

        # Optional dim-red plot
        self._dim_red_fig = None
        self._dim_red_canvas = None
        self._legend_window = None
        self.marker_size = 5.0
        self._scatter = None

        plot_added = False
        for key_hint in ("umap", "tsne", "pca", "spatial"):
            if self._try_plot_dim_red(s, key_hint):
                # Arrange as splitter: left = controls, right = plot
                left = QWidget(); left.setLayout(vbox)
                right_vbox = QVBoxLayout()
                if s.perform_spot_deconvolution:
                    note = QLabel("Colored by highest-probability cell type.")
                    note.setStyleSheet("color:gray; font-style:italic;")
                    right_vbox.addWidget(note)

                self._obsm_combo = QComboBox()
                for k in s.data.obsm.keys():
                    self._obsm_combo.addItem(k)
                self._obsm_combo.setCurrentIndex(
                    self._obsm_combo.findText(self._current_obsm_key)
                )
                self._obsm_combo.currentIndexChanged.connect(self._obsm_changed)

                ms_label = QLabel("Marker Size")
                self._ms_edit = QLineEdit(str(self.marker_size))
                self._ms_edit.setValidator(QtGui.QDoubleValidator(bottom=0))
                self._ms_edit.textChanged.connect(self._marker_size_changed)

                _legend_key = "\u2318L" if os.name != "nt" else "Ctrl+L"
                self._legend_btn = QPushButton(f"Show Legend ({_legend_key})")
                self._legend_btn.clicked.connect(self._show_legend)

                hbox_top = QHBoxLayout()
                hbox_top.addWidget(self._obsm_combo)
                hbox_top.addWidget(ms_label)
                hbox_top.addWidget(self._ms_edit)
                right_vbox.addLayout(hbox_top)
                right_vbox.addWidget(self._dim_red_canvas)
                right_vbox.addWidget(self._legend_btn)

                right = QWidget(); right.setLayout(right_vbox)
                splitter = QSplitter()
                splitter.addWidget(left)
                splitter.addWidget(right)
                outer = QVBoxLayout()
                outer.addWidget(splitter)
                self.setLayout(outer)
                plot_added = True
                break

        if not plot_added:
            self.setLayout(vbox)

        # Ctrl+L: toggle legend
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        legend_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        legend_shortcut.activated.connect(self._toggle_legend)

    # ------------------------------------------------------------------
    # Dim-red plot helpers
    # ------------------------------------------------------------------

    def _try_plot_dim_red(self, s, hint: str) -> bool:
        for key in s.data.obsm:
            if hint in key.lower():
                self._current_obsm_key = key
                self._plot_dim_red(s, key)
                return True
        return False

    def _plot_dim_red(self, s, key: str) -> None:
        import pandas as pd
        v = np.asarray(s.data.obsm[key])
        if self._dim_red_fig is None:
            self._dim_red_fig = Figure()
            self._dim_red_canvas = FigureCanvasQTAgg(self._dim_red_fig)
            plt.style.use("ggplot")
            self._ax = self._dim_red_fig.add_subplot(111, adjustable="box")

        labels = s.cell_types_max if s.perform_spot_deconvolution else s.cell_types_original
        cats = pd.CategoricalIndex(labels)
        idx = range(v.shape[0]) if v.shape[0] <= 1e5 else \
            np.random.choice(v.shape[0], 100_000, replace=False)
        self._scatter = self._ax.scatter(v[idx, 0], v[idx, 1],
                                         self.marker_size, c=cats.codes[list(idx)])
        self._ax.set_title(key)
        self._ax.set_aspect(1.0)
        self._dim_red_canvas.draw()

    def _close_legend(self) -> None:
        if self._legend_window is not None:
            self._legend_window.close()

    def _toggle_legend(self) -> None:
        """Ctrl+L: toggle legend visibility."""
        if self._legend_window is not None and self._legend_window.isVisible():
            self._legend_window.hide()
            return
        self._show_legend()

    def _show_legend(self) -> None:
        if self._scatter is None:
            return
        import matplotlib.patches as mpatches
        s = self.walkthrough.session
        labels = s.cell_types_max if s.perform_spot_deconvolution else s.cell_types_original
        import pandas as pd
        cats = pd.CategoricalIndex(labels)
        cmap = self._scatter.get_cmap()
        n = len(cats.categories)
        artists = [
            mpatches.Patch(color=cmap(i / max(n - 1, 1)), label=lbl)
            for i, lbl in enumerate(cats.categories)
        ]
        if self._legend_window is not None:
            self._legend_window.close()
        self._legend_window = LegendWindow(
            self, legend_artists=artists, legend_labels=list(cats.categories),
            legend_title="Cell Types",
        )
        self._legend_window.show()

    def _obsm_changed(self, _) -> None:
        key = self._obsm_combo.currentText()
        self._ax.cla()
        self._plot_dim_red(self.walkthrough.session, key)

    def _marker_size_changed(self, text: str) -> None:
        try:
            self.marker_size = float(text)
            if self._scatter is not None:
                sizes = np.full(len(self._scatter.get_offsets()), self.marker_size)
                self._scatter.set_sizes(sizes)
                self._dim_red_canvas.draw()
        except ValueError:
            pass

    def closeEvent(self, event):  # noqa: N802
        self._close_legend()
        if self._dim_red_fig is not None:
            self._dim_red_fig.clear()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Keep / Merge / Delete callbacks
    # ------------------------------------------------------------------

    def _on_toggle(self) -> None:
        n_checked = sum(1 for cb in self._checkbox.values() if cb.isChecked())
        self._delete_btn.setEnabled(n_checked >= 1)
        self._merge_btn.setEnabled(n_checked >= 2)

    def _keep_cb(self) -> None:
        self.walkthrough.stale_futures = True
        ct = self.sender().objectName()
        self._set_keep(ct)

    def _dissolve_solo_merge_partner(self, ct: str, old_target: str) -> None:
        """If *ct* leaving a merge group leaves exactly one partner, restore it to 'keep'."""
        s = self.walkthrough.session
        remaining = [
            k for k, v in s.cell_type_dict_on_edit.items()
            if k != ct and v == old_target and v is not None
        ]
        if len(remaining) == 1:
            self._set_keep(remaining[0], check_merge_group=False)

    def _set_keep(self, ct: str, check_merge_group: bool = True) -> None:
        s = self.walkthrough.session
        old_target = s.cell_type_dict_on_edit[ct]   # may be a merge-group target
        old_text   = self._checkbox[ct].text()       # capture before setText
        s.cell_type_dict_on_edit[ct] = ct
        self._checkbox[ct].setEnabled(True)
        self._checkbox[ct].setStyleSheet(_CB_STYLE(_KEEP_COLOR))
        self._checkbox[ct].setChecked(False)
        self._checkbox[ct].setText(ct)
        self._keep_btn[ct].setEnabled(False)

        if check_merge_group and "\u21d2 Merge Gp." in old_text:
            self._dissolve_solo_merge_partner(ct, old_target)

    def _delete_cb(self) -> None:
        self.walkthrough.stale_futures = True
        s = self.walkthrough.session
        for ct, cb in self._checkbox.items():
            if cb.isChecked():
                old_target = s.cell_type_dict_on_edit[ct]
                s.cell_type_dict_on_edit[ct] = None
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setStyleSheet(_CB_STYLE(_DELETE_COLOR))
                self._keep_btn[ct].setEnabled(True)

                if old_target is not None:
                    self._dissolve_solo_merge_partner(ct, old_target)

    def _merge_cb(self) -> None:
        self.walkthrough.stale_futures = True
        s = self.walkthrough.session
        self._merge_id += 1
        first_name = None
        for ct, cb in self._checkbox.items():
            if cb.isChecked():
                if first_name is None:
                    first_name = ct
                s.cell_type_dict_on_edit[ct] = first_name
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setStyleSheet(_CB_STYLE(_MERGE_COLOR))
                cb.setText(f"{ct} \u21d2 Merge Gp. #{self._merge_id}")
                self._keep_btn[ct].setEnabled(True)

    # ------------------------------------------------------------------
    # process_window
    # ------------------------------------------------------------------

    def process_window(self) -> None:
        self._close_legend()
        s = self.walkthrough.session
        s.compute_intermediate_types()
        self.walkthrough.advance()
