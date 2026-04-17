"""Serial communication handler for the Emotiva MC1 processor."""

import asyncio
import logging
import re
from collections.abc import Callable

import serial_asyncio_fast as serial_asyncio

from .const import (
    CMD_MUTE_OFF,
    CMD_MUTE_ON,
    CMD_POWER_OFF,
    CMD_POWER_ON,
    CMD_VOLUME_DOWN,
    CMD_VOLUME_SET,
    CMD_VOLUME_UP,
    DEFAULT_BAUD_RATE,
    QUERY_MUTE,
    QUERY_POWER,
    QUERY_SOURCE,
    QUERY_VOLUME,
    SERIAL_BYTESIZE,
    SERIAL_PARITY,
    SERIAL_STOPBITS,
    SOUND_MODES,
    SOURCES,
    VOLUME_MAX,
    VOLUME_MIN,
)

_LOGGER = logging.getLogger(__name__)

# Regex patterns for parsing responses
# Volume response: '@14K185' - @14K followed by 0-200 value
RE_VOLUME_14K = re.compile(r"@14K(\d+)")
# Legacy volume response: '@11S-45.5' or '@11P-30.0' or '@11T-46.0'
RE_VOLUME_LEGACY = re.compile(r"@11[STP](-?\d+\.?\d*)")
# Power responses
RE_POWER_ON = re.compile(r"@112")
RE_POWER_OFF = re.compile(r"@113")
# Mute responses
RE_MUTE_ON = re.compile(r"@11Q")
RE_MUTE_OFF = re.compile(r"@11R")
# Source response: '@15A', '@116', etc.
RE_SOURCE = re.compile(r"@1[15][0-9A-Z]")
# Sound mode responses - @11E, @11C, @11F, @13H, @13J, @13K
RE_SOUND_MODE = re.compile(r"@1[13][A-Z]")
# Query responses
RE_QUERY_POWER = re.compile(r"@PWR:(\d)")
RE_QUERY_VOLUME = re.compile(r"@VOL:([+-]?\d+)")
RE_QUERY_MUTE = re.compile(r"@A[TM]T:(\d)")
RE_QUERY_SOURCE = re.compile(r"@SRC:(.+)")

# MC1 volume scale
# Display shows 0.0 to 100.0, raw values are display * 10 (0 to 1000)
VOLUME_RAW_MAX = 1000
VOLUME_RAW_MIN = 0


class MC1State:
    """Current state of the MC1 processor."""

    def __init__(self):
        self.power: bool | None = None
        self.power_ever_responded: bool = False  # True once power query gets any response
        self.volume_raw: int | None = None  # Raw 0-200 scale from MC1
        self.muted: bool | None = None
        self.source: str | None = None
        self.sound_mode: str | None = None

    @property
    def volume_level(self) -> float | None:
        """Return volume as 0.0-1.0 float, clamped."""
        if self.volume_raw is None:
            return None
        return min(1.0, max(0.0, self.volume_raw / VOLUME_RAW_MAX))


