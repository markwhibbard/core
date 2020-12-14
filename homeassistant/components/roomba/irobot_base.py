"""Base class for iRobot devices."""
import asyncio
import logging
import time
import json
from roombaPic.roombaPic import draw_map, load_state_info

from homeassistant.components.vacuum import (
    ATTR_STATUS,
    STATE_CLEANING,
    STATE_DOCKED,
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_RETURNING,
    SUPPORT_BATTERY,
    SUPPORT_LOCATE,
    SUPPORT_PAUSE,
    SUPPORT_RETURN_HOME,
    SUPPORT_SEND_COMMAND,
    SUPPORT_START,
    SUPPORT_STATE,
    SUPPORT_STATUS,
    SUPPORT_STOP,
    StateVacuumEntity,
)
from homeassistant.helpers.entity import Entity

from . import roomba_reported_state
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ATTR_CLEANING_TIME = "cleaning_time"
ATTR_CLEANED_AREA = "cleaned_area"
ATTR_ERROR = "error"
ATTR_ERROR_CODE = "error_code"
ATTR_POSITION = "position"
ATTR_SOFTWARE_VERSION = "software_version"

# Commonly supported features
SUPPORT_IROBOT = (
    SUPPORT_BATTERY
    | SUPPORT_PAUSE
    | SUPPORT_RETURN_HOME
    | SUPPORT_SEND_COMMAND
    | SUPPORT_START
    | SUPPORT_STATE
    | SUPPORT_STATUS
    | SUPPORT_STOP
    | SUPPORT_LOCATE
)

STATE_MAP = {
    "": STATE_IDLE,
    "charge": STATE_DOCKED,
    "evac": STATE_RETURNING,  # Emptying at cleanbase
    "hmMidMsn": STATE_CLEANING,  # Recharging at the middle of a cycle
    "hmPostMsn": STATE_RETURNING,  # Cycle finished
    "hmUsrDock": STATE_RETURNING,
    "pause": STATE_PAUSED,
    "run": STATE_CLEANING,
    "stop": STATE_IDLE,
    "stuck": STATE_ERROR,
}


class IRobotEntity(Entity):
    """Base class for iRobot Entities."""

    def __init__(self, roomba, blid):
        """Initialize the iRobot handler."""
        self.vacuum = roomba
        self._blid = blid
        self.vacuum_state = roomba_reported_state(roomba)
        self._name = self.vacuum_state.get("name")
        self._version = self.vacuum_state.get("softwareVer")
        self._sku = self.vacuum_state.get("sku")

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def robot_unique_id(self):
        """Return the uniqueid of the vacuum cleaner."""
        return f"roomba_{self._blid}"

    @property
    def unique_id(self):
        """Return the uniqueid of the vacuum cleaner."""
        return self.robot_unique_id

    @property
    def device_info(self):
        """Return the device info of the vacuum cleaner."""
        return {
            "identifiers": {(DOMAIN, self.robot_unique_id)},
            "manufacturer": "iRobot",
            "name": str(self._name),
            "sw_version": self._version,
            "model": self._sku,
        }

    @property
    def _battery_level(self):
        """Return the battery level of the vacuum cleaner."""
        return self.vacuum_state.get("batPct")

    @property
    def _robot_state(self):
        """Return the state of the vacuum cleaner."""
        clean_mission_status = self.vacuum_state.get("cleanMissionStatus", {})
        cycle = clean_mission_status.get("cycle")
        phase = clean_mission_status.get("phase")
        try:
            state = STATE_MAP[phase]
        except KeyError:
            return STATE_ERROR
        if cycle != "none" and state in (STATE_IDLE, STATE_DOCKED):
            state = STATE_PAUSED
        return state

    async def async_added_to_hass(self):
        """Register callback function."""
        self.vacuum.register_on_message_callback(self.on_message)

    def new_state_filter(self, new_state):  # pylint: disable=no-self-use
        """Filter out wifi state messages."""
        return len(new_state) > 1 or "signal" not in new_state

    def on_message(self, json_data):
        """Update state on message change."""
        state = json_data.get("state", {}).get("reported", {})
        if self.new_state_filter(state):
            self.schedule_update_ha_state()


