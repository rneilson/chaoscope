import os
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from time import sleep
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from picamera2 import CompletedRequest, Picamera2  # type: ignore
    from picamera2.encoders import H264Encoder  # type: ignore
    from picamera2.outputs import PyavOutput  # type: ignore
    from picamera2.previews.qt import QGlPicamera2  # type: ignore

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
from PyQt5.QtWidgets import (
    QPushButton,
    QHBoxLayout,
    QVBoxLayout,
    QApplication,
    QWidget,
    QLabel,
)
from gpiozero import Button, DigitalInputDevice
from smbus2 import SMBus

TRANSLUCENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 63); border: 1px solid white; "
)
TRANSPARENT_STYLESHEET = (
    "color: white; background-color: rgba(255, 255, 255, 0); border: none; "
)
FONT_SM = QFont("Deja Vu Sans Mono", 12)
FONT_MD = QFont("Deja Vu Sans Mono", 18)
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

BASE_DIR = Path(__file__).parent
PHOTO_DIR = BASE_DIR / "photos"

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
        self.setFont(FONT_MD)
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
        self.setFont(FONT_MD)
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
    button_active: bool
    button_pressed = pyqtSignal()
    button_held = pyqtSignal()
    button_released = pyqtSignal()

    def __init__(
        self,
        pin: int,
        hold_time: float | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent=parent)
        button_args = {"bounce_time": 0.01}
        if hold_time is not None:
            button_args["hold_time"] = hold_time
            # button_args["hold_repeat"] = True
        self.button = Button(pin, **button_args)
        self.button_active = False
        self.button.when_activated = self.on_button_pressed
        self.button.when_deactivated = self.on_button_released
        if hold_time is not None:
            self.button.when_held = self.on_button_held

    def on_button_held(self):
        self.button_held.emit()

    def on_button_pressed(self):
        self.button_active = True
        self.button_pressed.emit()

    def on_button_released(self):
        self.button_active = False
        self.button_released.emit()


