"""Step 7: Select whether to generate cell parameters from the template's parameters or add a variation.
TODO: First, we are just creating a basic UI for this step. Then we will implement the parameter variation.
"""
from __future__ import annotations
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from biwt.gui.windows.base import BiwinformaticsWalkthroughWindow
from biwt.gui.widgets import GoBackButton, ContinueButton




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
                "Choose how each cell type should generate its parameter values."
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

        s.parameter_generation = {}

        for cell_type, combo in self.generation_boxes.items():
            if combo.currentIndex() == 0:
                s.parameter_generation[cell_type] = "use_default"
            else:
                # TODO: Implement parameter sampling.
                s.parameter_generation[cell_type] = "add_variation"

        s.parameter_generation_done = True
        self.walkthrough.advance()