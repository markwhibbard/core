import asyncio
from datetime import datetime
import json
import random
import time


class EspressoHub:
    def __init__(self, hass, topic):
        self._name = topic  # TODO is this what I want?
        self._topic = topic
        self._hass = hass
        # self._id = host.lower()  #figure this out later

    def turnon(self, uid):
        # TODO use uid to turn on specific unit
        self._hass.components.mqtt.async_publish(self._topic + "/turnon", None)

    def turnoff(self, uid):
        # TODO use uid to turn on specific unit
        self._hass.components.mqtt.async_publish(self._topic + "/turnoff", None)

    async def discover(self):

        self.devices = [EspressoDevice("mwh_espresso", "Espresso Machine", self)]
        # TODO ask for refresh from all devices
        self.refresh()
        return True

    def refresh(self):
        self._hass.components.mqtt.async_publish(self._topic + "/refresh", None)

    # TODO make async
    async def connect(self):

        # Listen to a message on MQTT.
        def message_received(topic, payload, qos):
            # TODO parse topic for device id
            uid = "mwh_espresso"
            thisdevice = None
            for device in self.devices:
                if device.uid == uid:
                    thisdevice = device
            if thisdevice is None:
                print(f"Error in mwh hub: didn't find device with uid {uid} loaded")
                return

            """A new MQTT message has been received."""
            if topic == self._topic + "/status":
                if len(payload) == 0:
                    print("Error in espresso sensor: No arguments in received status")
                else:
                    args = json.loads(payload)
                    if "tank" in args:
                        thisdevice._tanklevel = args["tank"]
                    if "switch" in args:
                        synced = args["switch"]
                        if synced:
                            thisdevice._is_on = True
                        else:
                            thisdevice._is_on = False
                    if "shot" in args:
                        if args["shot"]:
                            thisdevice._shottimestamp = datetime.now().strftime(
                                "%Y.%m.%d %H:%M:%S"
                            )
                            thisdevice._shottimer = args["shottime"]
                    thisdevice.publish_updates()

        await self._hass.components.mqtt.async_subscribe(
            self._topic + "/#", message_received
        )
        self._is_connected = True
        return True


class EspressoDevice:
    def __init__(self, uid, name, hub):
        """Init dummy roller."""
        self._uid = uid
        self.hub = hub
        self._name = name
        self._callbacks = set()

        self._tanklevel = 0
        self._shottimestamp = 0
        self._shottimer = 0
        self._is_on = False

    @property
    def uid(self):
        """Return ID for roller."""
        return self._uid

    @property
    def is_connected(self):
        """Return ID for roller."""
        return self.hub._is_connected

    @property
    def is_on(self):
        return self._is_on

    @property
    def shottimestamp(self):
        """Return ID for roller."""
        return self._shottimestamp

    @property
    def shottimer(self):
        """Return ID for roller."""
        return self._shottimer

    @property
    def tanklevel(self):
        """Return ID for roller."""
        return self._tanklevel

    @property
    def name(self):
        """Return ID for roller."""
        return self._name

    def register_callback(self, callback):
        """Register callback, called when Roller changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback):
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    def turnon(self):
        self.hub.turnon(self.uid)

    def turnoff(self):
        self.hub.turnoff(self.uid)

    def update(self):
        self.hub.refresh()

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()
