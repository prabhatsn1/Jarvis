# JARVIS v1

A Jarvis-like desktop assistant for **macOS and Windows**. Voice-activated, offline-first, with a native floating HUD.

**Not a chatbot.** Jarvis listens for commands, decides what to do, and does it — fast and deterministic.

---

## Architecture

```
┌──────────────────────────────────────────────┐
│             Native HUD Process               │
│  macOS: Swift/AppKit  │  Windows: C#/WPF     │
│           ↕ IPC (socket / named pipe)        │
└──────────────┬───────────────────────────────┘
               │
┌──────────────┴───────────────────────────────┐
│      Python Core Process (cross-platform)    │
│                                              │
│  Mic → OpenWakeWord/Clap → Record → Whisper   │
│      → Intent Engine → Action Executor       │
│      → TTS → IPC state → HUD                 │
│                                              │
│  SQLite memory (prefs, routines, phrases)     │
└──────────────────────────────────────────────┘
```

**Two processes, one soul:**

- **Python core** — audio capture, wake word detection, speech-to-text, intent matching, action execution, text-to-speech, memory (identical on both platforms)
- **Native HUD** — floating animated orb. Swift/AppKit on macOS, C#/WPF on Windows. Receives state updates over IPC (Unix socket on macOS, named pipe on Windows).

---

## Prerequisites

### macOS

| Requirement       | Version | Notes                          |
| ----------------- | ------- | ------------------------------ |
| macOS             | 14+     | Sonoma or later                |
| Python            | 3.10+   | `python3 --version` to check   |
| Xcode CLI Tools   | Latest  | `xcode-select --install`       |
| Microphone access | —       | macOS will prompt on first run |

### Windows

| Requirement       | Version | Notes                                      |
| ----------------- | ------- | ------------------------------------------ |
| Windows           | 10+     | Windows 10 1903 or later                   |
| Python            | 3.10+   | `python --version` to check                |
| .NET SDK          | 8.0+    | Download from https://dotnet.microsoft.com |
| Microphone access | —       | Windows will prompt on first run           |

**Optional (both platforms):**

- No extra accounts needed — OpenWakeWord includes a free pre-trained "hey jarvis" model.

---

## Installation

### macOS

#### 1. Clone & install

```bash
cd /path/to/Jarvis
./scripts/install.sh
```

This will:

- Create a Python virtual environment (`.venv/`)
- Install all Python dependencies
- Build the Swift HUD binary (`hud/.build/release/JarvisHUD`)
- Create `~/.jarvis/` for memory storage

### Windows

#### 1. Clone & install

```powershell
cd C:\path\to\Jarvis
.\scripts\install.ps1
```

This will:

