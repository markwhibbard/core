"""Support for the MWH smart_vid"""
import asyncio
import logging

# from pyoppleio.OppleLightDevice import OppleLightDevice
import voluptuous as vol

from homeassistant.components import mqtt

SUPPORT_STREAM = 2

from homeassistant.components.camera import PLATFORM_SCHEMA, Camera
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import (
    async_aiohttp_proxy_stream,
    async_aiohttp_proxy_web,
    async_get_clientsession,
)
import homeassistant.helpers.config_validation as cv

from . import hub
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config, async_add_entities) -> None:
    """Set up MWH smart_vid platform"""
    hub = hass.data[DOMAIN][config.entry_id]
    newdevices = []
    for device in hub.devices:
        newdevices.append(SmartVidCamera(device))

    async_add_entities(newdevices)


class SmartVidCamera(Camera):
    """MWH smart_vid camera"""

    should_poll = False

    def __init__(self, device):
        self._device = device
        super().__init__()

    async def async_added_to_hass(self):
        """Run when this Entity has been added to HA."""
        # Sensors should also register callbacks to HA when their state changes
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self._device.remove_callback(self.async_write_ha_state)

    async def stream_source(self):
        """Return the source of the stream."""
        return "mjpeg"

    @property
    def state_attributes(self):
        """Return the camera state attributes."""
        attrs = super().state_attributes

        if self._device.feed:
            attrs["feed"] = self._device.feed

        return attrs

    def camera_image(self):
        """Return bytes of camera image."""
        print("Asked for camera_image")
        return True

    async def handle_async_mjpeg_stream(self, request):
        """Serve an HTTP MJPEG stream from the camera."""
        if self.stream_source == "mjpeg":
            # stream an MJPEG image stream directly from the camera
            websession = async_get_clientsession(self.hass)
            streaming_url = self._device.feed
            stream_coro = websession.get(
                streaming_url, timeout=CAMERA_WEB_SESSION_TIMEOUT
            )
            return await async_aiohttp_proxy_web(self.hass, request, stream_coro)

    @property
    def available(self):
        """Return True if available."""
        return self._device.is_connected

    @property
    def unique_id(self):
        return self._device.uid

    @property
    def device_info(self):
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self._device.uid)},
            # If desired, the name for the device could be different to the entity
            "name": self._device.name,
        }

    @property
    def name(self):
        """Return the display name of this light."""
        return self._device.name

    @property
    def supported_features(self):
        """Return supported features."""
        if self._device.is_connected:
            return SUPPORT_STREAM
        return 0

    async def stream_source(self):
        """Return the stream source."""
        if self._device.is_connected:
            return self._device.feed
        return None

    @property
    def feedurl(sefl):
        if self._device.is_connected:
            return self._device.feed
        return None

    @property
    def entity_picture(self):
        """Return a link to the camera feed as entity picture."""
        return self._device.feed


#        return "http://192.168.1.117:9090/video/errorframe.jpg"
