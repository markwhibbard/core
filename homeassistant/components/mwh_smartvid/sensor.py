"""Support for the MWH Espresso"""
import logging
import asyncio

#from pyoppleio.OppleLightDevice import OppleLightDevice
import voluptuous as vol

from homeassistant.helpers.entity import Entity
from homeassistant.const import CONF_NAME
from .const import DOMAIN
from . import hub
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config, async_add_entities)->None:
    """Set up MWH Espresso platform"""
    hub = hass.data[DOMAIN][config.entry_id] 
    newdevices = []
    for device in hub.devices:
        newdevices.append(SmartVidDetect(device))

    async_add_entities(newdevices)



class SmartVidDetect(Entity):
    """MWH Espresso Tank"""


    should_poll = False


    def __init__(self, device):
        self._device = device

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._device.remove_callback(self.async_write_ha_state)

    @property
    def available(self):
        """Return True if switch is available."""
        return self._device.is_connected

    @property
    def unique_id(self):
        return self._device.uid + "_detect"
   
    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        attr = {'motion': (self._device.alertvalue > 0),
                'alert': self._device.alertvalue,
                'face_detected': self._device.facedetected,
                'name': self._device.facename
                }
        return attr

    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.uid)},
            # If desired, the name for the device could be different to the entity
            "name": self._device.name + " camera",
        }

    @property
    def name(self):
        """Return the display name of this light."""
        return self._device.name + " camera"


    @property
    def state(self):
        if self._device.alertvalue > 0:
            return "active"
        else:
            return "inactive"

    def update(self):
        """Synchronize state with switch."""
        self._device.update()
