"""Support for the MWH SONOS Sync"""
import logging
import asyncio

#from pyoppleio.OppleLightDevice import OppleLightDevice
import voluptuous as vol
from homeassistant.components import mqtt
import json
from threading import Thread
import time

from homeassistant.components.switch import (
    PLATFORM_SCHEMA,
    SwitchEntity,
)
from homeassistant.const import CONF_NAME
from .const import DOMAIN
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "SONOS Sync"
CONF_TOPIC = 'topic'

async def async_setup_entry(hass, config, async_add_entities):
    topic = config.data[CONF_TOPIC]
    name = config.data[CONF_NAME]
    entity1 = SyncSwitch(hass, name, topic)

    if not await entity1.connect():
        return True

    async_add_entities([entity1])
    print("Added sonos switch")



class SyncSwitch(SwitchEntity):
    """MWH SONOS Sync switch."""

    async def connect(self):

        def message_received(topic, payload, qos):
            """A new MQTT message has been received."""
            if len(payload) == 0:
                print("Error in mwh sonos sensor: No arguments in received status")
            else:
                args = json.loads(payload)
                self._equalizing = args['doequalize']
                self._levelsok = args['levelsok']
                self._status = args['lower']
                self._track = args['track']
                self._vol = args['vol']
                self.async_write_ha_state()


        await self.hass.components.mqtt.async_subscribe(self._topic + "/status/#", message_received)
        self._is_connected = True
        return True

    def __init__(self, hass, name, topic):

        self._topic = topic
        self._name = name
        self._is_on = True
        self._is_connected = False
        self.hass = hass
        self._equalizing = ''
        self._levelsok = ''
        self._status = ''
        self._track = ''
        self._vol = ''


    @property
    def unique_id(self):
        return self._name

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        #TODO fix button number mapping per device, maybe with constants

        attr = {'Volume': self._vol,
                'Status': self._status,
                'Track': self._track,
                'Leveling Volumes': self._equalizing,
                'Levels OK': self._levelsok,
                'Name': self._name
                }
        return attr

    @property
    def available(self):
        """Return True if switch is available."""
        return self._is_connected

    @property
    def name(self):
        return self._name


    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._name)},
            # If desired, the name for the device could be different to the entity
            "name": self._name,
        }

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._is_on


    def turn_on(self, **kwargs):
        """Instruct the switch to turn on."""
        self._is_on = True
        if self._is_connected:
            self.hass.components.mqtt.async_publish(self._topic+'/partymode', None)


    def turn_off(self, **kwargs):
        """Instruct the swtich to turn off."""
        self._is_on = False


    def update(self):
        if self._is_connected:
            self.hass.components.mqtt.async_publish(self._topic+'/refresh', None)
        if self._is_on:
            self.turn_on()



