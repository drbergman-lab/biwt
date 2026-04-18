"""Step: Ask whether to use spatial coordinates found in the data."""

from __future__ import annotations
from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QButtonGroup, QRadioButton,
)
from PyQt5.QtCore import Qt
from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow


class SpatialQueryWindow(BiwinformaticsWalkthroughWindow):
    """Ask the user whether to use the spatial data found in the imported file."""

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        header = QLabel("Spatial Data")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 18pt; font-weight: bold; margin-bottom: 10px;")

        msg = QLabel(
            f"It seems this data may contain spatial information in "
            f"{s.data.spatial_location}.\nWould you like to use this?"
        )

        self.yes_no_group = QButtonGroup()
        self.yes_rb = QRadioButton("Yes")
        self.no_rb = QRadioButton("No")
        self.yes_no_group.addButton(self.yes_rb, 0)
        self.yes_no_group.addButton(self.no_rb, 1)
        self.yes_no_group.idToggled.connect(self._toggled)
        self.yes_rb.setChecked(True)
        # Initialise session default
        walkthrough.session.use_spatial_data = True

        hbox_yn = QHBoxLayout()
        hbox_yn.addWidget(self.yes_rb)
        hbox_yn.addWidget(self.no_rb)

        vbox = QVBoxLayout()
        vbox.addWidget(header)
        vbox.addWidget(msg)
        vbox.addLayout(hbox_yn)
        vbox.addLayout(self.create_nav_bar())
        self.setLayout(vbox)

    def _toggled(self, btn_id: int) -> None:
        self.walkthrough.stale_futures = True
        self.walkthrough.session.use_spatial_data = (btn_id == 0)

    def process_window(self) -> None:
        self.walkthrough.advance()
