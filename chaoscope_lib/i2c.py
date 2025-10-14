import struct
from abc import ABC, abstractmethod

from smbus2 import SMBus

measure_vec_struct = struct.Struct("<hhh")


class I2CDevice(ABC):
    I2C_ADDR: int
    WHO_AM_I_REG: int
    WHO_AM_I_VAL: int

    def __init__(self, i2c: SMBus) -> None:
        self._i2c = i2c
        # Ensure device present and correct
        whoami = self._i2c.read_byte_data(self.I2C_ADDR, self.WHO_AM_I_REG)
        if whoami != self.WHO_AM_I_VAL:
            raise RuntimeError(
                f"Unexpected device at address 0x{self.WHO_AM_I_REG:02x}"
            )
        # Reset and configure
        self.setup()

    @abstractmethod
    def setup(self) -> None: ...

    def get_register_bit(self, reg: int, bit: int) -> bool:
        val = self._i2c.read_byte_data(self.I2C_ADDR, reg)
        return bool(val & (1 << bit))

    def set_register_bit(self, reg: int, bit: int, val: bool) -> None:
        reg_val = self._i2c.read_byte_data(self.I2C_ADDR, reg)
        mask = 1 << bit
        if val:
            reg_val |= mask
        else:
            reg_val &= ~mask
        self._i2c.write_byte_data(self.I2C_ADDR, reg, reg_val)

    def get_measurement_vector(self, reg: int) -> tuple[int, int, int]:
        values = self._i2c.read_i2c_block_data(
            self.I2C_ADDR, reg, measure_vec_struct.size
        )
        x, y, z = measure_vec_struct.unpack(bytes(values))
        return x, y, z