class CameraCapturer(QWidget):
    CAPTURE_LABEL_LEN: int = 16
    METADATA_LINE_LEN: int = 24
    METADATA_LINES: int = 10

    def __init__(
        self,
        pin: int,
        picam2: "Picamera2",
        qpicamera2: "QGlPicamera2",
        parent: QWidget | None = None,
        flags: Qt.WindowFlags | Qt.WindowType = Qt.WindowFlags(),
    ):
        super().__init__(parent, flags)
        self.capturing = False
        self.img_filename: str | None = None
        self.img_metadata: dict[str, Any] | None = None
        self._timer: QTimer | None = None

        self.recording = False
        self.vid_filename: str | None = None
        self.vid_started_at: datetime | None = None
        self.vid_finished_at: datetime | None = None

        self.button_obj = ButtonObject(pin, hold_time=0.5, parent=self)
        self.capture_label = QLabel()
        self.metadata_label = QLabel()
        self.layout_v = QVBoxLayout(self)

        self.picam2 = picam2
        self.qpicamera2 = qpicamera2

        self.button_obj.button_held.connect(self.on_button_held)
        self.button_obj.button_pressed.connect(self.on_button_pressed)
        self.button_obj.button_released.connect(self.on_button_released)
        self.qpicamera2.done_signal.connect(self.on_capture_done)
        # For now we'll handle requests ourselves
        # self.picam2.post_callback = self.on_completed_request

        self._blank_lines = "\n".join(
            [(" " * self.METADATA_LINE_LEN) for _ in range(self.METADATA_LINES)]
        )
        self.init_ui()

    def init_ui(self) -> None:
        self.capture_label.setFont(FONT_MD)
        self.setStyleSheet(TRANSPARENT_STYLESHEET)
        self.capture_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.capture_label.setTextFormat(Qt.TextFormat.PlainText)
        self.capture_label.setText(" " * len(self._img_filename(0)))

        self.metadata_label.setFont(FONT_SM)
        self.setStyleSheet(TRANSPARENT_STYLESHEET)
        self.metadata_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.metadata_label.setTextFormat(Qt.TextFormat.PlainText)
        self.metadata_label.setText(self._blank_lines)

        self.layout_v.addWidget(self.capture_label)
        self.layout_v.addWidget(self.metadata_label)

        self.update_ui()

    def update_ui(self):
        label_len = self.CAPTURE_LABEL_LEN
        if self.recording:
            time_str = self._get_recording_time()
            self.capture_label.setText(f"Rec {time_str}".ljust(label_len))
        elif self.vid_filename is not None:
            self.capture_label.setText(
                (self.vid_filename or "<error>").ljust(label_len)
            )
        elif self.capturing:
            self.capture_label.setText("Capturing...".ljust(label_len))
        elif self.img_filename is not None:
            self.capture_label.setText(
                (self.img_filename or "<error>").ljust(label_len)
            )
        else:
            self.capture_label.setText(" " * label_len)

        if self.recording:
            self.metadata_label.setText(self._blank_lines)
        elif self.vid_finished_at:
            time_str = self._get_recording_time()
            # TODO: parameterize encoding/format if we ever vary them
            self.metadata_label.setText(
                f"Duration: {time_str}\n" f"Encoding: H264\n" f"Format: MP4\n"
            )
        elif self.img_metadata:
            self.metadata_label.setText(
                "\n".join(f"{k}: {v}" for k, v in self._get_display_metadata().items())
            )
        else:
            self.metadata_label.setText(self._blank_lines)

        self.capture_label.adjustSize()
        self.metadata_label.adjustSize()
        self.adjustSize()

    def on_completed_request(self, request: "CompletedRequest") -> None:
        counter = self._get_next_counter()
        self.img_filename = self._img_filename(counter)
        self.img_metadata = request.get_metadata()
        # TODO: grab array and release request early, then save?
        request.save("main", str(PHOTO_DIR / self.img_filename))
        request.release()
        self._write_counter(counter)
        # TODO: get lowres preview image?

    @pyqtSlot()
    def on_button_held(self) -> None:
        if not self.recording:
            self._start_record()
        self.update_ui()

    @pyqtSlot()
    def on_button_pressed(self) -> None:
        if not self.capturing:
            self._start_capture()
        self.update_ui()

    @pyqtSlot()
    def on_button_released(self) -> None:
        if self.recording:
            self._finish_record()
        self.update_ui()

    @pyqtSlot(object)
    def on_capture_done(self, job: object) -> None:
        self._finish_capture(job)
        self.update_ui()

    @pyqtSlot()
    def on_clear(self) -> None:
        if not self.capturing:
            self.img_filename = None
            self.img_metadata = None
        if not self.recording:
            self.vid_filename = None
            self.vid_started_at = None
            self.vid_finished_at = None
        self._clear_timer()
        self.update_ui()

    def _img_filename(self, counter: int) -> str:
        return f"img_{counter:06}.jpg"

    def _vid_filename(self, counter: int) -> str:
        return f"vid_{counter:06}.mp4"

    def _get_next_counter(self) -> int:
        counter_file = PHOTO_DIR / "counter"
        try:
            last_counter = counter_file.read_text().strip()
        except FileNotFoundError:
            last_counter = "000000"
        counter = int(last_counter) + 1
        return counter

    def _write_counter(self, counter: int) -> None:
        counter_file = PHOTO_DIR / "counter"
        counter_file.write_text(f"{counter:06}")

    def _get_display_metadata(self) -> dict[str, Any]:
        metadata = {}
        if not self.img_metadata:
            return metadata

        keys = ("SensorTimestamp", "ExposureTime", "AnalogueGain", "DigitalGain")
        for key in keys:
            if key not in self.img_metadata:
                continue
            value = self.img_metadata[key]
            if isinstance(value, float):
                value = f"{value:.4f}"
            metadata[key] = value

        return metadata

    def _get_recording_time(self):
        if not self.vid_started_at:
            return "--:--:--"

        duration = (self.vid_finished_at or datetime.now()) - self.vid_started_at
        dur_secs = round(duration.total_seconds())
        hours = dur_secs // 3600
        mins = dur_secs // 60 % 60
        secs = dur_secs % 60

        return f"{hours:02}:{mins:02}:{secs:02}"

    def _clear_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _start_timer(self, ms=3000) -> None:
        self._clear_timer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.on_clear)
        self._timer.setSingleShot(True)
        self._timer.start(ms)

    def _start_capture(self) -> None:
        self.capturing = True
        self.picam2.capture_request(
            wait=False,
            signal_function=self.qpicamera2.signal_done,
        )
        self._clear_timer()

    def _finish_capture(self, job: object) -> None:
        request: "CompletedRequest" = self.picam2.wait(job)
        # TODO: run on_completed_request in another thread?
        self.on_completed_request(request)
        self.capturing = False
        # Clear filename/metadata after three seconds
        self._start_timer()

    def _start_record(self) -> None:
        self.recording = True

        # Get video filename
        counter = self._get_next_counter()
        self.vid_filename = self._vid_filename(counter)
        self._write_counter(counter)

        from picamera2.encoders import H264Encoder  # type: ignore
        from picamera2.outputs import PyavOutput  # type: ignore

        # Start recording
        # TODO: set up a CircularOutput2 as well so we make up the half-second
        # we're currently waiting for the on_button_held signal
        encoder = H264Encoder(repeat=True)
        output = PyavOutput(str(PHOTO_DIR / self.vid_filename))
        self.picam2.start_encoder(encoder, output)
        self.vid_started_at = datetime.now()

        # Timer to refresh the recording duration in the UI
        self._clear_timer()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update_ui)
        self._timer.start(200)  # Adjust as needed

    def _finish_record(self) -> None:
        if self.recording:
            # Stop recording
            self.picam2.stop_encoder()

            self.vid_finished_at = datetime.now()
            self.recording = False

        # Clear filename/time after three seconds
        self._start_timer()


