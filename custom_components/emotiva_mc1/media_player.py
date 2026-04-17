"""Media player entity for Emotiva MC1 RS232."""

import asyncio
import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_PLAYING, STATE_PAUSED
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    ATTR_MEDIA_DAG_ACTIVE_SOURCE_ENTITY,
    ATTR_MEDIA_DAG_DISPLAY_ENTITY,
    ATTR_MEDIA_DAG_INPUT_MAP,
    ATTR_MEDIA_DAG_ROLE,
    ATTR_MEDIA_DAG_SOURCE_ENTITIES,
    CONF_DISPLAY_ENTITY,
    CONF_INPUT_ENTITY_MAP,
    CONF_POLL_INTERVAL,
    CONF_POWER_ENTITY,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    SOUND_MODES,
    get_source_config,
)
from .mc1_serial import MC1Serial
from .power import discover_power_siblings

_LOGGER = logging.getLogger(__name__)

# Attribute key on source entities that contains now-playing info
ATTR_NOW_PLAYING = "media_dag_now_playing"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Emotiva MC1 media player."""
    device: MC1Serial = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EmotivaMC1MediaPlayer(hass, device, entry)])


class EmotivaMC1MediaPlayer(MediaPlayerEntity, RestoreEntity):
    """Representation of the Emotiva MC1 as a media player."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_has_entity_name = True
    _attr_name = None  # Use device name
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, device: MC1Serial, entry: ConfigEntry) -> None:
        self.hass = hass
        self._device = device
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_media_player"
        self._unregister_callback = None
        self._poll_task: asyncio.Task | None = None
        self._source_name_to_cmd, _ = get_source_config(entry.options)
        self._unsub_source_listeners: list = []
        self._power_sensors: dict[str, str] = {}

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Emotiva MC1",
            manufacturer="Emotiva",
            model="MC1",
        )

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = (
            MediaPlayerEntityFeature.VOLUME_STEP
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.SELECT_SOURCE
            | MediaPlayerEntityFeature.SELECT_SOUND_MODE
        )
        # Show playback controls only when the active source has active media
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            features |= (
                MediaPlayerEntityFeature.PLAY
                | MediaPlayerEntityFeature.PAUSE
                | MediaPlayerEntityFeature.STOP
                | MediaPlayerEntityFeature.NEXT_TRACK
                | MediaPlayerEntityFeature.PREVIOUS_TRACK
            )
        return features

    async def async_added_to_hass(self) -> None:
        """Register callback and restore previous state."""
        # Discover power sensor siblings from the power switch
        power_entity = self._entry.options.get(CONF_POWER_ENTITY)
        if power_entity:
            self._power_sensors = discover_power_siblings(self.hass, power_entity)

        self._unregister_callback = self._device.register_callback(
            self._handle_update
        )

        # Restore previous state
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in (MediaPlayerState.ON, MediaPlayerState.OFF):
                self._device.state.power = last_state.state == MediaPlayerState.ON
            attrs = last_state.attributes
            if (source := attrs.get("source")) is not None:
                self._device.state.source = source
            if (mode := attrs.get("sound_mode")) is not None:
                self._device.state.sound_mode = mode
            if (muted := attrs.get("is_volume_muted")) is not None:
                self._device.state.muted = muted
            if (vol_raw := attrs.get("volume_raw")) is not None:
                self._device.state.volume_raw = int(vol_raw)

        # Track state changes on all linked source entities
        self._setup_source_listeners()

        # Start polling task
        poll_interval = self._entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        if poll_interval > 0:
            self._poll_task = asyncio.create_task(self._poll_loop(poll_interval))

    def _setup_source_listeners(self) -> None:
        """Listen for state changes on all linked source and power entities."""
        # Clean up old listeners
        for unsub in self._unsub_source_listeners:
            unsub()
        self._unsub_source_listeners.clear()

        entities_to_track = set()

        input_entity_map = self._entry.options.get(CONF_INPUT_ENTITY_MAP, {})
        entities_to_track.update(eid for eid in input_entity_map.values() if eid)

        power_entity = self._entry.options.get(CONF_POWER_ENTITY)
        if power_entity:
            entities_to_track.add(power_entity)

        if entities_to_track:
            self._unsub_source_listeners.append(
                async_track_state_change_event(
                    self.hass, list(entities_to_track), self._handle_source_state_change
                )
            )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed."""
        if self._unregister_callback:
            self._unregister_callback()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        for unsub in self._unsub_source_listeners:
            unsub()
        self._unsub_source_listeners.clear()

    @callback
    def _handle_update(self) -> None:
        """Handle state update from the device."""
        self.schedule_update_ha_state()

    @callback
    def _handle_source_state_change(self, event: Event) -> None:
        """Handle state change of a linked source entity."""
        self.async_write_ha_state()

    async def _poll_loop(self, interval: int) -> None:
        """Periodically poll the MC1 for state."""
        while True:
            try:
                await asyncio.sleep(interval)
                if self._device.connected:
                    await self._device.query_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Error in poll loop")
                await asyncio.sleep(interval)

    def _get_active_source_entity_id(self) -> str | None:
        """Get the entity_id of the currently active source."""
        input_entity_map = self._entry.options.get(CONF_INPUT_ENTITY_MAP, {})
        current_source = self._device.state.source
        if not current_source:
            return None
        return input_entity_map.get(current_source)

    def _get_active_source_state(self):
        """Get the state object of the currently active source."""
        entity_id = self._get_active_source_entity_id()
        if not entity_id:
            return None
        return self.hass.states.get(entity_id)

    # ── State properties ──

    def _is_power_on(self) -> bool | None:
        """Determine if the receiver is powered on.

        Returns True/False if we can determine power, None if unknown.
        Priority: serial power query > infer from data > power entity (smart plug).

        The smart plug tells us the outlet has power (always on for standby),
        but the serial connection knows if the processor is actually on.
        """
        # 1. Serial power query — most accurate when responding
        if self._device.state.power_ever_responded:
            return self._device.state.power

        # 2. Infer from connection + data
        if self._device.connected and (
            self._device.state.source is not None
            or self._device.state.volume_raw is not None
        ):
            return True

        if not self._device.connected:
            return False

        # 3. Power entity (smart plug) — fallback only
        #    Plug being "on" just means the outlet has power, not that the
        #    processor is active. Only use when serial hasn't responded yet.
        power_entity = self._entry.options.get(CONF_POWER_ENTITY)
        if power_entity:
            power_state = self.hass.states.get(power_entity)
            if power_state and power_state.state == "off":
                return False

        return None

    @property
    def state(self) -> MediaPlayerState:
        # Plug off = truly off (no power at all)
        power_entity = self._entry.options.get(CONF_POWER_ENTITY)
        if power_entity:
            plug_state = self.hass.states.get(power_entity)
            if plug_state and plug_state.state == "off":
                return MediaPlayerState.OFF

        power = self._is_power_on()

        if power is False:
            return MediaPlayerState.IDLE  # serial says off, plug on = standby
        if power is None:
            return MediaPlayerState.IDLE

        # Receiver is on — it processes audio but doesn't generate content.
        # Playback state belongs to the source, not the receiver.
        return MediaPlayerState.ON

    @property
    def volume_level(self) -> float | None:
        return self._device.state.volume_level

    @property
    def is_volume_muted(self) -> bool | None:
        return self._device.state.muted

    @property
    def source(self) -> str | None:
        return self._device.state.source

    @property
    def source_list(self) -> list[str]:
        return list(self._source_name_to_cmd.keys())

    @property
    def sound_mode(self) -> str | None:
        return self._device.state.sound_mode

    @property
    def sound_mode_list(self) -> list[str]:
        return list(SOUND_MODES.keys())

    # ── Now-playing properties from active source ──

    @property
    def media_content_type(self) -> str | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_content_type")
        return None

    @property
    def media_title(self) -> str | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_title")
        return None

    @property
    def media_series_title(self) -> str | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_series_title")
        return None

    @property
    def media_season(self) -> str | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_season")
        return None

    @property
    def media_episode(self) -> str | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_episode")
        return None

    @property
    def media_duration(self) -> int | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_duration")
        return None

    @property
    def media_position(self) -> int | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_position")
        return None

    @property
    def media_position_updated_at(self):
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("media_position_updated_at")
        return None

    @property
    def media_image_url(self) -> str | None:
        active = self._get_active_source_state()
        if active and active.state in (STATE_PLAYING, STATE_PAUSED):
            return active.attributes.get("entity_picture")
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return extra state attributes including media DAG."""
        attrs = {}
        if self._device.state.volume_raw is not None:
            attrs["volume_raw"] = self._device.state.volume_raw
        attrs["connected"] = self._device.connected
        attrs["power_reported"] = self._device.state.power
        attrs["power_reliable"] = self._device.state.power_ever_responded

        # Power switch entity
        power_entity = self._entry.options.get(CONF_POWER_ENTITY)
        if power_entity:
            attrs["power_switch"] = power_entity

        # Power monitoring from smart plug
        if self._power_sensors:
            power_data = {}
            for key, entity_id in self._power_sensors.items():
                if key == "switch":
                    continue
                state = self.hass.states.get(entity_id)
                if state and state.state not in ("unavailable", "unknown"):
                    try:
                        power_data[key] = float(state.state)
                    except (ValueError, TypeError):
                        power_data[key] = state.state
            if power_data:
                attrs["power_monitoring"] = power_data

        # Media DAG attributes
        attrs[ATTR_MEDIA_DAG_ROLE] = "receiver"

        input_entity_map = self._entry.options.get(CONF_INPUT_ENTITY_MAP, {})
        attrs[ATTR_MEDIA_DAG_INPUT_MAP] = input_entity_map

        display_entity = self._entry.options.get(CONF_DISPLAY_ENTITY)
        if display_entity:
            attrs[ATTR_MEDIA_DAG_DISPLAY_ENTITY] = display_entity

        source_entities = list(
            {eid for eid in input_entity_map.values() if eid}
        )
        attrs[ATTR_MEDIA_DAG_SOURCE_ENTITIES] = source_entities

        current_source = self._device.state.source
        active_entity = input_entity_map.get(current_source) if current_source else None
        attrs[ATTR_MEDIA_DAG_ACTIVE_SOURCE_ENTITY] = active_entity

        return attrs

    # ── Receiver commands ──

    async def async_turn_on(self) -> None:
        await self._device.power_on()
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await self._device.power_off()
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        await self._device.volume_up()
        self.async_write_ha_state()

    async def async_volume_down(self) -> None:
        await self._device.volume_down()
        self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._device.volume_set_level(volume)
        self.async_write_ha_state()

    async def async_mute_volume(self, mute: bool) -> None:
        if mute:
            await self._device.mute_on()
        else:
            await self._device.mute_off()
        self.async_write_ha_state()

    async def async_select_source(self, source: str) -> None:
        await self._device.select_source(source)
        self.async_write_ha_state()

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        await self._device.select_sound_mode(sound_mode)
        self.async_write_ha_state()

    # ── Playback commands — forwarded to active source ──

    async def _forward_to_active_source(self, service: str, **kwargs) -> None:
        """Forward a media_player service call to the active source."""
        entity_id = self._get_active_source_entity_id()
        if not entity_id:
            _LOGGER.warning("No active source to forward %s to", service)
            return
        data = {"entity_id": entity_id}
        data.update(kwargs)
        await self.hass.services.async_call("media_player", service, data)

    async def async_media_play(self) -> None:
        await self._forward_to_active_source("media_play")

    async def async_media_pause(self) -> None:
        await self._forward_to_active_source("media_pause")

    async def async_media_stop(self) -> None:
        await self._forward_to_active_source("media_stop")

    async def async_media_next_track(self) -> None:
        await self._forward_to_active_source("media_next_track")

    async def async_media_previous_track(self) -> None:
        await self._forward_to_active_source("media_previous_track")
