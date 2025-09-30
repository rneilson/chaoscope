import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from time import sleep

from PyQt5.QtCore import (
    Qt,
    QPoint,
    QObject,
    QRect,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtGui import QFont, QPainter, QPaintEvent, QPen
from PyQt5.QtWidgets import QPushButton, QHBoxLayout, QApplication, QWidget, QLabel
from gpiozero import Button, DigitalInputDevice
from picamera2 import Picamera2  # type: ignore
from picamera2.previews.qt import QGlPicamera2  # type: ignore
from smbus2 import SMBus

TRANSLUCENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 63); border: 1px solid white; "
)
TRANSPARENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 0); border: none; "
)
FONT = QFont("Deja Vu Sans Mono", 18)
FONT_LG = QFont("Deja Vu Sans Mono", 24)

LIDAR_I2C_ADDRESS = 0x10
LIDAR_REG_DIST = 0x00
LIDAR_REG_ENABLE = 0x25
LIDAR_REG_FREQ = 0x26
LIDAR_REG_MODE = 0x23
LIDAR_REG_SAVE = 0x20
LIDAR_REG_REBOOT = 0x21
LIDAR_REG_TRIGGER = 0x24

ENABLE_RETICLE = False

if run_dir := os.environ.get("XDG_RUNTIME_DIR"):
    SHUTDOWN_FILE = Path(run_dir) / "chaoscope-shutdown"
else:
    SHUTDOWN_FILE = None


class OverlayWindow(QWidget):
    exit_code: int
    finish = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        flags: Qt.WindowFlags | Qt.WindowType = Qt.WindowFlags(),
    ) -> None:
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Chaoscope controls")
        self.setCursor(Qt.CursorShape.BlankCursor)
        self.setFont(FONT)
        self.exit_code = 0

    def on_close(self):
        # Set special exit code to indicate shutdown after exit
        self.exit_code = 2
        self.finish.emit()

    def on_restart(self):
        # Set successful exit code
        self.exit_code = 0
        self.finish.emit()


@dataclass
class PowerState:
    voltage: float | None
    current: float | None
    power: float | None


class PowerReader(QObject):
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

    @pyqtSlot(PowerState)
    def on_power_reading(self, power_state: PowerState):
        self.power_state = power_state
        self.update_ui()


class PowerMonitor(QWidget):
    power_reading = pyqtSignal(PowerState)

    def __init__(
        self,
        parent: QWidget | None = None,
        flags: Qt.WindowFlags | Qt.WindowType = Qt.WindowFlags(),
    ) -> None:
        super().__init__(parent, flags)

        self.voltage_label = PowerLabel(PowerLabelKind.VOLTAGE)
        self.current_label = PowerLabel(PowerLabelKind.CURRENT)
        self.power_label = PowerLabel(PowerLabelKind.POWER)

        self.power_monitor_layout = QHBoxLayout(self)
        self.power_monitor_layout.addWidget(self.voltage_label)
        self.power_monitor_layout.addWidget(self.current_label)
        self.power_monitor_layout.addWidget(self.power_label)

        self.power_reading.connect(self.voltage_label.on_power_reading)
        self.power_reading.connect(self.current_label.on_power_reading)
        self.power_reading.connect(self.power_label.on_power_reading)


class ButtonObject(QObject):
    button: Button
    button_pressed = pyqtSignal()
    button_released = pyqtSignal()

    def __init__(
        self,
        pin: int,
        parent: QWidget | None = None,
    ):
        super().__init__(parent=parent)
        self.button = Button(pin, bounce_time=0.01)
        self.button.when_activated = self.on_button_pressed
        self.button.when_deactivated = self.on_button_released

    def on_button_pressed(self):
        self.button_pressed.emit()

    def on_button_released(self):
        self.button_released.emit()


class ButtonLabel(QLabel):
    button: Button
    button_text: str
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
        self.button_text = name
        self.button_active = False
        self.button = Button(pin, bounce_time=0.01)
        self.button.when_activated = self.on_button_pressed
        self.button.when_deactivated = self.on_button_released
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(TRANSPARENT_STYLESHEET)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.update_ui()

    def update_ui(self):
        self.setText(
            self.button_text if self.button_active else (" " * len(self.button_text))
        )
        self.adjustSize()

    def on_button_pressed(self):
        self.button_active = True
        self.update_ui()
        self.button_pressed.emit()

    def on_button_released(self):
        self.button_active = False
        self.update_ui()
        self.button_released.emit()


