import json
import sys
from pathlib import Path
from time import sleep

from ahrs import DEG2RAD, RAD2DEG

# from ahrs.common.orientation import ecompass
from ahrs.common.quaternion import Quaternion
from ahrs.filters.tilt import Tilt
from numpy import array
from smbus2 import SMBus

from chaoscope_lib.inertial import IMU, ONE_G
from chaoscope_lib.magnometer import Magnometer, MagnometerCalibration

BASE_DIR = Path(__file__).parent.resolve()
CAL_FILE = BASE_DIR / "calibration.json"


def write_stdout(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def hide_cursor() -> None:
    write_stdout("\033[?25l")


def show_cursor() -> None:
    write_stdout("\033[?25h")


def test_accel(
    i2c_bus_num: int,
    mag_calibration: MagnometerCalibration,
) -> None:
    i2c = SMBus(i2c_bus_num)
    imu_obj = IMU(i2c)
    mag_obj = Magnometer(
        i2c,
        hard_offsets=mag_calibration.hard_offsets,
        soft_offsets=mag_calibration.soft_offsets,
        mag_field=mag_calibration.mag_field,
    )

    print("Testing accelerometer...")
    # input("Press enter when ready:")
    print()

    # For rotating to NED frame
    qr = Quaternion(rpy=array([0.0, 0.0, 90.0]) * DEG2RAD)

    while True:
        acc_out = imu_obj.get_scaled_accel()
        mag_out = mag_obj.get_scaled_mag()

        acc = array([v * ONE_G for v in acc_out])  # m/s^2
        mag = array(mag_out)  # uT

        heading = Quaternion(
            Tilt().estimate(acc=acc * -1, mag=mag, representation="quaternion")
        )
        heading_rot = Quaternion(heading * qr)
        ax, ay, az = acc_out
        mx, my, mz = mag_out
        roll, pitch, yaw = (float(v) for v in (heading_rot.to_angles() * RAD2DEG))

        write_stdout(
            f"\rax: {ax: 6.3f} ay: {ay: 6.3f} az: {az: 6.3f} "
            f"mx: {mx: 6.1f} my: {my: 6.1f} mz: {mz: 6.1f} "
            f"R: {roll: 4.0f}° P: {pitch: 4.0f}° Y: {yaw: 4.0f}°"
        )

        sleep(0.1)


if __name__ == "__main__":
    hide_cursor()
    try:
        cal_data = json.loads(CAL_FILE.read_text())
        test_accel(1, MagnometerCalibration.fromdict(cal_data["magnometer"]))
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        show_cursor()
        print()
