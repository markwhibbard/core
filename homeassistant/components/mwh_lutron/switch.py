import asyncio
import logging

import voluptuous as vol

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME
import homeassistant.helpers.config_validation as cv

from . import hub
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config, async_add_entities) -> None:
    hub = hass.data[DOMAIN][config.entry_id]
    newdevices = []
    for device in hub._scenes:
        newdevices.append(LutronSceneEntity(device))

    async_add_entities(newdevices)


class LutronSceneEntity(SwitchEntity):

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
        return self._device.entity_id

    @property
    def name(self):
        """Return the display name of this light."""
        return self._device.name

    @property
    def device_info(self):
        """Information about this entity/device."""
        return self._device.device_info

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._device.is_on

    def turn_on(self, **kwargs):
        if self.available:
            self._device.turnon()

    def turn_off(self, **kwargs):
        if self.available:
            self._device.turnoff()

    def update(self):
        """Synchronize state with switch."""
        self._device.update()
