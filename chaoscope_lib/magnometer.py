from time import sleep
from typing import Callable

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


class Magnometer(I2CDevice):
    I2C_ADDR = 0x1C
    WHO_AM_I_REG = 0x0F
    WHO_AM_I_VAL = 0x3D

    # At some point these could be made adjustable
    data_rate = 155  # Hz
    mag_scale = 4.0  # gauss
    mag_sens = 6842  # LSB/gauss

    def __init__(
        self, i2c: SMBus, mag_offsets: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ) -> None:
        super().__init__(i2c)
        self._mag_offset_x = mag_offsets[0]
        self._mag_offset_y = mag_offsets[1]
        self._mag_offset_z = mag_offsets[2]

    def reset(self):
        self.set_register_bit(CTRL_REG2, 2, True)
        while self.get_register_bit(CTRL_REG2, 2):
            sleep(0.001)

    def setup(self):
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
        return scaled_value

    def get_scaled_mag(self) -> tuple[float, float, float]:
        """
        Get magnetometer measurement vector, scaled to current range in gauss.
        """
        raw_x, raw_y, raw_z = self.get_raw_mag()
        x = self._scale_raw_mag(raw_x - self._mag_offset_x)
        y = self._scale_raw_mag(raw_y - self._mag_offset_y)
        z = self._scale_raw_mag(raw_z - self._mag_offset_z)
        return x, y, z

    def run_mag_calibration(
        self,
        secs: int = 10,
        hz: int = 40,
        on_measurement: Callable[[float, float, float], None] | None = None,
    ) -> tuple[float, float, float]:
        """
        Run calibration routine for `secs` at measurement frequency `hz`, calling
        `on_measurement` if given, and return a vector of hard-iron offsets in
        LSB/gauss.
        """
        self._mag_offset_x = 0.0
        self._mag_offset_y = 0.0
        self._mag_offset_z = 0.0

        init_x, init_y, init_z = self.get_raw_mag()
        min_x = max_x = init_x
        min_y = max_y = init_y
        min_z = max_z = init_z

        num_samples = secs * hz
        sleep_time = 1.0 / hz

        for _ in range(num_samples):
            x, y, z = self.get_raw_mag()

            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
            min_z = min(min_z, z)
            max_z = max(max_z, z)

            if on_measurement:
                on_measurement(x, y, z)

            sleep(sleep_time)

        # Use the midpoint of the samples
        self._mag_offset_x = (min_x + max_x) / 2
        self._mag_offset_y = (min_y + max_x) / 2
        self._mag_offset_z = (min_z + max_x) / 2

        return (self._mag_offset_x, self._mag_offset_y, self._mag_offset_z)
