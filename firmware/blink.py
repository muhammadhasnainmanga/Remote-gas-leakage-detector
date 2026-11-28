"""Poll the API and display a selected OLED animation or clock."""

import gc
import math
import random
import time
import ujson
import urequests
import newMQ2
from machine import I2C, Pin
import sh1106


POLL_INTERVAL_MS = 10000
PAKISTAN_UTC_OFFSET_SECONDS = 5 * 60 * 60
last_clock_second = None
last_random_clock_ms = None


def make_oled():
    i2c = I2C(0, scl=Pin(1), sda=Pin(0), freq=100000)
    addresses = i2c.scan()
    if 0x3C not in addresses and 0x3D not in addresses:
        raise OSError("OLED not found on I2C0; check GP0/GP1, power and GND")
    address = 0x3C if 0x3C in addresses else 0x3D
    return sh1106.SH1106_I2C(128, 64, i2c, addr=address)


def get_animation():
    response = None
    try:
        response = urequests.get(
            newMQ2.API + "/animation",
            headers={"Authorization": "Bearer " + newMQ2.TOKEN},
        )
        if response.status_code != 200:
            print("Animation API returned HTTP", response.status_code)
            return None
        return ujson.loads(response.text)
    except Exception as error:
        print("Could not read animation command:", error)
        return None
    finally:
        if response:
            response.close()
        gc.collect()


def draw_heart(oled, frame):
    heart = ("0110110", "1111111", "1111111", "0111110", "0011100", "0001000")
    scale = 5 if frame % 2 == 0 else 4
    x0 = 64 - (7 * scale) // 2
    y0 = 32 - (6 * scale) // 2
    oled.fill(0)
    for row, pixels in enumerate(heart):
        for col, pixel in enumerate(pixels):
            if pixel == "1":
                oled.fill_rect(x0 + col * scale, y0 + row * scale, scale, scale, 1)
    oled.show()


def draw_eyes_blink(oled, frame):
    oled.fill(0)
    if frame % 10 == 0:
        oled.line(28, 32, 56, 32, 1)
        oled.line(72, 32, 100, 32, 1)
    else:
        for center in (42, 86):
            oled.ellipse(center, 32, 14, 18, 1)
            oled.fill_rect(center - 2, 27, 5, 10, 1)
    oled.show()


def draw_eyes_wink(oled, frame):
    oled.fill(0)
    oled.ellipse(42, 32, 14, 18, 1)
    oled.fill_rect(40, 27, 5, 10, 1)
    if frame % 8 < 2:
        oled.line(72, 32, 100, 32, 1)
    else:
        oled.ellipse(86, 32, 14, 18, 1)
        oled.fill_rect(84, 27, 5, 10, 1)
    oled.show()


