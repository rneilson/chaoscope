from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QPushButton, QHBoxLayout, QApplication, QWidget, QLabel
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2

TRANSLUCENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 63); border: 1px solid white; "
)
TRANSPARENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 0); border: none; "
)


class ButtonLabel(QLabel):
    button_name: str
    button_active: bool
    # TODO: signals

    def __init__(
        self,
        name: str,
        parent: QWidget | None = None,
        flags: Qt.WindowFlags | Qt.WindowType = Qt.WindowFlags(),
    ):
        super().__init__(parent=parent, flags=flags)
        self.button_name = name
        self.button_active = False
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(TRANSPARENT_STYLESHEET)
        self.update_ui()

    def update_ui(self):
        self.setText(f"{self.button_name}: [{'X' if self.button_active else ' '}]")


picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration({"size": (640, 480)}))

app = QApplication([])

qpicamera2 = QGlPicamera2(picam2, width=640, height=480, keep_ar=False)
qpicamera2.setWindowFlag(Qt.FramelessWindowHint)
qpicamera2.setGeometry(0, 0, 640, 480)
qpicamera2.setWindowTitle("Chaoscope camera")

font = QFont("Deja Vu Sans Mono", 18)

button_window = QWidget()
button_window.setAttribute(Qt.WA_TranslucentBackground)
button_window.setWindowFlag(Qt.FramelessWindowHint)
button_window.setGeometry(0, 0, 640, 480)
button_window.setWindowTitle("Chaoscope controls")
button_window.setCursor(Qt.BlankCursor)
button_window.setFont(font)

close_button = QPushButton(button_window)
close_button.setStyleSheet(TRANSLUCENT_STYLESHEET)
close_button.setText("X")
close_button.setGeometry((640 - 40 - 5), 5, 40, 40)

button_A = ButtonLabel("A", button_window)
button_A.setGeometry(5, 5, button_A.width(), button_A.height())

button_B = ButtonLabel("B", button_window)
button_B.setGeometry(5, 5 + button_A.height(), button_B.width(), button_B.height())


def stop_and_exit():
    qpicamera2.close()
    button_window.close()
    app.quit()


close_button.clicked.connect(stop_and_exit)

if __name__ == "__main__":
    picam2.start()
    qpicamera2.show()
    button_window.show()
    button_window.raise_()
    button_window.activateWindow()
    app.exec()
    picam2.stop()
