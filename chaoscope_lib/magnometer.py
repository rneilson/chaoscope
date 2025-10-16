from dataclasses import asdict, dataclass
from pathlib import Path
from time import sleep
from typing import Any, Callable, Self, Sequence, TypeAlias

import numpy as np
from scipy import linalg
from smbus2 import SMBus

from .i2c import I2CDevice

OFFSET_X_REG_L_M = 0x05
CTRL_REG1 = 0x20
CTRL_REG2 = 0x21
CTRL_REG3 = 0x22
CTRL_REG4 = 0x23
CTRL_REG5 = 0x24
STATUS_REG = 0x27
OUT_X_L = 0x28


Array3: TypeAlias = np.ndarray[tuple[3], np.dtype[np.float32]]
ArrayNx3: TypeAlias = np.ndarray[tuple[int, 3], np.dtype[np.float32]]
Array3x3: TypeAlias = np.ndarray[tuple[3, 3], np.dtype[np.float32]]
Tuple3Float: TypeAlias = tuple[float, float, float]
Tuple3x3Float: TypeAlias = tuple[Tuple3Float, Tuple3Float, Tuple3Float]


@dataclass
class MagnometerCalibration:
    hard_offsets: Tuple3Float
    soft_offsets: Tuple3x3Float
    mag_field: float

    def asdict(self):
        return asdict(self)

    @classmethod
    def fromdict(cls, data: dict[str, Any]) -> Self:
        hard_offsets = tuple(data["hard_offsets"])
        soft_offsets = tuple(tuple(row) for row in data["soft_offsets"])
        mag_field = float(data["mag_field"])
        return cls(
            hard_offsets=hard_offsets,
            soft_offsets=soft_offsets,
            mag_field=mag_field,
        )


