"""Tool definitions and schemas for LLM function-calling."""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information. "
                "Returns titles, URLs, and snippets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (1-10).",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the contents of a text file on the local machine. "
                "Returns the text content with line numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read (1-based).",
                        "default": 1,
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read (1-based, inclusive).",
                        "default": 200,
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": (
                "Execute a short code snippet and return stdout/stderr. "
                "Supports Python only. Has a strict timeout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The code to execute.",
                    },
                    "language": {
                        "type": "string",
                        "description": "Programming language (only 'python' supported).",
                        "default": "python",
                        "enum": ["python"],
                    },
                },
                "required": ["code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schedule",
            "description": (
                "Fetch the user's calendar events for today (or a specified date). "
                "Returns a list of events with titles, times, and locations. "
                "Use this when the user asks about their schedule, meetings, or calendar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": (
                            "The date to fetch events for. "
                            "Use 'today' (default), 'tomorrow', or an ISO date like '2026-05-15'."
                        ),
                        "default": "today",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_next_event",
            "description": (
                "Fetch the single next upcoming calendar event. "
                "Use this when the user asks 'what's next on my calendar' or 'when is my next meeting'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {
                        "type": "integer",
                        "description": "Look ahead window in hours (default 24, max 168).",
                        "default": 24,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "browser_action",
            "description": (
                "Control a real web browser (Chrome/Chromium, Safari/WebKit, or Firefox) "
                "via Playwright to complete multi-step web tasks. "
                "Use this for: booking flights, online shopping, searching a website and "
                "summarizing the results, filling forms, reading live web pages. "
                "Chain multiple calls — e.g. navigate → type → click → get_text — to "
                "complete complex tasks autonomously."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The browser step to perform.",
                        "enum": [
                            "navigate",
                            "search",
                            "click",
                            "type",
                            "press_enter",
                            "get_text",
                            "get_url",
                            "screenshot",
                            "close",
                        ],
                    },
                    "url": {
                        "type": "string",
                        "description": "Full URL to navigate to (for 'navigate').",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search query string (for 'search').",
                    },
                    "selector": {
                        "type": "string",
                        "description": (
                            "CSS selector of the target element "
                            "(for 'click', 'type', 'get_text', 'press_enter')."
                        ),
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to enter into the element (for 'type').",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run a shell (terminal) command on the user's machine. "
                "ALWAYS requires user approval before executing — the tool returns "
                "a pending-approval message that the user must confirm by saying 'confirm'. "
                "Use this when the user explicitly asks to run a command or when a "
                "terminal operation is clearly necessary to answer the question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run (e.g. 'ls -la', 'pip list').",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Brief explanation of why this command is needed.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "smart_home_control",
            "description": (
                "Control smart home devices — Philips Hue lights, smart plugs, and "
                "thermostats — via Home Assistant or direct Hue API. "
                "Use this when the user asks to turn lights on/off, change brightness "
                "or colour, toggle a plug, set or read the thermostat temperature, "
                "check a device's state, or list all smart home devices."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "The smart home operation to perform.",
                        "enum": [
                            "turn_on_light",
                            "turn_off_light",
                            "set_brightness",
                            "set_color",
                            "turn_on_plug",
                            "turn_off_plug",
                            "set_temperature",
                            "get_temperature",
                            "get_state",
                            "list_devices",
                        ],
                    },
                    "entity": {
                        "type": "string",
                        "description": (
                            "Device name or Home Assistant entity_id "
                            "(e.g. 'bedroom light', 'light.bedroom', 'office plug', "
                            "'climate.living_room'). "
                            "Required for all actions except 'list_devices'."
                        ),
                    },
                    "brightness": {
                        "type": "integer",
                        "description": "Brightness 0–100. Used with 'turn_on_light' or 'set_brightness'.",
                    },
                    "color": {
                        "type": "string",
                        "description": (
                            "Colour name (e.g. 'red', 'warm white') or hex '#RRGGBB'. "
                            "Used with 'turn_on_light' or 'set_color'."
                        ),
                    },
                    "temperature": {
                        "type": "number",
                        "description": "Target temperature for 'set_temperature' (numeric, no unit symbol).",
                    },
                    "device_type": {
                        "type": "string",
                        "description": (
                            "Filter for 'list_devices': 'light', 'plug', or 'thermostat'. "
                            "Omit to list all device types."
                        ),
                        "enum": ["light", "plug", "thermostat"],
                    },
                },
                "required": ["action"],
            },
        },
    },
]


def get_enabled_schemas(config: dict) -> list:
    """Return only schemas for tools enabled in config."""
    enabled = []
    flags = {
        "web_search": config.get("web_search_enabled", True),
        "read_file": config.get("file_read_enabled", True),
        "run_code": config.get("code_exec_enabled", True),
        "get_schedule": config.get("calendar_enabled", True),
        "get_next_event": config.get("calendar_enabled", True),
        "browser_action": config.get("browser_automation_enabled", False),
        "smart_home_control": config.get("smart_home_enabled", False),
        "run_command": config.get("run_command_enabled", False),
    }
    for schema in TOOL_SCHEMAS:
        if flags.get(schema["function"]["name"], False):
            enabled.append(schema)
    return enabled
