"""Step: Map each final cell type to a PhysiCell cell-parameter template."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QWidget, QCompleter, QMessageBox,
)
from PyQt5.QtCore import QStringListModel
from PyQt5.QtCore import Qt

from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import GoBackButton, ContinueButton, ExtendedCombo
from biwt.core.parameters import cell_templates as cell_params


class LoadCellParametersWindow(BiwinformaticsWalkthroughWindow):
    """Let the user map each final cell type to an XML parameter template.

    The drop-down lists come from ``biwt.core.parameters.cell_templates``;
    each template is a named XML snippet that gets inserted into the output
    PhysiCell config.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        # Build sorted list of template names from the CELL_TEMPLATES registry
        list_cell_types = sorted(
            cell_params.CELL_TEMPLATES.keys(),
            key=lambda x: (x != "default", x),
        )

        self._model = QStringListModel(list_cell_types)
        self._dropdowns: list[tuple[str, ExtendedCombo]] = []

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel("Select parameter templates for your cell types:"))

        inner = QVBoxLayout()
        for cell_type in s.cell_types_list_final:
            hbox = QHBoxLayout()
            hbox.addWidget(QLabel(f"{cell_type} \u21d2 "))

            dd = ExtendedCombo()
            dd.objectName = cell_type   # store cell type name for the callback
            dd.setModel(self._model)
            dd.currentIndexChanged.connect(self._handle_dropdown_change)
            self._dropdowns.append((cell_type, dd))
            hbox.addWidget(dd)
            inner.addLayout(hbox)

        scroll_widget = QWidget()
        scroll_widget.setLayout(inner)
        scroll_area = QScrollArea()
        scroll_area.setWidget(scroll_widget)
        vbox.addWidget(scroll_area)

        go_back = GoBackButton(self, walkthrough)
        continue_btn = ContinueButton(self, self.process_window)
        hbox_nav = QHBoxLayout()
        hbox_nav.addWidget(go_back)
        hbox_nav.addWidget(continue_btn)
        vbox.addLayout(hbox_nav)

        self.setLayout(vbox)
        self.resize(400, 600)

        # Populate the registry with defaults immediately
        self._populate_registry_from_defaults()

    # ------------------------------------------------------------------

    def _populate_registry_from_defaults(self) -> None:
        s = self.walkthrough.session
        for cell_type, dd in self._dropdowns:
            template_elem = _make_cell_definition(cell_type, dd.currentText())
            s.cell_definitions_registry[cell_type] = template_elem

    def _handle_dropdown_change(self) -> None:
        sender = self.sender()
        cell_type = sender.objectName   # set in __init__ (not objectName() method)
        s = self.walkthrough.session
        s.cell_definitions_registry[cell_type] = _make_cell_definition(
            cell_type, sender.currentText()
        )

    def process_window(self) -> None:
        s = self.walkthrough.session
        # Sync final state from all dropdowns
        for cell_type, dd in self._dropdowns:
            s.cell_definitions_registry[cell_type] = _make_cell_definition(
                cell_type, dd.currentText()
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


def _make_cell_definition(cell_type: str, template_name: str):
    """Return an ``xml.etree.ElementTree.Element`` for *cell_type*."""
    import xml.etree.ElementTree as ET

    elem = ET.Element(
        "cell_definition",
        name=cell_type,
        ID=str(_cell_id_counter[0]),
    )
    _cell_id_counter[0] += 1

    template_xml = cell_params.CELL_TEMPLATES.get(template_name, cell_params.default_template)
    try:
        elem.append(ET.fromstring(template_xml))
    except ET.ParseError:
        pass  # bad template XML — return empty cell_definition element
    return elem