class RangeReader(QObject):
    READING_INTERVAL_MS = 40  # 25 Hz for now
    MIN_DISTANCE_CM = 25
    MAX_DISTANCE_CM = 800

    is_reading: bool
    data_ready = pyqtSignal()
    reading = pyqtSignal(float)
    finished = pyqtSignal()
    _i2c: SMBus | None
    _gpio: DigitalInputDevice | None
    _timer: QTimer | None

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
            qp.setFont(FONT_MD)
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

    print("Starting chaoscope...")

    # Doing this here so it doesn't cause delays elsewhere
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)

    app = QApplication([])

    ## Main window
    overlay_window = OverlayWindow()
    overlay_window.setGeometry(0, 0, 640, 480)

    ## Restart/exit buttons
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

    ## Power monitoring
    power_monitor = PowerMonitor(overlay_window)
    power_monitor.setGeometry(5, 480 - 5 - 40, 640 - 5 - 5, 40)

    power_reader = PowerReader()
    power_reader.output.connect(power_monitor.power_reading)

    power_thread = QThread()
    power_reader.moveToThread(power_thread)
    power_thread.started.connect(power_reader.start)
    overlay_window.finish.connect(power_reader.stop)
    power_reader.finished.connect(thread_finisher(power_thread))

    ## Lidar rangefinder
    range_button = ButtonObject(23, parent=overlay_window)

    # TODO: get value of enable_reticle from cli arg or something
    reticle = Reticle(320, 275, 50, parent=overlay_window)

    range_reader = RangeReader()
    range_reader.reading.connect(reticle.on_range_reading)
    range_button.button_pressed.connect(range_reader.on_start_reading)
    range_button.button_released.connect(range_reader.on_stop_reading)

    range_thread = QThread()
    range_reader.moveToThread(range_thread)
    range_thread.started.connect(range_reader.start)
    overlay_window.finish.connect(range_reader.stop)
    range_reader.finished.connect(thread_finisher(range_thread))

    to_run_on_stop: list[Callable] = []
    to_run_on_exit: list[Callable] = []

    def stop_and_exit():
        for func in to_run_on_stop:
            func()
        overlay_window.close()
        app.quit()

    overlay_window.finish.connect(stop_and_exit)

    # Put into a function so we can defer importing picamera2 stuff
    def start_and_setup_camera():
        from picamera2 import CompletedRequest, Picamera2, libcamera  # type: ignore
        from picamera2.encoders import H264Encoder  # type: ignore
        from picamera2.outputs import PyavOutput  # type: ignore
        from picamera2.previews.qt import QGlPicamera2  # type: ignore

        ## Picam setup, preview 640x480, video 1280x720, still half-size, 30fps
        # TODO: move to below rest of GUI setup
        picam2 = Picamera2()
        video_config = picam2.create_video_configuration(
            main={
                "size": tuple(ndim // 2 for ndim in picam2.sensor_resolution),
                "format": "XBGR8888",
                "preserve_ar": True,
            },
            lores={
                "size": (1280, 720),
                "format": "YUV420",
                "preserve_ar": False,
            },
            controls={
                "FrameDurationLimits": (33333, 33333),
                "NoiseReductionMode": libcamera.controls.draft.NoiseReductionModeEnum.Fast,
            },
            buffer_count=6,
            display="main",
            encode="lores",
        )
        picam2.configure(video_config)
        to_run_on_exit.append(picam2.stop)

        qpicamera2 = QGlPicamera2(picam2, width=640, height=480, keep_ar=False)
        qpicamera2.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        qpicamera2.setGeometry(0, 0, 640, 480)
        qpicamera2.setWindowTitle("Chaoscope camera")
        to_run_on_stop.append(qpicamera2.close)

        ## Photo capture
        capture_button = CameraCapturer(
            pin=24,
            picam2=picam2,
            qpicamera2=qpicamera2,
            parent=overlay_window,
        )
        capture_button.setGeometry(
            5, 5, capture_button.width(), capture_button.height()
        )
        capture_button.show()

        ## Starting properly now
        picam2.start()
        qpicamera2.show()
        overlay_window.raise_()

    overlay_window.show()
    overlay_window.raise_()
    overlay_window.activateWindow()

    power_thread.start()
    range_thread.start()

    start_and_setup_camera()

    exit_code = 0
    try:
        app.exec()
        exit_code = overlay_window.exit_code
    except KeyboardInterrupt:
        exit_code = 0
    finally:
        for func in to_run_on_exit:
            func()
        # Any other cleanup? Lidar? GPIOs?
        # Write value to shutdown file
        write_shutdown_file(exit_code)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
