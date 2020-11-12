"""Support for the MWH Espresso"""
import asyncio
import logging

# from pyoppleio.OppleLightDevice import OppleLightDevice
import voluptuous as vol

from homeassistant.const import CONF_NAME, DEVICE_CLASS_BATTERY
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity

from . import hub
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config, async_add_entities) -> None:
    """Set up MWH Espresso platform"""
    hub = hass.data[DOMAIN][config.entry_id]
    newdevices = []
    for device in hub.devices:
        newdevices.append(EspressoTank(device))

    async_add_entities(newdevices)


class EspressoTank(Entity):
    """MWH Espresso Tank"""

    should_poll = False

    device_class = DEVICE_CLASS_BATTERY

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
        return self._device.uid + "_sensor"

    @property
    def unit_of_measurement(self):
        return "%"

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        attr = {
            "last_shot": self._device.shottimestamp,
            "shot_timer": self._device.shottimer,
        }
        return attr

    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.uid)},
            # If desired, the name for the device could be different to the entity
            "name": self._device.name + " Tank Level",
        }

    @property
    def name(self):
        """Return the display name of this light."""
        return self._device.name + " Tank Level"

    @property
    def state(self):
        return self._device.tanklevel

    def update(self):
        """Synchronize state with switch."""
        self._device.update()
