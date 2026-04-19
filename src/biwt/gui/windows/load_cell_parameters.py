"""Step: Map each final cell type to a PhysiCell cell-parameter template."""

from __future__ import annotations
import os

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QFileDialog,
    QScrollArea, QWidget, QMessageBox, QPushButton,
)
from PyQt5.QtCore import QStringListModel
from PyQt5.QtCore import Qt

from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import GoBackButton, ContinueButton, ExtendedCombo
from biwt.core.parameters import cell_templates as cell_params


class LoadCellParametersWindow(BiwinformaticsWalkthroughWindow):
    """Let the user map each final cell type to an XML parameter template.

    The drop-down lists are populated from the built-in ``cell_templates.toml``
    plus any extra ``.toml`` files supplied via ``BiwtInput.extra_cell_template_paths``
    or loaded at runtime via the "Add templates from file…" button.

    Each dropdown entry is a display key of the form ``"name (source)"`` so
    that templates with the same name from different sources can coexist.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        # --- build template dict: display_key → xml_string -------------------
        # Built-ins first, tagged "(built-in)".
        self._templates: dict[str, str] = {
            f"{name} (built-in)": xml
            for name, xml in cell_params.CELL_TEMPLATES.items()
        }
        # Extra files from BiwtInput.
        for path in s.biwt_input.extra_cell_template_paths:
            self._merge_template_file(path, rebuild=False)

        self._dropdowns: list[tuple[str, ExtendedCombo]] = []
        self._model = QStringListModel(self._sorted_keys())

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

        vbox.addWidget(QLabel("Select parameter templates for your cell types:"))

        inner = QVBoxLayout()
        for cell_type in s.cell_types_list_final:
            hbox = QHBoxLayout()
            hbox.addWidget(QLabel(f"{cell_type} \u21d2 "))

            dd = ExtendedCombo()
            dd.objectName = cell_type
            dd.setModel(self._model)
            dd.currentIndexChanged.connect(self._handle_dropdown_change)
            self._dropdowns.append((cell_type, dd))
            hbox.addWidget(dd)
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

        go_back = GoBackButton(self, walkthrough)
        continue_btn = ContinueButton(self, self.process_window)
        hbox_nav = QHBoxLayout()
        hbox_nav.addWidget(go_back)
        hbox_nav.addWidget(continue_btn)
        vbox.addLayout(hbox_nav)

        self.setLayout(vbox)
        self.resize(400, 600)

        # Populate registry with defaults immediately
        self._populate_registry_from_defaults()

    # ------------------------------------------------------------------
    # Template loading helpers
    # ------------------------------------------------------------------

    def _sorted_keys(self) -> list[str]:
        """Return display keys sorted: 'default (built-in)' first, then alpha."""
        def _key(k):
            base = k.rsplit(" (", 1)[0]
            return (base != "default", k)
        return sorted(self._templates.keys(), key=_key)

    def _merge_template_file(self, path: str, rebuild: bool = True) -> None:
        """Load *path* (TOML), tag each entry with the filename, insert into
        ``self._templates``.  Calls ``_rebuild_model`` when *rebuild* is True."""
        try:
            data = cell_params.load_templates_from_file(path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Template Load Error",
                f"Could not load template file:\n{path}\n\n{exc}",
            )
            return
        source = os.path.basename(path)
        for name, xml in data.items():
            self._templates[f"{name} ({source})"] = xml
        if rebuild:
            self._rebuild_model()

    def _rebuild_model(self) -> None:
        """Refresh the shared QStringListModel from the current template dict."""
        self._model.setStringList(self._sorted_keys())

    def _add_templates_cb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open template file", "",
            "TOML files (*.toml);;All files (*)",
        )
        if path:
            self._merge_template_file(path)

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def _populate_registry_from_defaults(self) -> None:
        s = self.walkthrough.session
        for cell_type, dd in self._dropdowns:
            s.cell_definitions_registry[cell_type] = _make_cell_definition(
                cell_type, dd.currentText(), self._templates
            )

    def _handle_dropdown_change(self) -> None:
        sender = self.sender()
        cell_type = sender.objectName
        s = self.walkthrough.session
        s.cell_definitions_registry[cell_type] = _make_cell_definition(
            cell_type, sender.currentText(), self._templates
        )

    def process_window(self) -> None:
        s = self.walkthrough.session
        for cell_type, dd in self._dropdowns:
            s.cell_definitions_registry[cell_type] = _make_cell_definition(
                cell_type, dd.currentText(), self._templates
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_cell_id_counter = [1]  # mutable singleton so each call gets a unique ID


def _make_cell_definition(cell_type: str, display_key: str,
                          templates: dict[str, str] | None = None):
    """Return an ``xml.etree.ElementTree.Element`` for *cell_type*.

    *display_key* is a ``"name (source)"`` string from the dropdown.
    The XML is looked up directly by *display_key* in *templates*;
    falls back to ``cell_params.default_template`` if not found.
    """
    import xml.etree.ElementTree as ET

    if templates is None:
        templates = {
            f"{k} (built-in)": v for k, v in cell_params.CELL_TEMPLATES.items()
        }

    elem = ET.Element(
        "cell_definition",
        name=cell_type,
        ID=str(_cell_id_counter[0]),
    )
    _cell_id_counter[0] += 1

    template_xml = templates.get(display_key, cell_params.default_template)
    try:
        elem.append(ET.fromstring(template_xml))
    except ET.ParseError:
        pass  # bad template XML — return empty cell_definition element
    return elem
