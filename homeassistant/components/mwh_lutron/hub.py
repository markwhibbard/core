import asyncio
from datetime import datetime
import json
import random
import time

from .const import DOMAIN


class LutronHub:
    def __init__(self, hass, topic):
        self._name = topic  # TODO is this what I want?
        self._topic = topic
        self._hass = hass
        self._discovereddevices = []
        self._discoveredscenes = []
        self._picos = []
        self._scenes = []

    async def discoverscenes(self):
        # TODO handle case when smartvid server is not up when discovery is being done
        # TODO handle when we perform discovery and there are already devices in self.devices

        self._discoveredscenes = []
        self._scenes = []
        self._hass.components.mqtt.async_publish(self._topic + "/command/scenes", None)
        timeout = 5
        starttime = time.time()
        while time.time() < starttime + timeout:
            await asyncio.sleep(0.1)
            if len(self._discoveredscenes) > 0:
                for scene in self._discoveredscenes:
                    self._scenes.append(
                        SceneDevice(
                            "mwh_lutron_scene_" + str(scene["ButtonNumber"] + 1),
                            scene["Name"],
                            self,
                        )
                    )
                return True

        print("MWH Lutron Error: Timeout on scene discovery")
        return False

    async def discoverdevices(self):
        # TODO handle case when smartvid server is not up when discovery is being done
        # TODO handle when we perform discovery and there are already devices in self.devices

        self._discovereddevices = []
        self._picos = []
        self._hass.components.mqtt.async_publish(self._topic + "/command/devices", None)
        timeout = 5
        starttime = time.time()
        while time.time() < starttime + timeout:
            await asyncio.sleep(0.1)
            if len(self._discovereddevices) > 0:
                for device in self._discovereddevices:
                    if device["DeviceType"][0:4].lower() == "pico":
                        device_id = device["LinkNodes"][0]["href"].split("/")[4]
                        name = (
                            device["FullyQualifiedName"][0]
                            + "_"
                            + device["FullyQualifiedName"][1]
                        )
                        devtype = device["DeviceType"]
                        self._picos.append(PicoDevice(device_id, name, devtype, self))
                print(f"MWH Lutron: added {len(self._picos)} pico devices")
                return True

        print("MWH Lutron Error: Timeout on device discovery")
        return False

    def refresh(self):
        self._hass.components.mqtt.async_publish(self._topic + "/refresh", None)

    # TODO make async
    async def connect(self):
        def message_received(topic, payload, qos):

            # parse topic for discovery data
            dowhat = topic.split(self._topic + "/lutron/")[1]
            if dowhat == "scenes":
                # Handle incoming scene discovery
                self._discoveredscenes = json.loads(payload)
                print(
                    "Discovered {} lutron scenes:".format(len(self._discoveredscenes))
                )
                return
            if dowhat == "devices":
                # Handle incoming device discovery
                self._discovereddevices = json.loads(payload)
                print(
                    "Discovered {} lutron devices:".format(len(self._discovereddevices))
                )
                return
            if dowhat == "state":
                # Update device states
                if len(payload) > 0:
                    extracted = json.loads(payload)
                    for status in extracted:
                        if "scenes" in status.keys():
                            for scene_id, state in status["scenes"].items():
                                entity_id = "mwh_lutron_scene_" + scene_id
                                is_on = state.lower() == "true"
                                thisscene = None
                                for scene in self._scenes:
                                    if scene.entity_id == entity_id:
                                        thisscene = scene
                                if thisscene is None:
                                    print(
                                        "Error in mwh lutron: didn't find scene with id "
                                        + entity_id
                                    )
                                else:
                                    #                                    print(f"Matched incoming scene_id {scene_id} with scene named: {thisscene.name} with state {thisscene.is_on}")
                                    thisscene._is_on = is_on
                                    thisscene.publish_updates()
                        if "action" in status.keys():
                            device_id = status["device"]
                            entity_id = "mwh_lutron_pico_" + device_id
                            button = status["button"]
                            thispico = None
                            for pico in self._picos:
                                if pico.entity_id == entity_id:
                                    if thispico is not None:
                                        print(
                                            "Error in mwh lutron: found duplicate pico id"
                                        )
                                    else:
                                        thispico = pico
                            if thispico is None:
                                if (
                                    entity_id != "mwh_lutron_pico_1"
                                ):  # device 1 is the hub, ignore those
                                    print(
                                        "Error in mwh lutron: didn't find pico with id "
                                        + entity_id
                                    )
                            else:
                                # Ignore 0.25s of messages after initial button push, because there are replicates and other weird device #s that conflict
                                if time.time() - thispico._lastpushtime > 0.25:
                                    thispico._device_id = device_id
                                    thispico._lastpushtime = time.time()
                                    thispico._button = button
                                    thispico.publish_updates()

        await self._hass.components.mqtt.async_subscribe(
            self._topic + "/lutron/#", message_received
        )
        self._is_connected = True
        return True


class LutronDevice:
    def __init__(self, entity_id, name, hub):
        self._entity_id = entity_id
        self.hub = hub
        self._name = name
        self._device_id = None
        self._callbacks = set()

    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._name)},
            # If desired, the name for the device could be different to the entity
            "name": self._name,
        }

    @property
    def name(self):
        """Return ID for roller."""
        return self._name

    @property
    def entity_id(self):
        """Return ID for roller."""
        return self._entity_id

    @property
    def is_connected(self):
        """Return ID for roller."""
        return self.hub._is_connected

    def register_callback(self, callback):
        """Register callback, called when Roller changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback):
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    def update(self):
        self.hub.refresh()

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    def publish_updates(self) -> None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()


class SceneDevice(LutronDevice):
    def __init__(self, entity_id, name, hub):
        super().__init__(entity_id, name, hub)
        self._is_on = False

    @property
    def is_on(self):
        """Return ID for roller."""
        return self._is_on

    def turnon(self):
        self.hub._hass.components.mqtt.async_publish(
            self.hub._topic + "/command/scene",
            json.dumps(
                {"virtualButton": self._entity_id.split("mwh_lutron_scene_")[1]}
            ),
        )
        self.hub._hass.components.mqtt.async_publish(
            self.hub._topic + "/command/status", None
        )
        return True

    def turnoff(self):
        roomname = self.name.split()[0]
        for scene in self.hub._scenes:
            firstword = scene.name.split()[0]
            lastword = scene.name.split()[-1]
            if firstword == roomname and (
                lastword.lower() == "dark" or lastword.lower() == "off"
            ):
                scene.turnon()
                return True
        # TODO find matching blackout scene and activate it
        return True


class PicoDevice(LutronDevice):
    def __init__(self, device_id, name, picotype, hub):

        entity_id = "mwh_lutron_pico_" + device_id
        super().__init__(entity_id, name, hub)
        self._device_id = device_id
        self._lastpushtime = 0
        self._button = 0
        self._picotype = picotype

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        # TODO fix button number mapping per device, maybe with constants

        attr = {
            "pushed": datetime.fromtimestamp(self._lastpushtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            "button": self._button,
            "device Type": self._picotype,
            "name": self._name,
            "device_id": self._device_id,
        }
        return attr

    @property
    def state(self):
        """Return ID for roller."""
        return "push_me"
