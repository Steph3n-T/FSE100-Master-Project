#!/usr/bin/env python3
"""
NavPack — Navigation Aid for the Visually Impaired
FSE 100 · Team 1 · Arizona State University

Runs on Raspberry Pi. Two parallel systems:
  1. Continuous loop — ultrasonic sensors drive vibration motor intensity
  2. Interrupt-driven — button press triggers webcam scan + AI description
"""

import RPi.GPIO as GPIO
import time
import subprocess
import base64
import sys
import os
from openai import OpenAI
from gtts import gTTS


# ─────────────────────────────────────────────────────────────────────────────
# GPIO PIN ASSIGNMENTS  (BOARD numbering)
# ─────────────────────────────────────────────────────────────────────────────

LEFT_VIBRATOR         = 35   # GPIO 19 — hardware PWM
RIGHT_VIBRATOR        = 12   # GPIO 18 — hardware PWM
PUSH_BUTTON           = 15   # GPIO 22
LEFT_ULTRASONIC_TRIG  = 31   # GPIO 6
LEFT_ULTRASONIC_ECHO  = 29   # GPIO 5
RIGHT_ULTRASONIC_TRIG = 38   # GPIO 20
RIGHT_ULTRASONIC_ECHO = 40   # GPIO 21


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

client = OpenAI(api_key="YOUR_API_KEY_HERE")

MODEL = "gpt-5-nano-2025-08-07"
IMAGE_PATH = "captured_image.jpg"
RESOLUTION = "640x480"
DISTANCE_THRESHOLD = 18  # inches
TTS_OUTPUT = "/tmp/tts_output.mp3"


# ─────────────────────────────────────────────────────────────────────────────
# GLOBALS
# ─────────────────────────────────────────────────────────────────────────────

LEFT_PWM  = None   # set during setup()
RIGHT_PWM = None


# ─────────────────────────────────────────────────────────────────────────────
# AUDIO OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

def speak(text: str):
    """Convert text to speech using gTTS and play via mpg123."""
    try:
        tts = gTTS(text=text, lang="en")
        tts.save(TTS_OUTPUT)
        subprocess.run(["mpg123", "-q", TTS_OUTPUT])
        os.remove(TTS_OUTPUT)
    except Exception as e:
        print(f"[TTS ERROR] {e}")


# ─────────────────────────────────────────────────────────────────────────────
# IMAGE CAPTURE & ENCODING
# ─────────────────────────────────────────────────────────────────────────────

def capture_image(path: str):
    """Capture a JPEG from the webcam via fswebcam."""
    subprocess.run(["pkill", "-f", "fswebcam"], stderr=subprocess.DEVNULL)
    time.sleep(0.5)  # let camera settle before capture
    subprocess.run(
        ["fswebcam", "-r", RESOLUTION, "-S", "2", "--no-banner", path],
        check=True
    )


