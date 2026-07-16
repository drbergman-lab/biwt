"""Step 7: Select whether to generate cell parameters from the template's parameters or add a variation.
Done: 
- Created basic UI for parameter generation.
- Implemented variation logic for defined parameters:
    - Selected which parameters can be varied. 
        Note: If the template value is <= 0, it will not be varied. If the parameter is migration_bias, the new value will be clipped to [0, 1].
    - Implemented log-normal variation with fixed standard-variations for the selected parameters.
- add user input for variation strength.

TODO:
- other type of variation (e.g. uniform, normal, etc.)?
- create subclusters for inter-cluster variation?

"""
from __future__ import annotations
import numpy as np
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QRadioButton, QButtonGroup
from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import GoBackButton, ContinueButton
import xml.etree.ElementTree as ET

# Parameters that should receive log-normal variation.
VARIED_PARAMETERS = {
    "cycle": [
        "duration",
    ],
    "death": [
        "death_rate",
    ],
    "volume": [
        "total",
    ],
    "mechanics": [
        "cell_cell_adhesion_strength",
        "cell_cell_repulsion_strength",
        "attachment_rate",
        "detachment_rate",
    ],
    "motility": [
        "speed",
        "persistence_time",
        "migration_bias",
    ],
    "cell_interactions": [
        "apoptotic_phagocytosis_rate",
        "necrotic_phagocytosis_rate",
        "other_dead_phagocytosis_rate",
        "phagocytosis_rate",
    ]
}


class ParameterGenerationWindow(BiwinformaticsWalkthroughWindow):
    """
    Ask the user how they want to generate cell parameters.

    Possible choices:
    - No variation from the template's values.
    - Add a low log-normal variation to the template's values.
    - Add a medium log-normal variation to the template's values.
    - Add a high log-normal variation to the template's values.
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        vbox = QVBoxLayout()
        vbox.addWidget(
            QLabel(
                "Choose how each cell type should generate its parameter values: Template defaults or Variation (log-normal, sigma=0.05, 0.1 or 0.2)"
            )
        )

        self.generation_boxes = {}

        for cell_type in s.cell_types_list_final:
            hbox = QHBoxLayout()

            hbox.addWidget(QLabel(cell_type))
            hbox.addWidget(QLabel("Variation:"))

            group = QButtonGroup(self)

            none_btn = QRadioButton("None")
            low_btn = QRadioButton("Low")
            med_btn = QRadioButton("Medium")
            high_btn = QRadioButton("High")

            none_btn.setChecked(True)   # default

            group.addButton(none_btn, 0)
            group.addButton(low_btn, 1)
            group.addButton(med_btn, 2)
            group.addButton(high_btn, 3)

            self.generation_boxes[cell_type] = group

            hbox.addWidget(none_btn)
            hbox.addWidget(low_btn)
            hbox.addWidget(med_btn)
            hbox.addWidget(high_btn)

            vbox.addLayout(hbox)


        # Navigation
        go_back     = GoBackButton(self, walkthrough)
        continue_btn = ContinueButton(self, self.process_window)
        hbox_nav = QHBoxLayout()
        hbox_nav.addWidget(go_back)
        hbox_nav.addWidget(continue_btn)
        vbox.addLayout(hbox_nav)

        self.setLayout(vbox)


    def process_window(self):
        s = self.walkthrough.session

        for cell_type, group in self.generation_boxes.items():
            choice = group.checkedId()
            if choice == 1:          # Low
                sigma = 0.05
            elif choice == 2:        # Medium
                sigma = 0.10
            elif choice == 3:        # High
                sigma = 0.20
            else:                    # None
                continue

            cell_definition = s.cell_definitions_registry[cell_type]
            apply_variation(cell_definition, sigma=sigma)

        s.parameter_generation_done = True
        self.walkthrough.advance()



def _vary_element(elem: ET.Element, sigma: float) -> None:
    """Apply log-normal variation to a single XML parameter."""

    try:
        value = float(elem.text)
    except (TypeError, ValueError):
        return

    # Keep disabled parameters unchanged.
    if value <= 0:
        return

    new_value = np.random.lognormal(
        mean=np.log(value),
        sigma=sigma,
    )

    # Parameters constrained to [0, 1]
    if elem.tag == "migration_bias":
        new_value = np.clip(new_value, 0.0, 1.0)

    elem.text = f"{new_value:.5g}"


def apply_variation(cell_definition: ET.Element, sigma: float = 0.1) -> None:
    """Modify the selected PhysiCell parameters in place."""

    for block_name, tags in VARIED_PARAMETERS.items():

        block = cell_definition.find(f".//{block_name}")
        if block is None:
            continue

        for tag in tags:
            for elem in block.iter(tag):
                _vary_element(elem, sigma)
