"""Step: Ask whether to use spot deconvolution (spatial + probability data)."""

from __future__ import annotations

from biwt.gui.windows.base import YesNoQueryWindow


class SpotDeconvolutionQueryWindow(YesNoQueryWindow):
    """Ask whether to run spot deconvolution.

    Shown when the data has both spatial coordinates and per-cell-type
    probability columns.
    """

    title = "Spot Deconvolution"
    field = "perform_spot_deconvolution"
    include_back = False              # first step; nothing to go back to

    def message(self, session) -> str:
        return ("It seems this data may contain spatial coordinates and cell-type "
                "probabilities.\nWould you like to use spot deconvolution?")

    def process_window(self) -> None:
        # The probability-derived cell types, the coordinates, and the fact that
        # deconvolution implies spatial all follow from this one answer, via
        # WalkthroughSession.reseed_derived_state().
        self.walkthrough.session.spot_deconv_asked = True
        super().process_window()
