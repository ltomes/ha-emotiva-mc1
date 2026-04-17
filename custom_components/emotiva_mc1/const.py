"""Constants for the Emotiva MC1 RS232 integration."""

DOMAIN = "emotiva_mc1"

CONF_SERIAL_PORT = "serial_port"
CONF_BAUD_RATE = "baud_rate"
CONF_POLL_INTERVAL = "poll_interval"
CONF_ENABLED_SOURCES = "enabled_sources"
CONF_SOURCE_NAMES = "source_names"
CONF_INPUT_ENTITY_MAP = "input_entity_map"
CONF_DISPLAY_ENTITY = "display_entity"
CONF_POWER_ENTITY = "power_entity"

# Media DAG attribute keys (shared convention across integrations)
ATTR_MEDIA_DAG_ROLE = "media_dag_role"
ATTR_MEDIA_DAG_INPUT_MAP = "media_dag_input_map"
ATTR_MEDIA_DAG_ACTIVE_SOURCE_ENTITY = "media_dag_active_source_entity"
ATTR_MEDIA_DAG_DISPLAY_ENTITY = "media_dag_display_entity"
ATTR_MEDIA_DAG_SOURCE_ENTITIES = "media_dag_source_entities"

DEFAULT_BAUD_RATE = 9600
DEFAULT_POLL_INTERVAL = 30
DEFAULT_NAME = "Emotiva MC1"

# Serial settings
SERIAL_BYTESIZE = 8
SERIAL_PARITY = "N"
SERIAL_STOPBITS = 1

# Volume range (dB)
VOLUME_MIN = -96.0
VOLUME_MAX = 0.0
VOLUME_STEP = 0.5

# RS232 Commands - format: '@<code>'
# The MC1 uses ASCII commands wrapped in single quotes: '@XXX'
CMD_POWER_ON = "@112"
CMD_POWER_OFF = "@113"

CMD_VOLUME_UP = "@11S"
CMD_VOLUME_DOWN = "@11T"
CMD_VOLUME_SET = "@11P"  # followed by -XX.X (e.g. @11P-45.5)

CMD_MUTE_ON = "@11Q"
CMD_MUTE_OFF = "@11R"
CMD_MUTE_TOGGLE = "@11U"

CMD_MODE_UP = "@11D"
CMD_MODE_DOWN = "@13W"

# Navigation
CMD_MENU = "@141"
CMD_UP = "@142"
CMD_DOWN = "@143"
CMD_RIGHT = "@144"
CMD_LEFT = "@145"
CMD_ENTER = "@146"
CMD_EXIT = "@147"
CMD_RETURN = "@148"

# Query commands (without quotes, terminated with \r)
QUERY_POWER = "@PWR:?"
QUERY_VOLUME = "@VOL:?"
QUERY_MUTE = "@AMT:?"
QUERY_SOURCE = "@SRC:?"

# Source commands - mapping of command code to friendly name
# These are the MC1-specific input codes
SOURCES = {
    "@116": "HDMI 1",
    "@115": "HDMI 2",
    "@15A": "HDMI 3",
    "@15B": "HDMI 4",
    "@15C": "HDMI 5",
    "@15D": "HDMI 6",
    "@11B": "ARC",
    "@15H": "Bluetooth",
    "@15E": "Optical 1",
    "@119": "Optical 2",
    "@117": "Coax 1",
    "@118": "Coax 2",
    "@15F": "Analog 1",
    "@15G": "Analog 2",
}

# Reverse lookup: friendly name -> command code
SOURCE_NAME_TO_CMD = {v: k for k, v in SOURCES.items()}


def get_source_config(options: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Get active sources with custom names from options.

    Returns:
        (display_name -> cmd_code, cmd_code -> display_name)
    """
    enabled = options.get(CONF_ENABLED_SOURCES, list(SOURCES.values()))
    custom_names = options.get(CONF_SOURCE_NAMES, {})

    name_to_cmd = {}
    cmd_to_name = {}
    for cmd, default_name in SOURCES.items():
        if default_name not in enabled:
            continue
        display_name = custom_names.get(default_name, default_name)
        name_to_cmd[display_name] = cmd
        cmd_to_name[cmd] = display_name

    return name_to_cmd, cmd_to_name

# Sound mode commands
SOUND_MODES = {
    "Stereo": "@11E",
    "Dolby Upmix": "@11F",
    "Multi Channel": "@11C",
    "DTS Neural:X": "@13H",
    "Pure": "@13J",
    "Direct": "@13K",
}

# Reverse lookup
SOUND_MODE_NAME_TO_CMD = {v: k for k, v in SOUND_MODES.items()}

# All raw commands available for the remote/service
ALL_COMMANDS = {
    "power_on": CMD_POWER_ON,
    "power_off": CMD_POWER_OFF,
    "volume_up": CMD_VOLUME_UP,
    "volume_down": CMD_VOLUME_DOWN,
    "mute_on": CMD_MUTE_ON,
    "mute_off": CMD_MUTE_OFF,
    "mute_toggle": CMD_MUTE_TOGGLE,
    "mode_up": CMD_MODE_UP,
    "mode_down": CMD_MODE_DOWN,
    "menu": CMD_MENU,
    "up": CMD_UP,
    "down": CMD_DOWN,
    "right": CMD_RIGHT,
    "left": CMD_LEFT,
    "enter": CMD_ENTER,
    "exit": CMD_EXIT,
    "return": CMD_RETURN,
    "mode_stereo": SOUND_MODES["Stereo"],
    "mode_dolby_upmix": SOUND_MODES["Dolby Upmix"],
    "mode_multi_channel": SOUND_MODES["Multi Channel"],
    "mode_dts_neural_x": SOUND_MODES["DTS Neural:X"],
    "mode_pure": SOUND_MODES["Pure"],
    "mode_direct": SOUND_MODES["Direct"],
    "input_hdmi_1": "@116",
    "input_hdmi_2": "@115",
    "input_hdmi_3": "@15A",
    "input_hdmi_4": "@15B",
    "input_hdmi_5": "@15C",
    "input_hdmi_6": "@15D",
    "input_arc": "@11B",
    "input_bluetooth": "@15H",
    "input_optical_1": "@15E",
    "input_optical_2": "@119",
    "input_coax_1": "@117",
    "input_coax_2": "@118",
    "input_analog_1": "@15F",
    "input_analog_2": "@15G",
}
