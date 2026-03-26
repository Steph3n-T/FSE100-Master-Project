#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import subprocess
import base64
import sys
from openai import OpenAI

LeftVibrator = 11 #gpio17
RightVibrator = 12	#gpio18
PushButton = 15 #gpio22
LeftUltrasonicTrig = 31 #gpio6
LeftUltrasonicEcho = 29 #gpio5
RightUltrasonicTrig = 38 #gpio20
RightUltrasonicEcho = 40 #gpio21

client = OpenAI(api_key="sk-REPLACE_WITH_NEW_KEY")

MODEL = "gpt-5-nano-2025-08-07"
IMAGE_PATH = "captured_image.jpg"
RESOLUTION = "640x480"

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
    try:
        return resp.model_dump_json(indent=2)
    except Exception:
        return str(resp)

# sathwin's camera code ripped



def setup():
    GPIO.setmode(GPIO.BOARD)   	# Numbers GPIOs by physical location
    GPIO.setup(LeftUltrasonicTrig, GPIO.OUT) # left ultrasonic output
    GPIO.setup(LeftUltrasonicEcho, GPIO.IN) # left ultrasonic input
    GPIO.setup(RightUltrasonicTrig, GPIO.OUT) # right ultrasonic output
    GPIO.setup(RightUltrasonicEcho, GPIO.IN) # right ultrasonic input
    GPIO.setup(PushButton, GPIO.IN, pull_up_down=GPIO.PUD_UP) # push button input
    GPIO.setup(LeftVibrator, GPIO.OUT) # left vibrator output
    GPIO.setup(RightVibrator, GPIO.OUT) # right vibrator 
    GPIO.add_event_detect(PushButton, GPIO.BOTH, callback=detect, bouncetime=200) # when push button is pressed, call detect function

def detect(chn):
    try: # almost bar for bar rip of main() from sathwin's code.
        # Capture image
        capture_image(IMAGE_PATH)
        data_url = to_data_url(IMAGE_PATH)

        # AI prompt
        prompt = (
            "Reply with EXACTLY ONE short sentence (<= 15 words) "
            "describing the main visible objects. Do not read text."
            "The format should be 'there is a (insert color of object) (insert object name) in front of you'."
            "If no object found, reply with 'no object detected'."
        )

        # Send image to OpenAI API
        resp = client.responses.create(
            model=MODEL,
            reasoning={"effort": "low"},
            max_output_tokens=1024,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": data_url}
                ]
            }],
        )

        # Extract AI response
        ai_response = extract_text(resp)
        print(f"AI Response: {ai_response}")

        # Convert AI response to speech
        from gtts import gTTS
        tts = gTTS(ai_response, lang="en")
        tts.save("response.mp3")

        # Play audio through Bluetooth headphones
        subprocess.run(["mpg123", "response.mp3"], check=True)
    except Exception as e:
        print("ERROR:", repr(e), file=sys.stderr)
        raise

def leftDistance():
    GPIO.output(LeftUltrasonicTrig, 0)
    time.sleep(0.000002)

    GPIO.output(LeftUltrasonicTrig, 1)
    time.sleep(0.00001)
    GPIO.output(LeftUltrasonicTrig, 0)

    while GPIO.input(LeftUltrasonicEcho) == 0:
        a = 0
    time1 = time.time()
    while GPIO.input(LeftUltrasonicEcho) == 1:
        a = 1
    time2 = time.time()

    during = time2 - time1
    return during * 340 / 2 * 39.37 # recycled cm conversion code. 100 cm is 39.37 inches, the initial conversion (during * 340 / 2 * 100).

      
def rightDistance():
    GPIO.output(LeftUltrasonicTrig, 0)
    time.sleep(0.000002)

    GPIO.output(LeftUltrasonicTrig, 1)
    time.sleep(0.00001)
    GPIO.output(LeftUltrasonicTrig, 0)

    while GPIO.input(LeftUltrasonicEcho) == 0:
        a = 0
    time1 = time.time()
    while GPIO.input(LeftUltrasonicEcho) == 1:
        a = 1
    time2 = time.time()

    during = time2 - time1
    return during * 340 / 2 * 39.37 # recycled cm conversion code. 100 cm is 39.37 inches, the initial conversion (during * 340 / 2 * 100).
      
      

def loop():
    while True:
        lDis = leftDistance()
        rDis = rightDistance()
        if lDis < 18: # if left distance less than 18 inches, vibrate right vibrator
            GPIO.output(LeftVibrator, 1)
        if rDis < 18: # if right distance less than 18 inches, vibrate right vibrator
            GPIO.output(RightVibrator, 1)

def destroy():
	GPIO.cleanup() # Release resource

if __name__ == "__main__":
        setup()
        try:
            loop()
        except KeyboardInterrupt: # When 'Ctrl+C' is pressed, the child program destroy() will be executed.
            destroy()