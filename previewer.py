import cv2  # pyright: ignore[reportMissingImports]
import numpy as np
import time

from picamera2 import Picamera2, Preview  # pyright: ignore[reportMissingImports]

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration())
picam2.start_preview(Preview.QTGL, width=640, height=480, x=0, y=0)
picam2.start()

for time_left in range(10, 0, -1):
    colour = (0, 255, 0, 255)
    origin = (0, 30)
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = 1
    thickness = 2
    overlay = np.zeros((640, 480, 4), dtype=np.uint8)
    cv2.putText(overlay, f"Remaining: {time_left:2}s", origin, font, scale, colour, thickness)
    picam2.set_overlay(overlay)
    time.sleep(1)

picam2.stop_preview()
picam2.stop()