def to_data_url(path: str) -> str:
    """Base64-encode an image file into a data URL for the OpenAI API."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def extract_text(resp) -> str:
    """Pull the plain-text string out of an OpenAI API response object."""
    text = getattr(resp, "output_text", None)
    if text:
        return text.strip()
    try:
        for item in getattr(resp, "output", []):
            for part in getattr(item, "content", []):
                if getattr(part, "type", None) in ("output_text", "text"):
                    if getattr(part, "text", None):
                        return part.text.strip()
    except Exception:
        pass
    return str(resp)


# ─────────────────────────────────────────────────────────────────────────────
# OBJECT IDENTIFICATION
# ─────────────────────────────────────────────────────────────────────────────

def scan():
    """
    Capture a webcam image and ask the AI to describe the main
    visible object in one short sentence. Result is spoken aloud.
    """
    capture_image(IMAGE_PATH)
    data_url = to_data_url(IMAGE_PATH)

    prompt = (
        "Describe what you see in the image in front of you in 1-2 short sentences. "
        "Focus on the main subject, its color, shape, and surroundings if relevant. "
        "Keep it natural and concise. "
        "If the image is unclear or nothing is visible, reply with 'nothing visible'."
    )

    resp = client.responses.create(
        model=MODEL,
        reasoning={"effort": "low"},
        max_output_tokens=1024,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text",  "text": prompt},
                {"type": "input_image", "image_url": data_url}
            ]
        }],
    )

    ai_response = extract_text(resp)
    print(f"[SCAN] AI response: {ai_response}")
    speak(ai_response)


# ─────────────────────────────────────────────────────────────────────────────
# BUTTON HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def on_button_press(channel):
    """
    GPIO interrupt callback — fires when the push button is pressed.
    Announces the scan, then runs the object identification pipeline.
    """
    try:
        print("[BUTTON] Press detected — starting scan")
        speak("Scanning for objects now.")
        scan()
    except Exception as e:
        print(f"[ERROR] {repr(e)}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# DISTANCE MEASUREMENT
# ─────────────────────────────────────────────────────────────────────────────

def get_distance(trig_pin: int, echo_pin: int) -> float:
    """
    Trigger an ultrasonic pulse and measure the echo return time.
    Returns distance in inches. Returns 999 on timeout (nothing detected).
    """
    GPIO.output(trig_pin, 0)
    time.sleep(0.000002)

    # Send a 10 µs trigger pulse
    GPIO.output(trig_pin, 1)
    time.sleep(0.00001)
    GPIO.output(trig_pin, 0)

    # Wait for echo to go HIGH (start of return pulse)
    timeout = time.time() + 0.05
    while GPIO.input(echo_pin) == 0:
        if time.time() > timeout:
            return 999
    time1 = time.time()

    # Wait for echo to go LOW (end of return pulse)
    timeout = time.time() + 0.05
    while GPIO.input(echo_pin) == 1:
        if time.time() > timeout:
            return 999
    time2 = time.time()

    # Distance = speed of sound × travel time / 2, converted to inches
    return (time2 - time1) * 340 / 2 * 39.37


def distance_to_duty(distance: float) -> float:
    """
    Map a distance reading to a PWM duty cycle (0–100%).
    Closer object → higher duty cycle → stronger vibration.
    At or beyond DISTANCE_THRESHOLD (18 in) → motor off (0%).
    """
    if distance >= DISTANCE_THRESHOLD:
        return 0
    # Linear scale: 18 in = 10%, 0 in = 100%
    duty = 100 - (distance / DISTANCE_THRESHOLD) * 90
    return max(10, min(100, duty))


# ─────────────────────────────────────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────────────────────────────────────

def setup():
    """Initialize GPIO pins, PWM channels, and button interrupt."""
    global LEFT_PWM, RIGHT_PWM

    GPIO.setmode(GPIO.BOARD)

    # Ultrasonic sensors — trig OUT, echo IN
    GPIO.setup(LEFT_ULTRASONIC_TRIG,  GPIO.OUT)
    GPIO.setup(LEFT_ULTRASONIC_ECHO,  GPIO.IN)
    GPIO.setup(RIGHT_ULTRASONIC_TRIG, GPIO.OUT)
    GPIO.setup(RIGHT_ULTRASONIC_ECHO, GPIO.IN)

    # Push button — pull-up resistor (LOW when pressed)
    GPIO.setup(PUSH_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)

    # Vibration motors via hardware PWM at 100 Hz
    GPIO.setup(LEFT_VIBRATOR,  GPIO.OUT)
    GPIO.setup(RIGHT_VIBRATOR, GPIO.OUT)
    LEFT_PWM  = GPIO.PWM(LEFT_VIBRATOR,  100)
    RIGHT_PWM = GPIO.PWM(RIGHT_VIBRATOR, 100)
    LEFT_PWM.start(0)   # start with motors off
    RIGHT_PWM.start(0)

    # Register button interrupt — triggers on falling edge (press)
    GPIO.add_event_detect(
        PUSH_BUTTON, GPIO.FALLING,
        callback=on_button_press,
        bouncetime=200   # 200 ms debounce
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def loop():
    """
    Continuously poll both distance sensors and update motor PWM duty cycles.
    Button presses are handled asynchronously via GPIO interrupt — no polling
    needed here.
    """
    while True:
        l_dist = get_distance(LEFT_ULTRASONIC_TRIG,  LEFT_ULTRASONIC_ECHO)
        r_dist = get_distance(RIGHT_ULTRASONIC_TRIG, RIGHT_ULTRASONIC_ECHO)

        print(f"Left: {l_dist:.1f} in | Right: {r_dist:.1f} in")

        LEFT_PWM.ChangeDutyCycle(distance_to_duty(l_dist))
        RIGHT_PWM.ChangeDutyCycle(distance_to_duty(r_dist))

        time.sleep(0.1)   # ~10 readings per second


# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────────────────

def destroy():
    """Stop PWM, zero out motors, and release all GPIO resources."""
    LEFT_PWM.stop()
    RIGHT_PWM.stop()
    GPIO.output(LEFT_VIBRATOR,  0)
    GPIO.output(RIGHT_VIBRATOR, 0)
    GPIO.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup()
    try:
        loop()
    except KeyboardInterrupt:
        destroy()