- Create a Python virtual environment (`.venv\`)
- Install all Python dependencies (including `pywin32` for named pipe IPC)
- Build the WPF HUD binary (`hud-win\bin\Release\net8.0-windows\JarvisHUD.exe`)
- Create `%USERPROFILE%\.jarvis\` for memory storage

### Both platforms

### 2. Configure wake word (optional)

The default config uses OpenWakeWord with the pre-trained `hey_jarvis` model — no API key needed. You can adjust the detection threshold in `config.yaml`:

```yaml
wake:
  engine: "openwakeword"
  model: "hey_jarvis"
  threshold: 0.5 # Lower = more sensitive, higher = fewer false activations
```

Set `engine: "keyboard"` to disable wake word entirely and only use Enter key.

### 3. Grant permissions

**macOS:**

- **Microphone access** — required for voice input
- **Accessibility access** — required for some OS automation (System Settings → Privacy & Security → Accessibility)

**Windows:**

- **Microphone access** — Settings → Privacy → Microphone
- Allow the terminal/Python through Windows Defender if prompted

---

## Usage

### Start Jarvis

**macOS:**

```bash
./scripts/start.sh
```

**Windows:**

```powershell
.\scripts\start.ps1
```

This launches both the Python core and the HUD. Press `Ctrl+C` to stop.

### Wake Jarvis

Three ways to wake:

| Method          | How                         | Requires             |
| --------------- | --------------------------- | -------------------- |
| **Wake word**   | Say "Hey Jarvis"             | Nothing              |
| **Double clap** | Clap twice, 100-500ms apart | Nothing              |
| **Keyboard**    | Press Enter in the terminal | Nothing (fallback)   |

After waking, Jarvis plays a chime and starts listening. Speak your command within 5 seconds.

### Example commands

```
"Jarvis"                     → (chime)
"Open Safari"                → Opens Safari
"Switch to VS Code"          → Brings VS Code to front
"Volume 50"                  → Sets volume to 50%
"Dark mode"                  → Enables dark mode
"What time is it"            → "It's 2:30 PM"
"Take a screenshot"          → Opens macOS screenshot tool
"Lock screen"                → Locks the screen
"That's all"                 → "Standing by."
```

Jarvis understands natural phrasing:

- "Open Safari" = "Launch Safari" = "Could you please open Safari for me"
- "Volume down" = "Turn it down" = "Quieter"

If Jarvis doesn't understand, it says "I don't know how to do that" — it never guesses.

---

## Full Command Reference

### App Control

| Command       | Patterns                                                                  |
| ------------- | ------------------------------------------------------------------------- |
| Open app      | `open {app}`, `launch {app}`, `start {app}`, `fire up {app}`, `run {app}` |
| Close app     | `close {app}`, `quit {app}`, `kill {app}`, `exit {app}`                   |
| Switch to app | `switch to {app}`, `go to {app}`, `show {app}`, `focus {app}`             |

### Volume

| Command     | Patterns                                                    |
| ----------- | ----------------------------------------------------------- |
| Set volume  | `set volume to {level}`, `volume {level}`                   |
| Volume up   | `volume up`, `louder`, `turn it up`, `increase volume`      |
| Volume down | `volume down`, `quieter`, `turn it down`, `decrease volume` |
| Mute        | `mute`, `silence`, `mute audio`                             |
| Unmute      | `unmute`, `turn sound on`                                   |

### Display

| Command         | Patterns                                           |
| --------------- | -------------------------------------------------- |
| Brightness up   | `brightness up`, `brighter`, `increase brightness` |
| Brightness down | `brightness down`, `dimmer`, `decrease brightness` |
| Dark mode       | `dark mode`, `go dark`, `dark theme`               |
| Light mode      | `light mode`, `go light`, `light theme`            |

### System

| Command           | Patterns                                              |
| ----------------- | ----------------------------------------------------- |
| Do not disturb on | `do not disturb`, `dnd on`, `focus mode`              |
| DND off           | `turn off do not disturb`, `dnd off`, `disable focus` |
| Lock screen       | `lock screen`, `lock`                                 |
| Sleep             | `sleep`, `go to sleep`, `put the computer to sleep`   |
| Screenshot        | `screenshot`, `take a screenshot`, `capture screen`   |
| Empty trash       | `empty trash`, `clear trash`                          |

### Info

| Command | Patterns                                            |
| ------- | --------------------------------------------------- |
| Time    | `what time is it`, `tell me the time`, `time`       |
| Date    | `what's the date`, `what day is it`, `today's date` |

### Files

| Command     | Patterns                                   |
| ----------- | ------------------------------------------ |
| Open file   | `open file {path}`                         |
| Open folder | `open folder {path}`, `show folder {path}` |

### Jarvis Meta

| Command      | Patterns                                               |
| ------------ | ------------------------------------------------------ |
| Status check | `status`, `how are you`, `are you there`               |
| Stand by     | `stop listening`, `goodbye`, `that's all`, `shut down` |

### Calendar & Schedule

| Command           | Patterns                                                                         |
| ----------------- | -------------------------------------------------------------------------------- |
| Today's schedule  | `what is on my schedule today`, `todays schedule`, `do i have meetings today`    |
| Next event        | `what is my next meeting`, `next event`, `what is next on my calendar`           |
| Connect Google    | `connect google account`, `connect gmail`, `connect google calendar`             |
| Connect Outlook   | `connect outlook account`, `connect microsoft account`, `connect outlook calendar` |
| Disconnect        | `disconnect {provider}`, `remove {provider} account`                             |
| List accounts     | `what accounts are connected`, `list connected accounts`                         |

---

## Configuration

All configuration lives in `config.yaml`:

### Wake word

```yaml
wake:
  engine: "openwakeword" # openwakeword | keyboard
  model: "hey_jarvis" # Pre-trained model (hey_jarvis, alexa, hey_mycroft, etc.)
  threshold: 0.5 # 0.0 (loose) to 1.0 (strict)
```

Set `engine: "keyboard"` to disable wake word entirely and only use Enter key.

### Audio

```yaml
audio:
  sample_rate: 16000 # Don't change — matches Whisper/OpenWakeWord
  channels: 1 # Mono
  command_timeout: 5.0 # Max seconds to listen for a command
```

### Speech recognition

```yaml
speech:
  whisper_model: "base.en" # Model size (see table below)
  language: "en"
```

| Model      | Size   | Speed     | Accuracy | Best for                  |
| ---------- | ------ | --------- | -------- | ------------------------- |
| `tiny.en`  | ~40MB  | Very fast | Good     | Quick testing             |
| `base.en`  | ~150MB | Fast      | Better   | **Default — recommended** |
| `small.en` | ~500MB | Moderate  | Best     | Noisy environments        |

The model downloads automatically on first use.

### Voice output

```yaml
voice:
  engine: "system" # Uses macOS `say` or Windows SAPI
  voice: "Daniel" # macOS voice name (auto-switches to "David" on Windows)
  rate: 180 # Words per minute
```

**macOS voices** — to list available voices:

```bash
say -v '?'
```

Good choices for Jarvis:

- **Daniel** — British English, calm, professional (default)
- **Alex** — American English, clear
- **Tom** — American English, deeper
- **Samantha** — American English, neutral

Premium voices sound significantly better. Download them in: System Settings → Accessibility → Spoken Content → System Voice → Manage Voices.

**Windows voices** — uses System.Speech (SAPI). Default is "David". To see available voices:

```powershell
Add-Type -AssemblyName System.Speech
(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }
```

Good choices: **David** (default), **Mark**, **Zira**. Install additional voices in: Settings → Time & Language → Speech.

### Double clap

```yaml
clap:
  enabled: true # Set false to disable
  threshold: 0.6 # Loudness threshold (0.0-1.0)
  min_interval: 0.1 # Min seconds between the two claps
  max_interval: 0.5 # Max seconds between the two claps
```

If clap detection triggers too easily, raise `threshold` to 0.7-0.8.
If it's too hard to trigger, lower it to 0.4-0.5.

### Memory

```yaml
memory:
  db_path: "~/.jarvis/memory.db"
```

The memory database stores:

- **Preferences** — key-value pairs (e.g., default browser)
- **Routines** — named action sequences
- **Phrase mappings** — learned "your phrase" → intent mappings
- **Action log** — last 100 actions (auto-pruned)
- **Connected accounts** — OAuth account metadata (no tokens — those go in keyring)

To wipe all memory:

**macOS:**

```bash
rm ~/.jarvis/memory.db
```

**Windows:**

```powershell
Remove-Item "$env:USERPROFILE\.jarvis\memory.db"
```

### Calendar & Email Integrations

Jarvis can read your Google Calendar and Outlook calendar to answer schedule questions.

#### Step 1 — Create OAuth credentials

**Google (Gmail + Google Calendar):**

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Create an OAuth 2.0 Client ID of type **Desktop application**
3. Enable the **Google Calendar API** and **Gmail API** on your project
4. Download the client ID and secret

**Microsoft (Outlook Mail + Calendar):**

1. Go to [Azure Portal](https://portal.azure.com/) → App registrations → New registration
2. Set redirect URI to `http://localhost:8765/callback` (Web platform)
3. Under Certificates & secrets, create a new client secret
4. Grant delegated permissions: `Calendars.Read`, `Mail.Read`, `offline_access`

#### Step 2 — Add credentials to config.yaml

```yaml
integrations:
  enabled: true
  timezone: local  # or an IANA name like "America/New_York"

  google:
    client_id: "YOUR_GOOGLE_CLIENT_ID"
    client_secret: "YOUR_GOOGLE_CLIENT_SECRET"  # keep private

  microsoft:
    tenant: common  # or your Azure tenant ID
    client_id: "YOUR_MICROSOFT_CLIENT_ID"
    client_secret: "YOUR_MICROSOFT_CLIENT_SECRET"  # keep private
```

> **Security:** Client secrets are only read at connection time and are never written to logs.
> OAuth tokens are stored in the system keyring (Keychain on macOS, Credential Manager on Windows).
> If keyring is unavailable, tokens are AES-256-GCM encrypted under `~/.jarvis/credentials/`.

#### Step 3 — Connect accounts

Say to Jarvis:

```
"Hey Jarvis"
"Connect Google account"   ← opens browser for Google sign-in
"Connect Outlook account"  ← opens browser for Microsoft sign-in
```

Jarvis opens your browser, you authenticate, and it stores the token securely.

#### Step 4 — Ask about your schedule

```
"Hey Jarvis"
"What is on my schedule today"
"What is my next meeting"
"What accounts are connected"
"Disconnect Google"
```

**Example responses:**

```
"Boss, you have 3 events today. First is Standup at 10:00 AM.
 Next is Design Review at 1:30 PM. And finally Sprint Retro at 4:00 PM."

"You are clear today, Boss. No events on your calendar."

"Your next event is Team Sync at 2:00 PM."
```

#### Timezone configuration

By default, Jarvis uses your system local timezone. To specify an explicit timezone:

```yaml
integrations:
  timezone: "America/New_York"  # any IANA timezone name
```

---

## Project Structure

```
Jarvis/
├── config.yaml                          # Runtime configuration
├── commands.yaml                        # Command definitions (intent registry)
├── requirements.txt                     # Python dependencies
│
├── jarvis/                              # ── Python Core (cross-platform) ──
│   ├── __init__.py                      #   Package metadata
│   ├── __main__.py                      #   Entry point: python -m jarvis
│   ├── core.py                          #   Main orchestrator (Jarvis class)
│   ├── config.py                        #   YAML config loader (platform-aware)
│   │
│   ├── audio/                           # ── Audio Subsystem ─────────
│   │   ├── capture.py                   #   Mic input → numpy chunks
│   │   ├── wake.py                      #   OpenWakeWord wake word detection
│   │   └── clap.py                      #   Double-clap DSP detector
│   │
│   ├── speech/                          # ── Speech Subsystem ────────
│   │   ├── recognizer.py               #   faster-whisper STT
│   │   └── synthesizer.py              #   macOS say / Windows SAPI
│   │
│   ├── brain/                           # ── Intent Brain ────────────
│   │   ├── registry.py                  #   YAML → compiled Command objects
│   │   ├── engine.py                    #   5-phase intent matcher
│   │   ├── llm.py                       #   LLM adapter (HF + OpenAI)
│   │   ├── tools.py                     #   Tool implementations (web_search, read_file, run_code, get_schedule, get_next_event)
│   │   ├── tool_schemas.py              #   OpenAI-format tool schemas
│   │   └── tool_executor.py             #   Autonomous tool-calling loop
│   │
│   ├── actions/                         # ── OS Actions ──────────────
│   │   ├── executor.py                  #   Thread-pool action runner
│   │   ├── apps.py                      #   open / close / switch apps
│   │   ├── system.py                    #   volume, brightness, DND, etc.
│   │   ├── files.py                     #   open file / folder
│   │   ├── memory.py                    #   semantic memory actions
│   │   ├── monitor.py                   #   health monitor actions
│   │   └── integrations.py              #   calendar / email actions
│   │
│   ├── integrations/                    # ── External Integrations ───
│   │   ├── auth.py                      #   OAuth flows + secure token storage
│   │   ├── calendar_service.py          #   Unified Google + Outlook calendar
│   │   └── email_service.py             #   Gmail + Outlook mail connectivity
│   │
│   ├── memory/                          # ── Memory Store ────────────
│   │   └── store.py                     #   SQLite: prefs, routines, accounts, log
│   │
│   └── ipc/                             # ── IPC ─────────────────────
│       └── server.py                    #   Unix socket (macOS) / named pipe (Windows)
│
├── hud/                                 # ── Swift HUD (macOS) ───────
│   ├── Package.swift                    #   Swift Package Manager manifest
│   └── Sources/JarvisHUD/
│       ├── App.swift                    #   @main SwiftUI app
│       ├── AppDelegate.swift            #   Window + menu bar setup
│       ├── HUDPanel.swift               #   NSPanel (floating, borderless)
│       ├── OrbView.swift                #   Animated orb (6 states)
│       ├── StateManager.swift           #   IPC messages → SwiftUI state
│       └── IPCClient.swift              #   Unix socket client
│
├── hud-win/                             # ── WPF HUD (Windows) ──────
│   ├── JarvisHUD.csproj                 #   .NET 8 project file
│   ├── App.xaml / App.xaml.cs           #   WPF application entry
│   ├── HUDWindow.xaml / .xaml.cs        #   Transparent window + animations
│   ├── StateManager.cs                  #   IPC messages → WPF bindings
│   └── IPCClient.cs                     #   Named pipe client
│
└── scripts/                             # ── Launch Scripts ──────────
    ├── install.sh / install.ps1         #   Full setup (venv + deps + build)
    └── start.sh / start.ps1            #   Launch both processes
```

---

## How the Intent Engine Works

The brain uses a **4-phase** matching pipeline — no LLM, no hallucinations:

### Phase 1: Exact regex match (confidence: 1.0)

Each pattern in `commands.yaml` is compiled to a regex. `"open {app}"` becomes `^\s*open\s+(?P<app>.+?)\s*$`. Direct match → immediate execution.

### Phase 2: Normalized regex match (confidence: 0.9)

Strips filler words ("please", "could you", "hey jarvis", "just", "go ahead and") then retries Phase 1. This handles:

- "Hey Jarvis, could you please open Safari for me" → normalized to "open safari" → matches

### Phase 3: Fuzzy token match (confidence: 0.65–0.99)

Uses `rapidfuzz` token_sort_ratio to compare input against all known patterns. Threshold: 65%. Handles typos and reordering:

- "safari open" → matches "open {app}"
- "make it louder" → matches "volume up"

Slot values are extracted by removing known pattern words from the input.

### Phase 4: Memory lookup (confidence: 0.85)

Checks SQLite `phrase_mappings` table for previously taught mappings. This is how Jarvis learns:

- You say "fire up Chrome" → Jarvis doesn't understand
- You teach: "That means open Chrome"
- Next time "fire up Chrome" → matches instantly

### No match → "I don't know how to do that."

Jarvis never guesses. No match = no action. This is a feature, not a limitation.

### Phase 5: LLM fallback with function-calling tools (confidence: 0.5)

When no deterministic match is found and the LLM is enabled, Jarvis sends the query to an LLM. If `function_calling_enabled` is `true`, the LLM can autonomously invoke tools (web search, file reading, code execution) to fulfill complex requests before responding.

The tool loop works as follows:

1. User message + tool schemas are sent to the model.
2. If the model returns tool call(s), Jarvis executes them and appends results.
3. Loop continues until the model returns a plain text answer or `max_tool_calls` iterations are reached.
4. The final response is a short spoken sentence suitable for TTS.

**Example prompts that use tools:**

```
"Search the web for today's Python release notes and summarize in two lines."
"Read the first 80 lines of README.md and tell me setup prerequisites."
"Run this Python snippet and tell me the output: print(sum([3,5,8]))."
```

**Existing commands always take priority.** Tool-calling only activates in the LLM fallback path — deterministic regex, fuzzy, and memory matching still run first.

---

## Function-Calling Configuration

Enable LLM + function-calling in `config.yaml`:

```yaml
llm:
  enabled: true
  provider: "openai_compatible"     # or "huggingface"
  function_calling_enabled: true
  max_tool_calls: 4                 # Max tool-loop iterations per query
  tool_timeout_sec: 15              # Timeout for code execution

  # Per-tool toggles
  web_search_enabled: true
  code_exec_enabled: true
  file_read_enabled: true

  # Workspace root for read_file access control (empty = auto-detect)
  workspace_root: ""

  # OpenAI-compatible provider settings
  openai_base_url: "http://localhost:1234/v1"
  openai_api_key: ""                # Or set OPENAI_API_KEY env var
  openai_model: "gpt-3.5-turbo"
```

### Available tools

| Tool | Description | Safety |
|------|-------------|--------|
| `web_search(query, max_results)` | Search the web via DuckDuckGo | Results capped at 10 |
| `read_file(path, start_line, end_line)` | Read text file contents | Blocked for binary files, large files, and sensitive paths (.ssh, .aws, /etc) |
| `run_code(code, language)` | Execute Python snippets | Strict timeout, output size cap, minimal subprocess env, no shell passthrough |

### Backward compatibility

- If `function_calling_enabled` is `false` (default), behavior is identical to before — plain LLM text response.
- If the provider doesn't support tool calling, Jarvis gracefully degrades to a plain response.
- Deterministic command matching (regex, fuzzy, memory) is never bypassed.

---

## HUD Visual States

The floating orb has 6 animated states, all GPU-composited at 60fps:

| State       | Visual                                      | Duration      |
| ----------- | ------------------------------------------- | ------------- |
| `dormant`   | Gentle breathe pulse (scale 1.0→1.05, cyan) | Continuous    |
| `woke`      | Sharp snap expansion + bright glow          | ~200ms        |
| `listening` | Spinning ring + gentle pulse (blue)         | Until silence |
| `thinking`  | Fast spinning ring + ripple (purple)        | Until match   |
| `speaking`  | Symmetric pulse (cyan)                      | Until done    |
| `error`     | Red flash (3 pulses)                        | ~500ms        |

The HUD:

- Floats above all windows (NSPanel `.floating` on macOS, `Topmost` WPF window on Windows)
- Never steals keyboard focus
- Appears on all Spaces/desktops (macOS) or stays on top (Windows)
- Can be dragged by its background
- Has a menu bar icon to toggle visibility (macOS) / hidden from taskbar (Windows)
- Has no Dock icon (macOS) / no taskbar entry (Windows)

---

## Adding New Commands

Edit `commands.yaml` and add a new entry:

```yaml
- intent: play_music
  patterns:
    - "play music"
    - "play some music"
    - "put on some tunes"
  action: system.play_music # Must exist as a function
  response: "Playing music"
```

Then create the backing function in the appropriate action module. For example, in `jarvis/actions/system.py`:

```python
def play_music():
    if SYSTEM == "Darwin":
        subprocess.run(["open", "-a", "Music"], check=True, timeout=5)
    elif SYSTEM == "Windows":
        subprocess.run(["start", "", "mswindowsmusic:"], shell=True, timeout=5)
    return "Music started"
```

Restart Jarvis. The new command works immediately — no retraining, no model updates.

---

## Troubleshooting

### "I didn't catch that" every time

- Check microphone permissions:
  - **macOS:** System Settings → Privacy & Security → Microphone
  - **Windows:** Settings → Privacy → Microphone
- Test mic: `python3 -c "import sounddevice; print(sounddevice.query_devices())"`
- Try a larger Whisper model: change `speech.whisper_model` to `small.en` in config

### Wake word not triggering

- Try lowering the threshold: `wake.threshold: 0.3`
- Speak clearly: "Hey Jarvis"
- Ensure `openwakeword` is installed: `pip install openwakeword`
- Check logs for model loading errors

### Double clap triggers on noise

- Increase threshold: `clap.threshold: 0.8`
- Or disable: `clap.enabled: false`

### HUD not appearing (macOS)

- Rebuild: `cd hud && swift build -c release`
- Check: is the core running? HUD connects to `/tmp/jarvis.sock`
- Toggle via menu bar icon (small circle in top-right)

### HUD not appearing (Windows)

- Rebuild: `cd hud-win && dotnet build -c Release`
- Check: is the core running? HUD connects to `\\.\pipe\jarvis`
- Make sure .NET 8 runtime is installed: `dotnet --version`

### "Action timed out"

- Some actions (screenshot, Finder/Explorer operations) may need elevated permissions
- **macOS:** System Settings → Privacy & Security → Accessibility → add Terminal
- **Windows:** Run terminal as Administrator for some system actions

### Volume control on Windows

- Volume actions use `nircmd` (lightweight, free utility)
- Download from https://www.nirsoft.net/utils/nircmd.html
- Place `nircmd.exe` in your PATH (e.g., `C:\Windows\`)
- Without it, volume mute/unmute/up/down won't work (set_volume still works via PowerShell)

### Whisper model download slow

- First run downloads the model (~150MB for base.en). This is one-time.
- To pre-download: `python3 -c "from faster_whisper import WhisperModel; WhisperModel('base.en')"`

---

## Dependencies

### Python (installed via pip)

| Package                      | Purpose                                       |
| ---------------------------- | --------------------------------------------- |
| `openwakeword`               | Wake word detection (OpenWakeWord)             |
| `sounddevice`                | Real-time microphone capture                  |
| `numpy`                      | Audio buffer manipulation                     |
| `faster-whisper`             | Local speech-to-text (CTranslate2)            |
| `rapidfuzz`                  | Fuzzy string matching for intents             |
| `pyyaml`                     | Config and command file parsing               |
| `pywin32`                    | Named pipe IPC (Windows only)                 |
| `google-auth`                | Google OAuth 2.0 token management             |
| `google-auth-oauthlib`       | Google OAuth installed-app flow               |
| `google-api-python-client`   | Google Calendar and Gmail API client          |
| `msal`                       | Microsoft Authentication Library (Outlook)   |
| `requests`                   | HTTP calls to Microsoft Graph                 |
| `keyring`                    | Secure OS token storage (Keychain / Credential Manager) |
| `cryptography`               | AES-256-GCM fallback token encryption         |
| `python-dateutil`            | Timezone-aware datetime parsing               |
| `tzdata`                     | IANA timezone database                        |

### Swift HUD (macOS — no external dependencies)

The HUD uses only Apple frameworks:

- SwiftUI — declarative UI
- AppKit — NSPanel window management
- Foundation — Unix socket IPC

### WPF HUD (Windows — no external dependencies)

The HUD uses only .NET built-in frameworks:

- WPF — window rendering and animations
- System.IO.Pipes — named pipe IPC
- System.Text.Json — message parsing

---

## Design Principles

1. **Deterministic over smart.** Jarvis matches known commands. It never invents actions.
2. **Local over cloud.** Wake word, STT, intent matching, TTS, memory — all offline.
3. **Native over portable.** The HUD is a real NSPanel (macOS) or WPF window (Windows), not a web view. OS actions use native APIs.
4. **Fast over thorough.** <100ms wake, <2s transcription, <500ms action. Total: under 3 seconds.
5. **Transparent over magical.** Every intent is in `commands.yaml`. Every memory row is human-readable. Delete `~/.jarvis/memory.db` to reset everything.
