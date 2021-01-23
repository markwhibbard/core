"""Support for the Transmission BitTorrent client API."""
from datetime import timedelta
import logging
from typing import List

import transmissionrpc
from transmissionrpc.error import TransmissionError
import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import (
    CONF_HOST,
    CONF_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    ATTR_DELETE_DATA,
    ATTR_TORRENT,
    CONF_LIMIT,
    CONF_ORDER,
    DATA_UPDATED,
    DEFAULT_DELETE_DATA,
    DEFAULT_LIMIT,
    DEFAULT_NAME,
    DEFAULT_ORDER,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_DOWNLOADED_TORRENT,
    EVENT_REMOVED_TORRENT,
    EVENT_STARTED_TORRENT,
    SERVICE_ADD_TORRENT,
    SERVICE_REMOVE_TORRENT,
    SERVICE_START_TORRENT,
    SERVICE_STOP_TORRENT,
)
from .errors import AuthenticationError, CannotConnect, UnknownError

_LOGGER = logging.getLogger(__name__)


SERVICE_ADD_TORRENT_SCHEMA = vol.Schema(
    {vol.Required(ATTR_TORRENT): cv.string, vol.Required(CONF_NAME): cv.string}
)

SERVICE_REMOVE_TORRENT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ID): cv.positive_int,
        vol.Optional(ATTR_DELETE_DATA, default=DEFAULT_DELETE_DATA): cv.boolean,
    }
)

SERVICE_START_TORRENT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ID): cv.positive_int,
    }
)

SERVICE_STOP_TORRENT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ID): cv.positive_int,
    }
)

TRANS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required(CONF_HOST): cv.string,
            vol.Optional(CONF_PASSWORD): cv.string,
            vol.Optional(CONF_USERNAME): cv.string,
            vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
            vol.Optional(
                CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
            ): cv.time_period,
        }
    )
)

CONFIG_SCHEMA = vol.Schema(
    {DOMAIN: vol.All(cv.ensure_list, [TRANS_SCHEMA])}, extra=vol.ALLOW_EXTRA
)

PLATFORMS = ["sensor", "switch"]


async def async_setup(hass, config):
    """Import the Transmission Component from config."""
    if DOMAIN in config:
        for entry in config[DOMAIN]:
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=entry
                )
            )

    return True


async def async_setup_entry(hass, config_entry):
    """Set up the Transmission Component."""
    client = TransmissionClient(hass, config_entry)
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = client

    if not await client.async_setup():
        return False

    return True


async def async_unload_entry(hass, config_entry):
    """Unload Transmission Entry from config_entry."""
    client = hass.data[DOMAIN].pop(config_entry.entry_id)
    if client.unsub_timer:
        client.unsub_timer()

    for platform in PLATFORMS:
        await hass.config_entries.async_forward_entry_unload(config_entry, platform)

    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_ADD_TORRENT)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_TORRENT)
        hass.services.async_remove(DOMAIN, SERVICE_START_TORRENT)
        hass.services.async_remove(DOMAIN, SERVICE_STOP_TORRENT)

    return True


async def get_api(hass, entry):
    """Get Transmission client."""
    host = entry[CONF_HOST]
    port = entry[CONF_PORT]
    username = entry.get(CONF_USERNAME)
    password = entry.get(CONF_PASSWORD)

    try:
        api = await hass.async_add_executor_job(
            transmissionrpc.Client, host, port, username, password
        )
        _LOGGER.debug("Successfully connected to %s", host)
        return api

    except TransmissionError as error:
        if "401: Unauthorized" in str(error):
            _LOGGER.error("Credentials for Transmission client are not valid")
            raise AuthenticationError from error
        if "111: Connection refused" in str(error):
            _LOGGER.error("Connecting to the Transmission client %s failed", host)
            raise CannotConnect from error

        _LOGGER.error(error)
        raise UnknownError from error


