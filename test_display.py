#!/usr/bin/env python3
from waveshare_epd import epd7in5_V2

epd = epd7in5_V2.EPD()
epd.init()
epd.Clear()
epd.sleep()
print("Done - display should have flickered and gone white")
