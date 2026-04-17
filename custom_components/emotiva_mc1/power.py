"""Power monitoring helpers — discover sibling sensors from a power switch entity."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

# Map unit_of_measurement to a friendly key
_UNIT_TO_KEY = {
    "W": "power_w",
    "kWh": "energy_kwh",
    "V": "voltage_v",
    "A": "current_a",
}


def discover_power_siblings(
    hass: HomeAssistant, power_entity_id: str
) -> dict[str, str]:
    """Given a power switch entity_id, find sibling sensor entities on the same device.

    Returns a dict like:
        {
            "switch": "switch.wall_plug_switch",
            "power_w": "sensor.wall_plug_switch_electric_consumption_w",
            "energy_kwh": "sensor.wall_plug_switch_electric_consumption_kwh",
            "voltage_v": "sensor.wall_plug_switch_electric_consumption_v",
            "current_a": "sensor.wall_plug_switch_electric_consumption_a",
        }
    """
    registry = er.async_get(hass)
    result = {"switch": power_entity_id}

    # Find the device_id for the power entity
    power_entry = registry.async_get(power_entity_id)
    if not power_entry or not power_entry.device_id:
        _LOGGER.debug("Power entity %s has no device_id", power_entity_id)
        return result

    device_id = power_entry.device_id

    # Find all sensor siblings on the same device
    for entry in registry.entities.values():
        if entry.device_id != device_id:
            continue
        if entry.domain != "sensor":
            continue
        if entry.disabled_by is not None:
            continue

        unit = entry.unit_of_measurement
        if unit in _UNIT_TO_KEY:
            key = _UNIT_TO_KEY[unit]
            if key not in result:  # first match wins
                result[key] = entry.entity_id

    _LOGGER.debug("Power siblings for %s: %s", power_entity_id, result)
    return result
