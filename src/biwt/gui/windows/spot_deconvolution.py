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
        # Default: Yes.  Set explicitly rather than relying on the toggle the
        # line above emits, so the default does not depend on statement order.
        walkthrough.session.perform_spot_deconvolution = True

        hbox_yn = QHBoxLayout()
        hbox_yn.addWidget(self.yes_rb)
        hbox_yn.addWidget(self.no_rb)

        vbox = QVBoxLayout()
        vbox.addWidget(header)
        vbox.addWidget(msg)
        vbox.addLayout(hbox_yn)
        # First step of the walkthrough — nothing to go back to.
        vbox.addLayout(self.create_nav_bar(include_back=False))
        self.setLayout(vbox)

    def _toggled(self, btn_id: int, checked: bool) -> None:
        # idToggled fires for the button being unchecked too; ignore that one.
        if not checked:
            return
        self.walkthrough.stale_futures = True
        self.walkthrough.session.perform_spot_deconvolution = (btn_id == 0)

    def process_window(self) -> None:
        # The probability-derived cell types, the coordinates, and the fact that
        # deconvolution implies spatial are all derived from this one answer by
        # WalkthroughSession.reseed_derived_state().
        self.walkthrough.session.spot_deconv_asked = True
        self.walkthrough.advance()
