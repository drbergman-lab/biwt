"""Step: Ask whether to use spot deconvolution (spatial + probability data)."""

from __future__ import annotations
from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QButtonGroup, QRadioButton,
)
from PyQt5.QtCore import Qt
from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow


class SpotDeconvolutionQueryWindow(BiwinformaticsWalkthroughWindow):
    """Ask the user whether to run spot deconvolution.

    Shown when both spatial coordinates and per-cell-type probability columns
    are present in the imported data.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)

        header = QLabel("Spot Deconvolution")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet("font-size: 18pt; font-weight: bold; margin-bottom: 10px;")

        msg = QLabel(
            "It seems this data may contain spatial coordinates and cell-type "
            "probabilities.\nWould you like to use spot deconvolution?"
        )

        self.yes_no_group = QButtonGroup()
        self.yes_rb = QRadioButton("Yes")
        self.no_rb = QRadioButton("No")
        self.yes_no_group.addButton(self.yes_rb, 0)
        self.yes_no_group.addButton(self.no_rb, 1)
        self.yes_no_group.idToggled.connect(self._toggled)
        self.yes_rb.setChecked(True)
        # Default: Yes → use spot deconvolution + spatial
        walkthrough.session.perform_spot_deconvolution = True
        walkthrough.session.use_spatial_data = True  # will become None if user picks No

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
        self.walkthrough.session.perform_spot_deconvolution = (btn_id == 0)
        # Yes → spatial is definitely used; No → let SpatialQueryWindow decide
        self.walkthrough.session.use_spatial_data = True if btn_id == 0 else None

    def process_window(self) -> None:
        s = self.walkthrough.session
        s.spot_deconv_asked = True
        if s.perform_spot_deconvolution:
            s.setup_spot_deconvolution_data()
            s.setup_spatial_data()
            # Skip ClusterColumn — cell type list comes from probability columns
            s.current_column = "__spot_deconv__"
        self.walkthrough.advance()