class RangeReader(QObject):
    READING_INTERVAL_MS = 40  # 25 Hz for now
    MIN_DISTANCE_CM = 25
    MAX_DISTANCE_CM = 800

    is_reading: bool
    data_ready = pyqtSignal()
    reading = pyqtSignal(float)
    finished = pyqtSignal()
    _i2c: SMBus
    _gpio: DigitalInputDevice
    # # TEMP
    # _timer: QTimer | None

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent=parent)
        self.is_reading = False
        self._timer = None
        # Self-signal to link between threads
        self.data_ready.connect(self.on_data_ready)

    def start(self):
        try:
            # Open I2C bus
            self._i2c = SMBus(1)
            # Set lidar disabled, set trigger mode (frequency to 0)
            self._i2c.write_byte_data(LIDAR_I2C_ADDRESS, LIDAR_REG_ENABLE, 1)
            self._i2c.write_byte_data(LIDAR_I2C_ADDRESS, LIDAR_REG_MODE, 1)
            self._i2c.write_byte_data(LIDAR_I2C_ADDRESS, LIDAR_REG_SAVE, 1)
            self._i2c.write_byte_data(LIDAR_I2C_ADDRESS, LIDAR_REG_REBOOT, 2)
            sleep(0.1)  # guesstimate 100ms
            print("Lidar initialized")
            # Create GPIO input for data-ready pin
            self._gpio = DigitalInputDevice(16)
            # Connect GPIO input to on_data_ready slot
            self._gpio.when_activated = self.data_ready.emit
            # Timer to trigger regular readings
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.on_reading_triggered)
        except Exception as e:
            print(f"Error starting range reader: {e}", file=sys.stderr)
            raise

    def stop(self):
        self.is_reading = False
        self._timer.stop()
        self._timer = None
        self.finished.emit()

    @pyqtSlot()
    def on_start_reading(self):
        # Initial reading if only to clear the register
        self.on_reading_triggered()
        self.on_data_ready()
        self._timer.start(self.READING_INTERVAL_MS)

    @pyqtSlot()
    def on_stop_reading(self):
        self._timer.stop()
        self.is_reading = False
        # Emit special value to indicate no reading
        self.reading.emit(0.0)

    @pyqtSlot()
    def on_reading_triggered(self):
        self.is_reading = True
        self._i2c.write_byte_data(LIDAR_I2C_ADDRESS, LIDAR_REG_TRIGGER, 1)

    @pyqtSlot()
    def on_data_ready(self):
        # For now, early return if not reading - we may have to revisit this if
        # we need to read from the lidar and discard instead
        if not self.is_reading:
            # Emit special value to indicate no reading
            self.reading.emit(0.0)
            return
        # Read distance and amplitude from lidar
        try:
            vals = self._i2c.read_i2c_block_data(LIDAR_I2C_ADDRESS, LIDAR_REG_DIST, 4)
        except OSError as e:
            print(f"Error reading from lidar: {e}", file=sys.stderr)
            self.reading.emit(-1.0)
            return
        dist = (vals[1] << 8) + vals[0]
        amp = (vals[3] << 8) + vals[2]
        # Return special value if too close/far/weak/strong
        if (
            dist < self.MIN_DISTANCE_CM
            or dist > self.MAX_DISTANCE_CM
            or amp < 100
            or amp >= 65535
        ):
            self.reading.emit(-1.0)
        else:
            self.reading.emit(float(dist) / 100.0)