class TransmissionClient:
    """Transmission Client Object."""

    def __init__(self, hass, config_entry):
        """Initialize the Transmission RPC API."""
        self.hass = hass
        self.config_entry = config_entry
        self.tm_api = None  # type: transmissionrpc.Client
        self._tm_data = None  # type: TransmissionData
        self.unsub_timer = None

    @property
    def api(self) -> "TransmissionData":
        """Return the TransmissionData object."""
        return self._tm_data

    async def async_setup(self):
        """Set up the Transmission client."""

        try:
            self.tm_api = await get_api(self.hass, self.config_entry.data)
        except CannotConnect as error:
            raise ConfigEntryNotReady from error
        except (AuthenticationError, UnknownError):
            return False

        self._tm_data = TransmissionData(self.hass, self.config_entry, self.tm_api)

        await self.hass.async_add_executor_job(self._tm_data.init_torrent_list)
        await self.hass.async_add_executor_job(self._tm_data.update)
        self.add_options()
        self.set_scan_interval(self.config_entry.options[CONF_SCAN_INTERVAL])

        for platform in PLATFORMS:
            self.hass.async_create_task(
                self.hass.config_entries.async_forward_entry_setup(
                    self.config_entry, platform
                )
            )

        def add_torrent(service):
            """Add new torrent to download."""
            tm_client = None
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data[CONF_NAME] == service.data[CONF_NAME]:
                    tm_client = self.hass.data[DOMAIN][entry.entry_id]
                    break
            if tm_client is None:
                _LOGGER.error("Transmission instance is not found")
                return
            torrent = service.data[ATTR_TORRENT]
            if torrent.startswith(
                ("http", "ftp:", "magnet:")
            ) or self.hass.config.is_allowed_path(torrent):
                tm_client.tm_api.add_torrent(torrent)
                tm_client.api.update()
            else:
                _LOGGER.warning(
                    "Could not add torrent: unsupported type or no permission"
                )

        def start_torrent(service):
            """Start torrent."""
            tm_client = None
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data[CONF_NAME] == service.data[CONF_NAME]:
                    tm_client = self.hass.data[DOMAIN][entry.entry_id]
                    break
            if tm_client is None:
                _LOGGER.error("Transmission instance is not found")
                return
            torrent_id = service.data[CONF_ID]
            tm_client.tm_api.start_torrent(torrent_id)
            tm_client.api.update()

        def stop_torrent(service):
            """Stop torrent."""
            tm_client = None
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data[CONF_NAME] == service.data[CONF_NAME]:
                    tm_client = self.hass.data[DOMAIN][entry.entry_id]
                    break
            if tm_client is None:
                _LOGGER.error("Transmission instance is not found")
                return
            torrent_id = service.data[CONF_ID]
            tm_client.tm_api.stop_torrent(torrent_id)
            tm_client.api.update()

        def remove_torrent(service):
            """Remove torrent."""
            tm_client = None
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if entry.data[CONF_NAME] == service.data[CONF_NAME]:
                    tm_client = self.hass.data[DOMAIN][entry.entry_id]
                    break
            if tm_client is None:
                _LOGGER.error("Transmission instance is not found")
                return
            torrent_id = service.data[CONF_ID]
            delete_data = service.data[ATTR_DELETE_DATA]
            tm_client.tm_api.remove_torrent(torrent_id, delete_data=delete_data)
            tm_client.api.update()

        self.hass.services.async_register(
            DOMAIN, SERVICE_ADD_TORRENT, add_torrent, schema=SERVICE_ADD_TORRENT_SCHEMA
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_REMOVE_TORRENT,
            remove_torrent,
            schema=SERVICE_REMOVE_TORRENT_SCHEMA,
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_START_TORRENT,
            start_torrent,
            schema=SERVICE_START_TORRENT_SCHEMA,
        )

        self.hass.services.async_register(
            DOMAIN,
            SERVICE_STOP_TORRENT,
            stop_torrent,
            schema=SERVICE_STOP_TORRENT_SCHEMA,
        )

        self.config_entry.add_update_listener(self.async_options_updated)

        return True

    def add_options(self):
        """Add options for entry."""
        if not self.config_entry.options:
            scan_interval = self.config_entry.data.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            )
            limit = self.config_entry.data.get(CONF_LIMIT, DEFAULT_LIMIT)
            order = self.config_entry.data.get(CONF_ORDER, DEFAULT_ORDER)
            options = {
                CONF_SCAN_INTERVAL: scan_interval,
                CONF_LIMIT: limit,
                CONF_ORDER: order,
            }

            self.hass.config_entries.async_update_entry(
                self.config_entry, options=options
            )

    def set_scan_interval(self, scan_interval):
        """Update scan interval."""

        def refresh(event_time):
            """Get the latest data from Transmission."""
            self._tm_data.update()

        if self.unsub_timer is not None:
            self.unsub_timer()
        self.unsub_timer = async_track_time_interval(
            self.hass, refresh, timedelta(seconds=scan_interval)
        )

    @staticmethod
    async def async_options_updated(hass, entry):
        """Triggered by config entry options updates."""
        tm_client = hass.data[DOMAIN][entry.entry_id]
        tm_client.set_scan_interval(entry.options[CONF_SCAN_INTERVAL])
        await hass.async_add_executor_job(tm_client.api.update)