class MC1Serial:
    """Async serial interface to the Emotiva MC1 processor."""

    def __init__(
        self,
        serial_port: str,
        baud_rate: int = DEFAULT_BAUD_RATE,
    ):
        self._serial_port = serial_port
        self._baud_rate = baud_rate
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._connected = False
        self._write_lock = asyncio.Lock()

        self.state = MC1State()
        self._update_callbacks: list[Callable[[], None]] = []

        # Build reverse lookups for parsing responses
        self._cmd_to_source: dict[str, str] = dict(SOURCES)
        self._name_to_cmd: dict[str, str] = {v: k for k, v in SOURCES.items()}
        self._cmd_to_mode: dict[str, str] = {v: k for k, v in SOUND_MODES.items()}

    def update_source_config(self, name_to_cmd: dict[str, str], cmd_to_name: dict[str, str]) -> None:
        """Update source mappings from options."""
        self._name_to_cmd = name_to_cmd
        self._cmd_to_source = cmd_to_name

    @property
    def connected(self) -> bool:
        return self._connected

    def register_callback(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for state updates. Returns an unregister function."""
        self._update_callbacks.append(callback)

        def unregister():
            self._update_callbacks.remove(callback)

        return unregister

    def _notify_update(self) -> None:
        """Notify all registered callbacks of a state update."""
        for cb in self._update_callbacks:
            try:
                cb()
            except Exception:
                _LOGGER.exception("Error in update callback")

    async def connect(self) -> bool:
        """Open the serial connection and start reading."""
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self._serial_port,
                baudrate=self._baud_rate,
                bytesize=SERIAL_BYTESIZE,
                parity=SERIAL_PARITY,
                stopbits=SERIAL_STOPBITS,
            )
            self._connected = True
            self._read_task = asyncio.create_task(self._read_loop())
            _LOGGER.info("Connected to MC1 at %s", self._serial_port)
            # Query initial state
            await self.query_all()
            return True
        except Exception:
            _LOGGER.exception("Failed to connect to MC1 at %s", self._serial_port)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the serial connection."""
        self._connected = False
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
        self._reader = None
        _LOGGER.info("Disconnected from MC1")

    async def reconnect(self) -> bool:
        """Attempt to reconnect."""
        await self.disconnect()
        await asyncio.sleep(2)
        return await self.connect()

    async def _send_raw(self, data: str) -> None:
        """Send raw string data over serial."""
        if not self._writer or not self._connected:
            _LOGGER.warning("Cannot send command, not connected")
            return
        async with self._write_lock:
            try:
                self._writer.write(data.encode("ascii"))
                await self._writer.drain()
                _LOGGER.debug("Sent: %s", data.replace("\r", "\\r"))
            except Exception:
                _LOGGER.exception("Error sending command")
                self._connected = False

    async def send_command(self, cmd: str) -> None:
        """Send an action command (wrapped in single quotes with CR)."""
        await self._send_raw(f"'{cmd}'\r")
        # Small delay between commands
        await asyncio.sleep(0.1)

    async def send_query(self, query: str) -> None:
        """Send a query command (no quotes, with CR)."""
        await self._send_raw(f"{query}\r")
        await asyncio.sleep(0.1)

    async def query_all(self) -> None:
        """Query all state from the MC1."""
        for query in [QUERY_POWER, QUERY_VOLUME, QUERY_MUTE, QUERY_SOURCE]:
            await self.send_query(query)
            await asyncio.sleep(0.2)

    async def _read_loop(self) -> None:
        """Continuously read from serial and parse responses."""
        buffer = ""
        while self._connected and self._reader:
            try:
                data = await asyncio.wait_for(self._reader.read(256), timeout=1.0)
                if not data:
                    continue
                decoded = data.decode("ascii", errors="replace")
                buffer += decoded
                _LOGGER.debug("Serial RX buffer: %r", buffer)

                # Process complete messages from the buffer
                # Messages are delimited by single quotes: '@xxx' or by \r\n
                while buffer:
                    # Look for quoted message: '@...'
                    quote_start = buffer.find("'@")
                    cr_pos = buffer.find("\r")
                    lf_pos = buffer.find("\n")

                    if quote_start >= 0:
                        # Find the closing quote
                        end_quote = buffer.find("'", quote_start + 2)
                        if end_quote >= 0:
                            msg = buffer[quote_start + 1 : end_quote]  # strip quotes
                            buffer = buffer[end_quote + 1 :]
                            self._parse_message(msg)
                            continue
                        else:
                            # Incomplete quoted message, wait for more data
                            break
                    elif cr_pos >= 0:
                        # CR-terminated message (query responses)
                        msg = buffer[:cr_pos].strip()
                        buffer = buffer[cr_pos + 1 :]
                        if msg.startswith("@"):
                            self._parse_message(msg)
                        continue
                    elif lf_pos >= 0:
                        msg = buffer[:lf_pos].strip()
                        buffer = buffer[lf_pos + 1 :]
                        if msg.startswith("@"):
                            self._parse_message(msg)
                        continue
                    else:
                        # No complete message yet
                        break

                # Prevent buffer from growing unbounded
                if len(buffer) > 1024:
                    _LOGGER.warning("Serial buffer overflow, clearing")
                    buffer = ""

            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Error in serial read loop")
                await asyncio.sleep(1)

    def _parse_message(self, msg: str) -> None:
        """Parse a single response message and update state."""
        if not msg:
            return
        _LOGGER.debug("MC1 RX: %r", msg)
        updated = False

        # Check query responses first
        m = RE_QUERY_POWER.search(msg)
        if m:
            self.state.power = m.group(1) == "2"
            self.state.power_ever_responded = True
            _LOGGER.debug("Power state (query): %s", self.state.power)
            updated = True

        m = RE_QUERY_VOLUME.search(msg)
        if m:
            # Query response - store as raw
            self.state.volume_raw = int(m.group(1))
            _LOGGER.debug("Volume (query): raw=%d", self.state.volume_raw)
            updated = True

        m = RE_QUERY_MUTE.search(msg)
        if m:
            self.state.muted = m.group(1) == "2"
            _LOGGER.debug("Mute state (query): %s", self.state.muted)
            updated = True

        m = RE_QUERY_SOURCE.search(msg)
        if m:
            src_code = m.group(1).strip()
            # Try to map to friendly name
            for cmd, name in self._cmd_to_source.items():
                if cmd.endswith(src_code) or src_code == cmd:
                    self.state.source = name
                    break
            else:
                self.state.source = src_code
            _LOGGER.debug("Source (query): %s", self.state.source)
            updated = True

        # Check action echoes / unsolicited updates
        if not updated:
            # Volume: @14K### (MC1 native format, 0-200 scale)
            m = RE_VOLUME_14K.search(msg)
            if m:
                raw_vol = int(m.group(1))
                self.state.volume_raw = raw_vol
                self.state.muted = False
                _LOGGER.debug("MC1 Volume: raw=%d", raw_vol)
                updated = True
            else:
                # Legacy volume format: @11S-45.5
                m = RE_VOLUME_LEGACY.search(msg)
                if m:
                    self.state.volume_raw = int(float(m.group(1)))
                    self.state.muted = False
                    updated = True

            if not updated and RE_POWER_ON.search(msg):
                self.state.power = True
                self.state.power_ever_responded = True
                _LOGGER.debug("Power ON")
                updated = True
            elif not updated and RE_POWER_OFF.search(msg):
                self.state.power = False
                self.state.power_ever_responded = True
                _LOGGER.debug("Power OFF")
                updated = True

            if not updated and RE_MUTE_ON.search(msg):
                self.state.muted = True
                _LOGGER.debug("Muted")
                updated = True
            elif not updated and RE_MUTE_OFF.search(msg):
                self.state.muted = False
                _LOGGER.debug("Unmuted")
                updated = True

            # Source change echo
            if not updated:
                m = RE_SOURCE.search(msg)
                if m and msg in self._cmd_to_source:
                    self.state.source = self._cmd_to_source[msg]
                    _LOGGER.debug("Source: %s", self.state.source)
                    updated = True

            # Sound mode echo
            if not updated and msg in self._cmd_to_mode:
                self.state.sound_mode = self._cmd_to_mode[msg]
                _LOGGER.debug("Sound mode: %s", self.state.sound_mode)
                updated = True

        if updated:
            self._notify_update()

    # ── High-level command methods ──

    async def power_on(self) -> None:
        await self.send_command(CMD_POWER_ON)
        self.state.power = True
        self._notify_update()

    async def power_off(self) -> None:
        await self.send_command(CMD_POWER_OFF)
        self.state.power = False
        self._notify_update()

    async def volume_up(self) -> None:
        await self.send_command(CMD_VOLUME_UP)
        if self.state.volume_raw is not None:
            self.state.volume_raw = min(VOLUME_RAW_MAX, self.state.volume_raw + 5)
        self.state.muted = False
        self._notify_update()

    async def volume_down(self) -> None:
        await self.send_command(CMD_VOLUME_DOWN)
        if self.state.volume_raw is not None:
            self.state.volume_raw = max(VOLUME_RAW_MIN, self.state.volume_raw - 5)
        self.state.muted = False
        self._notify_update()

    async def volume_set_raw(self, raw_vol: int) -> None:
        """Set volume to raw value (0-200)."""
        raw_vol = max(VOLUME_RAW_MIN, min(VOLUME_RAW_MAX, raw_vol))
        # Round to nearest step of 5
        raw_vol = round(raw_vol / 5) * 5
        cmd = f"{CMD_VOLUME_SET}{raw_vol}"
        await self.send_command(cmd)
        self.state.volume_raw = raw_vol
        self.state.muted = False
        self._notify_update()

    async def volume_set_level(self, level: float) -> None:
        """Set volume from 0.0-1.0 float."""
        raw = int(level * VOLUME_RAW_MAX)
        await self.volume_set_raw(raw)

    async def mute_on(self) -> None:
        await self.send_command(CMD_MUTE_ON)
        self.state.muted = True
        self._notify_update()

    async def mute_off(self) -> None:
        await self.send_command(CMD_MUTE_OFF)
        self.state.muted = False
        self._notify_update()

    async def mute_toggle(self) -> None:
        if self.state.muted:
            await self.mute_off()
        else:
            await self.mute_on()

    async def select_source(self, source_name: str) -> None:
        """Select input source by friendly name."""
        cmd = self._name_to_cmd.get(source_name)
        if cmd:
            await self.send_command(cmd)
            self.state.source = source_name
            self._notify_update()
        else:
            _LOGGER.error("Unknown source: %s", source_name)

    async def select_sound_mode(self, mode_name: str) -> None:
        """Select sound mode by name."""
        cmd = SOUND_MODES.get(mode_name)
        if cmd:
            await self.send_command(cmd)
            self.state.sound_mode = mode_name
            self._notify_update()
        else:
            _LOGGER.error("Unknown sound mode: %s", mode_name)
