from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PyQt5.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QPushButton, QHBoxLayout, QApplication, QWidget, QLabel
from gpiozero import Button
from picamera2 import Picamera2  # type: ignore
from picamera2.previews.qt import QGlPicamera2  # type: ignore

TRANSLUCENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 63); border: 1px solid white; "
)
TRANSPARENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 0); border: none; "
)

FONT = QFont("Deja Vu Sans Mono", 18)


@dataclass
class PowerState:
    voltage: float | None
    current: float | None
    power: float | None


class PowerMonitor(QObject):
    INTERVAL_MS = 1000

    _hwmon_dir: Path | None
    _timer: QTimer | None
    output = pyqtSignal(PowerState)
    finished = pyqtSignal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent=parent)
        self._hwmon_dir = self._find_hwmon_dir()
        self._timer = None

    def _find_hwmon_dir(self) -> Path | None:
        for subdir in Path("/sys/class/hwmon").glob("hwmon*"):
            name_file = subdir / "name"
            if name_file.exists() and name_file.read_text().strip() == "ina219":
                return subdir
        return None

    def start(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_power_state)
        self._timer.start(self.INTERVAL_MS)

    def stop(self):
        self._timer.stop()
        self._timer = None
        self.finished.emit()

    def check_power_state(self):
        voltage = self.get_voltage()
        current = self.get_current()
        power = self.get_power()
        self.output.emit(PowerState(voltage=voltage, current=current, power=power))

    def get_voltage(self) -> float | None:
        """
        Gets battery voltage in V from hwmon sysfs interface
        """
        voltage_file0 = self._hwmon_dir / "in0_input"
        voltage_file1 = self._hwmon_dir / "in1_input"
        try:
            voltage_str0 = voltage_file0.read_text()
            voltage_str1 = voltage_file1.read_text()
        except FileNotFoundError:
            return None

        voltage = (float(voltage_str0) + float(voltage_str1)) / 1_000

        return voltage

    def get_current(self) -> int | None:
        """
        Gets battery current in mA from hwmon sysfs interface
        """
        current_file = self._hwmon_dir / "curr1_input"
        try:
            current_str = current_file.read_text()
        except FileNotFoundError:
            return None

        current = int(current_str)

        return current

    def get_power(self) -> float | None:
        """
        Gets battery power in W from hwmon sysfs interface
        """
        power_file = self._hwmon_dir / "power1_input"
        try:
            power_str = power_file.read_text()
        except FileNotFoundError:
            return None

        power = float(power_str) / 1_000_000

        return power


class PowerLabelKind(StrEnum):
    VOLTAGE = "voltage"
    CURRENT = "current"
    POWER = "power"


class PowerLabel(QLabel):
    label_kind: PowerLabelKind
    power_state: PowerState

    def __init__(
        self,
        kind: PowerLabelKind,
        parent: QWidget | None = None,
        flags: Qt.WindowFlags | Qt.WindowType = Qt.WindowFlags(),
    ):
        super().__init__(parent=parent, flags=flags)
        self.label_kind = kind
        self.power_state = PowerState(None, None, None)
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(TRANSPARENT_STYLESHEET)
        self.setFont(FONT)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.update_ui()

    def update_ui(self):
        match self.label_kind:
            case PowerLabelKind.VOLTAGE:
                v = self.power_state.voltage or 0.0
                self.setText(f"{v:.2f} V")
            case PowerLabelKind.CURRENT:
                i = int(self.power_state.current or 0.0)
                self.setText(f"{i:4} mA")
            case PowerLabelKind.POWER:
                p = self.power_state.power or 0.0
                self.setText(f"{p:.2f} W")

    def on_power_reading(self, power_state: PowerState):
        self.power_state = power_state
        self.update_ui()


class ButtonLabel(QLabel):
    button: Button
    button_name: str
    button_active: bool
    button_pressed = pyqtSignal()
    button_released = pyqtSignal()

    def __init__(
        self,
        pin: int,
        name: str,
        parent: QWidget | None = None,
        flags: Qt.WindowFlags | Qt.WindowType = Qt.WindowFlags(),
    ):
        super().__init__(parent=parent, flags=flags)
        self.button_name = name
        self.button_active = False
        self.button = Button(pin, bounce_time=0.01)
        self.button.when_activated = self.on_button_pressed
        self.button.when_deactivated = self.on_button_released
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(TRANSPARENT_STYLESHEET)
        self.update_ui()

    def update_ui(self):
        self.setText(f"{self.button_name}: [{'X' if self.button_active else ' '}]")

    def on_button_pressed(self):
        self.button_active = True
        self.update_ui()

    def on_button_released(self):
        self.button_active = False
        self.update_ui()


def main():
    picam2 = Picamera2()
    picam2.configure(picam2.create_preview_configuration({"size": (640, 480)}))

    app = QApplication([])

    qpicamera2 = QGlPicamera2(picam2, width=640, height=480, keep_ar=False)
    qpicamera2.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    qpicamera2.setGeometry(0, 0, 640, 480)
    qpicamera2.setWindowTitle("Chaoscope camera")

    button_window = QWidget()
    button_window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    button_window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    button_window.setGeometry(0, 0, 640, 480)
    button_window.setWindowTitle("Chaoscope controls")
    button_window.setCursor(Qt.CursorShape.BlankCursor)
    button_window.setFont(FONT)

    close_button = QPushButton(button_window)
    close_button.setStyleSheet(TRANSLUCENT_STYLESHEET)
    close_button.setText("X")
    close_button.setGeometry((640 - 60 - 5), 5, 60, 60)

    button_A = ButtonLabel(23, "A", button_window)
    button_A.setGeometry(5, 5, button_A.width(), button_A.height())

    button_B = ButtonLabel(24, "B", button_window)
    button_B.setGeometry(5, 5 + button_A.height(), button_B.width(), button_B.height())

    power_monitor = QWidget(button_window)
    power_monitor.setGeometry(5, 480 - 5 - 40, 640 - 5 - 5, 40)

    voltage_label = PowerLabel(PowerLabelKind.VOLTAGE)
    current_label = PowerLabel(PowerLabelKind.CURRENT)
    power_label = PowerLabel(PowerLabelKind.POWER)

    power_monitor_layout = QHBoxLayout(power_monitor)
    power_monitor_layout.addWidget(voltage_label)
    power_monitor_layout.addWidget(current_label)
    power_monitor_layout.addWidget(power_label)

    ## Starting properly now
    picam2.start()
    qpicamera2.show()

    button_window.show()
    button_window.raise_()
    button_window.activateWindow()

    thread = QThread()
    worker = PowerMonitor()
    worker.moveToThread(thread)
    thread.started.connect(worker.start)
    close_button.clicked.connect(worker.stop)

    worker.output.connect(voltage_label.on_power_reading)
    worker.output.connect(current_label.on_power_reading)
    worker.output.connect(power_label.on_power_reading)

    def finish_thread():
        thread.quit()
        thread.wait()

    worker.finished.connect(finish_thread)

    def stop_and_exit():
        qpicamera2.close()
        button_window.close()
        thread.quit()
        thread.wait()
        app.quit()

    close_button.clicked.connect(stop_and_exit)

    thread.start()
    app.exec()

    picam2.stop()
    # Any other cleanup?

if __name__ == "__main__":
    main()