def draw_eyes_look(oled, frame):
    oled.fill(0)
    if frame % 12 == 0:
        oled.line(28, 32, 56, 32, 1)
        oled.line(72, 32, 100, 32, 1)
    else:
        shift = (-5, 0, 5, 0)[(frame // 3) % 4]
        for center in (42, 86):
            oled.ellipse(center, 32, 14, 18, 1)
            oled.fill_rect(center - 2 + shift, 27, 5, 10, 1)
    oled.show()


def draw_inverse_eyes(oled, frame):
    oled.fill(1)
    if frame % 10 == 0:
        oled.line(28, 32, 56, 32, 0)
        oled.line(72, 32, 100, 32, 0)
    else:
        for center in (42, 86):
            oled.ellipse(center, 32, 14, 18, 0)
            oled.fill_rect(center - 2, 27, 5, 10, 0)
    oled.show()


def draw_inverse_heart(oled, frame):
    heart = ("0110110", "1111111", "1111111", "0111110", "0011100", "0001000")
    scale = 5 if frame % 2 == 0 else 4
    x0 = 64 - (7 * scale) // 2
    y0 = 32 - (6 * scale) // 2
    oled.fill(1)
    for row, pixels in enumerate(heart):
        for col, pixel in enumerate(pixels):
            if pixel == "1":
                oled.fill_rect(x0 + col * scale, y0 + row * scale, scale, scale, 0)
    oled.show()


def draw_sine_wave(oled, frame, color=1, background=0):
    oled.fill(background)
    phase = frame * 0.12
    previous_y = 32 + int(17 * math.sin(phase))
    for x in range(1, 128):
        y = 32 + int(17 * math.sin(x * 0.10 + phase))
        oled.line(x - 1, previous_y, x, y, color)
        previous_y = y
    oled.show()


def draw_inverse_wave(oled, frame):
    draw_sine_wave(oled, frame, color=0, background=1)


def draw_clock(oled, frame):
    global last_clock_second
    local_time = time.localtime(time.time() + PAKISTAN_UTC_OFFSET_SECONDS)
    if local_time[0] >= 2024:
        if local_time[5] == last_clock_second:
            return
        last_clock_second = local_time[5]
    else:
        if last_clock_second == -1:
            return
        last_clock_second = -1
    oled.fill(0)
    if local_time[0] < 2024:
        oled.text("Syncing clock", 16, 28, 1)
    else:
        time_text = "%02d:%02d:%02d" % (local_time[3], local_time[4], local_time[5])
        date_text = "%02d/%02d/%04d" % (local_time[2], local_time[1], local_time[0])
        oled.text("PAKISTAN TIME", 20, 12, 1)
        oled.text(time_text, 32, 28, 1)
        oled.text(date_text, 24, 44, 1)
    oled.show()


def draw_random_clock(oled, frame):
    global last_random_clock_ms
    now = time.ticks_ms()
    if last_random_clock_ms is not None and time.ticks_diff(now, last_random_clock_ms) < 350:
        return
    last_random_clock_ms = now

    center_x = 64 + random.randint(-5, 5)
    center_y = 32 + random.randint(-3, 3)
    oled.fill(0)
    oled.ellipse(center_x, center_y, 25, 25, 1)
    for hour in range(12):
        angle = (hour * math.pi / 6) - math.pi / 2
        x = center_x + int(20 * math.cos(angle))
        y = center_y + int(20 * math.sin(angle))
        oled.fill_rect(x - 1, y - 1, 3, 3, 1)

    angles = [random.random() * 2 * math.pi for _ in range(3)]
    lengths = (11, 17, 22)
    for angle, length in zip(angles, lengths):
        end_x = center_x + int(length * math.cos(angle))
        end_y = center_y + int(length * math.sin(angle))
        oled.line(center_x, center_y, end_x, end_y, 1)
    oled.fill_rect(center_x - 2, center_y - 2, 5, 5, 1)
    oled.show()


def animation(wifi_ssid, wifi_password):
    global last_clock_second, last_random_clock_ms
    oled = make_oled()
    current = None
    display_mode = "animation"
    text_lines = ["", "", ""]
    text_needs_draw = True
    frame = 0
    animations = {
        "heart": draw_heart,
        "eyes_blink": draw_eyes_blink,
        "eyes_wink": draw_eyes_wink,
        "eyes_look": draw_eyes_look,
        "inverse_eyes": draw_inverse_eyes,
        "inverse_heart": draw_inverse_heart,
        "sine_wave": draw_sine_wave,
        "inverse_wave": draw_inverse_wave,
        "clock": draw_clock,
        "random_clock": draw_random_clock,
    }
    last_poll = time.ticks_ms() - POLL_INTERVAL_MS
    oled.fill(0)
    oled.text("Waiting for", 0, 16)
    oled.text("display mode...", 0, 32)
    oled.show()

    while True:
        if not newMQ2.check_wifi(wifi_ssid, wifi_password):
            oled.fill(0)
            oled.text("Wi-Fi offline", 0, 16)
            oled.text("Reconnecting...", 0, 32)
            oled.show()
            time.sleep_ms(1000)
            continue

        now = time.ticks_ms()
        if time.ticks_diff(now, last_poll) >= POLL_INTERVAL_MS:
            last_poll = now
            command = get_animation()
            if command is not None:
                new_mode = command.get("display_mode", "animation")
                new_current = command.get("keyword") or command.get("current_animation")
                new_lines = command.get("text_lines", ["", "", ""])
                if new_mode != display_mode or new_lines != text_lines:
                    text_needs_draw = True
                if new_current != current:
                    frame = 0
                    last_clock_second = None
                    last_random_clock_ms = None
                current = new_current
                display_mode = new_mode
                text_lines = new_lines
                print("OLED mode:", display_mode, "selection:", current)

        if display_mode == "text" and text_needs_draw:
            oled.fill(0)
            for line_number, line in enumerate(text_lines[:3]):
                oled.text(str(line)[:16], 0, 8 + line_number * 16, 1)
            oled.show()
            text_needs_draw = False
        elif display_mode == "animation":
            draw_function = animations.get(current)
            if draw_function:
                draw_function(oled, frame)
                frame += 1
            else:
                oled.fill(0)
                oled.text("Unknown display", 0, 16)
                oled.text(str(current or "unknown")[:16], 0, 32)
                oled.show()


animation("Error", "rimjhim125")
