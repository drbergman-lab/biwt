from PyQt5.QtGui import QPalette, QColor
from PyQt5.QtCore import Qt


def create_light_palette():
    palette = QPalette()

    palette.setColor(QPalette.Window, QColor("white"))
    palette.setColor(QPalette.WindowText, Qt.black)

    palette.setColor(QPalette.Base, QColor("white"))
    palette.setColor(QPalette.AlternateBase, QColor("white"))

    palette.setColor(QPalette.Text, Qt.black)

    palette.setColor(QPalette.Button, QColor("lightgray"))
    palette.setColor(QPalette.ButtonText, Qt.black)

    return palette


def apply_light_palette(app):
    app.setPalette(create_light_palette())