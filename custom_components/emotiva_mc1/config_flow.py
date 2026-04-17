"""Config flow for Emotiva MC1 RS232 integration."""

import glob
import logging

import serial
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_BAUD_RATE,
    CONF_DISPLAY_ENTITY,
    CONF_ENABLED_SOURCES,
    CONF_INPUT_ENTITY_MAP,
    CONF_POLL_INTERVAL,
    CONF_POWER_ENTITY,
    CONF_SERIAL_PORT,
    CONF_SOURCE_NAMES,
    DEFAULT_BAUD_RATE,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    SOURCES,
)

# Key used for the ObjectSelector list of input configs
CONF_INPUTS = "inputs"

_LOGGER = logging.getLogger(__name__)


def _detect_serial_ports() -> list[str]:
    """Detect available serial ports."""
    ports = []
    by_id = glob.glob("/dev/serial/by-id/*")
    ports.extend(sorted(by_id))
    tty_usb = glob.glob("/dev/ttyUSB*")
    ports.extend(sorted(tty_usb))
    return ports


def _test_serial_port(port: str, baud: int) -> bool:
    """Test if we can open the serial port."""
    try:
        ser = serial.Serial(port, baud, timeout=1)
        ser.close()
        return True
    except Exception as e:
        _LOGGER.error("Failed to open serial port %s: %s", port, e)
        return False


class EmotivaMC1ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Emotiva MC1 RS232."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            port = user_input[CONF_SERIAL_PORT]
            baud = user_input.get(CONF_BAUD_RATE, DEFAULT_BAUD_RATE)

            can_open = await self.hass.async_add_executor_job(
                _test_serial_port, port, baud
            )
            if not can_open:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(port)
                self._abort_if_unique_id_configured()

                # Enable all sources by default
                all_source_names = list(SOURCES.values())

                return self.async_create_entry(
                    title=DEFAULT_NAME,
                    data={
                        CONF_SERIAL_PORT: port,
                        CONF_BAUD_RATE: baud,
                    },
                    options={
                        CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL,
                        CONF_ENABLED_SOURCES: all_source_names,
                        CONF_SOURCE_NAMES: {},
                    },
                )

        ports = await self.hass.async_add_executor_job(_detect_serial_ports)
        port_selector = vol.In(ports) if ports else str

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIAL_PORT): port_selector,
                    vol.Optional(CONF_BAUD_RATE, default=DEFAULT_BAUD_RATE): vol.In(
                        [9600, 19200, 38400, 57600, 115200]
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EmotivaMC1OptionsFlow(config_entry)


class EmotivaMC1OptionsFlow(config_entries.OptionsFlow):
    """Handle options for Emotiva MC1."""

    def __init__(self, config_entry):
        self._config_entry = config_entry
        self._options = dict(config_entry.options)

    def _options_to_input_list(self) -> list[dict]:
        """Convert current options into the ObjectSelector list format."""
        enabled = self._options.get(CONF_ENABLED_SOURCES, [])
        custom_names = self._options.get(CONF_SOURCE_NAMES, {})
        entity_map = self._options.get(CONF_INPUT_ENTITY_MAP, {})

        items = []
        for default_name in enabled:
            display_name = custom_names.get(default_name, default_name)
            item = {"input": default_name, "name": display_name}
            entity_id = entity_map.get(display_name)
            if entity_id:
                item["entity"] = entity_id
            items.append(item)
        return items

    def _input_list_to_options(self, items: list[dict]) -> None:
        """Convert the ObjectSelector list back into options format."""
        enabled_sources = []
        source_names = {}
        input_entity_map = {}

        for item in items:
            default_name = item.get("input", "")
            if not default_name:
                continue
            enabled_sources.append(default_name)

            custom_name = item.get("name", "").strip()
            if custom_name and custom_name != default_name:
                source_names[default_name] = custom_name
            display_name = custom_name if (custom_name and custom_name != default_name) else default_name

            entity_id = item.get("entity")
            if entity_id:
                input_entity_map[display_name] = entity_id

        self._options[CONF_ENABLED_SOURCES] = enabled_sources
        self._options[CONF_SOURCE_NAMES] = source_names
        self._options[CONF_INPUT_ENTITY_MAP] = input_entity_map

    async def async_step_init(self, user_input=None):
        """Unified config: general settings + per-input configuration."""
        if user_input is not None:
            self._options[CONF_POLL_INTERVAL] = user_input[CONF_POLL_INTERVAL]

            display_entity = user_input.get(CONF_DISPLAY_ENTITY)
            if display_entity:
                self._options[CONF_DISPLAY_ENTITY] = display_entity
            else:
                self._options.pop(CONF_DISPLAY_ENTITY, None)

            power_entity = user_input.get(CONF_POWER_ENTITY)
            if power_entity:
                self._options[CONF_POWER_ENTITY] = power_entity
            else:
                self._options.pop(CONF_POWER_ENTITY, None)

            self._input_list_to_options(user_input.get(CONF_INPUTS, []))

            return self.async_create_entry(title="", data=self._options)

        # Build the input list from current options
        current_inputs = self._options_to_input_list()

        all_input_options = [
            selector.SelectOptionDict(value=name, label=name)
            for name in SOURCES.values()
        ]

        input_object_sel = selector.ObjectSelector(
            selector.ObjectSelectorConfig(
                multiple=True,
                label_field="name",
                description_field="input",
                fields={
                    "input": {
                        "label": "Physical Input",
                        "required": True,
                        "selector": {
                            "select": {
                                "options": [
                                    {"value": name, "label": name}
                                    for name in SOURCES.values()
                                ],
                                "mode": "dropdown",
                            }
                        },
                    },
                    "name": {
                        "label": "Friendly Name",
                        "required": True,
                        "selector": {"text": {}},
                    },
                    "entity": {
                        "label": "Linked Device",
                        "selector": {
                            "entity": {
                                "domain": ["media_player", "remote"],
                            }
                        },
                    },
                },
            )
        )

        entity_sel = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["media_player", "remote"],
            )
        )

        schema_dict = {}

        # Poll interval
        schema_dict[vol.Optional(
            CONF_POLL_INTERVAL,
            default=self._options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=300, step=1, mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="seconds",
            )
        )

        # Power entity (smart plug switch)
        power_sel = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["switch", "binary_sensor"],
            )
        )
        current_power = self._options.get(CONF_POWER_ENTITY)
        power_key = vol.Optional(CONF_POWER_ENTITY)
        if current_power:
            power_key = vol.Optional(CONF_POWER_ENTITY, default=current_power)
        schema_dict[power_key] = power_sel

        # Display entity
        current_display = self._options.get(CONF_DISPLAY_ENTITY)
        display_key = vol.Optional(CONF_DISPLAY_ENTITY)
        if current_display:
            display_key = vol.Optional(CONF_DISPLAY_ENTITY, default=current_display)
        schema_dict[display_key] = entity_sel

        # Inputs — ObjectSelector with pre-populated list
        schema_dict[vol.Optional(
            CONF_INPUTS, default=current_inputs
        )] = input_object_sel

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
        )