class TransmissionData:
    """Get the latest data and update the states."""

    def __init__(self, hass, config, api: transmissionrpc.Client):
        """Initialize the Transmission RPC API."""
        self.hass = hass
        self.config = config
        self.data = None  # type: transmissionrpc.Session
        self.available = True  # type: bool
        self._all_torrents = []  # type: List[transmissionrpc.Torrent]
        self._api = api  # type: transmissionrpc.Client
        self._completed_torrents = []  # type: List[transmissionrpc.Torrent]
        self._session = None  # type: transmissionrpc.Session
        self._started_torrents = []  # type: List[transmissionrpc.Torrent]
        self._torrents = []  # type: List[transmissionrpc.Torrent]

    @property
    def host(self):
        """Return the host name."""
        return self.config.data[CONF_HOST]

    @property
    def signal_update(self):
        """Update signal per transmission entry."""
        return f"{DATA_UPDATED}-{self.host}"

    @property
    def torrents(self) -> List[transmissionrpc.Torrent]:
        """Get the list of torrents."""
        return self._torrents

    def update(self):
        """Get the latest data from Transmission instance."""
        try:
            self.data = self._api.session_stats()
            self._torrents = self._api.get_torrents()
            self._session = self._api.get_session()

            self.check_completed_torrent()
            self.check_started_torrent()
            self.check_removed_torrent()
            _LOGGER.debug("Torrent Data for %s Updated", self.host)

            self.available = True
        except TransmissionError:
            self.available = False
            _LOGGER.error("Unable to connect to Transmission client %s", self.host)
        dispatcher_send(self.hass, self.signal_update)

    def init_torrent_list(self):
        """Initialize torrent lists."""
        self._torrents = self._api.get_torrents()
        self._completed_torrents = [
            torrent for torrent in self._torrents if torrent.status == "seeding"
        ]
        self._started_torrents = [
            torrent for torrent in self._torrents if torrent.status == "downloading"
        ]

    def check_completed_torrent(self):
        """Get completed torrent functionality."""
        current_completed_torrents = [
            torrent for torrent in self._torrents if torrent.status == "seeding"
        ]
        freshly_completed_torrents = set(current_completed_torrents).difference(
            self._completed_torrents
        )
        self._completed_torrents = current_completed_torrents

        for torrent in freshly_completed_torrents:
            self.hass.bus.fire(
                EVENT_DOWNLOADED_TORRENT, {"name": torrent.name, "id": torrent.id}
            )

    def check_started_torrent(self):
        """Get started torrent functionality."""
        current_started_torrents = [
            torrent for torrent in self._torrents if torrent.status == "downloading"
        ]
        freshly_started_torrents = set(current_started_torrents).difference(
            self._started_torrents
        )
        self._started_torrents = current_started_torrents

        for torrent in freshly_started_torrents:
            self.hass.bus.fire(
                EVENT_STARTED_TORRENT, {"name": torrent.name, "id": torrent.id}
            )

    def check_removed_torrent(self):
        """Get removed torrent functionality."""
        freshly_removed_torrents = set(self._all_torrents).difference(self._torrents)
        self._all_torrents = self._torrents
        for torrent in freshly_removed_torrents:
            self.hass.bus.fire(
                EVENT_REMOVED_TORRENT, {"name": torrent.name, "id": torrent.id}
            )

    def start_torrents(self):
        """Start all torrents."""
        if len(self._torrents) <= 0:
            return
        self._api.start_all()

    def stop_torrents(self):
        """Stop all active torrents."""
        torrent_ids = [torrent.id for torrent in self._torrents]
        self._api.stop_torrent(torrent_ids)

    def set_alt_speed_enabled(self, is_enabled):
        """Set the alternative speed flag."""
        self._api.set_session(alt_speed_enabled=is_enabled)

    def get_alt_speed_enabled(self):
        """Get the alternative speed flag."""
        if self._session is None:
            return None

        return self._session.alt_speed_enabled
