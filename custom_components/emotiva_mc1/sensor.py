"""Sensor entities for Emotiva MC1 RS232."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfSoundPressure
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import CONF_INPUT_ENTITY_MAP, CONF_SOURCE_NAMES, DOMAIN, SOURCES
from .mc1_serial import MC1Serial

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Emotiva MC1 sensor entities."""
    device: MC1Serial = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            EmotivaMC1VolumeSensor(device, entry),
            EmotivaMC1SourceSensor(device, entry),
            EmotivaMC1SoundModeSensor(device, entry),
            EmotivaMC1ActiveDeviceSensor(device, entry),
        ]
    )


class EmotivaMC1SensorBase(SensorEntity, RestoreEntity):
    """Base class for MC1 sensors."""

    _attr_has_entity_name = True

    def __init__(self, device: MC1Serial, entry: ConfigEntry) -> None:
        self._device = device
        self._entry = entry
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

    async def async_will_remove_from_hass(self) -> None:
        if self._unregister_callback:
            self._unregister_callback()

    @callback
    def _handle_update(self) -> None:
        self.schedule_update_ha_state()


class EmotivaMC1VolumeSensor(EmotivaMC1SensorBase):
    """Volume level (raw 0-200 scale)."""

    _attr_name = "Volume"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:volume-high"

    def __init__(self, device: MC1Serial, entry: ConfigEntry) -> None:
        super().__init__(device, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_volume"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._device.state.volume_raw = int(float(last_state.state) * 10)

    @property
    def native_value(self) -> float | None:
        if self._device.state.volume_raw is None:
            return None
        return self._device.state.volume_raw / 10.0


class EmotivaMC1SourceSensor(EmotivaMC1SensorBase):
    """Current input source."""

    _attr_name = "Input Source"
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, device: MC1Serial, entry: ConfigEntry) -> None:
        super().__init__(device, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_source"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._device.state.source = last_state.state

    @property
    def native_value(self) -> str | None:
        return self._device.state.source


class EmotivaMC1SoundModeSensor(EmotivaMC1SensorBase):
    """Current sound mode."""

    _attr_name = "Sound Mode"
    _attr_icon = "mdi:surround-sound"

    def __init__(self, device: MC1Serial, entry: ConfigEntry) -> None:
        super().__init__(device, entry)
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_sound_mode"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state not in (None, "unknown", "unavailable"):
                self._device.state.sound_mode = last_state.state

    @property
    def native_value(self) -> str | None:
        return self._device.state.sound_mode


class EmotivaMC1ActiveDeviceSensor(EmotivaMC1SensorBase):
    """Resolves the current input to a linked HA entity."""

    _attr_name = "Active Device"
    _attr_icon = "mdi:link-variant"

    def __init__(self, device: MC1Serial, entry: ConfigEntry) -> None:
        super().__init__(device, entry)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_active_device"

    @property
    def native_value(self) -> str | None:
        """Return the entity_id of the device linked to the current input."""
        current_source = self._device.state.source
        if not current_source:
            return None
        input_entity_map = self._entry.options.get(CONF_INPUT_ENTITY_MAP, {})
        return input_entity_map.get(current_source)

    @property
    def extra_state_attributes(self) -> dict:
        """Return the current input name and linked entity."""
        attrs = {}
        current_source = self._device.state.source
        attrs["input_name"] = current_source
        input_entity_map = self._entry.options.get(CONF_INPUT_ENTITY_MAP, {})
        attrs["linked_entity"] = input_entity_map.get(current_source) if current_source else None
        attrs["input_entity_map"] = input_entity_map
        return attrs
