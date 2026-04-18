"""Step: Write the placed cell positions to a CSV file (and optionally XML)."""

from __future__ import annotations

import copy
import os
import time
from pathlib import Path

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QFileDialog,
    QMessageBox,
)

from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import GoBackButton, ContinueButton, QHLine


class WritePositionsWindow(BiwinformaticsWalkthroughWindow):
    """Let the user confirm the output path, then overwrite or append.

    After writing, calls ``walkthrough.advance()`` which triggers
    ``BioinformaticsWalkthrough._finish()`` to assemble a ``BiwtResult``
    and return it to the host.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        csv_path = s.biwt_input.output_csv_path or "./config/cells.csv"
        self._full_fname: str | None = None

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(
            "Confirm output file, then choose to overwrite or append."
        ))

        self._csv_path_edit = QLineEdit(csv_path)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_cb)

        hbox_path = QHBoxLayout()
        hbox_path.addWidget(self._csv_path_edit)
        hbox_path.addWidget(browse_btn)
        vbox.addLayout(hbox_path)

        _btn_style = "QPushButton {background-color: yellow; font-weight: bold;}"
        overwrite_btn = QPushButton("Overwrite")
        overwrite_btn.setStyleSheet(_btn_style)
        overwrite_btn.clicked.connect(self._overwrite_cb)

        append_btn = QPushButton("Append")
        append_btn.setStyleSheet(_btn_style)
        append_btn.clicked.connect(self._append_cb)

        hbox_btns = QHBoxLayout()
        hbox_btns.addWidget(overwrite_btn)
        hbox_btns.addWidget(append_btn)
        vbox.addLayout(hbox_btns)

        vbox.addWidget(QHLine())

        hbox_nav = QHBoxLayout()
        hbox_nav.addWidget(GoBackButton(self, walkthrough))
        hbox_nav.addWidget(ContinueButton(self, self.process_window, text="Finish"))
        vbox.addLayout(hbox_nav)

        self.setLayout(vbox)

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _browse_cb(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose output CSV", self._csv_path_edit.text(),
            "CSV files (*.csv);;All files (*)",
        )
        if path:
            self._csv_path_edit.setText(path)

    def _resolve_path(self) -> str:
        """Ensure the output directory exists and return the full file path."""
        full = self._csv_path_edit.text().strip()
        dir_name = os.path.dirname(full)
        if dir_name and not os.path.isdir(dir_name):
            os.makedirs(dir_name, exist_ok=True)
            time.sleep(0.2)
        Path(full).touch()
        return full

    def _overwrite_cb(self) -> None:
        self._full_fname = self._resolve_path()
        with open(self._full_fname, "w") as f:
            f.write("x,y,z,type\n")
        self._append_positions()

    def _append_cb(self) -> None:
        self._full_fname = self._resolve_path()
        with open(self._full_fname, "r") as f:
            first_line = f.readline()
        if "x,y,z,type" not in first_line:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Format error",
                f"{self._full_fname} does not start with 'x,y,z,type,...'.\n"
                "Please overwrite instead.",
            )
            return
        self._append_positions()

    def _append_positions(self) -> None:
        s = self.walkthrough.session
        with open(self._full_fname, "a") as f:
            if s.perform_spot_deconvolution:
                for spot_info in s.plotted_cell_types_per_spot:
                    spot_coords = spot_info["spot_coords"]
                    cell_types = spot_info["cell_types"]
                    sub_spots = spot_info["sub_spots"]
                    for i, ct in enumerate(cell_types):
                        x, y = sub_spots[i][0], sub_spots[i][1]
                        z = spot_coords[2] if len(spot_coords) > 2 else 0
                        f.write(f"{x},{y},{z},{ct}\n")
            else:
                for ct, coords in s.coords_by_type.items():
                    for pos in coords:
                        f.write(f"{pos[0]},{pos[1]},{pos[2]},{ct}\n")

        # Also write XML cell definitions to PhysiCell_new.xml
        self._write_xml_cell_definitions()

    def _write_xml_cell_definitions(self) -> None:
        """Build cell-definitions XML and store in session (no disk write).

        The host application (e.g. Studio) receives the XML via
        ``BiwtResult.cell_definitions_xml`` and decides where / whether to
        save it.
        """
        import xml.etree.ElementTree as ET
        from biwt.core.parameters.xml_defaults import xml_defaults

        root = ET.Element("PhysiCell_settings", version="devel-version")
        for key, xml_str in xml_defaults.items():
            wrapped = f"<{key}>{xml_str.strip()}</{key}>"
            root.append(ET.fromstring(wrapped))

        cell_defs = ET.SubElement(root, "cell_definitions")
        s = self.walkthrough.session
        for template_elem in s.cell_definitions_registry.values():
            cell_defs.append(copy.deepcopy(template_elem))

        s.cell_definitions_xml = ET.tostring(
            root, encoding="unicode", xml_declaration=False
        )

    # ------------------------------------------------------------------

    def process_window(self) -> None:
        """Store resolved path on session and advance (triggers _finish)."""
        s = self.walkthrough.session

        csv_path = Path(self._csv_path_edit.text().strip())

        if csv_path.suffix.lower() != ".csv":
            QMessageBox.warning(
                self,
                "Invalid output path",
                f"The output file must have a .csv extension.\n\nCurrent path: {csv_path}",
            )
            return

        if not csv_path.parent.exists():
            QMessageBox.warning(
                self,
                "Directory does not exist",
                f"The directory for the output file does not exist:\n\n{csv_path.parent}\n\n"
                "Please choose a path inside an existing directory, or use Browse\u2026 "
                "to select a valid location.",
            )
            return

        if self._full_fname:
            s.biwt_input.output_csv_path = self._full_fname
        s.output_written = True
        self.walkthrough.advance()
