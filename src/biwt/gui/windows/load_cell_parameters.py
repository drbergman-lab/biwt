"""Step: Map each final cell type to a PhysiCell cell-parameter template."""

from __future__ import annotations
import os
from collections import defaultdict, Counter
from typing import Optional

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFileDialog,
    QScrollArea, QWidget, QMessageBox, QPushButton,
    QButtonGroup, QRadioButton, QComboBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItem, QStandardItemModel, QColor

from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import GoBackButton, ContinueButton
from biwt.core.parameters import cell_templates as cell_params

_BUILTIN_PATH = "<built-in>"


def _minimal_unique_suffixes(filepaths: list[str]) -> dict[str, str]:
    """Return the shortest path suffix that uniquely identifies each filepath.

    ``'<built-in>'`` is always labelled ``'built-in'``.  File paths are
    shortened to the minimal trailing suffix (basename, then parent/basename,
    etc.) that avoids collisions within this group.
    """
    result: dict[str, str] = {}
    file_fps = [fp for fp in filepaths if fp != _BUILTIN_PATH]

    if _BUILTIN_PATH in filepaths:
        result[_BUILTIN_PATH] = "built-in"

    if not file_fps:
        return result

    parts = {fp: list(reversed(fp.replace("\\", "/").split("/"))) for fp in file_fps}
    max_depth = max(len(p) for p in parts.values())

    for depth in range(1, max_depth + 1):
        candidate = {fp: "/".join(reversed(ps[:depth])) for fp, ps in parts.items()}
        if max(Counter(candidate.values()).values()) == 1:
            result.update(candidate)
            return result

    result.update({fp: fp for fp in file_fps})  # fallback: full path
    return result


