#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import subprocess
import base64
import sys
import speech_recognition as sr
from openai import OpenAI


LeftVibrator = 13 #gpio27
RightVibrator = 12	#gpio18
PushButton = 15 #gpio22
LeftUltrasonicTrig = 31 #gpio6
LeftUltrasonicEcho = 29 #gpio5
RightUltrasonicTrig = 38 #gpio20
RightUltrasonicEcho = 40 #gpio21

MIC_DEADZONE = 2 # seconds to wait between microphone inputs

DISTANCE_THRESHOLD = 18 # distance threshold in inches for vibrators



client = OpenAI(api_key="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")

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

# sathwin's camera code ripped. utilized for image detection and we'll write our own code for the ai response.

r = sr.Recognizer()  # Create a recognizer object

def listen(): # speech to text code ripped from canvas
    try:
        with sr.Microphone() as source:  
            r.adjust_for_ambient_noise(source, duration=0.1)  # Adjust for background noise
            audio = r.listen(source)  # Record audio
            return r.recognize_google(audio)  # Convert speech to text using Google's API
    except sr.RequestError:
        print("Can't get results")  # Handle API request failure
    except sr.UnknownValueError:
        return ""  # Handle cases where speech isn't recognized

def speechSearch(userInp):
    """
    Searches for the object specified by the user in the AI's response.
    """
    try:
        # Capture image and get AI response
        capture_image(IMAGE_PATH)
        data_url = to_data_url(IMAGE_PATH)

        prompt = (
            "Reply with EXACTLY ONE short sentence (<= 15 words) "
            "describing the main visible objects. Do not read text."
            "The format should be 'there is a (insert color of object) (insert object name) in front of you'."
            "If no object found, reply with 'no object detected'."
        )

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

        ai_response = extract_text(resp)
        print(f"AI Response: {ai_response}")

        # Check if the user's input matches the AI's detected object
        if userInp.lower() in ai_response.lower():
            print(f"Object '{userInp}' found!")
            from gtts import gTTS
            tts = gTTS(f"Yes, {userInp} is in front of you.", lang="en")
            tts.save("response.mp3")
            subprocess.run(["mpg123", "response.mp3"], check=True)
        else:
            print(f"Object '{userInp}' not found.")
            from gtts import gTTS
            tts = gTTS(f"No, {userInp} is not in front of you.", lang="en")
            tts.save("response.mp3")
            subprocess.run(["mpg123", "response.mp3"], check=True)

    except Exception as e:
        print("ERROR in speechSearch:", repr(e), file=sys.stderr)
    



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
            "Don't describe people or objects related to people (i.e. black man is in front of you, a yellow hand is in front of)"
            "The format should be 'there is a (insert color of object) (insert object name) in front of you'."
            "For example, 'there is a orange shirt in front of you' or 'there is a black cell phone in front of you'"
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

def getDistance(trig_pin, echo_pin):
    # ultrasonic distance calculation in inches
    # if times out, return 999 to keep vibrator off
    GPIO.output(trig_pin, 0)
    time.sleep(0.000002)

    GPIO.output(trig_pin, 1)
    time.sleep(0.00001)
    GPIO.output(trig_pin, 0)

    timeout = time.time() + 0.05
    while GPIO.input(echo_pin) == 0:
        if time.time() > timeout:
            print(f"[WARN] Echo timeout (waiting High) on pin {echo_pin}")
            return 999
    time1 = time.time()

    timeout = time.time() + 0.05
    while GPIO.input(echo_pin) == 1:
        if time.time() > timeout:
            print(f"[WARN] Echo timeout (waiting High) on pin {echo_pin}")
            return 999
    time2 = time.time()  

    during = time2 - time1
    distance_inches = during * 340 / 2 * 39.37
      

def loop():
    global last_mic_time
    
    while True:
        lDis = getDistance(LeftUltrasonicTrig, LeftUltrasonicEcho)
        rDis = getDistance(RightUltrasonicTrig, RightUltrasonicEcho)

        print(f"Left: {lDis:.1f} in | Right: {rDis:.1f} in")

        # Left vibrator: turn on if object detected, off otherwise
        if lDis < DISTANCE_THRESHOLD:
            GPIO.output(LeftVibrator, 1)
        else:
            GPIO.output(LeftVibrator, 0)

        # Right vibrator: turn on if object detected, off otherwise
        if rDis < DISTANCE_THRESHOLD:
            GPIO.output(RightVibrator, 1)
        else:
            GPIO.output(RightVibrator, 0)

        time.sleep(0.1)  # Avoid reading too fast to reduce sensor noise        

        if time.time() - last_mic_time > MIC_DEADZONE:
            print("Listening for user input...")
            userSpeech = listen()
            if userSpeech:  # If valid input is detected
                speechSearch(userSpeech)
                last_mic_time = time.time()

def destroy():
    GPIO.output(LeftVibrator, GPIO.LOW)
    GPIO.output(LeftVibrator, GPIO.LOW)
    GPIO.cleanup() # Release resource

if __name__ == "__main__":
        setup()
        try:
            loop()
        except KeyboardInterrupt: # When 'Ctrl+C' is pressed, the child program destroy() will be executed.
            destroy()