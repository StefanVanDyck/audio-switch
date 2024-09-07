import json
import logging
import os
import asyncio
import asyncio_mqtt as aiomqtt
import pulsectl

import RPi.GPIO as GPIO
import pulsectl_asyncio

DISCOVER_TOPIC = "homeassistant/switch/kitchen-audio/config"

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'DEBUG')
MQTT_HOST = os.environ.get('MQTT_HOST', '192.168.129.14')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
PIN = 17

STATE_TOPIC = "homeassistant/switch/kitchen-audio/state"
COMMAND_TOPIC = "homeassistant/switch/kitchen-audio/set"
ON = "ON"
OFF = "OFF"

logging.basicConfig(level=LOG_LEVEL)
LOGGER = logging.getLogger(__name__)

CONFIG = {
    "unique_id": "audio-switch-rbpi-1",
    "name": "Audio Switch",
    "state_topic": STATE_TOPIC,
    "command_topic": COMMAND_TOPIC,
    "payload_on": ON,
    "payload_off": OFF,
    "state_on": ON,
    "state_off": OFF,
    "optimistic": False,
    "qos": 0,
    "retain": True
}


async def listen():
    async with aiomqtt.Client(MQTT_HOST, MQTT_PORT) as client:
        LOGGER.info("Connected to MQTT broker")
        async with client.messages() as messages:
            LOGGER.debug("Publish switch config")
            client.publish(DISCOVER_TOPIC, json.dumps(CONFIG), qos=2, retain=False)
            LOGGER.debug("Publish switch state off")
            client.publish(STATE_TOPIC, OFF, qos=2, retain=False)
            LOGGER.debug("Subscribing to %s", COMMAND_TOPIC)
            await client.subscribe(COMMAND_TOPIC)
            async for message in messages:
                value = message.payload.decode("utf-8")
                LOGGER.debug("Recevied message on %s: %s", message.topic, value)
                switch(client, value)


def switch(client, value):
    if value == ON:
        LOGGER.info("Turning on")
        GPIO.output(PIN, GPIO.HIGH)
        client.publish(STATE_TOPIC, ON, qos=2, retain=False)
    elif value == OFF:
        LOGGER.info("Turning off")
        GPIO.output(PIN, GPIO.LOW)
        client.publish(STATE_TOPIC, OFF, qos=2, retain=False)
    else:
        LOGGER.error("Invalid payload %s", value)


async def main():
    LOGGER.info("Setting up GPIO")
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN, GPIO.OUT)

    try:
        asyncio.run(listen())
        async with pulsectl_asyncio.PulseAsync('event-printer') as pulse:
            async for event in pulse.subscribe_events('all'):
                print('Pulse event:', event)

    finally:
        GPIO.cleanup()


if __name__ == '__main__':
    event_loop = asyncio.get_event_loop()
    event_loop.run_until_complete(main())