class LoadCellParametersWindow(BiwinformaticsWalkthroughWindow):
    """Let the user map each final cell type to an XML parameter template.

    The template database is keyed by ``(name, filepath)`` so identically
    named templates from different sources coexist without overwriting each
    other.  Radio buttons let the user switch between two display modes:

    * **By Name** — all templates alphabetically; source shown in parentheses
      using the minimal path suffix that distinguishes same-name entries.
    * **By Source** — templates grouped under bold section headers per file;
      within each section, entries are listed by name.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        # --- template database: (name, filepath) → xml_string ----------------
        self._template_db: dict[tuple[str, str], str] = {}
        for name, xml in cell_params.CELL_TEMPLATES.items():
            self._template_db[(name, _BUILTIN_PATH)] = xml
        for path in s.biwt_input.extra_cell_template_paths:
            self._load_template_file(path)

        # Sort mode: True = by name, False = by source
        self._sort_by_name: bool = True

        # Shared model and dropdowns
        self._model = QStandardItemModel(self)
        self._dropdowns: list[tuple[str, QComboBox]] = []

        # --- layout -----------------------------------------------------------
        vbox = QVBoxLayout()

        # Experimental banner
        banner = QLabel(
            "\u26a0\u2002Experimental \u2014 These templates are PhysiCell-specific "
            "and may change in future releases."
        )
        banner.setStyleSheet(
            "background-color: #FFF3CD; color: #856404; "
            "padding: 6px; border: 1px solid #FFEEBA; font-weight: bold;"
        )
        banner.setWordWrap(True)
        vbox.addWidget(banner)

        # Sort radio buttons
        sort_group = QButtonGroup(self)
        by_name_rb  = QRadioButton("By Name")
        by_src_rb   = QRadioButton("By Source")
        by_name_rb.setChecked(True)
        sort_group.addButton(by_name_rb, 0)
        sort_group.addButton(by_src_rb,  1)
        sort_group.idToggled.connect(self._sort_toggled)
        hbox_sort = QHBoxLayout()
        hbox_sort.addWidget(QLabel("Sort templates:"))
        hbox_sort.addWidget(by_name_rb)
        hbox_sort.addWidget(by_src_rb)
        hbox_sort.addStretch()
        vbox.addLayout(hbox_sort)

        vbox.addWidget(QLabel("Select parameter templates for your cell types:"))

        # Scrollable cell-type → dropdown rows
        inner = QVBoxLayout()
        for cell_type in s.cell_types_list_final:
            hbox = QHBoxLayout()
            hbox.addWidget(QLabel(f"{cell_type} \u21d2 "))
            dd = QComboBox()
            dd.setModel(self._model)
            dd._cell_type = cell_type  # Python attribute for callback lookup
            dd.currentIndexChanged.connect(self._handle_dropdown_change)
            self._dropdowns.append((cell_type, dd))
            hbox.addWidget(dd, 1)
            inner.addLayout(hbox)

        scroll_widget = QWidget()
        scroll_widget.setLayout(inner)
        scroll_area = QScrollArea()
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        vbox.addWidget(scroll_area)

        # "Add templates from file…" button
        add_btn = QPushButton("Add templates from file\u2026")
        add_btn.clicked.connect(self._add_templates_cb)
        vbox.addWidget(add_btn)

        # Navigation
        go_back     = GoBackButton(self, walkthrough)
        continue_btn = ContinueButton(self, self.process_window)
        hbox_nav = QHBoxLayout()
        hbox_nav.addWidget(go_back)
        hbox_nav.addWidget(continue_btn)
        vbox.addLayout(hbox_nav)

        self.setLayout(vbox)

        # Populate model and registry, then size to fit
        self._rebuild_model()
        self._populate_registry_from_defaults()
        self._fit_width(s)

    # ------------------------------------------------------------------
    # Template loading
    # ------------------------------------------------------------------

    def _load_template_file(self, path: str) -> None:
        """Load *path* (TOML) into ``_template_db``. Does not rebuild model."""
        try:
            data = cell_params.load_templates_from_file(path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Template Load Error",
                f"Could not load template file:\n{path}\n\n{exc}",
            )
            return
        for name, xml in data.items():
            self._template_db[(name, path)] = xml

    def _add_templates_cb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open template file", "",
            "TOML files (*.toml);;All files (*)",
        )
        if not path:
            return
        saved = self._save_selections()
        self._load_template_file(path)
        self._rebuild_model()
        self._restore_selections(saved)

    # ------------------------------------------------------------------
    # Sort mode
    # ------------------------------------------------------------------

    def _sort_toggled(self, btn_id: int, checked: bool) -> None:
        if not checked:
            return
        saved = self._save_selections()
        self._sort_by_name = (btn_id == 0)
        self._rebuild_model()
        self._restore_selections(saved)

    # ------------------------------------------------------------------
    # Model construction
    # ------------------------------------------------------------------

    def _build_by_name_labels(self) -> dict[tuple[str, str], str]:
        """Compute ``"name (source_suffix)"`` display label for every db entry."""
        by_name: dict[str, list[str]] = defaultdict(list)
        for name, fp in self._template_db:
            by_name[name].append(fp)

        result: dict[tuple[str, str], str] = {}
        for name, fps in by_name.items():
            suffixes = _minimal_unique_suffixes(fps)
            for fp in fps:
                result[(name, fp)] = f"{name} ({suffixes[fp]})"
        return result

    def _source_display_names(self) -> dict[str, str]:
        """Short display label for each unique source filepath (for headers)."""
        filepaths = list({fp for _, fp in self._template_db})
        suffixes = _minimal_unique_suffixes(filepaths)
        result: dict[str, str] = {}
        for fp in filepaths:
            result[fp] = "Built-in templates" if fp == _BUILTIN_PATH else suffixes[fp]
        return result

    def _rebuild_model(self) -> None:
        self._model.clear()
        if self._sort_by_name:
            self._build_by_name_model()
        else:
            self._build_by_source_model()

    def _build_by_name_model(self) -> None:
        labels = self._build_by_name_labels()

        def _key(entry):
            (name, fp), _ = entry
            return (name != "default", name, fp)

        for (name, fp), label in sorted(labels.items(), key=_key):
            item = QStandardItem(label)
            item.setData((name, fp), Qt.UserRole)
            self._model.appendRow(item)

    def _build_by_source_model(self) -> None:
        src_labels = self._source_display_names()

        # Insertion order: built-in first, then user files
        ordered_fps: list[str] = []
        seen: set[str] = set()
        if _BUILTIN_PATH in {fp for _, fp in self._template_db}:
            ordered_fps.append(_BUILTIN_PATH)
            seen.add(_BUILTIN_PATH)
        for _, fp in self._template_db:
            if fp not in seen:
                ordered_fps.append(fp)
                seen.add(fp)

        for fp in ordered_fps:
            # Section header — enabled but not selectable
            header = QStandardItem(src_labels[fp])
            header.setFlags(Qt.ItemIsEnabled)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setBackground(QColor("#e8e8e8"))
            header.setData(None, Qt.UserRole)
            self._model.appendRow(header)

            # Templates in this source, "default" first then alpha
            keys = sorted(
                ((n, f) for n, f in self._template_db if f == fp),
                key=lambda k: (k[0] != "default", k[0]),
            )
            for name, path in keys:
                item = QStandardItem(f"\u2003{name}")  # em-space indent
                item.setData((name, path), Qt.UserRole)
                self._model.appendRow(item)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _current_key(self, dd: QComboBox) -> Optional[tuple[str, str]]:
        """Return ``(name, filepath)`` for the current dropdown selection."""
        idx = dd.currentIndex()
        if idx < 0:
            return None
        item = self._model.item(idx)
        return None if item is None else item.data(Qt.UserRole)

    def _save_selections(self) -> dict[str, Optional[tuple[str, str]]]:
        return {ct: self._current_key(dd) for ct, dd in self._dropdowns}

    def _restore_selections(
        self, saved: dict[str, Optional[tuple[str, str]]]
    ) -> None:
        for ct, dd in self._dropdowns:
            key = saved.get(ct)
            if key is None:
                continue
            for row in range(self._model.rowCount()):
                item = self._model.item(row)
                if item is not None and item.data(Qt.UserRole) == key:
                    dd.setCurrentIndex(row)
                    break

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------

    def _populate_registry_from_defaults(self) -> None:
        s = self.walkthrough.session
        for ct, dd in self._dropdowns:
            key = self._current_key(dd)
            if key is not None:
                s.cell_definitions_registry[ct] = _make_cell_definition(
                    ct, key, self._template_db
                )

    def _handle_dropdown_change(self) -> None:
        sender = self.sender()
        ct  = sender._cell_type
        key = self._current_key(sender)
        if key is None:
            return  # section header — ignore
        self.walkthrough.session.cell_definitions_registry[ct] = _make_cell_definition(
            ct, key, self._template_db
        )

    def process_window(self) -> None:
        s = self.walkthrough.session
        for ct, dd in self._dropdowns:
            key = self._current_key(dd)
            if key is not None:
                s.cell_definitions_registry[ct] = _make_cell_definition(
                    ct, key, self._template_db
                )

        missing = [
            ct for ct in s.cell_types_list_final
            if ct not in s.cell_definitions_registry
        ]
        if missing:
            QMessageBox.warning(
                self,
                "Missing cell parameter templates",
                "The following cell types have no parameter template assigned "
                "and cannot be written to the output config:\n\n"
                + "\n".join(f"  \u2022 {ct}" for ct in missing)
                + "\n\nPlease assign a template for each type before continuing.",
            )
            return

        s.parameters_loaded = True
        self.walkthrough.advance()

    # ------------------------------------------------------------------
    # Window sizing
    # ------------------------------------------------------------------

    def _fit_width(self, s) -> None:
        """Resize so the longest label + longest cell-type name fit without truncation."""
        fm = self.fontMetrics()
        labels = self._build_by_name_labels()
        max_dd  = max((fm.horizontalAdvance(v) for v in labels.values()), default=200)
        max_lbl = max(
            (fm.horizontalAdvance(f"{ct} \u21d2 ") for ct in s.cell_types_list_final),
            default=100,
        ) if s.cell_types_list_final else 100
        # Add scrollbar (~20 px) + layout margins (~60 px)
        self.resize(max(max_dd + max_lbl + 80, 500), 600)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_cell_id_counter = [1]  # mutable singleton — each call gets a unique ID


def _make_cell_definition(cell_type: str, key: tuple[str, str],
                          template_db: dict[tuple[str, str], str]):
    """Return an ``xml.etree.ElementTree.Element`` for *cell_type*.

    *key* is a ``(name, filepath)`` tuple looked up in *template_db*;
    falls back to ``cell_params.default_template`` if not found.
    """
    import xml.etree.ElementTree as ET

    elem = ET.Element(
        "cell_definition",
        name=cell_type,
        ID=str(_cell_id_counter[0]),
    )
    _cell_id_counter[0] += 1

    template_xml = template_db.get(key, cell_params.default_template)
    try:
        elem.append(ET.fromstring(template_xml))
    except ET.ParseError:
        pass  # malformed template XML — return empty cell_definition
    return elem
