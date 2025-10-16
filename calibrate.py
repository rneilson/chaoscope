import json
import sys
from pathlib import Path
from typing import Any

from smbus2 import SMBus

from chaoscope_lib.inertial import IMU
from chaoscope_lib.magnometer import Magnometer

BASE_DIR = Path(__file__).parent.resolve()
CAL_FILE = BASE_DIR / "calibration.json"
RAW_MAG_FILE = BASE_DIR / "raw_mag.txt"
CAL_MAG_FILE = BASE_DIR / "cal_mag.txt"


def write_stdout(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def hide_cursor() -> None:
    write_stdout("\033[?25l")


def show_cursor() -> None:
    write_stdout("\033[?25h")


def calibrate(i2c_bus_num: int) -> dict[str, Any]:
    """
    Calibrate gyroscope, then magnometer.
    """
    i2c = SMBus(i2c_bus_num)
    imu = IMU(i2c)
    mag = Magnometer(i2c)

    def gyro_measurement(x: float, y: float, z: float) -> None:
        write_stdout(f"\r[Gyro] X: {x: 8.5f} Y: {y: 8.5f} Z: {z: 8.5f}")

    def acc_measurement(x: float, y: float, z: float) -> None:
        write_stdout(f"\r[Acc]  X: {x: 8.5f} Y: {y: 8.5f} Z: {z: 8.5f}")

    def mag_measurement(x: float, y: float, z: float) -> None:
        write_stdout(f"\r[Mag]  X: {x: 8.1f} Y: {y: 8.1f} Z: {z: 8.1f}")

    ## Gyroscope

    print("\nCalibrating gyroscope...")
    input("Lie device flat and press enter to continue:")
    print()
    gyro_offsets = imu.run_gyro_calibration(on_measurement=gyro_measurement)
    print("\n")

    ## Accelerometer

    print("Calibrating accelerometer...")

    input("Lie device with z-axis up and press enter to continue:")
    print()
    imu.run_acc_calibration(on_measurement=acc_measurement)
    print("\n")

    # input("Lie device with y-axis up and press enter to continue:")
    # print()
    # imu.run_acc_calibration(on_measurement=acc_measurement)
    # print("\n")

    # input("Lie device with x-axis up and press enter to continue:")
    # print()
    # imu.run_acc_calibration(on_measurement=acc_measurement)
    # print("\n")

    ## Magnometer

    print("Calibrating magnometer...")
    input("Press enter to continue:")
    print()

    mag_offsets = mag.run_mag_calibration(
        on_measurement=mag_measurement,
        raw_measurement_file=RAW_MAG_FILE,
        calibrated_measurement_file=CAL_MAG_FILE,
    )
    print("\n")

    print("Final calibrations:")
    gx, gy, gz = gyro_offsets
    mx, my, mz = mag_offsets.hard_offsets
    s0, s1, s2 = mag_offsets.soft_offsets
    print(f"[Gyro] X: {gx: 8.5f} Y: {gy: 8.5f} Z: {gz: 8.5f}")
    print(f"[Mag]  X: {mx: 8.5f} Y: {my: 8.5f} Z: {mz: 8.5f}")
    print(f"[Mag] [ [ {s0[0]: 8.5f}, {s0[1]: 8.5f}, {s0[2]: 8.5f} ],  ")
    print(f"[Mag]   [ {s1[0]: 8.5f}, {s1[1]: 8.5f}, {s1[2]: 8.5f} ],  ")
    print(f"[Mag]   [ {s2[0]: 8.5f}, {s2[1]: 8.5f}, {s2[2]: 8.5f} ], ]")

    return {
        "gyroscope": list(gyro_offsets),
        "magnometer": mag_offsets.asdict(),
    }


if __name__ == "__main__":
    hide_cursor()
    try:
        cal_data = calibrate(1)
        CAL_FILE.write_text(json.dumps(cal_data))
    finally:
        show_cursor()
