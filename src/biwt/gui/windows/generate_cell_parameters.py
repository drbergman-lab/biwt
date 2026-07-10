"""Step 7: Select whether to generate cell parameters from the template's parameters or add a variation.
Done: 
- Created basic UI for parameter generation.
- Implemented variation logic for defined parameters

TODO:
- add tests.
- add user input for variation strength.
- create subclusters for inter-cluster viriation. --> Next PR? 

"""
from __future__ import annotations
import numpy as np
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QComboBox
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
    - Generate from template
    - Add variation
    """

    def __init__(self, walkthrough):
        super().__init__(walkthrough)
        s = walkthrough.session

        vbox = QVBoxLayout()
        vbox.addWidget(
            QLabel(
                "Choose how each cell type should generate its parameter values: Template defaults or Variation (log-normal, sigma=0.1)"
            )
        )

        self.generation_boxes = {}

        for cell_type in s.cell_types_list_final:
            hbox = QHBoxLayout()
            combo = QComboBox()
            combo.addItems([
                "Use template defaults",
                "Add variation",
            ])

            self.generation_boxes[cell_type] = combo

            hbox.addWidget(QLabel(cell_type))
            hbox.addWidget(QLabel("⇒"))
            hbox.addWidget(combo)
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

        for cell_type, combo in self.generation_boxes.items():
            if combo.currentIndex() == 1:
                cell_definition = s.cell_definitions_registry[cell_type]
                apply_variation(cell_definition)

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