class Reticle(QWidget):
    # TODO: determine from font somehow
    LABEL_HEIGHT = 40
    LABEL_MIN_WIDTH = 100
    RETICLE_LINE_WIDTH = 3

    def __init__(
        self,
        center_x: int,
        center_y: int,
        radius: int,
        enable_reticle: bool = ENABLE_RETICLE,
        parent: QWidget | None = None,
        flags: Qt.WindowFlags | Qt.WindowType = Qt.WindowFlags(),
    ) -> None:
        super().__init__(parent, flags)
        self.center_x = center_x
        self.center_y = center_y
        self.radius = radius
        self.enable_reticle = enable_reticle
        self.outer_radius = radius + self.RETICLE_LINE_WIDTH
        self.text_width = max(self.outer_radius * 2, self.LABEL_MIN_WIDTH)
        self.text = ""
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(TRANSPARENT_STYLESHEET)

        self.setGeometry(
            self.center_x - (self.text_width // 2),
            self.center_y - (self.LABEL_HEIGHT + self.outer_radius),
            self.text_width,
            (self.outer_radius * 2) + self.LABEL_HEIGHT,
        )

    def on_range_reading(self, range: float):
        if range == 0.0:
            # Zero value indicates no reading, clear text
            self.text = ""
        elif range < 0.0:
            # Negative value indicates invalid reading (too close/far/weak/strong)
            self.text = "---"
        else:
            self.text = f"{range:.2f}m"
        self.update()

    def paintEvent(self, event: QPaintEvent):
        qp = QPainter()
        qp.begin(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = event.rect()
        width = rect.width()
        top_left = rect.topLeft()
        center_x = top_left.x() + (width // 2)
        center_y = top_left.y() + self.LABEL_HEIGHT + self.outer_radius
        label_x = top_left.x()
        label_y = top_left.y()
        label_w = width
        label_h = rect.height() - (self.outer_radius * 2)

        if self.text:
            qp.setPen(QPen(Qt.GlobalColor.white))
            qp.setFont(FONT)
            qp.drawText(
                QRect(label_x, label_y, label_w, label_h),
                Qt.AlignmentFlag.AlignCenter,
                self.text,
            )

        if self.enable_reticle:
            qp.setPen(
                QPen(
                    Qt.GlobalColor.white, self.RETICLE_LINE_WIDTH, Qt.PenStyle.SolidLine
                )
            )
            qp.drawEllipse(QPoint(center_x, center_y), self.radius, self.radius)
            # TODO: draw center point when ranging active

        qp.end()


def thread_finisher(thread):
    def finish_thread():
        thread.quit()
        thread.wait()

    return finish_thread


def clear_shutdown_file() -> None:
    if not SHUTDOWN_FILE:
        return
    try:
        SHUTDOWN_FILE.unlink()
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"Error removing shutdown file: {e}", file=sys.stderr)


def write_shutdown_file(exit_code: int) -> None:
    if not SHUTDOWN_FILE:
        return
    value = b"1" if exit_code == 2 else b"0"
    try:
        SHUTDOWN_FILE.write_bytes(value)
    except Exception as e:
        print(f"Error writing shutdown file: {e}", file=sys.stderr)


def main() -> int:
    # Remove shutdown file from previous run, if required
    clear_shutdown_file()

    # Picam setup, 640x480@30
    picam2 = Picamera2()
    preview_config = picam2.create_preview_configuration(
        main={"size": (640, 480)},
        controls={"FrameDurationLimits": (33333, 33333)},
    )
    picam2.configure(preview_config)

    app = QApplication([])

    qpicamera2 = QGlPicamera2(picam2, width=640, height=480, keep_ar=False)
    qpicamera2.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    qpicamera2.setGeometry(0, 0, 640, 480)
    qpicamera2.setWindowTitle("Chaoscope camera")

    overlay_window = OverlayWindow()
    overlay_window.setGeometry(0, 0, 640, 480)

    close_button = QPushButton(overlay_window)
    close_button.setStyleSheet(TRANSLUCENT_STYLESHEET)
    close_button.setFont(FONT_LG)
    close_button.setText("⨯")
    close_button.setGeometry((640 - 60 - 5), 5, 60, 60)
    close_button.clicked.connect(overlay_window.on_close)

    restart_button = QPushButton(overlay_window)
    restart_button.setStyleSheet(TRANSLUCENT_STYLESHEET)
    restart_button.setFont(FONT_LG)
    restart_button.setText("⟳")
    restart_button.setGeometry((640 - 60 - 60 - 20 - 5), 5, 60, 60)
    restart_button.clicked.connect(overlay_window.on_restart)

    button_A = ButtonObject(23, overlay_window)

    button_B = ButtonLabel(24, "Capturing", overlay_window)
    button_B.setGeometry(5, 5, button_B.width(), button_B.height())

    # TODO: get value of enable_reticle from cli arg or something
    reticle = Reticle(320, 275, 50, parent=overlay_window)

    power_monitor = PowerMonitor(overlay_window)
    power_monitor.setGeometry(5, 480 - 5 - 40, 640 - 5 - 5, 40)

    ## Starting properly now
    # TODO: move stop signal to button window and have close button trigger it
    picam2.start()
    qpicamera2.show()

    overlay_window.show()
    overlay_window.raise_()
    overlay_window.activateWindow()

    power_reader = PowerReader()
    power_reader.output.connect(power_monitor.power_reading)
    power_thread = QThread()
    power_reader.moveToThread(power_thread)
    power_thread.started.connect(power_reader.start)
    overlay_window.finish.connect(power_reader.stop)
    power_reader.finished.connect(thread_finisher(power_thread))

    range_reader = RangeReader()
    range_reader.reading.connect(reticle.on_range_reading)
    button_A.button_pressed.connect(range_reader.on_start_reading)
    button_A.button_released.connect(range_reader.on_stop_reading)
    range_thread = QThread()
    range_reader.moveToThread(range_thread)
    range_thread.started.connect(range_reader.start)
    overlay_window.finish.connect(range_reader.stop)
    range_reader.finished.connect(thread_finisher(range_thread))

    def stop_and_exit():
        qpicamera2.close()
        overlay_window.close()
        app.quit()

    overlay_window.finish.connect(stop_and_exit)

    power_thread.start()
    range_thread.start()

    exit_code = 0
    try:
        app.exec()
        exit_code = overlay_window.exit_code
    except KeyboardInterrupt:
        exit_code = 0
    finally:
        picam2.stop()
        # Any other cleanup? Lidar? GPIOs?
        # Write value to shutdown file
        write_shutdown_file(exit_code)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
