"""Step: Rename intermediate (post-edit) cell types."""

from __future__ import annotations
from PyQt5.QtWidgets import (
    QVBoxLayout, QGridLayout, QLabel, QLineEdit,
    QScrollArea, QWidget, QMessageBox,
)
from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import row_arrow, row_label
from biwt.core.cell_types import alpha_key, suggest_name_mappings


class RenameCellTypesWindow(BiwinformaticsWalkthroughWindow):
    """Allow the user to rename each intermediate cell type.

    Pre-populates each field with the first original name that maps to that
    intermediate type, and — if the host supplied its own cell-type names —
    offers a suggestion via the placeholder text.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        # Suggest matches against the host's own cell-type names
        suggestions = suggest_name_mappings(
            s.intermediate_types,
            s.biwt_input.host_cell_type_names,
            matches=s.name_matcher,
        )

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel("Rename your cell types if you like:"))

        # A grid rather than a row of HBoxes: the labels then share one column and
        # every field starts at the same x, instead of each row sizing its own.
        inner = QGridLayout()
        inner.setColumnStretch(2, 1)
        self._line_edits: dict[str, QLineEdit] = {}
        self._labels: dict[str, QLabel] = {}
        for row, intermed in enumerate(s.intermediate_types):
            originals = s.intermediate_type_pre_image[intermed]
            label = row_label(", ".join(originals))
            self._labels[intermed] = label
            inner.addWidget(label, row, 0)
            inner.addWidget(row_arrow(), row, 1)
            le = QLineEdit()
            le.setText(originals[0])
            suggestion = suggestions.get(intermed)
            if suggestion:
                le.setPlaceholderText(f"Suggestion: {suggestion}")
            le.textChanged.connect(lambda _: setattr(walkthrough, "stale_futures", True))
            self._line_edits[intermed] = le
            inner.addWidget(le, row, 2)
        # Pack the rows at the top rather than spreading them down the viewport.
        inner.setRowStretch(len(s.intermediate_types), 1)

        scroll_widget = QWidget()
        scroll_widget.setLayout(inner)
        scroll_area = QScrollArea()
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        vbox.addWidget(scroll_area)
        vbox.addLayout(self.create_nav_bar())
        self.setLayout(vbox)

    def process_window(self) -> None:
        s = self.walkthrough.session
        final_names = [le.text() for le in self._line_edits.values()]

        # Block on exact duplicate names — two cell types with identical names
        # would collide downstream. Note: names that differ only by case
        # (e.g. "CD8" vs "cd8") are allowed, and stay distinct.
        seen: set[str] = set()
        dupes: list[str] = []
        for name in final_names:
            if name in seen and name not in dupes:
                dupes.append(name)
            seen.add(name)
        if dupes:
            QMessageBox.warning(
                self,
                "Duplicate cell type names",
                "The following names appear more than once. Each cell type "
                "must have a unique name before continuing:\n\n"
                + "\n".join(f"  \u2022 {d}" for d in sorted(dupes, key=alpha_key)),
            )
            return

        s.cell_types_list_final = final_names
        s.cell_type_dict_on_rename = {}
        for intermed, le in self._line_edits.items():
            for orig in s.intermediate_type_pre_image[intermed]:
                s.cell_type_dict_on_rename[orig] = le.text()

        s.apply_rename()
        self.walkthrough.advance()
