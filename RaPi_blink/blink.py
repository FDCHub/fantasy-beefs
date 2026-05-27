import RPi.GPIO as GPIO
import time
# blinking function
def blink(pin):
GPIO.output(pin,GPIO.HIGH)
time.sleep(1)
GPIO.output(pin,GPIO.LOW)
time.sleep(1)
return
