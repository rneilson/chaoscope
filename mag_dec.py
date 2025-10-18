from datetime import datetime

from ahrs.utils.wmm import WMM

CURRENT_TZ = datetime.now().astimezone().tzinfo
CURRENT_LAT = 44.663719
CURRENT_LON = -63.669704
CURRENT_ALT = 0.1

wmm = WMM(
    date=datetime.now(tz=CURRENT_TZ).date(),
    # TODO: make these variable somehow
    latitude=CURRENT_LAT,
    longitude=CURRENT_LON,
    height=CURRENT_ALT,
)
deg = wmm.magnetic_elements["D"]

print(f"Magnetic declination: {deg}°")
