from PyQt5.QtCore import Qt, QTimer
# from PyQt5.QtGui import QRawFont
from PyQt5.QtWidgets import QPushButton, QVBoxLayout, QApplication, QWidget
from picamera2 import Picamera2
from picamera2.previews.qt import QGlPicamera2

FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration({'size': (640, 480)}))

app = QApplication([])

qpicamera2 = QGlPicamera2(picam2, width=640, height=480, keep_ar=False)
qpicamera2.setWindowFlag(Qt.FramelessWindowHint)
qpicamera2.setGeometry(0, 0, 640, 480)
qpicamera2.setWindowTitle('Chaoscope camera')

# font = QRawFont(FONT_PATH, 18)

button_window = QWidget()
button_window.setAttribute(Qt.WA_TranslucentBackground)
button_window.setWindowFlag(Qt.FramelessWindowHint)
button_window.setGeometry(0, 0, 640, 480)
button_window.setWindowTitle('Chaoscope controls')
button_window.setCursor(Qt.BlankCursor)

close_button = QPushButton(button_window)
close_button.setText('X')
# close_button.setFont(font)
# close_button.setWindowOpacity(0.5)
close_button.setStyleSheet('background-color: rgba(255, 255, 255, 63); border: none;')
close_button.setGeometry((640 - 40 - 5), 5, 40, 40)
close_button.setCursor(Qt.BlankCursor)

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
