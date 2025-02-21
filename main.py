import json
import logging
import os
import asyncio
import aiomqtt
import pulsectl

import RPi.GPIO as GPIO
import pulsectl_asyncio

DISCOVER_TOPIC = "homeassistant/switch/kitchen-audio/config"

LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
MQTT_HOST = os.environ.get('MQTT_HOST', '192.168.129.14')
MQTT_PORT = int(os.environ.get('MQTT_PORT', '1883'))
IDLE_TIMEOUT_SECONDS = int(os.environ.get('IDLE_TIMEOUT_SECONDS', '120'))
SINK_NAME = os.environ.get('SINK_NAME')
PIN = int(os.environ.get('GPIO_PIN'))
MQTT_RECONNECT_DELAY = int(os.environ.get('MQTT_RECONNECT_DELAY', '10'))

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


async def mqtt(mqtt_client: aiomqtt.Client):
    LOGGER.info("Connected to MQTT broker")
    LOGGER.debug("Publish switch config")
    await mqtt_client.publish(DISCOVER_TOPIC, json.dumps(CONFIG), qos=2, retain=False)
    LOGGER.debug("Publish switch state off")
    await mqtt_client.publish(STATE_TOPIC, OFF, qos=2, retain=False)
    LOGGER.debug("Subscribing to %s", COMMAND_TOPIC)
    await mqtt_client.subscribe(COMMAND_TOPIC)
    async for message in mqtt_client.messages:
        value = message.payload.decode("utf-8")
        LOGGER.debug("Recevied message on %s: %s", message.topic, value)
        await switch(mqtt_client, value)


async def pulseaudio(mqtt_client: aiomqtt.Client):
    scheduled_off = None

    pulse = pulsectl_asyncio.PulseAsync('audio-switch')
    await pulse.connect()

    async with pulsectl_asyncio.PulseAsync('sync-status-monitor') as pulse:
        LOGGER.info("Listening to PulseAudio sink state changes")
        async for event in pulse.subscribe_events('sink'):
            if event.t == "change":
                event: pulsectl.PulseEventInfo
                LOGGER.debug("Pulse event: %r", event)
                sink_info: pulsectl.PulseSinkInfo = await pulse.sink_info(event.index)

                if SINK_NAME is not None and sink_info.name != SINK_NAME:
                    LOGGER.debug("Ignoring sink %s", sink_info.name)
                    continue

                if sink_info.state == "running":
                    if scheduled_off is not None:
                        LOGGER.info("Cancelling scheduled off")
                        scheduled_off.cancel()
                        scheduled_off = None
                    await switch(mqtt_client, ON)
                elif sink_info.state == "idle" or sink_info.state == "suspended":
                    if scheduled_off is None:
                        LOGGER.info("Scheduling off")
                        scheduled_off = asyncio.create_task(schedule_off(mqtt_client))
                LOGGER.debug("Sink info: %r", sink_info.state)


async def switch(client, value):
    if value == ON:
        LOGGER.info("Turning on")
        GPIO.output(PIN, GPIO.LOW)
        await client.publish(STATE_TOPIC, ON, qos=2, retain=False)
    elif value == OFF:
        LOGGER.info("Turning off")
        GPIO.output(PIN, GPIO.HIGH)
        await client.publish(STATE_TOPIC, OFF, qos=2, retain=False)
    else:
        LOGGER.error("Invalid payload %s", value)


async def schedule_off(mqtt_client):
    await asyncio.sleep(IDLE_TIMEOUT_SECONDS)
    await switch(mqtt_client, OFF)


async def main():
    LOGGER.info("Setting up GPIO")
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN, GPIO.OUT)

    try:
        while True:
            try:
                LOGGER.info("Connecting to MQTT broker")
                async with aiomqtt.Client(MQTT_HOST, MQTT_PORT) as mqtt_client:
                    await asyncio.gather(mqtt(mqtt_client), pulseaudio(mqtt_client))
            except aiomqtt.exceptions.MqttError as e:
                LOGGER.error("MQTT error: %s", e)
                LOGGER.error("Try to reconnect in %d seconds", MQTT_RECONNECT_DELAY)
                await asyncio.sleep(MQTT_RECONNECT_DELAY)
    finally:
        GPIO.cleanup()

if __name__ == '__main__':
    asyncio.run(main())
