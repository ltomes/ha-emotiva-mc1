"""Select entity for Emotiva MC1 RS232 - source selection for dashboards."""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, SOUND_MODES, get_source_config
from .mc1_serial import MC1Serial

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Emotiva MC1 select entities."""
    device: MC1Serial = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EmotivaMC1SourceSelect(device, entry),
        EmotivaMC1SoundModeSelect(device, entry),
    ])


class EmotivaMC1SourceSelect(SelectEntity, RestoreEntity):
    """Source selector for dashboard use."""

    _attr_has_entity_name = True
    _attr_name = "Source"
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, device: MC1Serial, entry: ConfigEntry) -> None:
        self._device = device
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_source_select"
        name_to_cmd, _ = get_source_config(entry.options)
        self._attr_options = list(name_to_cmd.keys())
        self._unregister_callback = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Emotiva MC1",
            manufacturer="Emotiva",
            model="MC1",
        )

    async def async_added_to_hass(self) -> None:
        self._unregister_callback = self._device.register_callback(
            self._handle_update
        )
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state and last_state.state != "unknown":
                self._device.state.source = last_state.state

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister_callback:
            self._unregister_callback()

    @callback
    def _handle_update(self) -> None:
        self.schedule_update_ha_state()

    @property
    def current_option(self) -> str | None:
        return self._device.state.source

    async def async_select_option(self, option: str) -> None:
        await self._device.select_source(option)


class EmotivaMC1SoundModeSelect(SelectEntity, RestoreEntity):
    """Sound mode selector for dashboard use."""

    _attr_has_entity_name = True
    _attr_name = "Sound Mode"
    _attr_icon = "mdi:surround-sound"

    def __init__(self, device: MC1Serial, entry: ConfigEntry) -> None:
        self._device = device
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_sound_mode_select"
        self._attr_options = list(SOUND_MODES.keys())
        self._unregister_callback = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Emotiva MC1",
            manufacturer="Emotiva",
            model="MC1",
        )

    async def async_added_to_hass(self) -> None:
        self._unregister_callback = self._device.register_callback(
            self._handle_update
        )
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state and last_state.state != "unknown":
                self._device.state.sound_mode = last_state.state

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister_callback:
            self._unregister_callback()

    @callback
    def _handle_update(self) -> None:
        self.schedule_update_ha_state()

    @property
    def current_option(self) -> str | None:
        return self._device.state.sound_mode

    async def async_select_option(self, option: str) -> None:
        await self._device.select_sound_mode(option)
