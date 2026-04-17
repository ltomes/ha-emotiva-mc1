"""The Emotiva MC1 RS232 integration."""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .const import ALL_COMMANDS, CONF_BAUD_RATE, CONF_SERIAL_PORT, DEFAULT_BAUD_RATE, DOMAIN, get_source_config
from .mc1_serial import MC1Serial

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.SELECT, Platform.SENSOR]

SERVICE_SEND_COMMAND = "send_command"
ATTR_COMMAND = "command"
ATTR_ENTRY_ID = "entry_id"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_COMMAND): vol.In(list(ALL_COMMANDS.keys())),
        vol.Optional(ATTR_ENTRY_ID): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Emotiva MC1 from a config entry."""
    serial_port = entry.data[CONF_SERIAL_PORT]
    baud_rate = entry.data.get(CONF_BAUD_RATE, DEFAULT_BAUD_RATE)

    device = MC1Serial(serial_port, baud_rate)

    # Apply source configuration from options
    name_to_cmd, cmd_to_name = get_source_config(entry.options)
    device.update_source_config(name_to_cmd, cmd_to_name)

    if not await device.connect():
        _LOGGER.error("Failed to connect to Emotiva MC1 at %s", serial_port)
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = device

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Register the send_command service if not already registered
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_COMMAND):

        async def handle_send_command(call: ServiceCall) -> None:
            """Handle the send_command service call."""
            command = call.data[ATTR_COMMAND]
            entry_id = call.data.get(ATTR_ENTRY_ID)

            if command not in ALL_COMMANDS:
                raise ServiceValidationError(
                    f"Unknown command: {command}. Valid commands: {', '.join(sorted(ALL_COMMANDS.keys()))}"
                )

            rs232_code = ALL_COMMANDS[command]

            if entry_id:
                # Target a specific device
                device = hass.data.get(DOMAIN, {}).get(entry_id)
                if not device:
                    raise ServiceValidationError(f"No Emotiva MC1 device found with entry_id: {entry_id}")
                await device.send_command(rs232_code)
            else:
                # Send to all connected devices
                for dev in hass.data.get(DOMAIN, {}).values():
                    if isinstance(dev, MC1Serial):
                        await dev.send_command(rs232_code)

        hass.services.async_register(
            DOMAIN, SERVICE_SEND_COMMAND, handle_send_command, schema=SERVICE_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        device: MC1Serial = hass.data[DOMAIN].pop(entry.entry_id)
        await device.disconnect()

    # Unregister service when last entry is unloaded
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_COMMAND)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
