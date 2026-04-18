"""Step 1 (or 2): Select the obs column that contains cell-type labels."""

from __future__ import annotations
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PyQt5.QtCore import QTimer
from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import GoBackButton


class ClusterColumnWindow(BiwinformaticsWalkthroughWindow):
    """Ask the user which obs column holds cell-type labels.

    If the home-screen hint column name is already present in the data,
    ``auto_continue`` is set to True so the walkthrough can skip display and
    advance immediately.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session
        hint = walkthrough.column_line_edit.text().strip()

        col_keys = sorted(s.data.obs.columns.tolist())

        self.auto_continue = False
        if hint and hint in col_keys:
            prompt = "Select column that contains cell type info:"
            self.auto_continue = True
        elif hint:
            prompt = (
                f"'{hint}' was not found in the obs columns.\n"
                "Select from the following:"
            )
        else:
            prompt = "Select column that contains cell type info:"

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(prompt))

        self.column_combobox = QComboBox()
        for col in col_keys:
            self.column_combobox.addItem(col)
        if self.auto_continue:
            self.column_combobox.setCurrentIndex(self.column_combobox.findText(hint))
        self.column_combobox.currentIndexChanged.connect(
            lambda _: setattr(walkthrough, "stale_futures", True)
        )
        vbox.addWidget(self.column_combobox)

        hbox = QHBoxLayout()
        if walkthrough.session.spot_deconv_asked:
            hbox.addWidget(GoBackButton(self, walkthrough))
        hbox.addWidget(self.create_continue_button())
        vbox.addLayout(hbox)
        self.setLayout(vbox)

        if self.auto_continue:
            QTimer.singleShot(0, self.process_window)

    def process_window(self) -> None:
        s = self.walkthrough.session
        s.current_column = self.column_combobox.currentText()
        s.collect_cell_type_data()
        # use_spatial_data stays None → SpatialQuery will be shown if needed
        self.walkthrough.advance()
