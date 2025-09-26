from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QPalette
from PyQt5.QtWidgets import QPushButton, QHBoxLayout, QApplication, QWidget, QLabel
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration({'size': (640, 480)}))

app = QApplication([])

qpicamera2 = QGlPicamera2(picam2, width=640, height=480, keep_ar=False)
qpicamera2.setWindowFlag(Qt.FramelessWindowHint)
qpicamera2.setGeometry(0, 0, 640, 480)
qpicamera2.setWindowTitle('Chaoscope camera')

font = QFont('Deja Vu Sans Mono', 18)

button_window = QWidget()
button_window.setAttribute(Qt.WA_TranslucentBackground)
button_window.setWindowFlag(Qt.FramelessWindowHint)
button_window.setGeometry(0, 0, 640, 480)
button_window.setWindowTitle('Chaoscope controls')
button_window.setCursor(Qt.BlankCursor)
button_window.setFont(font)

TRANSLUCENT_STYLESHEET = (
    'color: white; '
    'background-color: rgba(255, 255, 255, 63); '
    'border: none; '
)

close_button = QPushButton(button_window)
close_button.setStyleSheet(TRANSLUCENT_STYLESHEET)
close_button.setText('X')
close_button.setGeometry((640 - 40 - 5), 5, 40, 40)

button_label_A = QLabel(button_window)
button_label_A.setStyleSheet(TRANSLUCENT_STYLESHEET)
button_label_A.setText('A: [ ]')
button_label_A.setGeometry(
    5, 5, button_label_A.width(), button_label_A.height()
)

button_label_B = QLabel(button_window)
button_label_B.setStyleSheet(TRANSLUCENT_STYLESHEET)
button_label_B.setText('B: [ ]')
button_label_B.setGeometry(
    5, 5 + button_label_A.height(), button_label_B.width(), button_label_B.height()
)


def stop_and_exit():
    qpicamera2.close()
    button_window.close()
    app.quit()

close_button.clicked.connect(stop_and_exit)

if __name__ == '__main__':
    picam2.start()
    qpicamera2.show()
    button_window.show()
    button_window.raise_()
    button_window.activateWindow()
    app.exec()
    picam2.stop()
