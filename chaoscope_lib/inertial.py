from statistics import fmean
from time import sleep
from typing import Callable

from smbus2 import SMBus

from .i2c import I2CDevice

INT1_CTRL = 0x0D
INT2_CTRL = 0x0E
CTRL1_XL = 0x10
CTRL2_G = 0x11
CTRL3_C = 0x12
CTRL9_XL = 0x18
STATUS_REG = 0x1E
OUTX_L_G = 0x22
OUTX_L_A = 0x28

MILLI_G = 0.00980665  # m/s^2


class IMU(I2CDevice):
    I2C_ADDR = 0x6A
    WHO_AM_I_REG = 0x0F
    WHO_AM_I_VAL = 0x6C

    # At some point these could be made adjustable
    data_rate = 104  # Hz
    accel_scale = 4  # g
    accel_sens = 0.122  # milli-g/LSB
    gyro_scale = 500  # deg/sec
    gyro_sens = 17.5  # milli-deg/sec/LSB

    def __init__(
        self, i2c: SMBus, gyro_offsets: tuple[float, float, float] = (0.0, 0.0, 0.0)
    ) -> None:
        super().__init__(i2c)
        self._gyro_offset_x = gyro_offsets[0]
        self._gyro_offset_y = gyro_offsets[1]
        self._gyro_offset_z = gyro_offsets[2]

    def reset(self):
        self.set_register_bit(CTRL3_C, 0, True)
        while self.get_register_bit(CTRL3_C, 0):
            sleep(0.001)

    def setup(self):
        self.reset()

        ## Disable I3C mode
        self.set_register_bit(CTRL9_XL, 1, True)

        ## Block data update
        # The Adafruit library sets this by default, so let's do the same and
        # see how it goes
        self.set_register_bit(CTRL3_C, 6, True)

        ## Accel config
        reg_val = 0
        # Data rate selection - go with 104 Hz
        reg_val += 0b0100 << 4
        # Scale selection - go with 4g
        reg_val += 0b10 << 2
        # Remaining lower 2 bits 00
        self._i2c.write_byte_data(self.I2C_ADDR, CTRL1_XL, reg_val)

        ## Gyro config
        reg_val = 0
        # Data rate selection - go with 104 Hz
        reg_val += 0b0100 << 4
        # Scale selection - go with 500 dps
        reg_val += 0b01 << 2
        # Remaining lower 2 bits 00
        self._i2c.write_byte_data(self.I2C_ADDR, CTRL2_G, reg_val)

        ## Let settle
        sleep(0.1)

    def get_raw_accel(self) -> tuple[int, int, int]:
        return self.get_measurement_vector(OUTX_L_A)

    def _scale_raw_accel(self, raw_value: int) -> float:
        scaled_value = raw_value * self.accel_sens / 1_000  # g
        # Return +/- saturated value if reached
        # This could raise instead, as the value isn't supposed to be valid
        if scaled_value > self.accel_scale:
            return self.accel_scale
        if scaled_value < -self.accel_scale:
            return -self.accel_scale
        # Value in valid range
        return scaled_value

    def get_scaled_accel(self) -> tuple[float, float, float]:
        """
        Get accelerometer measurement vector, scaled to current range in g.
        """
        raw_x, raw_y, raw_z = self.get_raw_accel()
        x = self._scale_raw_accel(raw_x)
        y = self._scale_raw_accel(raw_y)
        z = self._scale_raw_accel(raw_z)
        return x, y, z

    def get_raw_gyro(self) -> tuple[int, int, int]:
        return self.get_measurement_vector(OUTX_L_G)

    def _scale_raw_gyro(self, raw_value: int) -> float:
        scaled_value = raw_value * self.gyro_sens / 1_000  # deg/sec
        # Return +/- saturated value if reached
        # This could raise instead, as the value isn't supposed to be valid
        if scaled_value > self.gyro_scale:
            return self.gyro_scale
        if scaled_value < -self.gyro_scale:
            return -self.gyro_scale
        # Value in valid range
        return scaled_value

    def get_scaled_gyro(self) -> tuple[float, float, float]:
        """
        Get gyroscope measurement vector, scaled to current range in deg/sec.
        """
        raw_x, raw_y, raw_z = self.get_raw_gyro()
        x = self._scale_raw_gyro(raw_x) - self._gyro_offset_x
        y = self._scale_raw_gyro(raw_y) - self._gyro_offset_y
        z = self._scale_raw_gyro(raw_z) - self._gyro_offset_z
        return x, y, z

    def run_gyro_calibration(
        self,
        secs: int = 10,
        hz: int = 25,
        on_measurement: Callable[[float, float, float], None] | None = None,
    ) -> tuple[float, float, float]:
        """
        Run calibration routine for `secs` at measurement frequency `hz`, calling
        `on_measurement` if given, and return a vector of zero-rate offsets in
        deg/sec.
        """
        self._gyro_offset_x = 0.0
        self._gyro_offset_y = 0.0
        self._gyro_offset_z = 0.0

        x_vals = []
        y_vals = []
        z_vals = []

        num_samples = secs * hz
        sleep_time = 1.0 / hz

        for _ in range(num_samples):
            x, y, z = self.get_scaled_gyro()

            x_vals.append(x)
            y_vals.append(y)
            z_vals.append(z)

            if on_measurement:
                on_measurement(x, y, z)

            sleep(sleep_time)

        # Use the arithmetic mean of the samples
        self._gyro_offset_x = fmean(x_vals)
        self._gyro_offset_y = fmean(y_vals)
        self._gyro_offset_z = fmean(z_vals)

        return (self._gyro_offset_x, self._gyro_offset_y, self._gyro_offset_z)
