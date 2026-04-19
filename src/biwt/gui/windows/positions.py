"""Step: Interactively place cells in the simulation domain."""

from __future__ import annotations

import copy
import os

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle, Annulus, Wedge, Patch
from matplotlib.collections import PatchCollection
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from PyQt5 import QtCore, QtGui
from PyQt5.QtWidgets import (
    QApplication, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox, QPushButton, QScrollArea, QButtonGroup, QGridLayout,
    QLineEdit, QSplitter, QSpinBox, QMessageBox, QShortcut,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QKeySequence

from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import (
    GoBackButton, ContinueButton, LegendWindow, QCheckBox_custom, QLineEdit_custom,
)
from biwt.core.domain import classify_domain_mismatch
from biwt.gui.walkthrough import DomainEditorDialog, _build_mismatch_message


# ---------------------------------------------------------------------------
# PositionsWindow
# ---------------------------------------------------------------------------

class PositionsWindow(BiwinformaticsWalkthroughWindow):
    """Let the user choose a plotter and place each cell type.

    Layout:
      - Plotter toolbar (horizontal strip, top)
      - Left sidebar (cell types + parameters + help) | Right (canvas + action buttons)
      - Navigation (Go Back / Continue) at bottom
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        self._get_domain_dims(s)
        self._create_cell_type_scroll_area(s)
        self._create_plotter_toolbar(s)

        # --- Plot state setup ---
        self._setup_system_keys()

        self.preview_patch = None
        self.alpha_value = 1.0

        # Initialize coords_by_type for all cell types
        s.coords_by_type = {ct: np.empty((0, 3)) for ct in s.cell_types_list_final}
        s.plotted_cell_types_per_spot = []

        # Color map
        _colors = [
            "gray", "red", "yellow", "green", "blue", "magenta", "orange",
            "lime", "cyan", "hotpink", "peachpuff", "darkseagreen",
            "lightskyblue",
        ]
        n = len(s.cell_types_list_final)
        colors = (_colors[:n] if n <= len(_colors)
                  else [_colors[i % len(_colors)] for i in range(n)])
        self.color_by_celltype = dict(zip(s.cell_types_list_final, colors))

        self._create_patch_history()

        from biwt.gui.widgets import QHLine

        # --- Left sidebar: Plotters | Cell Types | Parameters ---
        sidebar_vbox = QVBoxLayout()

        # --- Plotters section ---
        sidebar_vbox.addWidget(QLabel("<b>Plotters</b>"))
        sidebar_vbox.addWidget(self.plotter_buttons_widget)
        sidebar_vbox.addWidget(QHLine())

        # --- Cell Types section ---
        sidebar_vbox.addWidget(QLabel("<b>Cell Types</b>"))
        sidebar_vbox.addWidget(self.cell_type_panel)
        sidebar_vbox.addWidget(QHLine())

        # --- Parameters section ---
        sidebar_vbox.addWidget(QLabel("<b>Parameters</b>"))
        self.par_area_container = QWidget()
        self.par_area_container_layout = QVBoxLayout()
        self.par_area_container_layout.setContentsMargins(0, 0, 0, 0)
        self.par_area_container.setLayout(self.par_area_container_layout)
        self.par_area_container_layout.addLayout(self._create_par_area())
        sidebar_vbox.addWidget(self.par_area_container)

        if s.use_spatial_data:
            sidebar_vbox.addLayout(self._create_spot_num_box())

        _legend_key = "\u2318L" if os.name != "nt" else "Ctrl+L"
        self.mouse_keyboard_label = QLabel(
            f"Draw with mouse and keyboard:<html><ul>"
            f"<li>Click: set (x0,y0)</li>"
            f"<li>{self._shift_key}\u2011click: set (w,h) or r or r1</li>"
            f"<li>{self._ctrl_key}\u2011click: set r0</li>"
            f"<li>{self._alt_ctrl}\u2011click: set \u03b81</li>"
            f"<li>{self._alt_shift}\u2011click: set \u03b82</li>"
            f"<li>{self._alt_key}\u2011click\u2011drag: set (\u03b81,\u03b82)</li>"
            f"</ul></html>"
            f"Notes:<html><ul>"
            f"<li>1\u20136: select plotter (plot focused)</li>"
            f"<li>\u21b5: plot cells</li>"
            f"<li>Focus on plot for hotkeys.</li>"
            f"<li>{self._cmd_z}: undo</li>"
            f"<li>{self._cmd_shift_z}: redo</li>"
            f"</ul></html>"
        )
        self.mouse_keyboard_label.setStyleSheet(
            "QLabel:enabled {color:black;} QLabel:disabled {color:rgb(150,150,150);}"
        )
        sidebar_vbox.addWidget(self.mouse_keyboard_label)
        sidebar_vbox.addStretch(1)

        sidebar_widget = QWidget()
        sidebar_widget.setLayout(sidebar_vbox)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(sidebar_widget)
        sidebar_scroll.setMinimumWidth(230)

        # --- Right side: canvas + preview image + plotter name + action buttons ---
        self._create_figure()

        self.plotter_preview_label = QLabel()
        self.plotter_preview_size = 160
        self.plotter_preview_label.setFixedSize(self.plotter_preview_size, self.plotter_preview_size)
        self.plotter_preview_label.setAlignment(Qt.AlignCenter)
        if self._initial_preview_icon_path:
            pix = QtGui.QPixmap(self._initial_preview_icon_path).scaled(
                self.plotter_preview_size, self.plotter_preview_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.plotter_preview_label.setPixmap(pix)

        self.plotter_name_label = QLabel(self._initial_preview_name + " Plotter")
        self.plotter_name_label.setAlignment(Qt.AlignCenter)
        self.plotter_name_label.setStyleSheet("font-size: 13pt; font-weight: bold;")

        preview_hbox = QHBoxLayout()
        preview_vbox = QVBoxLayout()
        preview_vbox.addWidget(self.plotter_preview_label, alignment=Qt.AlignCenter)
        preview_vbox.addWidget(self.plotter_name_label, alignment=Qt.AlignCenter)
        preview_hbox.addStretch(1)
        preview_hbox.addLayout(preview_vbox)

        self.plot_cells_button = QPushButton("Plot (\u21b5)", enabled=True)
        self.plot_cells_button.setStyleSheet(
            "QPushButton:enabled {background-color:lightgreen;}"
            "QPushButton:disabled {background-color:grey;}"
        )
        self.plot_cells_button.clicked.connect(self.plot_cell_pos)

        self.show_legend_button = QPushButton(f"Show Legend ({_legend_key})")
        self.show_legend_button.setStyleSheet(
            "QPushButton {background-color:lightgreen;}"
        )
        self.show_legend_button.clicked.connect(self._show_legend_cb)

        self.domain_settings_button = QPushButton("Domain Settings\u2026")
        self.domain_settings_button.clicked.connect(self._open_domain_editor)

        action_hbox = QHBoxLayout()
        action_hbox.addStretch(1)
        action_hbox.addWidget(self.plot_cells_button)
        action_hbox.addWidget(self.show_legend_button)
        action_hbox.addWidget(self.domain_settings_button)
        action_hbox.addStretch(1)

        right_vbox = QVBoxLayout()
        right_vbox.addLayout(preview_hbox)
        right_vbox.addWidget(self.canvas, stretch=1)
        right_vbox.addLayout(action_hbox)
        right_widget = QWidget()
        right_widget.setLayout(right_vbox)

        self.sync_par_area()

        # --- Hotkeys ---
        enter_shortcut = QShortcut(QKeySequence(Qt.Key_Return), self)
        enter_shortcut.activated.connect(self._enter_shortcut_cb)
        legend_shortcut = QShortcut(QKeySequence("Ctrl+L"), self)
        legend_shortcut.activated.connect(self._toggle_legend)

        # --- Assemble: splitter (sidebar | canvas+preview) ---
        splitter = QSplitter()
        splitter.addWidget(sidebar_scroll)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 0)  # sidebar: don't stretch
        splitter.setStretchFactor(1, 1)  # figure: take remaining space

        vbox = QVBoxLayout()
        vbox.addWidget(splitter, stretch=1)

        go_back_button = GoBackButton(self, walkthrough, pre_cb=self._close_legend)
        self.continue_to_write_button = ContinueButton(
            self, self.process_window
        )
        self.continue_to_write_button.setEnabled(False)

        hbox_write = QHBoxLayout()
        hbox_write.addWidget(go_back_button)
        hbox_write.addWidget(self.continue_to_write_button)
        vbox.addLayout(hbox_write)

        self.setLayout(vbox)
        self._maybe_show_domain_editor()

    # ------------------------------------------------------------------
    # Domain
    # ------------------------------------------------------------------

    def _maybe_show_domain_editor(self) -> None:
        """Auto-show the domain editor on first entry if there is a mismatch."""
        s = self.walkthrough.session
        if s.domain_accepted:
            return
        # Domain doesn't affect non-spatial placement (random positions fill the domain).
        if not s.use_spatial_data:
            s.domain_accepted = True
            return
        data_d = s.data_domain
        if data_d is None or data_d.source == "default":
            s.domain_accepted = True
            return
        mismatch = classify_domain_mismatch(data_d, s.effective_domain)
        if mismatch is None:
            s.domain_accepted = True
            return
        host_name = s.biwt_input.host_name
        msg = _build_mismatch_message(mismatch, data_d, s.effective_domain, host_name)
        dlg = DomainEditorDialog(
            self, data_d, s.preferred_domain,
            context_message=msg,
            initial_domain=s.user_domain,  # show prior values if revisiting
            host_name=host_name,
        )
        if dlg.exec_() == QDialog.Accepted:
            user_domain, auto_scale = dlg.result()
            s.user_domain = user_domain
            s.auto_scale_to_domain = auto_scale
            old_is_2d = self.plot_is_2d
            self._get_domain_dims(s)
            self._apply_domain_change_and_redraw(old_is_2d)
        s.domain_accepted = True

    def _get_domain_dims(self, s) -> None:
        d = s.effective_domain
        self.plot_xmin = d.xmin
        self.plot_xmax = d.xmax
        self.plot_dx   = d.xmax - d.xmin
        self.plot_ymin = d.ymin
        self.plot_ymax = d.ymax
        self.plot_dy   = d.ymax - d.ymin
        self.plot_zmin = d.zmin
        self.plot_zmax = d.zmax
        self.plot_dz   = d.zmax - d.zmin
        self.plot_zdel = 20.0  # default PhysiCell voxel thickness
        self.plot_is_2d = d.is_2d

    def _close_legend(self) -> None:
        if hasattr(self, "legend_window") and self.legend_window is not None:
            self.legend_window.close()

    def _rebuild_par_area(self) -> None:
        """Destroy existing par widgets and rebuild for current dimensionality."""
        layout = self.par_area_container_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.layout():
                # Grid → HBox rows → (label, lineEdit)
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.layout():
                        while child.layout().count():
                            w = child.layout().takeAt(0)
                            if w.widget():
                                w.widget().deleteLater()
            elif item.widget():
                item.widget().deleteLater()
        self.par_label = []
        self.par_text = []
        layout.addLayout(self._create_par_area())

    def _update_plotter_button_labels(self) -> None:
        """Update labels and plotter names after a 2D↔3D switch."""
        is_2d = self.plot_is_2d
        updates = {
            1: ("Rectangle" if is_2d else "Box",
                f"{'Rectangle' if is_2d else 'Box'} (2)"),
            2: ("Disc" if is_2d else "Sphere",
                f"{'Disc' if is_2d else 'Sphere'} (3)"),
            3: ("Annulus" if is_2d else "Spherical Shell",
                f"{'Annulus' if is_2d else 'Spherical Shell'} (4)"),
        }
        for bid, (display_name, label_text) in updates.items():
            self._plotter_names[bid] = display_name
            if bid < len(self._plotter_small_labels):
                self._plotter_small_labels[bid].setText(label_text)
            btn = self.cell_pos_button_group.button(bid)
            if btn:
                btn.setToolTip(label_text)
        cur = self.cell_pos_button_group.checkedId()
        if cur in updates and hasattr(self, "plotter_name_label"):
            self.plotter_name_label.setText(updates[cur][0])

    # ------------------------------------------------------------------
    # Cell-type panel (sidebar section, no scroll area)
    # ------------------------------------------------------------------

    def _create_cell_type_scroll_area(self, s) -> None:
        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(
            "Select cell type(s) to place.\n"
            "Greyed out cell types have already been placed."
        ))

        hbox_mid = QHBoxLayout()
        vbox_checks = QVBoxLayout()

        self.cell_type_button_group = QButtonGroup(exclusive=False)
        self.cell_type_button_group.buttonClicked.connect(self._cell_type_cb)

        self.checkbox_dict: dict[str, QCheckBox_custom] = {}
        for ct in s.cell_types_list_final:
            cb = QCheckBox_custom(ct)
            cb.setChecked(False)
            cb.setEnabled(True)
            vbox_checks.addWidget(cb)
            self.cell_type_button_group.addButton(cb)
            self.checkbox_dict[ct] = cb

        _undo_style = (
            "QPushButton:enabled  { background-color: yellow; }"
            "QPushButton:disabled { background-color: grey; }"
        )
        vbox_undos = QVBoxLayout()
        self.undo_button: dict[str, QPushButton] = {}
        for ct in s.cell_types_list_final:
            btn = QPushButton("Undo", enabled=False, objectName=ct)
            btn.setStyleSheet(_undo_style)
            btn.clicked.connect(self._undo_button_cb)
            self.undo_button[ct] = btn
            vbox_undos.addWidget(btn)

        hbox_mid.addLayout(vbox_checks)
        hbox_mid.addLayout(vbox_undos)
        vbox.addLayout(hbox_mid)

        _btn_style = (
            "QPushButton:enabled  { background-color: lightgreen; }"
            "QPushButton:disabled { background-color: grey; }"
        )
        select_all = QPushButton("Select remaining", styleSheet=_btn_style)
        select_all.clicked.connect(self._select_all_cb)
        deselect_all = QPushButton("Unselect all", styleSheet=_btn_style)
        deselect_all.clicked.connect(self._deselect_all_cb)
        hbox_sel = QHBoxLayout()
        hbox_sel.addWidget(select_all)
        hbox_sel.addWidget(deselect_all)
        vbox.addLayout(hbox_sel)

        _undo_style2 = (
            "QPushButton:enabled  { background-color: yellow; }"
            "QPushButton:disabled { background-color: grey; }"
        )
        self.undo_all_button = QPushButton("Undo All", enabled=False)
        self.undo_all_button.setStyleSheet(_undo_style2)
        self.undo_all_button.clicked.connect(self._undo_all_cb)
        vbox.addWidget(self.undo_all_button)

        self.cell_type_panel = QWidget()
        self.cell_type_panel.setLayout(vbox)

    # ------------------------------------------------------------------
    # Plotter toolbar
    # ------------------------------------------------------------------

    def _create_plotter_toolbar(self, s) -> None:
        """Build the plotter icon buttons widget (for left sidebar Plotters section)."""
        self.spatial_plotter_id: int | None = None
        self.cell_pos_button_group = QButtonGroup()
        self.cell_pos_button_group.setExclusive(True)
        self.cell_pos_button_group.idToggled.connect(self._plotter_changed)

        btn_size = 48
        icon_size = QtCore.QSize(round(0.8 * btn_size), round(0.8 * btn_size))
        next_id = 0
        self._plotter_icon_paths: list[str] = []
        self._plotter_names: list[str] = []
        self._plotter_small_labels: list[QLabel] = []
        _initial_icon_path: list[str] = []   # mutable cell: [path] of initially checked
        _initial_name: list[str] = []        # mutable cell: [name] of initially checked

        _btn_style = """
            QPushButton          { background-color: lightblue; color: black; }
            QPushButton::checked { background-color: black; }
        """

        icon_dir = os.path.join(os.path.dirname(__file__), "..", "icons")

        hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)

        btn_lbl_spc = 8

        def _add_btn(icon_name: str, label: str, display_name: str,
                     checked: bool = False) -> int:
            nonlocal next_id
            icon_path = os.path.join(icon_dir, icon_name)
            self._plotter_icon_paths.append(icon_path)
            self._plotter_names.append(display_name)
            if checked:
                _initial_icon_path.append(icon_path)
                _initial_name.append(display_name)
            btn = QPushButton(
                icon=QIcon(icon_path), iconSize=icon_size,
                checkable=True, checked=checked,
                toolTip=label,
            )
            btn.setFixedSize(btn_size, btn_size)
            btn.setStyleSheet(_btn_style)
            self.cell_pos_button_group.addButton(btn, next_id)
            col = QVBoxLayout()
            col.setSpacing(btn_lbl_spc)
            col.addWidget(btn, alignment=Qt.AlignCenter)
            lbl = QLabel(label)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-size: 10px;")
            col.addWidget(lbl, alignment=Qt.AlignCenter)
            hbox.addLayout(col)
            self._plotter_small_labels.append(lbl)
            bid = next_id
            next_id += 1
            return bid

        _everywhere_name = "Everywhere"
        _rect_name = "Rectangle" if self.plot_is_2d else "Box"
        _disc_name = "Disc" if self.plot_is_2d else "Sphere"
        _annulus_name = "Annulus" if self.plot_is_2d else "Spherical Shell"

        _add_btn("scatter_square.svg", "Everywhere (1)", _everywhere_name,
                 checked=(not s.use_spatial_data))
        _add_btn("rectangle.svg", f"{_rect_name} (2)", _rect_name)
        _add_btn("disc.svg", f"{_disc_name} (3)", _disc_name)
        _add_btn("annulus.svg", f"{_annulus_name} (4)", _annulus_name)
        _add_btn("wedge.svg", "Wedge (5)", "Wedge")

        if s.use_spatial_data:
            self.spatial_plotter_id = next_id
            icon_path = os.path.join(icon_dir, "spatial.png")
            self._plotter_icon_paths.append(icon_path)
            self._plotter_names.append("Spatial")
            _initial_icon_path.append(icon_path)
            _initial_name.append("Spatial")
            btn = QPushButton(
                icon=QIcon(icon_path), iconSize=icon_size,
                checkable=True, checked=True,
                toolTip="Spatial Plotter",
            )
            btn.setFixedSize(btn_size, btn_size)
            btn.setStyleSheet(_btn_style)
            btn.toggled.connect(self._spatial_button_cb)
            self.cell_pos_button_group.addButton(btn, next_id)
            col = QVBoxLayout()
            col.setSpacing(btn_lbl_spc)
            col.addWidget(btn, alignment=Qt.AlignCenter)
            lbl = QLabel("Spatial (6)")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("font-size: 10px;")
            col.addWidget(lbl, alignment=Qt.AlignCenter)
            hbox.addLayout(col)
            self._plotter_small_labels.append(lbl)

        hbox.addStretch(1)

        self.plotter_buttons_widget = QWidget()
        self.plotter_buttons_widget.setLayout(hbox)

        # Initial preview icon + name (used when building the right panel)
        self._initial_preview_icon_path = _initial_icon_path[0] if _initial_icon_path else ""
        self._initial_preview_name = _initial_name[0] if _initial_name else ""

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _plotter_changed(self) -> None:
        if hasattr(self, "canvas"):
            self.sync_par_area()
            self.canvas.setFocus()
        s = self.walkthrough.session
        if s.use_spatial_data and hasattr(self, "num_box"):
            is_spatial = (
                self.cell_pos_button_group.checkedId() == self.spatial_plotter_id
            )
            self.num_box.setEnabled(is_spatial)
        # Update the 128×128 preview icon
        bid = self.cell_pos_button_group.checkedId()
        if (hasattr(self, "plotter_preview_label")
                and 0 <= bid < len(self._plotter_icon_paths)):
            pix = QtGui.QPixmap(self._plotter_icon_paths[bid]).scaled(
                self.plotter_preview_size, self.plotter_preview_size,
                Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.plotter_preview_label.setPixmap(pix)
        if (hasattr(self, "plotter_name_label")
                and 0 <= bid < len(self._plotter_names)):
            self.plotter_name_label.setText(self._plotter_names[bid] + " Plotter")

    def _spatial_button_cb(self, checked: bool) -> None:
        if not checked:
            return
        for cb in self.checkbox_dict.values():
            if cb.isEnabled():
                cb.setChecked(True)

    def is_any_cell_type_checked(self) -> bool:
        return self.cell_type_button_group.checkedButton() is not None

    def _cell_type_cb(self) -> None:
        if self.is_any_cell_type_checked():
            self.sync_par_area()
        else:
            self.plot_cells_button.setEnabled(False)

    def _select_all_cb(self) -> None:
        for cb in self.checkbox_dict.values():
            if cb.isEnabled():
                cb.setChecked(True)
        if self.is_any_cell_type_checked():
            self.sync_par_area()

    def _deselect_all_cb(self) -> None:
        for cb in self.checkbox_dict.values():
            if cb.isEnabled():
                cb.setChecked(False)
        self.plot_cells_button.setEnabled(False)

    def _undo_button_cb(self) -> None:
        ct = self.sender().objectName()
        self._undo_cell_type(ct)
        self._replot_all_after_undo()

    def _undo_cell_type(self, ct: str, undo_all_flag: bool = False) -> None:
        s = self.walkthrough.session
        s.coords_by_type[ct] = np.empty((0, 3))
        self.checkbox_dict[ct].setEnabled(True)
        self.checkbox_dict[ct].setChecked(False)
        self.undo_button[ct].setEnabled(False)
        if undo_all_flag:
            return
        for arr in s.coords_by_type.values():
            if arr.shape[0] > 0:
                return
        self.undo_all_button.setEnabled(False)

    def _replot_all_after_undo(self) -> None:
        s = self.walkthrough.session
        self.ax0.cla()
        self.preview_patch = None
        self.format_axis()
        self.legend_artists = []
        self.legend_labels = []

        for ct, coords in s.coords_by_type.items():
            if coords.shape[0] == 0:
                continue
            if self.plot_is_2d:
                r = np.sqrt(self.cell_type_micron2_area_dict[ct] / np.pi)
                self.circles(coords, s=r, color=self.color_by_celltype[ct],
                             edgecolor="none", linewidth=0.5, alpha=self.alpha_value)
                self.legend_artists.append(
                    Patch(facecolor=self.color_by_celltype[ct], edgecolor="none")
                )
            else:
                self.ax0.scatter(
                    coords[:, 0], coords[:, 1], coords[:, 2],
                    s=8.0, color=self.color_by_celltype[ct], alpha=self.alpha_value
                )
                self.legend_artists.append(
                    plt.Line2D([], [], marker="o", color="w",
                               markerfacecolor=self.color_by_celltype[ct], markersize=8)
                )
            self.legend_labels.append(ct)

        self.update_legend_window()
        self.sync_par_area()
        self.continue_to_write_button.setEnabled(False)

    def _undo_all_cb(self) -> None:
        for ct in self.checkbox_dict:
            self._undo_cell_type(ct, undo_all_flag=True)
        self._replot_all_after_undo()
        self.undo_all_button.setEnabled(False)

    # ------------------------------------------------------------------

    def process_window(self) -> None:
        self._close_legend()
        self.walkthrough.session.positions_set = True
        self.walkthrough.advance()

    # ------------------------------------------------------------------
    # System key labels (OS-dependent)
    # ------------------------------------------------------------------

    def _setup_system_keys(self) -> None:
        if os.name == "nt":
            self._alt_key   = "Alt"
            self._ctrl_key  = "Ctrl"
            self._shift_key = "Shift"
            self._cmd_z       = "Ctrl-Z"
            self._cmd_shift_z = "Ctrl-Shift-Z"
            self._alt_ctrl  = "Alt-Ctrl"
            self._alt_shift = "Alt-Shift"
            self._lower_modifier = QtCore.Qt.MetaModifier
        else:
            self._alt_key   = "\u2325"
            self._ctrl_key  = "\u2303"
            self._shift_key = "\u21e7"
            self._cmd_z       = "\u2318Z"
            self._cmd_shift_z = "\u21e7\u2318Z"
            self._alt_ctrl  = "\u2325\u2303"
            self._alt_shift = "\u2325\u21e7"
            self._lower_modifier = QtCore.Qt.MetaModifier

    # ------------------------------------------------------------------
    # Patch history (undo/redo per plotter)
    # ------------------------------------------------------------------

    def _create_patch_history(self) -> None:
        self.patch_history = [
            [],
            [self._default_rectangle_pars()],
            [self._default_disc_pars()],
            [self._default_annulus_pars()],
            [self._default_wedge_pars()],
            [self._default_spatial_pars()],
        ]
        self.patch_history_idx = [0] * len(self.patch_history)

    def _default_center(self):
        x0 = 0.5 * (self.plot_xmin + self.plot_xmax)
        y0 = 0.5 * (self.plot_ymin + self.plot_ymax)
        return (x0, y0) if self.plot_is_2d else (x0, y0, 0.5 * (self.plot_zmin + self.plot_zmax))

    def _default_wh(self, x0y0=None, factor=0.5):
        if x0y0 is None:
            x0y0 = self._default_center()
        dim_lengths = []
        bounds = [
            (self.plot_xmin, self.plot_xmax),
            (self.plot_ymin, self.plot_ymax),
            (self.plot_zmin, self.plot_zmax),
        ]
        for i, c in enumerate(x0y0):
            mn, mx = bounds[i]
            dL = abs(mn - c)
            dR = abs(mx - c)
            if dL > dR:
                dl = factor * dL
                c -= dl
                self._assign_par(c, i)
            else:
                dl = factor * dR
            dim_lengths.append(dl)
        return tuple(dim_lengths)

    def _default_radius(self, x0y0=None, factor=0.9):
        if x0y0 is None:
            x0y0 = self._default_center()
        if self.plot_is_2d:
            x0, y0 = x0y0
            return factor * min(abs(v) for v in [
                self.plot_xmax - x0, self.plot_xmin - x0,
                self.plot_ymax - y0, self.plot_ymin - y0,
            ])
        x0, y0, z0 = x0y0
        return factor * min(abs(v) for v in [
            self.plot_xmax - x0, self.plot_xmin - x0,
            self.plot_ymax - y0, self.plot_ymin - y0,
            self.plot_zmax - z0, self.plot_zmin - z0,
        ])

    def _default_rectangle_pars(self):
        c = self._default_center()
        return [*c, *self._default_wh(c)]

    def _default_disc_pars(self):
        c = self._default_center()
        return [*c, self._default_radius(c)]

    def _default_annulus_pars(self):
        disc = self._default_disc_pars()
        r0 = self._default_radius(factor=0.5)
        center = disc[:-1]
        r1 = disc[-1]
        return [*center, r0, r1]

    def _default_wedge_pars(self):
        ann = self._default_annulus_pars()
        angles = ("0", "270") if self.plot_is_2d else ("0", "270", "0", "45")
        return [*ann, *angles]

    def _default_spatial_pars(self):
        s = self.walkthrough.session
        if not s.use_spatial_data or s.spatial_data_final is None:
            return []

        # Compute data bounding box (same for both scale modes).
        xy = s.spatial_data_final[:, :2]
        xL, xR = float(xy[:, 0].min()), float(xy[:, 0].max())
        yL, yR = float(xy[:, 1].min()), float(xy[:, 1].max())
        if xL == xR:
            xL -= 0.5; xR += 0.5
        if yL == yR:
            yL -= 0.5; yR += 0.5
        data_dx = xR - xL
        data_dy = yR - yL

        if not self.plot_is_2d:
            zL = float(s.spatial_data_final[:, 2].min())
            zR = float(s.spatial_data_final[:, 2].max())
            if zL == zR:
                zL -= 0.5; zR += 0.5
            data_dz = zR - zL

        # Normalised base coords used by the spatial plotter: [0, 1] in each axis.
        self.spatial_base_coords = (xy - [xL, yL]) / [data_dx, data_dy]
        if not self.plot_is_2d:
            self.spatial_base_coords = np.hstack((
                self.spatial_base_coords,
                ((s.spatial_data_final[:, 2] - zL) / data_dz).reshape(-1, 1),
            ))

        if s.auto_scale_to_domain:
            # Scale to fill domain while preserving aspect ratio.
            sf_x = self.plot_dx / data_dx
            sf_y = self.plot_dy / data_dy
            if self.plot_is_2d:
                sf = min(sf_x, sf_y)
            else:
                sf = min(sf_x, sf_y, self.plot_dz / data_dz)

            width  = data_dx * sf
            height = data_dy * sf
            x0 = 0.5 * (self.plot_xmin + self.plot_xmax) - width / 2
            y0 = 0.5 * (self.plot_ymin + self.plot_ymax) - height / 2

            if self.plot_is_2d:
                return [x0, y0, width, height]

            depth = data_dz * sf
            z0 = 0.5 * (self.plot_zmin + self.plot_zmax) - depth / 2
            return [x0, y0, z0, width, height, depth]

        else:
            # No scaling: report original data bounding box, centered in domain.
            x0 = 0.5 * (self.plot_xmin + self.plot_xmax) - data_dx / 2
            y0 = 0.5 * (self.plot_ymin + self.plot_ymax) - data_dy / 2

            if self.plot_is_2d:
                return [x0, y0, data_dx, data_dy]

            z0 = 0.5 * (self.plot_zmin + self.plot_zmax) - data_dz / 2
            return [x0, y0, z0, data_dx, data_dy, data_dz]

    # ------------------------------------------------------------------
    # Parameter text boxes
    # ------------------------------------------------------------------

    def _create_par_area(self) -> QGridLayout:
        par_label_w, par_text_w = 50, 75
        self.par_label: list[QLabel] = []
        self.par_text: list[QLineEdit_custom] = []
        grid = QGridLayout()
        rI, cI, cmax = 0, 0, 2

        nonneg = QtGui.QDoubleValidator()
        nonneg.setBottom(0)
        coord_v = QtGui.QDoubleValidator()

        n_pars = 6 if self.plot_is_2d else 9
        for i in range(n_pars):
            lbl = QLabel()
            lbl.setAlignment(QtCore.Qt.AlignRight)
            lbl.setFixedWidth(par_label_w)
            pt = QLineEdit_custom(ndigits=2)
            pt.setFixedWidth(par_text_w)
            pt.editingFinished.connect(self._par_editing_finished)
            hbox = QHBoxLayout()
            hbox.addWidget(lbl)
            hbox.addWidget(pt)
            grid.addLayout(hbox, rI, cI)
            rI, cI = (rI, cI + 1) if cI < cmax else (rI + 1, 0)
            self.par_label.append(lbl)
            self.par_text.append(pt)

        if self.plot_is_2d:
            for i in [0, 1, 4, 5]:
                self.par_text[i].setValidator(coord_v)
            for i in [2, 3]:
                self.par_text[i].setValidator(nonneg)
        else:
            for i in [0, 1, 2, 5, 6]:
                self.par_text[i].setValidator(coord_v)
            for i in [3, 4]:
                self.par_text[i].setValidator(nonneg)
            phi_v = QtGui.QDoubleValidator(0, 180, 6)
            phi_v.setNotation(QtGui.QDoubleValidator.StandardNotation)
            for i in [7, 8]:
                self.par_text[i].setValidator(phi_v)

        return grid

    def _assign_par(self, value, idx: int) -> None:
        self.par_text[idx].setText(str(value))
        self.par_text[idx].setCursorPosition(0)

    def _par_editing_finished(self, reset_cursor: bool = True) -> None:
        self._read_par_texts()
        if self.current_pars_acceptable:
            self._append_to_history()
        if reset_cursor and self.sender():
            self.sender().setCursorPosition(0)

    def _read_par_texts(self) -> None:
        self.current_pars = []
        for pt in self.par_text:
            if not pt.isEnabled():
                break
            if pt.check_validity():
                try:
                    self.current_pars.append(float(pt.text()))
                    continue
                except ValueError:
                    pt.setStyleSheet(pt.invalid_style)
            self.plot_cells_button.setEnabled(False)
            self.current_pars_acceptable = False
            return
        self.current_pars_acceptable = True

    def _append_to_history(self) -> None:
        bid = self.cell_pos_button_group.checkedId()
        idx = self.patch_history_idx[bid]
        if idx < len(self.patch_history[bid]) - 1:
            del self.patch_history[bid][idx + 1:]
        self.patch_history[bid].append(list(self.current_pars))
        self.patch_history_idx[bid] += 1

    def _get_current_pars(self):
        return list(self.current_pars)

    # ------------------------------------------------------------------
    # Spot-count spinbox
    # ------------------------------------------------------------------

    def _create_spot_num_box(self) -> QHBoxLayout:
        self.num_box = QSpinBox(minimum=1, maximum=10_000_000, singleStep=1, value=1)
        self.num_box.setStyleSheet(
            "QSpinBox {color:black; background-color:white;}"
            "QSpinBox:disabled {background-color:lightgray;}"
        )
        self.num_box.valueChanged.connect(self._num_box_cb)
        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addWidget(QLabel("Num cells per spot:"))
        hbox.addWidget(self.num_box)
        return hbox

    def _num_box_cb(self, v: int) -> None:
        if hasattr(self, "single_scatter_sizes"):
            self.scatter_sizes = v * self.single_scatter_sizes
            if self.preview_patch is not None:
                self.preview_patch.set_sizes(self.scatter_sizes)
            self.current_plotter()

    # ------------------------------------------------------------------
    # Figure creation
    # ------------------------------------------------------------------

    def _create_figure(self) -> None:
        self.figure = Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        plt.style.use("ggplot")
        self.canvas.setStyleSheet("background-color:transparent;")
        self.canvas.setFocusPolicy(QtCore.Qt.ClickFocus)

        proj = None if self.plot_is_2d else "3d"
        self.ax0 = self.figure.add_subplot(111, adjustable="box", projection=proj)
        self.format_axis()

        self.mpl_cid = []
        self.mouse_pressed = False
        self.canvas.focusInEvent  = lambda e: self._canvas_focus_in(e)
        self.canvas.focusOutEvent = lambda e: self._canvas_focus_out(e)
        self.canvas.keyPressEvent = lambda e: self._canvas_key_press(e)
        self.canvas.update()
        self.canvas.draw()

        self._recompute_scatter_sizes()

        self.legend_artists: list = []
        self.legend_labels: list  = []
        self.legend_window: LegendWindow | None = None
        self.update_legend_window()

    def format_axis(self) -> None:
        self.ax0.set_xlim(self.plot_xmin, self.plot_xmax)
        self.ax0.set_ylim(self.plot_ymin, self.plot_ymax)
        self.ax0.set_xlabel("X (\u03bcm)")
        self.ax0.set_ylabel("Y (\u03bcm)")
        if self.plot_is_2d:
            self.ax0.set_aspect(1.0)
        else:
            self.ax0.set_zlim(self.plot_zmin, self.plot_zmax)
            self.ax0.set_box_aspect([1, 1, 1])
            self.ax0.set_zlabel("Z (\u03bcm)")

    def _recompute_scatter_sizes(self) -> None:
        """Recompute scatter point sizes from current axis transform.

        Must be called after format_axis() so that transData reflects the
        current domain limits.  Also called at init (via _create_figure) and
        whenever the domain changes (via _open_domain_editor).
        """
        s = self.walkthrough.session
        dx, dy = (self.ax0.transData.transform((1, 1))
                  - self.ax0.transData.transform((0, 0)))
        area_sf = dx * dy * (72 / self.figure.dpi) ** 2
        # Matplotlib scatter expects marker "size" (s) as marker-size^2 in pt^2.
        # For the default circular marker "o", rendered marker area is (pi/4) * s.
        # We convert physical cross-sectional area (true area in pt^2) to scatter s
        # so that scatter preview circles match self.circles(..., s=radius_in_data).
        marker_area_to_scatter_size = 4.0 / np.pi
        default_vol = 2494.0
        std_area = (((9 * np.pi * default_vol ** 2) / 16) ** (1.0 / 3))

        if s.perform_spot_deconvolution:
            self._deconvolution_scatter_size = (
                marker_area_to_scatter_size * area_sf * std_area * (
                    self.num_box.value() if s.use_spatial_data else 1
                )
            )
            self.cell_type_micron2_area_dict = {
                ct: std_area for ct in s.cell_types_list_final
            }
            self.cell_type_pt_area_dict = {
                ct: marker_area_to_scatter_size * area_sf * A
                for ct, A in self.cell_type_micron2_area_dict.items()
            }
            if s.cell_types_final:
                self.single_scatter_sizes = np.array([
                    self.cell_type_pt_area_dict[ct] for ct in s.cell_types_final
                ])
        else:
            vols = s.cell_volume or {}
            self.cell_type_micron2_area_dict = {
                ct: (((9 * np.pi * vols.get(ct, 2494.0) ** 2) / 16) ** (1.0 / 3))
                for ct in s.cell_types_list_final
            }
            if s.use_spatial_data or not self.plot_is_2d:
                self.cell_type_pt_area_dict = {
                    ct: marker_area_to_scatter_size * area_sf * A
                    for ct, A in self.cell_type_micron2_area_dict.items()
                }
                if s.cell_types_final:
                    self.single_scatter_sizes = np.array([
                        self.cell_type_pt_area_dict[ct] for ct in s.cell_types_final
                    ])
                    if s.use_spatial_data:
                        self.scatter_sizes = (
                            self.num_box.value() * self.single_scatter_sizes
                        )

    # ------------------------------------------------------------------
    # Canvas focus / key events
    # ------------------------------------------------------------------

    def _canvas_focus_in(self, _) -> None:
        self.mouse_keyboard_label.setEnabled(True)

    def _canvas_focus_out(self, _) -> None:
        self.mouse_keyboard_label.setEnabled(False)

    def _canvas_key_press(self, event) -> None:
        mods = QApplication.keyboardModifiers()
        key = event.key()

        # Number keys 1-6: select plotter (no modifiers)
        if mods == QtCore.Qt.NoModifier:
            _plotter_keys = {
                QtCore.Qt.Key_1: 0, QtCore.Qt.Key_2: 1, QtCore.Qt.Key_3: 2,
                QtCore.Qt.Key_4: 3, QtCore.Qt.Key_5: 4, QtCore.Qt.Key_6: 5,
            }
            if key in _plotter_keys:
                target_id = _plotter_keys[key]
                btn = self.cell_pos_button_group.button(target_id)
                if btn is not None:
                    btn.setChecked(True)
                return

        # Undo / redo
        bid = self.cell_pos_button_group.checkedId()
        if bid == 0 or key != QtCore.Qt.Key_Z:
            return
        if mods == QtCore.Qt.ControlModifier:
            if self.patch_history_idx[bid] == 0:
                return
            self.patch_history_idx[bid] -= 1
        elif mods == (QtCore.Qt.ControlModifier | QtCore.Qt.ShiftModifier):
            if self.patch_history_idx[bid] == len(self.patch_history[bid]) - 1:
                return
            self.patch_history_idx[bid] += 1
        self._load_previous_patch_pars(
            self.patch_history[bid][self.patch_history_idx[bid]]
        )

    def _load_previous_patch_pars(self, pars) -> None:
        for i, pt in enumerate(self.par_text):
            if i >= len(pars):
                return
            pt.setText(str(pars[i]))

    # ------------------------------------------------------------------
    # sync_par_area — called when plotter selection changes
    # ------------------------------------------------------------------

    def sync_par_area(self) -> None:
        if self.preview_patch is not None:
            if isinstance(self.preview_patch, list):
                for p in self.preview_patch:
                    p.remove()
            else:
                self.preview_patch.remove()
            self.canvas.update()
            self.canvas.draw()
            self.preview_patch = None

        for cid in self.mpl_cid:
            self.canvas.mpl_disconnect(cid)
        self.mpl_cid = []

        bid = self.cell_pos_button_group.checkedId()
        is_2d = self.plot_is_2d

        if bid == 0:  # everywhere
            for pt in self.par_text:
                pt.setEnabled(False)
            for pl in self.par_label:
                pl.setText("")
            self.current_plotter = (
                self.everywhere_plotter_2d if is_2d else self.everywhere_plotter_3d
            )

        else:
            self.mpl_cid.append(
                self.canvas.mpl_connect("button_release_event", self._mouse_released_cb)
            )
            if bid == 1:  # rectangle
                self.par_label[0].setText("x0")
                self.par_label[1].setText("y0")
                if is_2d:
                    self.par_label[2].setText("width")
                    self.par_label[3].setText("height")
                    self.mpl_cid += [
                        self.canvas.mpl_connect("button_press_event", self._rect_press),
                        self.canvas.mpl_connect("motion_notify_event", self._rect_motion),
                    ]
                    self.current_plotter = self.rectangle_plotter_2d
                else:
                    self.par_label[2].setText("z0")
                    self.par_label[3].setText("width")
                    self.par_label[4].setText("height")
                    self.par_label[5].setText("depth")
                    self.current_plotter = self.rectangle_plotter_3d

            elif bid == 2:  # disc
                self.par_label[0].setText("x0")
                self.par_label[1].setText("y0")
                if is_2d:
                    self.par_label[2].setText("r")
                    self.mpl_cid += [
                        self.canvas.mpl_connect("button_press_event", self._disc_press),
                        self.canvas.mpl_connect("motion_notify_event", self._disc_motion),
                    ]
                    self.current_plotter = self.disc_plotter_2d
                else:
                    self.par_label[2].setText("z0")
                    self.par_label[3].setText("r")
                    self.current_plotter = self.disc_plotter_3d

            elif bid == 3:  # annulus
                self.par_label[0].setText("x0")
                self.par_label[1].setText("y0")
                if is_2d:
                    self.par_label[2].setText("r0")
                    self.par_label[3].setText("r1")
                    self.mpl_cid += [
                        self.canvas.mpl_connect("button_press_event", self._annulus_press),
                        self.canvas.mpl_connect("motion_notify_event", self._annulus_motion),
                    ]
                    self.current_plotter = self.annulus_plotter_2d
                else:
                    self.par_label[2].setText("z0")
                    self.par_label[3].setText("r0")
                    self.par_label[4].setText("r1")
                    self.current_plotter = self.annulus_plotter_3d

            elif bid == 4:  # wedge
                self.par_label[0].setText("x0")
                self.par_label[1].setText("y0")
                if is_2d:
                    self.par_label[2].setText("r0")
                    self.par_label[3].setText("r1")
                    self.par_label[4].setText("\u03b81 (\u00b0)")
                    self.par_label[5].setText("\u03b82 (\u00b0)")
                    self.mpl_cid += [
                        self.canvas.mpl_connect("button_press_event", self._wedge_press),
                        self.canvas.mpl_connect("motion_notify_event", self._wedge_motion),
                    ]
                    self.current_plotter = self.wedge_plotter_2d
                else:
                    self.par_label[2].setText("z0")
                    self.par_label[3].setText("r0")
                    self.par_label[4].setText("r1")
                    self.par_label[5].setText("\u03b81 (\u00b0)")
                    self.par_label[6].setText("\u03b82 (\u00b0)")
                    self.par_label[7].setText("\u03d51 (\u00b0)")
                    self.par_label[8].setText("\u03d52 (\u00b0)")
                    self.current_plotter = self.wedge_plotter_3d

            elif bid == self.spatial_plotter_id:  # spatial
                self.par_label[0].setText("x0")
                self.par_label[1].setText("y0")
                if is_2d:
                    self.par_label[2].setText("width")
                    self.par_label[3].setText("height")
                else:
                    self.par_label[2].setText("z0")
                    self.par_label[3].setText("width")
                    self.par_label[4].setText("height")
                    self.par_label[5].setText("depth")
                self.mpl_cid += [
                    self.canvas.mpl_connect("button_press_event", self._rect_press),
                    self.canvas.mpl_connect("motion_notify_event", self._rect_motion),
                ]
                self.current_plotter = self.spatial_plotter

            self._activate_par_texts(bid, self.current_plotter)

        self.current_plotter()

    def _activate_par_texts(self, bid: int, plotter) -> None:
        pars = self.patch_history[bid][self.patch_history_idx[bid]]
        for i, pt in enumerate(self.par_text):
            enabled = i < len(pars)
            pt.setEnabled(enabled)
            if enabled:
                try:
                    pt.textChanged.disconnect()
                except TypeError:
                    pass
                pt.textChanged.connect(plotter)
        for i in range(len(pars), len(self.par_label)):
            self.par_label[i].setText("")
        self._load_previous_patch_pars(pars)

    # ------------------------------------------------------------------
    # Mouse event helpers
    # ------------------------------------------------------------------

    def _get_x0y0(self):
        return float(self.par_text[0].text()), float(self.par_text[1].text())

    def _set_x0y0(self, event) -> None:
        self._assign_par(event.xdata, 0)
        self._assign_par(event.ydata, 1)

    def _mouse_released_cb(self, event) -> None:
        if self.mouse_pressed:
            self._par_editing_finished(reset_cursor=False)
        self.mouse_pressed = False

    def _standard_press(self, event, fn_on_shift, modifiers=None) -> bool:
        if event.inaxes is None:
            return False
        if modifiers is None:
            modifiers = QApplication.keyboardModifiers()
        if modifiers == QtCore.Qt.ShiftModifier:
            x0y0 = self._get_x0y0()
            self.updater = lambda e: fn_on_shift(e, *x0y0)
        elif modifiers == QtCore.Qt.NoModifier:
            self.updater = lambda e: self._set_x0y0(e)
        else:
            return False
        self.updater(event)
        return True

    # Rectangle mouse
    def _rect_press(self, event) -> None:
        self.mouse_pressed = self._standard_press(event, self._rect_helper)

    def _rect_helper(self, event, xL, yL) -> None:
        xR, yR = event.xdata, event.ydata
        self._assign_par(min(xL, xR), 0)
        self._assign_par(min(yL, yR), 1)
        self._assign_par(abs(xR - xL), 2)
        self._assign_par(abs(yR - yL), 3)

    def _rect_motion(self, event) -> None:
        if event.inaxes is None or not self.mouse_pressed:
            return
        self.updater(event)

    # Disc mouse
    def _disc_press(self, event) -> None:
        self.mouse_pressed = self._standard_press(
            event, lambda e, x0, y0: self._set_radius_helper(e, x0, y0, 2)
        )

    def _set_radius_helper(self, event, x0, y0, idx) -> None:
        r = self._compute_radius(event, x0, y0)
        if r is not None:
            self._assign_par(r, idx)

    def _compute_radius(self, event, x0, y0):
        return np.sqrt((event.xdata - x0) ** 2 + (event.ydata - y0) ** 2)

    def _disc_motion(self, event) -> None:
        if event.inaxes is None or not self.mouse_pressed:
            return
        self.updater(event)

    # Annulus mouse
    def _annulus_press(self, event) -> None:
        if event.inaxes is None:
            self.mouse_pressed = False
            return
        self._annulus_setup(event, QApplication.keyboardModifiers())

    def _annulus_setup(self, event, mods) -> None:
        if mods == QtCore.Qt.NoModifier:
            self.updater = lambda e: self._set_x0y0(e)
        elif mods == QtCore.Qt.ShiftModifier:
            r0 = float(self.par_text[2].text())
            x0y0 = self._get_x0y0()
            self.updater = lambda e: self._radii_motion(e, *x0y0, r0)
        elif mods == self._lower_modifier:
            r0 = float(self.par_text[3].text())
            x0y0 = self._get_x0y0()
            self.updater = lambda e: self._radii_motion(e, *x0y0, r0)
        else:
            self.mouse_pressed = False
            return
        self.mouse_pressed = True
        self.updater(event)

    def _radii_motion(self, event, x0, y0, r0) -> None:
        r1 = self._compute_radius(event, x0, y0)
        r0, r1 = (r0, r1) if r0 < r1 else (r1, r0)
        self._assign_par(r0, 2)
        self._assign_par(r1, 3)

    def _annulus_motion(self, event) -> None:
        if event.inaxes is None or not self.mouse_pressed:
            return
        self.updater(event)

    # Wedge mouse
    def _wedge_press(self, event) -> None:
        if event.inaxes is None:
            self.mouse_pressed = False
            return
        mods = QApplication.keyboardModifiers()
        x0y0 = self._get_x0y0()
        if mods == QtCore.Qt.AltModifier:
            theta = self._get_angle(event, *x0y0)
            self._assign_par(theta, 4)
            idx = 5
        elif mods == (QtCore.Qt.AltModifier | QtCore.Qt.MetaModifier):
            idx = 4
        elif mods == (QtCore.Qt.AltModifier | QtCore.Qt.ShiftModifier):
            idx = 5
        else:
            self._annulus_setup(event, mods)
            return
        self.mouse_pressed = True
        self.updater = lambda e: self._assign_par(self._get_angle(e, *x0y0), idx)
        self.updater(event)

    def _get_angle(self, event, x0, y0) -> float:
        return 57.295779513082323 * np.arctan2(event.ydata - y0, event.xdata - x0)

    def _wedge_motion(self, event) -> None:
        if event.inaxes is None or not self.mouse_pressed:
            return
        self.updater(event)

    # ------------------------------------------------------------------
    # Geometric helpers
    # ------------------------------------------------------------------

    def _get_distance2_to_domain_2d(self, x0, y0):
        dx = (x0 - self.plot_xmin) if x0 < self.plot_xmin else (
            x0 - self.plot_xmax if x0 > self.plot_xmax else 0
        )
        dy = (y0 - self.plot_ymin) if y0 < self.plot_ymin else (
            y0 - self.plot_ymax if y0 > self.plot_ymax else 0
        )
        return dx * dx + dy * dy, dx, dy

    def _get_circumscribing_r2_2d(self, x0, y0) -> float:
        dx = self.plot_xmax - x0 if 2 * x0 < self.plot_xmin + self.plot_xmax else x0 - self.plot_xmin
        dy = self.plot_ymax - y0 if 2 * y0 < self.plot_ymin + self.plot_ymax else y0 - self.plot_ymin
        return dx * dx + dy * dy

    def _max_dist_domain_2d(self, x0, y0) -> float:
        xL, xR = self.plot_xmin, self.plot_xmax
        yL, yR = self.plot_ymin, self.plot_ymax
        dx = xL - x0 if 2 * x0 > xL + xR else x0 - xR
        dy = yL - y0 if 2 * y0 > yL + yR else y0 - yR
        return np.sqrt(dx * dx + dy * dy)

    def _get_distance2_to_domain_3d(self, x0, y0, z0):
        r2, dx, dy = self._get_distance2_to_domain_2d(x0, y0)
        dz = (z0 - self.plot_zmin) if z0 < self.plot_zmin else (
            z0 - self.plot_zmax if z0 > self.plot_zmax else 0
        )
        return r2 + dz * dz, dx, dy, dz

    def _get_circumscribing_r2_3d(self, x0, y0, z0) -> float:
        r2 = self._get_circumscribing_r2_2d(x0, y0)
        dz = self.plot_zmax - z0 if 2 * z0 < self.plot_zmin + self.plot_zmax else z0 - self.plot_zmin
        return r2 + dz * dz

    def _max_dist_domain_3d(self, x0, y0, z0) -> float:
        r = self._max_dist_domain_2d(x0, y0)
        zL, zR = self.plot_zmin, self.plot_zmax
        dz = zL - z0 if 2 * z0 > zL + zR else z0 - zR
        return np.sqrt(r * r + dz * dz)

    def _constrain_corners_2d(self, corners):
        corners = np.array([
            [min(max(x, self.plot_xmin), self.plot_xmax),
             min(max(y, self.plot_ymin), self.plot_ymax)]
            for x, y in corners
        ])
        return [corners[0, 0], corners[0, 1],
                corners[1, 0] - corners[0, 0], corners[1, 1] - corners[0, 1]]

    def _constrain_rect_3d(self):
        x0, y0, z0, w, h, d = self._get_current_pars()
        base = []
        dims = []
        for c0, l, mn, mx in zip(
            [x0, y0, z0], [w, h, d],
            [self.plot_xmin, self.plot_ymin, self.plot_zmin],
            [self.plot_xmax, self.plot_ymax, self.plot_zmax],
        ):
            cL = min(max(c0, mn), mx)
            cR = max(min(c0 + l, mx), mn)
            base.append(cL)
            dims.append(cR - cL)
        return [*base, *dims]

    # ------------------------------------------------------------------
    # Sampling functions
    # ------------------------------------------------------------------

    def _wedge_sample_2d(self, N, x0, y0, r1, r0=0.0, th_lim=(0, 2 * np.pi)):
        i_start = 0
        new_pos = np.empty((N, 3))
        new_pos[:, 2] = 0
        while i_start < N:
            if r0 == 0:
                d = r1 * np.sqrt(np.random.uniform(size=N - i_start))
            else:
                d = np.sqrt(r0 * r0 + (r1 * r1 - r0 * r0) * np.random.uniform(size=N - i_start))
            th = th_lim[0] + (th_lim[1] - th_lim[0]) * np.random.uniform(size=N - i_start)
            x = x0 + d * np.cos(th)
            y = y0 + d * np.sin(th)
            xy = np.array([
                [a, b] for a, b in zip(x, y)
                if self.plot_xmin <= a <= self.plot_xmax
                and self.plot_ymin <= b <= self.plot_ymax
            ])
            if len(xy) == 0:
                continue
            new_pos[i_start:i_start + len(xy), :2] = xy
            i_start += len(xy)
        return new_pos

    def _wedge_sample_3d(self, N, x0, y0, z0, r1, r0=0.0,
                         th_lim=(0, 2 * np.pi), phi_lim=(0, np.pi)):
        i_start = 0
        new_pos = np.empty((N, 3))
        max_fails = max_start = 100
        while i_start < N:
            if r0 == 0:
                d = r1 * np.random.uniform(size=N - i_start) ** (1 / 3)
            else:
                r03 = r0 ** 3
                d = (r03 + (r1 ** 3 - r03) * np.random.uniform(size=N - i_start)) ** (1 / 3)
            th  = th_lim[0]  + (th_lim[1]  - th_lim[0])  * np.random.uniform(size=N - i_start)
            phi = phi_lim[0] + (phi_lim[1] - phi_lim[0]) * np.random.uniform(size=N - i_start)
            xyz = np.column_stack([
                x0 + d * np.cos(th) * np.sin(phi),
                y0 + d * np.sin(th) * np.sin(phi),
                z0 + d * np.cos(phi),
            ])
            valid = np.array([
                self.plot_xmin <= p[0] <= self.plot_xmax
                and self.plot_ymin <= p[1] <= self.plot_ymax
                and self.plot_zmin <= p[2] <= self.plot_zmax
                for p in xyz
            ])
            xyz = xyz[valid]
            if len(xyz) == 0:
                max_fails -= 1
                if max_fails <= 0:
                    return np.empty((0, 3))
                continue
            max_fails = max_start
            n = min(len(xyz), N - i_start)
            new_pos[i_start:i_start + n] = xyz[:n]
            i_start += n
        return new_pos

    # ------------------------------------------------------------------
    # Plot-cell dispatch and single-type helpers
    # ------------------------------------------------------------------

    def plot_cell_pos(self) -> None:
        s = self.walkthrough.session
        self.preview_constrained_to_axes = False
        n_per_spot = self.num_box.value() if hasattr(self, "num_box") else 1

        bid = self.cell_pos_button_group.checkedId()
        if bid == self.spatial_plotter_id:
            self._plot_spatial(n_per_spot)
        else:
            for ct, cb in self.checkbox_dict.items():
                if cb.isChecked():
                    self._plot_single_cell_type(ct)

        self.canvas.update()
        self.canvas.draw()
        self.update_legend_window()

        # Enable continue when all types placed
        for cb in self.checkbox_dict.values():
            if cb.isEnabled():
                return
        self.continue_to_write_button.setEnabled(True)

    def _plot_spatial(self, n_per_spot: int) -> None:
        s = self.walkthrough.session
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return

        if self.plot_is_2d:
            x0, y0, width, height = self.current_pars
        else:
            x0, y0, z0, width, height, depth = self.current_pars

        if s.perform_spot_deconvolution:
            self._plot_spot_deconvolution(x0, y0, width, height, n_per_spot)
        else:
            for ct, cb in self.checkbox_dict.items():
                if not cb.isChecked():
                    continue
                mask = [ctn == ct for ctn in s.cell_types_final]
                cell_r = np.sqrt(self.cell_type_micron2_area_dict[ct] / np.pi)
                coords = np.hstack((
                    self.spatial_base_coords[mask, :2] * [width, height] + [x0, y0],
                    np.zeros((sum(mask), 1)),
                ))
                inbounds = [
                    self.plot_xmin <= c[0] <= self.plot_xmax
                    and self.plot_ymin <= c[1] <= self.plot_ymax
                    for c in coords
                ]
                if not self.plot_is_2d:
                    coords[:, 2] = self.spatial_base_coords[mask, 2] * depth + z0
                    inbounds = [
                        ib and self.plot_zmin <= c[2] <= self.plot_zmax
                        for ib, c in zip(inbounds, coords)
                    ]
                coords = coords[inbounds]

                if n_per_spot == 1:
                    s.coords_by_type[ct] = np.vstack((s.coords_by_type[ct], coords))
                    if self.plot_is_2d:
                        self.circles(coords, s=cell_r, color=self.color_by_celltype[ct],
                                     edgecolor="none", linewidth=0.5, alpha=self.alpha_value)
                        self.legend_artists.append(
                            Patch(facecolor=self.color_by_celltype[ct], edgecolor="none")
                        )
                    else:
                        self.ax0.scatter(
                            coords[:, 0], coords[:, 1], coords[:, 2],
                            s=8.0, color=self.color_by_celltype[ct], alpha=self.alpha_value
                        )
                        self.legend_artists.append(
                            plt.Line2D([], [], marker="o", color=self.color_by_celltype[ct],
                                       markersize=8.0)
                        )
                else:
                    r = cell_r * np.sqrt(n_per_spot)
                    all_new = np.empty((0, 3))
                    for cc in coords:
                        all_new = np.vstack((all_new, self._wedge_sample_2d(
                            n_per_spot, cc[0], cc[1], r
                        )))
                    s.coords_by_type[ct] = np.vstack((s.coords_by_type[ct], all_new))
                    self.circles(all_new, s=cell_r, color=self.color_by_celltype[ct],
                                 edgecolor="none", linewidth=0.5, alpha=self.alpha_value)
                    self.legend_artists.append(
                        Patch(facecolor=self.color_by_celltype[ct], edgecolor="none")
                    )

                self.legend_labels.append(ct)
                cb.setEnabled(False)
                cb.setChecked(False)
                self.undo_button[ct].setEnabled(True)
                self.undo_all_button.setEnabled(True)
                self.plot_cells_button.setEnabled(False)

    def _plot_spot_deconvolution(self, x0, y0, width, height, n_per_spot: int) -> None:
        s = self.walkthrough.session
        selected = {ct for ct, cb in self.checkbox_dict.items() if cb.isChecked()}
        cell_r = np.sqrt((((9 * np.pi * 2494 ** 2) / 16) ** (1.0 / 3)) / np.pi)
        coords_all = np.hstack((
            self.spatial_base_coords[:, :2] * [width, height] + [x0, y0],
            np.zeros((self.spatial_base_coords.shape[0], 1)),
        ))

        for idx, pos in enumerate(coords_all):
            probs = {
                k: v for k, v in s.cell_prob_feature_dicts[idx].items()
                if k in selected
            }
            if not probs:
                continue

            # Equal-proportions apportionment
            priorities = {k: v / np.sqrt(2) for k, v in probs.items()}
            spot_counts: dict[str, int] = {k: 0 for k in probs}
            for _ in range(n_per_spot):
                nk = max(priorities, key=priorities.get)
                spot_counts[nk] += 1
                priorities[nk] = probs[nk] / np.sqrt(
                    (spot_counts[nk] + 1) * (spot_counts[nk] + 2)
                )

            color_seq: list[str] = []
            type_seq:  list[str] = []
            for pf, cnt in spot_counts.items():
                color_seq.extend([self.color_by_celltype[pf]] * cnt)
                type_seq.extend([pf] * cnt)

            if not color_seq:
                color_seq = ["gray"] * n_per_spot
                type_seq  = ["Unknown"] * n_per_spot
            else:
                while len(color_seq) < n_per_spot:
                    color_seq.append(color_seq[0])
                    type_seq.append(type_seq[0])
            color_seq = color_seq[:n_per_spot]
            type_seq  = type_seq[:n_per_spot]

            if n_per_spot == 1:
                ct = type_seq[0]
                coord = np.array(pos).reshape(1, 3)
                s.coords_by_type.setdefault(ct, np.empty((0, 3)))
                s.coords_by_type[ct] = np.vstack((s.coords_by_type[ct], coord))
                self.circles(coord, s=cell_r, color=color_seq[0],
                             edgecolor="black", linewidth=0.5, alpha=self.alpha_value)
                s.plotted_cell_types_per_spot.append({
                    "spot_coords": pos,
                    "cell_types": type_seq,
                    "sub_spots": [pos],
                })
            else:
                r = cell_r * np.sqrt(n_per_spot)
                sub_spots = self._wedge_sample_2d(n_per_spot, pos[0], pos[1], r)
                for i, color in enumerate(color_seq):
                    self.circles(sub_spots[i:i+1], s=cell_r, color=color,
                                 edgecolor="none", linewidth=0.5, alpha=self.alpha_value)
                s.plotted_cell_types_per_spot.append({
                    "spot_coords": pos,
                    "cell_types": type_seq,
                    "sub_spots": sub_spots,
                })

        for ct in selected:
            cb = self.checkbox_dict.get(ct)
            if cb is not None:
                cb.setChecked(False)
                cb.setEnabled(False)
            self.undo_button[ct].setEnabled(True)

        for ct in selected:
            self.legend_artists.append(
                Patch(facecolor=self.color_by_celltype[ct], edgecolor="black")
            )
            self.legend_labels.append(ct)

        self.undo_all_button.setEnabled(True)
        self.plot_cells_button.setEnabled(False)

    def _plot_single_cell_type(self, ct: str) -> None:
        if self.plot_is_2d:
            self._plot_single_2d(ct)
        else:
            self._plot_single_3d(ct)

    def _plot_single_2d(self, ct: str) -> None:
        s = self.walkthrough.session
        N = s.cell_counts[ct]
        plotter = self.current_plotter
        if plotter in (self.everywhere_plotter_2d, self.rectangle_plotter_2d):
            new_pos = self._rectangle_positions_2d(N)
        elif plotter == self.disc_plotter_2d:
            new_pos = self._disc_positions_2d(N)
        elif plotter == self.annulus_plotter_2d:
            new_pos = self._annulus_positions_2d(N)
        elif plotter == self.wedge_plotter_2d:
            new_pos = self._wedge_positions_2d(N)
        else:
            return

        s.coords_by_type[ct] = np.append(s.coords_by_type[ct], new_pos, axis=0)
        vol = (s.cell_volume or {}).get(ct, 2494.0)
        r = (0.75 * vol / np.pi) ** (1 / 3)
        self.circles(new_pos, s=r, color=self.color_by_celltype[ct],
                     edgecolor="none", linewidth=0.5, alpha=self.alpha_value)
        self.legend_artists.append(
            Patch(facecolor=self.color_by_celltype[ct], edgecolor="none")
        )
        self.legend_labels.append(ct)
        self.checkbox_dict[ct].setEnabled(False)
        self.checkbox_dict[ct].setChecked(False)
        self.undo_button[ct].setEnabled(True)
        self.undo_all_button.setEnabled(True)
        self.plot_cells_button.setEnabled(False)

    def _plot_single_3d(self, ct: str) -> None:
        s = self.walkthrough.session
        N = s.cell_counts[ct]
        plotter = self.current_plotter
        if plotter == self.everywhere_plotter_3d:
            new_pos = _random_rectangle_3d(
                self.plot_xmin, self.plot_ymin, self.plot_zmin,
                self.plot_dx, self.plot_dy, self.plot_dz, N
            )
        elif plotter == self.rectangle_plotter_3d:
            x0, y0, z0, w, h, d = self._constrain_rect_3d()
            new_pos = _random_rectangle_3d(x0, y0, z0, w, h, d, N)
        elif plotter == self.disc_plotter_3d:
            new_pos = self._disc_positions_3d(N)
        elif plotter == self.annulus_plotter_3d:
            new_pos = self._annulus_positions_3d(N)
        elif plotter == self.wedge_plotter_3d:
            new_pos = self._wedge_positions_3d(N)
        else:
            return

        if new_pos.shape[0] == 0:
            return
        s.coords_by_type[ct] = np.append(s.coords_by_type[ct], new_pos, axis=0)
        vol = (s.cell_volume or {}).get(ct, 2494.0)
        self.ax0.scatter(
            new_pos[:, 0], new_pos[:, 1], new_pos[:, 2],
            s=(0.75 * vol / np.pi) ** (1 / 3),
            color=self.color_by_celltype[ct], alpha=self.alpha_value,
        )
        self.legend_artists.append(
            plt.Line2D([], [], marker="o", color=self.color_by_celltype[ct],
                       markersize=8.0)
        )
        self.legend_labels.append(ct)
        self.checkbox_dict[ct].setEnabled(False)
        self.checkbox_dict[ct].setChecked(False)
        self.undo_button[ct].setEnabled(True)
        self.undo_all_button.setEnabled(True)
        self.plot_cells_button.setEnabled(False)

    # ------------------------------------------------------------------
    # 2D plotters
    # ------------------------------------------------------------------

    def complete_plotter(self, valid: bool = True) -> None:
        self.plot_cells_button.setEnabled(valid and self.is_any_cell_type_checked())
        self.canvas.update()
        self.canvas.draw()

    def everywhere_plotter_2d(self) -> None:
        if self.preview_patch is None:
            self.preview_patch = self.ax0.add_patch(
                Rectangle((self.plot_xmin, self.plot_ymin),
                           self.plot_dx, self.plot_dy, alpha=0.2)
            )
        else:
            self.preview_patch.set_bounds(
                self.plot_xmin, self.plot_ymin, self.plot_dx, self.plot_dy
            )
        self.complete_plotter()

    def rectangle_plotter_2d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, w, h = self.current_pars
        if self.preview_patch is None:
            self.preview_patch = self.ax0.add_patch(
                Rectangle((x0, y0), w, h, alpha=0.2)
            )
        else:
            self.preview_patch.set_bounds(x0, y0, w, h)
        valid = (x0 < self.plot_xmax and x0 + w > self.plot_xmin
                 and y0 < self.plot_ymax and y0 + h > self.plot_ymin)
        self.complete_plotter(valid)

    def _rectangle_positions_2d(self, N: int) -> np.ndarray:
        x0, y0 = self.preview_patch.get_xy()
        w, h = self.preview_patch.get_width(), self.preview_patch.get_height()
        if not self.preview_constrained_to_axes:
            x0, y0, w, h = self._constrain_corners_2d(
                self.preview_patch.get_corners()[[0, 2]]
            )
            self.preview_patch.set_bounds(x0, y0, w, h)
            self.preview_constrained_to_axes = True
        x = x0 + w * np.random.uniform(size=(N, 1))
        y = y0 + h * np.random.uniform(size=(N, 1))
        return np.concatenate([x, y, np.zeros((N, 1))], axis=1)

    def disc_plotter_2d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, r = self.current_pars
        if self.preview_patch is None:
            self.preview_patch = self.ax0.add_patch(Circle((x0, y0), r, alpha=0.2))
        else:
            self.preview_patch.set(center=(x0, y0), radius=r)
        r2 = self._get_distance2_to_domain_2d(x0, y0)[0]
        self.complete_plotter(r2 < r * r)

    def _disc_positions_2d(self, N: int) -> np.ndarray:
        x0, y0 = self.preview_patch.get_center()
        r = self.preview_patch.get_radius()
        if not self.preview_constrained_to_axes:
            r = min(r, self._max_dist_domain_2d(x0, y0))
            self.preview_patch.set_radius(r)
            self.preview_constrained_to_axes = True
        return self._wedge_sample_2d(N, x0, y0, r)

    def annulus_plotter_2d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, r0, r1 = self.current_pars
        if r1 == 0 or r1 < r0:
            if self.preview_patch:
                self.preview_patch.remove()
                self.canvas.update()
                self.canvas.draw()
                self.preview_patch = None
            self.plot_cells_button.setEnabled(False)
            return
        width = r1 - r0
        try:
            self._annulus_setter_2d(x0, y0, r1, width)
        except Exception:
            self._annulus_setter_2d(x0, y0, r1, width * (1 - np.finfo(float).eps))
        r2 = self._get_distance2_to_domain_2d(x0, y0)[0]
        cr2 = self._get_circumscribing_r2_2d(x0, y0)
        self.complete_plotter(r2 < r1 * r1 and cr2 > r0 * r0)

    def _annulus_setter_2d(self, x0, y0, r1, width) -> None:
        if self.preview_patch is None:
            self.preview_patch = self.ax0.add_patch(
                Annulus((x0, y0), r1, width, alpha=0.2)
            )
        else:
            self.preview_patch.set(center=(x0, y0), radii=r1, width=width)

    def _annulus_positions_2d(self, N: int) -> np.ndarray:
        x0, y0 = self.preview_patch.get_center()
        r1 = self.preview_patch.get_radii()[0]
        r0 = r1 - self.preview_patch.get_width()
        if not self.preview_constrained_to_axes:
            r1 = min(r1, self._max_dist_domain_2d(x0, y0))
            r0 = max(r0, np.sqrt(self._get_distance2_to_domain_2d(x0, y0)[0]))
            self.preview_patch.set_radii(r1)
            self.preview_patch.set_width(r1 - r0)
            self.preview_constrained_to_axes = True
        return self._wedge_sample_2d(N, x0, y0, r1, r0=r0)

    def wedge_plotter_2d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, r0, r1, th1, th2 = self.current_pars
        if r1 < r0:
            if self.preview_patch:
                self.preview_patch.remove()
                self.canvas.update()
                self.canvas.draw()
                self.preview_patch = None
            self.plot_cells_button.setEnabled(False)
            return
        if self.preview_patch is None:
            self.preview_patch = self.ax0.add_patch(
                Wedge((x0, y0), r1, th1, th2, width=r1 - r0, alpha=0.2)
            )
        else:
            self.preview_patch.set(
                center=(x0, y0), radius=r1, theta1=th1, theta2=th2, width=r1 - r0
            )
        r2, dx, dy = self._get_distance2_to_domain_2d(x0, y0)
        cr2 = self._get_circumscribing_r2_2d(x0, y0)
        valid = (r2 < r1 * r1 and cr2 > r0 * r0
                 and _wedge_in_domain_2d(
                     self, x0, y0, r0, r1, th1, th2, dx, dy, r2
                 ))
        self.complete_plotter(valid)

    def _wedge_positions_2d(self, N: int) -> np.ndarray:
        x0, y0 = self.preview_patch.center
        r1 = self.preview_patch.r
        r0 = r1 - self.preview_patch.width
        th1, th2 = self.preview_patch.theta1, self.preview_patch.theta2
        if not self.preview_constrained_to_axes:
            r1 = min(r1, self._max_dist_domain_2d(x0, y0))
            if th2 != th1:
                if ((th2 - th1) % 360) == 0:
                    th2 = th1 + 360
                else:
                    th2 -= 360 * ((th2 - th1) // 360)
            r0 = max(r0, np.sqrt(self._get_distance2_to_domain_2d(x0, y0)[0]))
            self.preview_patch.set(
                center=(x0, y0), radius=r1, theta1=th1, theta2=th2, width=r1 - r0
            )
            self.preview_constrained_to_axes = True
        return self._wedge_sample_2d(
            N, x0, y0, r1, r0=r0,
            th_lim=(th1 * 0.017453292519943, th2 * 0.017453292519943)
        )

    # ------------------------------------------------------------------
    # 3D plotters
    # ------------------------------------------------------------------

    def everywhere_plotter_3d(self) -> None:
        faces = _rectangular_prism_faces(
            self.plot_xmin, self.plot_xmax,
            self.plot_ymin, self.plot_ymax,
            self.plot_zmin, self.plot_zmax,
        )
        self.preview_patch = self.ax0.add_collection3d(
            Poly3DCollection(faces, alpha=0.2, facecolors="gray",
                             linewidths=1, edgecolors="black")
        )
        self.complete_plotter()

    def rectangle_plotter_3d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, z0, w, h, d = self.current_pars
        faces = _rectangular_prism_faces(x0, x0+w, y0, y0+h, z0, z0+d)
        if self.preview_patch is None:
            self.preview_patch = self.ax0.add_collection3d(
                Poly3DCollection(faces, alpha=0.2, facecolors="gray",
                                 linewidths=1, edgecolors="black")
            )
        else:
            self.preview_patch.set_verts(faces)
        valid = (x0 < self.plot_xmax and x0+w > self.plot_xmin
                 and y0 < self.plot_ymax and y0+h > self.plot_ymin
                 and z0 < self.plot_zmax and z0+d > self.plot_zmin)
        self.complete_plotter(valid)

    def disc_plotter_3d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, z0, r = self.current_pars
        self._annulus_setter_3d(x0, y0, z0, r)
        r2 = self._get_distance2_to_domain_3d(x0, y0, z0)[0]
        self.complete_plotter(r2 < r * r)

    def _annulus_setter_3d(self, x0, y0, z0, r1, width=None) -> None:
        if width is None:
            width = r1
        self._plot_shell_surfaces(x0, y0, z0, r1, r1 - width)

    def _plot_shell_surfaces(self, x0, y0, z0, r1, r0=0,
                             th_lim=(0, 2*np.pi), phi_lim=(0, np.pi)) -> None:
        u = np.linspace(*th_lim, 100)
        v = np.linspace(*phi_lim, 100)
        xo = r1 * np.outer(np.cos(u), np.sin(v)) + x0
        yo = r1 * np.outer(np.sin(u), np.sin(v)) + y0
        zo = r1 * np.outer(np.ones_like(u), np.cos(v)) + z0
        if self.preview_patch is not None:
            for p in self.preview_patch:
                p.remove()
        self.preview_patch = [self.ax0.plot_surface(xo, yo, zo, color="gray", alpha=0.5)]
        if r0 > 0:
            xi = r0 * np.outer(np.cos(u), np.sin(v)) + x0
            yi = r0 * np.outer(np.sin(u), np.sin(v)) + y0
            zi = r0 * np.outer(np.ones_like(u), np.cos(v)) + z0
            self.preview_patch.append(
                self.ax0.plot_surface(xi, yi, zi, color="gray", alpha=0.2)
            )

    def annulus_plotter_3d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, z0, r0, r1 = self.current_pars
        if r1 == 0 or r1 < r0:
            if self.preview_patch:
                for p in self.preview_patch:
                    p.remove()
                self.canvas.update()
                self.canvas.draw()
                self.preview_patch = None
            self.plot_cells_button.setEnabled(False)
            return
        w = r1 - r0
        try:
            self._annulus_setter_3d(x0, y0, z0, r1, w)
        except Exception:
            self._annulus_setter_3d(x0, y0, z0, r1, w * (1 - np.finfo(float).eps))
        r2 = self._get_distance2_to_domain_3d(x0, y0, z0)[0]
        cr2 = self._get_circumscribing_r2_3d(x0, y0, z0)
        self.complete_plotter(r2 < r1 * r1 and cr2 > r0 * r0)

    def _annulus_positions_3d(self, N: int) -> np.ndarray:
        x0, y0, z0, r0, r1 = self._get_current_pars()
        r1 = min(r1, self._max_dist_domain_3d(x0, y0, z0))
        r0 = max(r0, np.sqrt(self._get_distance2_to_domain_3d(x0, y0, z0)[0]))
        return self._wedge_sample_3d(N, x0, y0, z0, r1, r0=r0)

    def wedge_plotter_3d(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable:
            return
        x0, y0, z0, r0, r1, th1, th2, phi1, phi2 = self.current_pars
        if r1 < r0:
            if self.preview_patch:
                for p in self.preview_patch:
                    p.remove()
                self.canvas.update()
                self.canvas.draw()
                self.preview_patch = None
            self.plot_cells_button.setEnabled(False)
            return
        self._plot_shell_surfaces(
            x0, y0, z0, r1, r0=r0,
            th_lim=(th1 * np.pi/180, th2 * np.pi/180),
            phi_lim=(phi1 * np.pi/180, phi2 * np.pi/180),
        )
        r2 = self._get_distance2_to_domain_3d(x0, y0, z0)[0]
        cr2 = self._get_circumscribing_r2_3d(x0, y0, z0)
        self.complete_plotter(r2 < r1 * r1 and cr2 > r0 * r0)

    def _wedge_positions_3d(self, N: int) -> np.ndarray:
        x0, y0, z0, r0, r1, th1, th2, phi1, phi2 = self._get_current_pars()
        r1 = min(r1, self._max_dist_domain_3d(x0, y0, z0))
        r0 = max(r0, np.sqrt(self._get_distance2_to_domain_3d(x0, y0, z0)[0]))
        if th2 != th1:
            if ((th2 - th1) % 360) == 0:
                th2 = th1 + 360
            else:
                th2 -= 360 * ((th2 - th1) // 360)
        if phi1 > phi2:
            phi1, phi2 = phi2, phi1
        return self._wedge_sample_3d(
            N, x0, y0, z0, r1, r0=r0,
            th_lim=(th1 * 0.017453292519943, th2 * 0.017453292519943),
            phi_lim=(phi1 * 0.017453292519943, phi2 * 0.017453292519943),
        )

    def _disc_positions_3d(self, N: int) -> np.ndarray:
        x0, y0, z0, r = self._get_current_pars()
        r = min(r, self._max_dist_domain_3d(x0, y0, z0))
        return self._wedge_sample_3d(N, x0, y0, z0, r)

    # ------------------------------------------------------------------
    # Spatial plotter
    # ------------------------------------------------------------------

    def spatial_plotter(self) -> None:
        self._read_par_texts()
        if not self.current_pars_acceptable or not self.current_pars:
            return
        if self.plot_is_2d:
            x0, y0, width, height = self.current_pars
            if self.preview_patch is None:
                self._initial_x0, self._initial_y0 = x0, y0
                self._initial_w, self._initial_h = width, height
                coords = self.spatial_base_coords * [width, height] + [x0, y0]
                sz = (getattr(self, "_deconvolution_scatter_size", None)
                      if self.walkthrough.session.perform_spot_deconvolution
                      else getattr(self, "scatter_sizes", 1.0))
                self.preview_patch = self.ax0.scatter(
                    coords[:, 0], coords[:, 1], sz, "gray", alpha=0.5,
                    edgecolors="none", linewidths=0.0
                )
                self._initial_offsets = self.preview_patch.get_offsets()
            else:
                offset = (self._initial_offsets
                          + self.spatial_base_coords * [width - self._initial_w,
                                                         height - self._initial_h]
                          + [x0 - self._initial_x0, y0 - self._initial_y0])
                self.preview_patch.set_offsets(offset)
            valid = (x0 < self.plot_xmax and x0 + width  > self.plot_xmin
                     and y0 < self.plot_ymax and y0 + height > self.plot_ymin)
        else:
            x0, y0, z0, width, height, depth = self.current_pars
            valid = (x0 < self.plot_xmax and x0 + width  > self.plot_xmin
                     and y0 < self.plot_ymax and y0 + height > self.plot_ymin
                     and z0 < self.plot_zmax and z0 + depth  > self.plot_zmin)
        self.complete_plotter(valid)

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------

    def update_legend_window(self) -> None:
        hidden = (self.legend_window is None or self.legend_window.isHidden())
        if self.legend_window is not None:
            self.legend_window.close()
        self.legend_window = LegendWindow(
            self,
            legend_artists=self.legend_artists,
            legend_labels=self.legend_labels,
            legend_title="Cell Types",
        )
        if not hidden:
            self.legend_window.show()

    def _show_legend_cb(self) -> None:
        self.legend_window.show()

    def _toggle_legend(self) -> None:
        """Ctrl+L: toggle legend visibility."""
        if hasattr(self, "legend_window") and self.legend_window is not None:
            if self.legend_window.isVisible():
                self.legend_window.hide()
                return
        self._show_legend_cb()

    def _enter_shortcut_cb(self) -> None:
        """Enter key: trigger Plot if enabled."""
        if self.plot_cells_button.isEnabled():
            self.plot_cell_pos()

    # ------------------------------------------------------------------
    # Domain editor
    # ------------------------------------------------------------------

    def _open_domain_editor(self) -> None:
        """Manually open the domain editor dialog (no mismatch header)."""
        s = self.walkthrough.session
        data_d = s.data_domain or s.preferred_domain

        # Record baseline domain for change detection
        old_domain = s.effective_domain
        old_is_2d = self.plot_is_2d

        dlg = DomainEditorDialog(
            self, data_d, s.preferred_domain,
            context_message="",
            initial_domain=s.user_domain,  # show prior values if already set
            host_name=s.biwt_input.host_name,
        )
        if dlg.exec_() == QDialog.Accepted:
            user_domain, auto_scale = dlg.result()
            s.user_domain = user_domain
            s.auto_scale_to_domain = auto_scale
            self._get_domain_dims(s)

            # Apply domain changes to plot (handles 2D/3D switch, axes reset, etc.)
            self._apply_domain_change_and_redraw(old_is_2d)

            # Check if domain actually changed
            new_domain = s.effective_domain
            if new_domain != old_domain:
                # Domain changed; check for out-of-bounds cells
                out_of_bounds = self._check_out_of_bounds_cells(new_domain)
                if out_of_bounds:
                    should_proceed = self._show_out_of_bounds_warning(out_of_bounds)
                    if should_proceed:
                        self._undo_all_cb()
        s.domain_accepted = True

    # ------------------------------------------------------------------
    # Domain change helpers
    # ------------------------------------------------------------------

    def _apply_domain_change_and_redraw(self, old_is_2d: bool) -> None:
        """Reset plot state after domain dimensions may have changed.

        Handles projection switch (2D/3D), axes reset, and scatter recompute.
        Must be called after domain values have been synced via _get_domain_dims().

        Args:
            old_is_2d: Whether plot was 2D before domain change.
        """
        if self.plot_is_2d != old_is_2d:
            # Dimensionality changed; recreate subplot, patch history, labels, and par area
            self.figure.clear()
            proj = None if self.plot_is_2d else "3d"
            self.ax0 = self.figure.add_subplot(111, adjustable="box", projection=proj)
            self._create_patch_history()
            self._update_plotter_button_labels()
            self._rebuild_par_area()
        else:
            # Still 2D or still 3D; just reset current axes
            self.ax0.cla()
            # Refresh spatial plotter defaults for the new domain, but only if
            # the user hasn't manually modified those parameters yet (history length == 1).
            if (hasattr(self, "patch_history") and len(self.patch_history) > 5
                    and len(self.patch_history[5]) == 1):
                self.patch_history[5] = [self._default_spatial_pars()]
                self.patch_history_idx[5] = 0

        # Domain area changed → confluence-based cell counts are stale.
        self.walkthrough.session.cell_counts_confirmed = False

        # Replot all previously placed cells (restores visual state and legend);
        # also re-enables checkboxes for any cell types that have no placed cells.
        self._replot_all_after_undo()
        self._recompute_scatter_sizes()
        # Restore Continue button if all cell types were already placed.
        if all(not cb.isEnabled() for cb in self.checkbox_dict.values()):
            self.continue_to_write_button.setEnabled(True)
        self.canvas.update()
        self.canvas.draw()

    def _check_out_of_bounds_cells(self, new_domain) -> dict[str, int] | None:
        """Check if any placed cells fall outside new domain.

        Scans s.coords_by_type to find cells that would spawn outside the
        new domain bounds. Accounts for 2D vs 3D dimensionality.

        Args:
            new_domain: DomainSpec with new bounds (xmin/max, ymin/max, zmin/max, is_2d).

        Returns:
            Dict of {cell_type: count} for out-of-bounds cells, or None if all OK.
        """
        s = self.walkthrough.session
        out_of_bounds = {}

        for ct, coords in s.coords_by_type.items():
            if coords.shape[0] == 0:
                continue

            # Check bounds for 2D or 3D coords
            mask = ((coords[:, 0] < new_domain.xmin) | (coords[:, 0] > new_domain.xmax) |
                    (coords[:, 1] < new_domain.ymin) | (coords[:, 1] > new_domain.ymax))

            if not new_domain.is_2d:
                mask |= ((coords[:, 2] < new_domain.zmin) | (coords[:, 2] > new_domain.zmax))

            if mask.any():
                out_of_bounds[ct] = int(mask.sum())

        return out_of_bounds if out_of_bounds else None

    def _show_out_of_bounds_warning(self, out_of_bounds: dict[str, int]) -> bool:
        """Show warning dialog for out-of-bounds cells and return user choice.

        Displays which cell types have cells outside the new domain and indicates
        that either the cells should be undone or the domain adjusted. Returns
        True if user chooses to proceed anyway (and trigger undo), False if cancel.

        Args:
            out_of_bounds: Dict of {cell_type: count} from _check_out_of_bounds_cells().

        Returns:
            True if user clicked "Proceed & Undo All"; False for "Cancel".
        """
        summary = "\n".join(
            f"  \u2022 {ct}: {count} cell(s) outside new domain"
            for ct, count in sorted(out_of_bounds.items())
        )
        msg = (
            f"The new domain excludes some placed cells:\n\n"
            f"{summary}\n\n"
            f"These cells would initialize outside the simulation domain.\n"
            f"You can clear all placed cells now, or keep them as-is."
        )

        box = QMessageBox(QMessageBox.Warning, "Out-of-Bounds Cells", msg, parent=self)
        clear_btn = box.addButton("Clear All Placed Cells", QMessageBox.AcceptRole)
        keep_btn  = box.addButton("Keep Placed Cells",      QMessageBox.RejectRole)
        box.setDefaultButton(keep_btn)
        box.exec_()

        return box.clickedButton() is clear_btn

    # ------------------------------------------------------------------
    # circles() helper — scatter with radii in data units
    # ------------------------------------------------------------------

    def circles(self, pos, s, c="b", vmin=None, vmax=None, **kwargs):
        """Draw circles with radius *s* in data coordinates.
        Mirrors the same-named function from the original ``biwt_tab.py``.
        """
        x, y = pos.T[:2]
        if np.isscalar(c):
            kwargs.setdefault("color", c)
            c = None
        for alias, full in [("fc", "facecolor"), ("ec", "edgecolor"),
                             ("ls", "linestyle"), ("lw", "linewidth")]:
            if alias in kwargs:
                kwargs.setdefault(full, kwargs.pop(alias))

        zipped = np.broadcast(x, y, s)
        patches = [Circle((x_, y_), s_) for x_, y_, s_ in zipped]
        coll = PatchCollection(patches, **kwargs)
        if c is not None:
            c = np.broadcast_to(c, zipped.shape).ravel()
            coll.set_array(c)
            coll.set_clim(vmin, vmax)
        self.ax0.add_collection(coll)
        if c is not None:
            self.ax0.sci(coll)
        return coll

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):  # noqa: N802
        if hasattr(self, "legend_window") and self.legend_window is not None:
            self.legend_window.close()
        if hasattr(self, "figure"):
            self.figure.clear()
        super().closeEvent(event)


# ---------------------------------------------------------------------------
# Module-level geometry helpers (standalone functions)
# ---------------------------------------------------------------------------

def _random_rectangle_3d(x0, y0, z0, w, h, d, N: int) -> np.ndarray:
    return np.concatenate([
        x0 + w * np.random.uniform(size=(N, 1)),
        y0 + h * np.random.uniform(size=(N, 1)),
        z0 + d * np.random.uniform(size=(N, 1)),
    ], axis=1)


def _rectangular_prism_faces(x_min, x_max, y_min, y_max, z_min, z_max):
    c = np.array([
        [x_min, y_min, z_min], [x_max, y_min, z_min],
        [x_max, y_max, z_min], [x_min, y_max, z_min],
        [x_min, y_min, z_max], [x_max, y_min, z_max],
        [x_max, y_max, z_max], [x_min, y_max, z_max],
    ])
    return [
        [c[0], c[1], c[2], c[3]], [c[4], c[5], c[6], c[7]],
        [c[0], c[1], c[5], c[4]], [c[2], c[3], c[7], c[6]],
        [c[0], c[3], c[7], c[4]], [c[1], c[2], c[6], c[5]],
    ]


def _normalize_thetas(th1, th2):
    th1 = th1 % 360
    th1 = th1 - 360 if th1 >= 180 else th1
    th2 -= 360 * ((th2 - th1) // 360)
    return th1, th2


def _wedge_in_domain_2d(plot_win, x0, y0, r0, r1, th1, th2, dx, dy, r2) -> bool:
    """Simplified wedge-in-domain test; returns True if any part of the wedge
    could overlap the simulation domain."""
    # For now use a conservative approximation: check if the outer disc
    # reaches the domain at all.
    return r2 < r1 * r1
