#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import subprocess
import base64
import sys
import os
import speech_recognition as sr
from openai import OpenAI
from gtts import gTTS

LeftVibrator = 13 #gpio27
RightVibrator = 12	#gpio18
PushButton = 15 #gpio22
LeftUltrasonicTrig = 31 #gpio6
LeftUltrasonicEcho = 29 #gpio5
RightUltrasonicTrig = 38 #gpio20
RightUltrasonicEcho = 40 #gpio21

MIC_DEADZONE = 2
DISTANCE_THRESHOLD = 18

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

MODEL = "gpt-5-nano-2025-08-07"
IMAGE_PATH = "captured_image.jpg"
RESOLUTION = "640x480"

last_mic_time = time.time()
button_pressed = False

r = sr.Recognizer()

def capture_image(path: str):
    subprocess.run(["fswebcam", "-r", RESOLUTION, "-S", "2", "--no-banner", path], check=True)

def to_data_url(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"

def extract_text(resp):
    text = getattr(resp, "output_text", None)
    if text:
        return text.strip()
    try:
        for item in getattr(resp, "output", []):
            for part in getattr(item, "content", []):
                if getattr(part, "type", None) in ("output_text", "text") and getattr(part, "text", None):
                    return part.text.strip()
    except Exception:
        pass
    return str(resp)

def speak(text):
    tts = gTTS(text, lang="en")
    tts.save("response.mp3")
    subprocess.run(["mpg123", "response.mp3"], check=True)

def listen():
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.1)
            audio = r.listen(source, timeout=3, phrase_time_limit=4)
            return r.recognize_google(audio)
    except Exception:
        return ""

def analyze_scene():
    capture_image(IMAGE_PATH)
    data_url = to_data_url(IMAGE_PATH)

    prompt = (
        "Reply with EXACTLY ONE short sentence (<= 15 words) "
        "describing the main visible object. Do not read text. "
        "Do not describe people. "
        "Format: 'there is a (color) (object) in front of you'. "
        "If none, say 'no object detected'."
    )

    resp = client.responses.create(
        model=MODEL,
        reasoning={"effort": "low"},
        max_output_tokens=100,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": data_url}
            ]
        }],
    )

    return extract_text(resp)

def detect(channel):
    global button_pressed
    button_pressed = True

def handle_button():
    print("Button pressed - analyzing scene...")
    try:
        result = analyze_scene()
        print("AI:", result)
        speak(result)
    except Exception as e:
        print("ERROR:", e)

def speechSearch(userInp):
    try:
        result = analyze_scene()
        print("AI:", result)

        if any(word in result.lower() for word in userInp.lower().split()):
            speak(f"Yes, {userInp} is in front of you.")
        else:
            speak(f"No, {userInp} is not in front of you.")

    except Exception as e:
        print("ERROR:", e)

def getDistance(trig_pin, echo_pin):
    GPIO.output(trig_pin, 0)
    time.sleep(0.000002)

    GPIO.output(trig_pin, 1)
    time.sleep(0.00001)
    GPIO.output(trig_pin, 0)

    timeout = time.time() + 0.05
    while GPIO.input(echo_pin) == 0:
        if time.time() > timeout:
            return 999
    t1 = time.time()

    timeout = time.time() + 0.05
    while GPIO.input(echo_pin) == 1:
        if time.time() > timeout:
            return 999
    t2 = time.time()

    return (t2 - t1) * 340 / 2 * 39.37

def setup():
    GPIO.setmode(GPIO.BOARD)

    GPIO.setup(LeftUltrasonicTrig, GPIO.OUT)
    GPIO.setup(LeftUltrasonicEcho, GPIO.IN)
    GPIO.setup(RightUltrasonicTrig, GPIO.OUT)
    GPIO.setup(RightUltrasonicEcho, GPIO.IN)

    GPIO.setup(PushButton, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(LeftVibrator, GPIO.OUT)
    GPIO.setup(RightVibrator, GPIO.OUT)

    GPIO.add_event_detect(PushButton, GPIO.FALLING, callback=detect, bouncetime=200)

def loop():
    global last_mic_time, button_pressed

    while True:
        # Distance sensing
        lDis = getDistance(LeftUltrasonicTrig, LeftUltrasonicEcho)
        rDis = getDistance(RightUltrasonicTrig, RightUltrasonicEcho)

        print(f"Left: {lDis:.1f} in | Right: {rDis:.1f} in")

        GPIO.output(LeftVibrator, lDis < DISTANCE_THRESHOLD)
        GPIO.output(RightVibrator, rDis < DISTANCE_THRESHOLD)

        # Button handling
        if button_pressed:
            button_pressed = False
            handle_button()

        # Voice input
        if time.time() - last_mic_time > MIC_DEADZONE:
            print("Listening...")
            speech = listen()
            if speech:
                print("You said:", speech)
                speechSearch(speech)
                last_mic_time = time.time()

        time.sleep(0.1)

def destroy():
    GPIO.output(LeftVibrator, GPIO.LOW)
    GPIO.output(RightVibrator, GPIO.LOW)
    GPIO.cleanup()

if __name__ == "__main__":
    setup()
    try:
        loop()
    except KeyboardInterrupt:
        destroy()