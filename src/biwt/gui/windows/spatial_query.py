"""Step: Ask whether to use spatial coordinates found in the data."""

from __future__ import annotations

from biwt.gui.windows.base import YesNoQueryWindow


class SpatialQueryWindow(YesNoQueryWindow):
    """Ask whether to use the spatial data found in the imported file."""

    title = "Spatial Data"
    field = "spatial_query_answer"

    def message(self, session) -> str:
        return (f"It seems this data may contain spatial information in "
                f"{session.data.spatial_location}.\nWould you like to use this?")