class Magnometer(I2CDevice):
    I2C_ADDR = 0x1C
    WHO_AM_I_REG = 0x0F
    WHO_AM_I_VAL = 0x3D

    # At some point these could be made adjustable
    data_rate = 155  # Hz
    mag_scale = 4.0  # gauss
    mag_sens = 6842  # LSB/gauss

    def __init__(
        self,
        i2c: SMBus,
        hard_offsets: Sequence[float] = (0.0, 0.0, 0.0),
        soft_offsets: Sequence[Sequence[float]] | None = None,
        mag_field: int | float = 1000,  # uT
    ) -> None:
        super().__init__(i2c)
        self._hard_offsets = np.array(hard_offsets, dtype=np.float32)
        self._soft_offsets = np.array(soft_offsets or np.eye(3), dtype=np.float32)
        self._mag_field = float(mag_field)
        assert self._hard_offsets.shape == (3,)
        assert self._soft_offsets.shape == (3, 3)

    def reset(self) -> None:
        self.set_register_bit(CTRL_REG2, 2, True)
        while self.get_register_bit(CTRL_REG2, 2):
            sleep(0.001)

    def setup(self) -> None:
        self.reset()

        ## Block data update
        # The Adafruit library sets this by default, so let's do the same and
        # see how it goes
        self.set_register_bit(CTRL_REG5, 6, True)

        ## Rate config
        reg_val = 0
        # Performance mode - go with ultra-high
        reg_val += 0b11 << 5
        # Data rate selection - go with fast-ODR, 155 Hz
        reg_val += 0b0001 << 1
        # Remaining lower bit 0
        self._i2c.write_byte_data(self.I2C_ADDR, CTRL_REG1, reg_val)

        ## Scale config
        reg_val = 0
        # Scale selection - go with 4 gauss
        reg_val += 0b00 << 5
        # Remaining bits 0
        self._i2c.write_byte_data(self.I2C_ADDR, CTRL_REG2, reg_val)

        ## Set x/y-axis mode to continuous, low-power off
        self._i2c.write_byte_data(self.I2C_ADDR, CTRL_REG3, 0)

        ## Set z-axis performance mode to ultra-high
        reg_val = 0b11 << 2
        # Remaining bits 0, little-endian and fixed 0
        self._i2c.write_byte_data(self.I2C_ADDR, CTRL_REG4, 0)

        ## Let settle
        sleep(0.01)

    def get_raw_mag(self) -> tuple[int, int, int]:
        return self.get_measurement_vector(OUT_X_L)

    def _scale_raw_mag(self, raw_value: int) -> float:
        scaled_value = raw_value / self.mag_sens  # in gauss
        if scaled_value > self.mag_scale:
            return self.mag_scale
        if scaled_value < -self.mag_scale:
            return -self.mag_scale
        return scaled_value * 100  # in uT

    def _get_scaled_mag_array(self) -> Array3:
        """
        Get magnetometer measurement vector, scaled to current range in uT,
        as numpy ndarray of shape (1, 3).
        """
        raw_x, raw_y, raw_z = self.get_raw_mag()
        x = self._scale_raw_mag(raw_x)
        y = self._scale_raw_mag(raw_y)
        z = self._scale_raw_mag(raw_z)
        return np.array([x, y, z], dtype=np.float32)

    def _get_corrected_mag_array(self, scaled: Array3 | ArrayNx3) -> Array3 | ArrayNx3:
        """
        Get magnetometer measurement vector corrected with hard- and soft-iron
        offsets, from vector scaled to current range in uT, as numpy ndarray of
        shape (3,) or (n, 3), depending on input.
        """
        return (scaled - self._hard_offsets) @ self._soft_offsets

    def get_scaled_mag(self) -> Tuple3Float:
        scaled = self._get_scaled_mag_array()
        corrected = self._get_corrected_mag_array(scaled)
        return tuple(float(v) for v in corrected.flatten())

    def _ellipsoid_fit(
        self,
        s: np.ndarray[tuple[3, int], np.dtype[np.float32]],
    ) -> tuple[np.ndarray, np.ndarray, float]:
        """
        Estimate ellipsoid parameters from a set of points.
        Adapted from:
        https://github.com/nliaudat/magnetometer_calibration/blob/main/calibrate.py

        References
        ----------
        .. [1] Qingde Li; Griffiths, J.G., "Least squares ellipsoid specific
            fitting," in Geometric Modeling and Processing, 2004.
            Proceedings, vol., no., pp.335-340, 2004
        """
        # D (samples)
        D = np.array(
            [
                s[0] ** 2.0,
                s[1] ** 2.0,
                s[2] ** 2.0,
                2.0 * s[1] * s[2],
                2.0 * s[0] * s[2],
                2.0 * s[0] * s[1],
                2.0 * s[0],
                2.0 * s[1],
                2.0 * s[2],
                np.ones_like(s[0]),
            ]
        )

        # S, S_11, S_12, S_21, S_22 (eq. 11)
        S = np.dot(D, D.T)
        S_11 = S[:6, :6]
        S_12 = S[:6, 6:]
        S_21 = S[6:, :6]
        S_22 = S[6:, 6:]

        # C (Eq. 8, k=4)
        C = np.array(
            [
                [-1, 1, 1, 0, 0, 0],
                [1, -1, 1, 0, 0, 0],
                [1, 1, -1, 0, 0, 0],
                [0, 0, 0, -4, 0, 0],
                [0, 0, 0, 0, -4, 0],
                [0, 0, 0, 0, 0, -4],
            ]
        )

        # v_1 (eq. 15, solution)
        E = np.dot(linalg.inv(C), S_11 - np.dot(S_12, np.dot(linalg.inv(S_22), S_21)))

        E_w, E_v = np.linalg.eig(E)
        v_1 = E_v[:, np.argmax(E_w)]
        if v_1[0] < 0:
            v_1 = -v_1

        # v_2 (eq. 13, solution)
        v_2 = np.dot(np.dot(-np.linalg.inv(S_22), S_21), v_1)

        # quadratic-form parameters, parameters h and f swapped as per
        # correction by Roger R on Teslabs page
        M = np.array(
            [
                [v_1[0], v_1[5], v_1[4]],
                [v_1[5], v_1[1], v_1[3]],
                [v_1[4], v_1[3], v_1[2]],
            ]
        )
        n = np.array([[v_2[0]], [v_2[1]], [v_2[2]]])
        d = v_2[3]

        return M, n, d

    def run_mag_calibration(
        self,
        secs: int = 10,
        hz: int = 40,
        on_measurement: Callable[[float, float, float], None] | None = None,
        raw_measurement_file: Path | str | None = None,
        calibrated_measurement_file: Path | str | None = None,
    ) -> MagnometerCalibration:
        """
        Run calibration routine for `secs` at measurement frequency `hz`, calling
        `on_measurement` if given, and return hard-iron and soft-iron offsets.
        """
        # Calibration params adapted from
        # https://github.com/nliaudat/magnetometer_calibration/blob/main/calibrate.py

        num_samples = secs * hz
        sleep_time = 1.0 / hz

        data = np.zeros([num_samples, 3], dtype=np.float32)

        for idx in range(num_samples):
            x, y, z = (float(v) for v in self._get_scaled_mag_array())
            data[idx] = [x, y, z]

            if on_measurement:
                on_measurement(x, y, z)

            sleep(sleep_time)

        # Save raw data if requested
        if raw_measurement_file:
            save_to = Path(raw_measurement_file)
            np.savetxt(save_to, data, delimiter=",")

        # Ellipsoid fit
        M, n, d = self._ellipsoid_fit(data.T)

        # Calculate calibration parameters
        M_1 = linalg.inv(M)
        # hard iron
        b: np.ndarray = -np.dot(M_1, n)
        # soft iron
        F = self._mag_field
        A_1: np.ndarray = np.real(
            F / np.sqrt(np.dot(n.T, np.dot(M_1, n)) - d) * linalg.sqrtm(M)
        )

        self._hard_offsets = b.T.flatten()
        self._soft_offsets = A_1.T

        if calibrated_measurement_file:
            save_to = Path(calibrated_measurement_file)
            corrected = self._get_corrected_mag_array(data)
            np.savetxt(save_to, corrected, delimiter=",")

        return MagnometerCalibration(
            hard_offsets=self._hard_offsets.tolist(),
            soft_offsets=self._soft_offsets.tolist(),
            mag_field=self._mag_field,
        )
