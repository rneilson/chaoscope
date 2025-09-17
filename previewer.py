import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from picamera2 import Picamera2, Preview  # pyright: ignore[reportMissingImports]

FONT_PATH = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'

picam2 = Picamera2()
picam2.configure(picam2.create_preview_configuration())
picam2.start_preview(Preview.QTGL, width=640, height=480, x=0, y=0)
picam2.start()

font = ImageFont.truetype(FONT_PATH, 24)
text_color = (239, 239, 239, 255)
text_origin = (10, 10)

for time_left in range(10, 0, -1):
    text_overlay = Image.new('RGBA', (640, 480), (255, 255, 255, 0))
    draw = ImageDraw.Draw(text_overlay)
    text = f"Remaining: {time_left:2}s"

    draw.text(text_origin, text, font=font, fill=text_color)

    overlay = np.asarray(text_overlay)
    picam2.set_overlay(overlay)
    time.sleep(1)

picam2.stop_preview()
picam2.stop()