class IRobotVacuum(IRobotEntity, StateVacuumEntity):
    """Base class for iRobot robots."""

    should_poll = True

    def __init__(self, roomba, blid):
        """Initialize the iRobot handler."""
        super().__init__(roomba, blid)
        self._cap_position = self.vacuum_state.get("cap", {}).get("pose") == 1

        self.cache_index = 0
        self.cached_map = None
        self.save_state = False
        self.last_save = time.time()
        self.draw_map = False
        self.last_draw = time.time()
        self.max_age = 5 * 12 * 3600
        self.io_interval = 60
        self.draw_interval = 10
        self.state_filename = "/home/mwh/Scripts/core/config/" + blid + ".json"
        self.map_filename = "/home/mwh/Scripts/TileBoard/build/images/" + blid + ".png"
        try:
            
            with open(self.state_filename) as f:
                last_state = json.load(f)
            
            #last_state = load_state_info(self.state_filename)
            self._last_cleaning_time = last_state['last_cleaning_time']
            self._last_cleaned_area = last_state['last_cleaned_area']
            self._positions = last_state['positions']
        except FileNotFoundError:
            self._last_cleaning_time = 0
            self._last_cleaned_area = 0
            self._positions = []
            print("No history file found, reinitializing")   

        self._last_connect_timestamp = 0

    @property
    def supported_features(self):
        """Flag vacuum cleaner robot features that are supported."""
        return SUPPORT_IROBOT

    @property
    def battery_level(self):
        """Return the battery level of the vacuum cleaner."""
        return self._battery_level

    @property
    def state(self):
        """Return the state of the vacuum cleaner."""
        return self._robot_state

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True  # Always available, otherwise setup will fail

    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        state = self.vacuum_state

        # Roomba software version
        software_version = state.get("softwareVer")

        # Set properties that are to appear in the GUI
        state_attrs = {ATTR_SOFTWARE_VERSION: software_version}

        # Set legacy status to avoid break changes
        state_attrs[ATTR_STATUS] = self.vacuum.current_state

        state_attrs["last_connected_at"] = self._last_connect_timestamp

        # Only add cleaning time and cleaned area attrs when the vacuum is
        # currently on
        if self.state == STATE_CLEANING:
            # Get clean mission status
            mission_state = state.get("cleanMissionStatus", {})
            self._last_cleaning_time = mission_state.get("mssnM")
            self._last_cleaned_area = mission_state.get("sqft")  # Imperial
            # Convert to m2 if the unit_system is set to metric
            if self._last_cleaned_area and self.hass.config.units.is_metric:
                self._last_cleaned_area = round(self._last_cleaned_area * 0.0929)
            self.save_state = True
        state_attrs[ATTR_CLEANING_TIME] = self._last_cleaning_time
        state_attrs[ATTR_CLEANED_AREA] = self._last_cleaned_area

        # Error
        if self.vacuum.error_code != 0:
            state_attrs[ATTR_ERROR] = self.vacuum.error_message
            state_attrs[ATTR_ERROR_CODE] = self.vacuum.error_code

        # Not all Roombas expose position data
        # https://github.com/koalazak/dorita980/issues/48
        if self._cap_position:
            pos_state = state.get("pose", {})
            position = None
            pos_x = pos_state.get("point", {}).get("x")
            pos_y = pos_state.get("point", {}).get("y")
            theta = pos_state.get("theta")
            if all(item is not None for item in [pos_x, pos_y, theta]):
                position = f"({pos_x}, {pos_y}, {theta})"
                pos_list = [pos_x, pos_y, theta, time.time()]
                if len(self._positions) > 1:
                    if self._positions[-1][0:2] != pos_list[0:2]:
                        self._positions.append(pos_list)
                        self.draw_map = True
                        self.save_state = True
                else:
                    self._positions.append(pos_list)
                    self.draw_map = True
                    self.save_state = True
            state_attrs[ATTR_POSITION] = position

        return state_attrs

    def on_message(self, json_data):
        """Update state on message change."""
        state = json_data.get("state", {}).get("reported", {})
        if self.new_state_filter(state):
            _LOGGER.debug("Got new state from the vacuum: %s", json_data)
            self.schedule_update_ha_state(force_refresh=True)

    async def async_start(self, **kwargs):
        """Start or resume the cleaning task."""
        if self.state == STATE_PAUSED:
            await self.hass.async_add_executor_job(self.vacuum.send_command, "resume")
        else:
            await self.hass.async_add_executor_job(self.vacuum.send_command, "start")

    async def async_stop(self, **kwargs):
        """Stop the vacuum cleaner."""
        await self.hass.async_add_executor_job(self.vacuum.send_command, "stop")

    async def async_pause(self):
        """Pause the cleaning cycle."""
        await self.hass.async_add_executor_job(self.vacuum.send_command, "pause")

    async def async_return_to_base(self, **kwargs):
        """Set the vacuum cleaner to return to the dock."""
        if self.state == STATE_CLEANING:
            await self.async_pause()
            for _ in range(0, 10):
                if self.state == STATE_PAUSED:
                    break
                await asyncio.sleep(1)
        await self.hass.async_add_executor_job(self.vacuum.send_command, "dock")

    async def async_locate(self, **kwargs):
        """Located vacuum."""
        await self.hass.async_add_executor_job(self.vacuum.send_command, "find")

    async def async_send_command(self, command, params=None, **kwargs):
        """Send raw command."""
        _LOGGER.debug("async_send_command %s (%s), %s", command, params, kwargs)
        await self.hass.async_add_executor_job(
            self.vacuum.send_command, command, params
        )

    def age_out_positions(self):
        while True:
            if len(self._positions) < 1:
                return
            if time.time() - self._positions[0][3] < self.max_age:
                return
            self._positions.pop(0)

    def do_save_state(self):
        #print("Saving roomba state information")
        state_info = {
            "last_cleaning_time": self._last_cleaning_time,
            "last_cleaned_area": self._last_cleaned_area,
            "positions": self._positions
        }
        with open(self.state_filename, "w") as f:
            json.dump(state_info, f)

    def update(self):

        if self.save_state and time.time() - self.last_save > self.io_interval:
            self.last_save = time.time()
            self.do_save_state()
            #print("Save took" + str(time.time() - self.last_save))
            self.save_state = False
            self.cache_index = 0
            self.cached_map = None

        if self.draw_map and time.time() - self.last_draw > self.draw_interval:
            #print("Drawing map, elapsed time: " + str(time.time() - self.last_draw))
            self.last_draw = time.time()
            self.draw_map = False
            self.cached_map = draw_map(self._positions, self.map_filename, startindex=self.cache_index, cache=self.cached_map)
            self.cache_index = len(self._positions) - 1
            print("Draw took: "  + str(time.time() - self.last_draw))

        self.age_out_positions()
        return

        if self.vacuum.roomba_connected:
            self._last_connect_timestamp = time.time()
        else:
            if time.time() - self._last_connect_timestamp > 20:
                _LOGGER.error("Timeout on connection... attempting to reconnect...")
                print("Attempting to reconnect")
                try:
                    roomba.connect()
                except RoombaConnectionError as err:
                    _LOGGER.error("Error to connect to vacuum")
                    print("Could not connect")
