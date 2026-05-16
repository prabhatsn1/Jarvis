# JARVIS v1 — Comprehensive Technical Documentation

> **Generated from source analysis.** Assumptions and open questions are called out explicitly in each section and consolidated in the Appendix.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Overview](#2-architecture-overview)
3. [Repository Structure](#3-repository-structure)
4. [Key Design Decisions](#4-key-design-decisions)
5. [Core Workflows](#5-core-workflows)
6. [Configuration & Environment](#6-configuration--environment)
7. [Development Guide](#7-development-guide-internal)
8. [Non-Functional Aspects](#8-non-functional-aspects)
9. [Limitations & Known Gaps](#9-limitations--known-gaps)
10. [Appendix](#10-appendix)

---

## 1. Project Overview

### What Problem It Solves

JARVIS is a **local, voice-activated desktop assistant** for macOS and Windows. It bridges the gap between conversational AI assistants (which require cloud connectivity and behave as chatbots) and deterministic automation tools (which lack natural language input). The system lets users control their computer, manage calendars, query system health, and run arbitrary workflows using natural speech — with no mandatory cloud dependency.

### High-Level Description

JARVIS runs as two coordinated processes on the same machine:

- A **Python core** handles all intelligence and automation: continuous audio capture, wake-word detection, speech-to-text transcription, intent matching, action execution, text-to-speech, and persistent memory.
- A **native HUD** (Heads-Up Display) — Swift/AppKit on macOS, C#/WPF on Windows — renders an animated floating orb that visually reflects the assistant's state (dormant, listening, thinking, speaking).

The system is designed to be **offline-first**: wake-word detection, speech-to-text, intent matching, and most actions work without internet access. Optional integrations (LLM fallback, calendar sync, smart home) can reach the network when configured.

### Target Users and Use Cases

| Audience                    | Use Cases                                                              |
| --------------------------- | ---------------------------------------------------------------------- |
| Power users / developers    | Hands-free system control, terminal command execution, file management |
| Productivity users          | Calendar queries, reminders, timers, email summary, schedule awareness |
| Home automation enthusiasts | Smart home control via Home Assistant or Philips Hue                   |
| Privacy-conscious users     | Local speech processing with no mandatory cloud calls                  |

---

## 2. Architecture Overview

### Two-Process Model

```
┌─────────────────────────────────────────────────────────────────┐
│                       Native HUD Process                         │
│                                                                  │
│   macOS: Swift/AppKit (JarvisHUD)  │  Windows: C#/WPF (JarvisHUD)│
│     OrbView  StateManager           │    HUDWindow  StateManager   │
│     HUDPanel IPCClient              │    IPCClient                 │
│                                                                  │
│   ← JSON over Unix socket (/tmp/jarvis.sock)                    │
│   ← JSON over Windows Named Pipe   (\\.\\pipe\\jarvis)          │
└────────────────────────────┬────────────────────────────────────┘
                             │  IPC (newline-delimited JSON)
┌────────────────────────────┴────────────────────────────────────┐
│                    Python Core Process                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Audio Layer                                              │    │
│  │  AudioCapture → WakeWordDetector / ClapDetector          │    │
│  │                       │                                  │    │
│  │               SpeechRecognizer (Whisper)                 │    │
│  │               EmotionAnalyzer                            │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │ transcribed text + emotion           │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │ Brain Layer                                              │    │
│  │  IntentEngine                                            │    │
│  │   Phase 1: Regex match   (CommandRegistry)               │    │
│  │   Phase 2: Normalized    (stop-word stripping)           │    │
│  │   Phase 3: Fuzzy match   (RapidFuzz token_sort_ratio)    │    │
│  │   Phase 4: Memory match  (learned phrase mappings)       │    │
│  │   Phase 5: LLM fallback  (HuggingFace / OpenAI)         │    │
│  │                       │                                  │    │
│  │  LLMEngine ────── ToolExecutor (function-calling loop)   │    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │ IntentResult                         │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │ Action Layer (ActionExecutor)                             │    │
│  │  apps  system  files  browser  exec_commands             │    │
│  │  memory  notify  smarthome  integrations  vision  monitor│    │
│  └────────────────────────┬────────────────────────────────┘    │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │ Support Services (daemon threads)                         │    │
│  │  Synthesizer   MemoryStore   IPCServer                   │    │
│  │  SystemHealthMonitor   StatsBroadcaster                  │    │
│  │  EventScheduler   NotificationScheduler                  │    │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Major Components and Responsibilities

| Component             | Location                            | Responsibility                                                                                                                                         |
| --------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `Jarvis` (core)       | `jarvis/core.py`                    | Top-level orchestrator; owns the main event loop and state machine                                                                                     |
| `AudioCapture`        | `jarvis/audio/capture.py`           | Continuous 16 kHz mono PCM streaming via `sounddevice`; switches between passthrough and record modes                                                  |
| `WakeWordDetector`    | `jarvis/audio/wake.py`              | Processes 80 ms audio frames through OpenWakeWord; emits a signal when the wake phrase is detected                                                     |
| `ClapDetector`        | `jarvis/audio/clap.py`              | Detects double-clap gestures using RMS + crest-factor analysis as an alternative activation method                                                     |
| `EmotionAnalyzer`     | `jarvis/audio/emotion.py`           | Extracts RMS energy, ZCR variance, and voiced-frame ratio to classify utterance tone as _normal_, _urgent_, or _frustrated_                            |
| `SpeechRecognizer`    | `jarvis/speech/recognizer.py`       | Lazy-loads `faster-whisper` (CTranslate2 int8) for offline STT; beam_size=1 for low latency                                                            |
| `Synthesizer`         | `jarvis/speech/synthesizer.py`      | Platform TTS wrapper: macOS `say`, Windows `System.Speech`; also plays chime sounds at state transitions                                               |
| `CommandRegistry`     | `jarvis/brain/registry.py`          | Loads `commands.yaml` at startup; compiles patterns to named-capture-group regexes                                                                     |
| `IntentEngine`        | `jarvis/brain/engine.py`            | 5-phase matching pipeline (see Section 5)                                                                                                              |
| `LLMEngine`           | `jarvis/brain/llm.py`               | Stateful conversation wrapper supporting HuggingFace Inference API, OpenAI, and OpenAI-compatible endpoints                                            |
| `ToolExecutor`        | `jarvis/brain/tool_executor.py`     | Autonomous tool-calling loop for LLM function-calling (web search, file read, code exec, calendar, browser, smart home, shell)                         |
| `ActionExecutor`      | `jarvis/actions/executor.py`        | Resolves dotted action paths (`apps.open_app`) to callables; executes them in a thread pool with a configurable timeout                                |
| `MemoryStore`         | `jarvis/memory/store.py`            | SQLite-backed structured store for preferences, routines, learned phrase mappings, action log, and OAuth account metadata                              |
| `SemanticMemory`      | `jarvis/memory/semantic.py`         | ChromaDB + `sentence-transformers` (all-MiniLM-L6-v2) for vector similarity recall and fact extraction                                                 |
| `IPCServer`           | `jarvis/ipc/server.py`              | Broadcasts newline-delimited JSON to connected HUD clients; Unix socket on macOS, named pipe on Windows                                                |
| `SystemHealthMonitor` | `jarvis/monitor/health.py`          | Background thread sampling CPU/RAM/disk/GPU via `psutil`/`GPUtil`; fires callback on threshold crossing with configurable severity levels and cooldown |
| `StatsBroadcaster`    | `jarvis/monitor/stats.py`           | Emits `{"type":"stats", ...}` IPC payloads every 5 seconds for the HUD's live dashboard                                                                |
| `EventScheduler`      | `jarvis/actions/event_scheduler.py` | Background daemon that polls calendar at configurable intervals and fires proactive voice alerts at configurable lead times before events              |
| HUD (macOS)           | `hud/`                              | SwiftUI `OrbView` inside a borderless `NSPanel`; animated states driven by `StateManager` receiving IPC messages                                       |
| HUD (Windows)         | `hud-win/`                          | WPF `HUDWindow` with equivalent animated states; `IPCClient` reads from the named pipe                                                                 |

### Key Architectural Patterns

- **Layered architecture** — Audio → Brain → Actions → Support Services. Layers depend only downward.
- **State machine** — The core runs a simple finite state machine: `dormant → woke → listening → thinking → speaking → dormant`. Every state transition broadcasts a JSON message to the HUD.
- **Context injection** — Optional subsystems (smart home, vision, integrations, exec commands) receive their configuration via module-level `set_*_context()` functions called once at startup. This avoids tight coupling while supporting runtime optionality.
- **Daemon threads** — Background services (health monitor, stats broadcaster, event scheduler, IPC accept loop) run as Python daemon threads and are silently terminated when the main process exits.
- **Approval gate** — Potentially destructive terminal commands require explicit voice confirmation before execution.

### External Dependencies and Integrations

| Dependency                                         | Purpose                                          |
| -------------------------------------------------- | ------------------------------------------------ |
| `openwakeword`                                     | Offline wake-word detection (pre-trained models) |
| `sounddevice`                                      | Cross-platform microphone capture                |
| `faster-whisper`                                   | On-device speech-to-text (CTranslate2 runtime)   |
| `rapidfuzz`                                        | Fuzzy intent matching                            |
| `huggingface_hub`                                  | HuggingFace Inference API client (LLM fallback)  |
| `openai`                                           | OpenAI and compatible LLM API clients            |
| `chromadb`                                         | Vector database for semantic memory              |
| `sentence-transformers`                            | Embeddings for semantic memory                   |
| `playwright`                                       | Browser automation                               |
| `duckduckgo-search`                                | Web search for LLM tools                         |
| `psutil` / `GPUtil`                                | System resource metrics                          |
| `google-api-python-client`, `google-auth-oauthlib` | Google Calendar / Gmail OAuth integration        |
| `msal`                                             | Microsoft (Outlook/Graph) OAuth integration      |
| `keyring`                                          | Secure OS credential storage                     |
| `cryptography`                                     | AES-256-GCM fallback credential encryption       |
| Swift/AppKit                                       | macOS native HUD                                 |
| .NET 8 / WPF                                       | Windows native HUD                               |

---

## 3. Repository Structure

```
Jarvis/
├── config.yaml            ← Primary runtime configuration (all tunable knobs)
├── commands.yaml          ← Intent registry: patterns, slots, actions, responses
├── requirements.txt       ← Python package dependencies
├── Jarvis.sln             ← Visual Studio solution (references hud-win project)
├── README.md              ← Quick-start guide
│
├── jarvis/                ← Python core package
│   ├── __main__.py        ← Entry point: python -m jarvis
│   ├── core.py            ← Jarvis class: orchestrator + main loop
│   ├── config.py          ← YAML loader with validation and safe defaults
│   │
│   ├── audio/             ← Microphone capture and signal analysis
│   │   ├── capture.py     ← AudioCapture: streaming + command recording
│   │   ├── wake.py        ← WakeWordDetector: OpenWakeWord wrapper
│   │   ├── clap.py        ← ClapDetector: double-clap gesture detection
│   │   └── emotion.py     ← EmotionAnalyzer: signal-level tone detection
│   │
│   ├── speech/            ← Speech I/O
│   │   ├── recognizer.py  ← SpeechRecognizer: faster-whisper STT
│   │   └── synthesizer.py ← Synthesizer: platform TTS + chime sounds
│   │
│   ├── brain/             ← Intent resolution and LLM integration
│   │   ├── registry.py    ← CommandRegistry: loads and compiles commands.yaml
│   │   ├── engine.py      ← IntentEngine: 5-phase matching pipeline
│   │   ├── llm.py         ← LLMEngine: conversational LLM with history
│   │   ├── tool_executor.py ← ToolExecutor: autonomous tool-calling loop
│   │   ├── tools.py       ← Tool implementations (web_search, read_file, etc.)
│   │   └── tool_schemas.py ← OpenAI function-call schema definitions
│   │
│   ├── actions/           ← Callable action implementations
│   │   ├── executor.py    ← ActionExecutor: dynamic dispatch with timeout
│   │   ├── apps.py        ← App open/close/switch
│   │   ├── system.py      ← Volume, brightness, DND, dark mode, screenshot, etc.
│   │   ├── files.py       ← File/folder open
│   │   ├── browser.py     ← Playwright browser automation
│   │   ├── exec_commands.py ← Terminal/Python execution with approval gate
│   │   ├── memory.py      ← Semantic memory voice actions
│   │   ├── notify.py      ← Timers, alarms, reminders with OS banners
│   │   ├── smarthome.py   ← Light/plug/thermostat voice actions
│   │   ├── integrations.py ← Calendar/email voice actions
│   │   ├── event_scheduler.py ← Proactive calendar event reminders
│   │   ├── vision.py      ← Screenshot + GPT-4 Vision screen analysis
│   │   └── monitor.py     ← Health monitor voice actions
│   │
│   ├── integrations/      ← Third-party service adapters
│   │   ├── auth.py        ← OAuth flow + credential persistence
│   │   ├── calendar_service.py ← Unified Google/Outlook calendar adapter
│   │   ├── email_service.py    ← Unified Gmail/Outlook email adapter
│   │   └── smarthome.py   ← Home Assistant + Philips Hue REST clients
│   │
│   ├── memory/            ← Persistent storage
│   │   ├── store.py       ← MemoryStore: SQLite (prefs, routines, phrases, log)
│   │   └── semantic.py    ← SemanticMemory: ChromaDB vector store
│   │
│   ├── monitor/           ← System observability
│   │   ├── health.py      ← SystemHealthMonitor: CPU/RAM/disk/GPU sampling
│   │   └── stats.py       ← StatsBroadcaster: periodic IPC stats payloads
│   │
│   └── ipc/
│       └── server.py      ← IPCServer: Unix socket / named pipe broadcast
│
├── hud/                   ← macOS Swift HUD (Swift Package)
│   ├── Package.swift      ← Swift PM manifest (macOS 14+)
│   └── Sources/JarvisHUD/
│       ├── App.swift      ← @main entry, no window scene
│       ├── AppDelegate.swift ← NSPanel creation, status bar item
│       ├── HUDPanel.swift ← Borderless floating NSPanel
│       ├── OrbView.swift  ← Animated orb SwiftUI view
│       ├── StateManager.swift ← @Published state + IPC message decoder
│       └── IPCClient.swift ← Unix socket client with reconnect loop
│
├── hud-win/               ← Windows C#/WPF HUD (.NET 8)
│   ├── JarvisHUD.csproj
│   ├── App.xaml / App.xaml.cs
│   ├── HUDWindow.xaml / HUDWindow.xaml.cs
│   ├── IPCClient.cs       ← Named pipe client with reconnect loop
│   └── StateManager.cs    ← State + IPC message decoder
│
├── scripts/
│   ├── install.sh         ← macOS: venv setup + Swift HUD build
│   ├── install.ps1        ← Windows: venv setup + .NET HUD build
│   ├── start.sh           ← macOS: launch Python core + HUD binary
│   └── start.ps1          ← Windows: launch Python core + HUD binary
│
└── tests/                 ← Unit and integration tests
    ├── test_tool_loop.py
    ├── test_tools.py
    ├── test_auth_storage.py
    ├── test_calendar_service.py
    ├── test_exec_commands.py
    ├── test_health_monitor.py
    ├── test_integrations_actions.py
    ├── test_memory_commands.py
    ├── test_monitor_actions.py
    ├── test_notify.py
    ├── test_semantic_memory.py
    └── test_smarthome.py
```

### Entry Points

| Entry Point                           | How to Invoke  | What It Does                       |
| ------------------------------------- | -------------- | ---------------------------------- |
| `python -m jarvis`                    | CLI            | Starts the full Python core        |
| `jarvis/__main__.py`                  | Direct         | Calls `Jarvis().run()`             |
| `hud/.build/release/JarvisHUD`        | macOS binary   | Starts the Swift HUD               |
| `hud-win/bin/Release/…/JarvisHUD.exe` | Windows binary | Starts the WPF HUD                 |
| `scripts/start.sh`                    | Shell          | Launches both processes on macOS   |
| `scripts/start.ps1`                   | PowerShell     | Launches both processes on Windows |

---

## 4. Key Design Decisions

### 1. Two-Process Architecture

**Decision:** Separate the native HUD from the Python core into independent OS processes connected via IPC.

**Rationale:**

- The HUD requires platform-specific native UI frameworks (AppKit, WPF) that are not accessible from Python. Running them in a native process yields smooth 60 fps animations and proper OS integration (menu bar, window layering).
- Process isolation means a Python crash does not take down the visual layer, and vice versa.
- The IPC interface (newline-delimited JSON) is simple, debuggable, and language-agnostic.

**Trade-off:** Adds operational complexity (two processes to start and stop, IPC protocol to maintain).

### 2. Offline-First with Optional Cloud Fallback

**Decision:** All core functionality (wake word, STT, intent matching, most actions) runs entirely locally. Cloud services (LLM, calendar, email) are opt-in.

**Rationale:**

- Eliminates latency from network round-trips on the hot path.
- Protects user privacy by default — no audio ever leaves the machine unless explicitly configured.
- Works without an internet connection.

**Trade-off:** Local `faster-whisper` requires ~150 MB of model data on first run; local LLM (if self-hosted via `openai_compatible`) requires significant RAM/GPU.

### 3. Five-Phase Intent Matching (Escalating Fallback)

**Decision:** Intent resolution attempts exact regex → normalized regex → fuzzy string → learned memory → LLM, in that order, stopping at the first match.

**Rationale:**

- Regex is zero-latency and deterministic for known commands.
- Fuzzy matching (RapidFuzz `token_sort_ratio`, threshold 65) handles natural variation in phrasing without requiring an LLM.
- Memory lookup personalises recognition over time from usage.
- LLM fallback handles truly open-ended queries without rewriting the core matching logic.

**Trade-off:** LLM fallback adds 0.5–3 s latency. The system logs a `no match` at each phase; failed phases are not retried.

### 4. YAML-Driven Command Registry

**Decision:** All voice commands are defined in `commands.yaml`, not in Python code.

**Rationale:**

- Non-programmers can add or modify commands without editing source files.
- The pattern-to-regex compiler in `CommandRegistry` handles escaping and named slot capture groups automatically.
- Commands can be reloaded without restarting by re-instantiating `CommandRegistry` (not wired up at runtime currently — see Limitations).

**Trade-off:** Complex conditional logic cannot be expressed in YAML; such actions must still be implemented as Python callables.

### 5. Context Injection for Optional Subsystems

**Decision:** Optional modules (smart home, vision, exec commands, integrations) receive their runtime configuration through module-level `set_*_context()` calls from `core.py`.

**Rationale:**

- Avoids import-time side effects (no network calls or heavy model loading at import).
- Allows graceful degradation: if a subsystem's dependencies are missing, `core.py` logs a warning and continues.
- Keeps action modules independently testable by injecting mock context.

**Trade-off:** Module-level state is a form of implicit global state; concurrent test isolation requires care (mock patches).

### 6. Approval Gate for Shell Execution

**Decision:** Terminal commands and Python scripts (`exec_commands.py`) require an explicit voice confirmation ("confirm") before execution.

**Rationale:**

- Shell execution is high-risk; accidental or misheard commands could cause data loss.
- A hard-coded blocklist rejects patterns matching disk wipes, fork bombs, and writes to block devices even after user confirmation.

**Trade-off:** Adds a round-trip latency (extra listen cycle) for every command execution request.

### 7. Credential Security Strategy

**Decision:** OAuth tokens are stored in the system keyring when available (`keyring` library); if not, they are persisted as AES-256-GCM encrypted files under `~/.jarvis/credentials/`, with permissions set to `0600`.

**Rationale:**

- Never write secrets to plain files or logs.
- System keyring is the highest-security option on both platforms.
- Encrypted file fallback ensures functionality on headless or keyring-unavailable systems.

---

## 5. Core Workflows

### 5.1 Wake-Word Activation Cycle

```
Microphone (continuous stream)
    │
    ├─ 80 ms chunk ──→ WakeWordDetector.process()
    │                        │
    │                  score ≥ threshold?
    │                        │ YES
    │                  wake_queue.put(True)
    │
    ├─ main loop wakes (wake_queue.get())
    │
    ├─ _set_state("listening")  ──→ IPC broadcast + chime
    │
    ├─ AudioCapture.record_command()
    │       records until 1.5 s silence or 5 s timeout
    │       returns float32 numpy array
    │
    ├─ SpeechRecognizer.transcribe(audio)
    │       faster-whisper with VAD filter
    │       returns text string
    │
    ├─ EmotionAnalyzer.analyze_emotion(audio, text)
    │       returns EmotionResult {emotion, confidence}
    │       LLMEngine.set_tone(emotion)
    │
    └─ Intent matching + execution  (see 5.2)
```

**Double-clap activation** follows the same path from the `wake_queue` step.

### 5.2 Intent Resolution Pipeline

```
transcribed text
    │
    ▼
IntentEngine.match(text)
    │
    ├─ Phase 1: regex match (CommandRegistry)
    │     Iterate compiled patterns, check re.match()
    │     Extract named slots from match groups
    │     → IntentResult(confidence=1.0) if matched
    │
    ├─ Phase 2: normalized regex
    │     Strip stop-words ("please", "hey", "jarvis", etc.)
    │     Retry Phase 1 on cleaned text
    │     → IntentResult(confidence=0.9) if matched
    │
    ├─ Phase 3: fuzzy token match (RapidFuzz)
    │     Compare cleaned text against all patterns (stop-word stripped)
    │     token_sort_ratio ≥ 65 → match
    │     → IntentResult(confidence=score/100) if matched
    │
    ├─ Phase 4: memory phrase lookup
    │     Query MemoryStore.get_phrase_mapping(text)
    │     Learned from past corrections stored in SQLite
    │     → IntentResult if found
    │
    └─ Phase 5: LLM fallback
          Query SemanticMemory for 3 relevant facts (if enabled)
          LLMEngine.query(text, context_facts)
          Asynchronously extract + store new facts from the query
          → IntentResult(intent="llm_response", action="noop")
          → None if LLM disabled or returns empty
```

### 5.3 Action Execution

```
IntentResult {intent, action, slots, response}
    │
    ├─ action == "noop"?  → skip execution
    │
    ▼
ActionExecutor.execute(action_path, slots)
    │
    ├─ Resolve "apps.open_app" → jarvis.actions.apps.open_app
    │     (module cache avoids repeated imports)
    │
    ├─ Submit to ThreadPoolExecutor (max_workers=2)
    │     timeout: 5 s default, 35 s for browser actions
    │
    ├─ action_result returned (string or None)
    │
    ├─ response template interpolation:
    │     "{result}" in response → replaced by action_result
    │     "{app}" etc. → replaced by slot value
    │
    └─ Synthesizer.speak(response)
           _set_state("speaking")  ──→ IPC broadcast + chime
           platform TTS executes synchronously
           _set_state("dormant")   ──→ IPC broadcast + chime
```

### 5.4 LLM Tool-Calling Loop

When `llm.function_calling_enabled: true` in config, the LLM can invoke tools autonomously:

```
User query → LLMEngine.query(text)
    │
    └─ ToolExecutor.execute_loop(client, messages)
           │
           ├─ Iteration 1..max_tool_calls:
           │       client.chat_with_tools(messages, schemas)
           │       → (content, tool_calls)
           │
           ├─ tool_calls not empty?
           │       run_tool(name, arguments)
           │           web_search → duckduckgo_search
           │           read_file  → filesystem (path safety checked)
           │           run_code   → subprocess Python with timeout
           │           get_schedule / get_next_event → CalendarService
           │           browser_action → Playwright
           │           smart_home_control → SmartHomeClient
           │           run_command → shell (requires approval gate)
           │       Append tool result as role="tool" message
           │       Continue loop
           │
           └─ tool_calls empty (or max iterations reached)
                   Return final text response
```

### 5.5 Health Alert Deferred Delivery

Health alerts from `SystemHealthMonitor` are not spoken immediately to avoid interrupting an in-progress command:

```
SystemHealthMonitor (background thread)
    │ threshold crossed
    ▼
_on_health_alert() → _alert_queue.put(alert_message)

Main loop transitions to "dormant" or "thinking"
    │
    ▼
_flush_alert_queue()
    → dequeue all pending alerts
    → synthesizer.speak() for each
```

### 5.6 Approval Gate Flow

```
action_result starts with APPROVAL_PREFIX?
    │ YES
    ├─ _awaiting_approval = True
    ├─ Synthesizer.speak(approval_prompt)
    ├─ _set_state("dormant") — wait for next wake event
    │
    Next activation:
    ├─ transcribe user response
    ├─ _is_confirmation(text)? → execute_pending() → speak result
    ├─ _is_rejection(text)?   → cancel_pending() → speak "Cancelled"
    └─ neither?               → speak re-prompt
```

### 5.7 State Machine

The assistant has six named states:

| State       | HUD Orb Appearance  | Audio Feedback       |
| ----------- | ------------------- | -------------------- |
| `dormant`   | Dim, slow breathing | Soft chime on return |
| `woke`      | Brightening         | —                    |
| `listening` | Spinning ring       | High ping chime      |
| `thinking`  | Spinning ring       | Double-click chime   |
| `speaking`  | Sound wave rings    | Low chime            |
| `error`     | Red tint            | —                    |

Every state change calls `ipc.broadcast({"type": "state", "state": new_state})`.

---

## 6. Configuration & Environment

### Primary Configuration File: `config.yaml`

All runtime behaviour is controlled by `config.yaml` in the project root. The file is loaded at startup by `jarvis/config.py`, which applies safe defaults and range-clamps numeric values.

#### Key Sections

| Section           | Purpose                      | Notable Keys                                               |
| ----------------- | ---------------------------- | ---------------------------------------------------------- |
| `wake`            | Wake-word detection          | `engine` (openwakeword/keyboard), `model`, `threshold`     |
| `audio`           | Microphone settings          | `sample_rate`, `channels`, `command_timeout`               |
| `speech`          | STT model                    | `whisper_model` (tiny.en/base.en/small.en), `language`     |
| `voice`           | TTS settings                 | `engine` (system), `voice`, `rate`                         |
| `memory`          | Persistence                  | `db_path`, `semantic_enabled`, `vector_db_path`            |
| `ipc`             | HUD communication            | `socket_path` (Unix socket path)                           |
| `clap`            | Double-clap activation       | `enabled`, `threshold`, `min_interval`                     |
| `llm`             | LLM integration              | `enabled`, `provider`, `model`, `function_calling_enabled` |
| `browser`         | Playwright automation        | `browser` (chromium/webkit/firefox), `headless`            |
| `health_monitor`  | System resource monitoring   | `enabled`, `sample_interval_sec`, `thresholds.*`           |
| `integrations`    | Calendar/email               | `calendar.*`, `email.*`, `oauth.*`                         |
| `smart_home`      | Home automation              | `enabled`, `backend` (home_assistant/hue_direct)           |
| `exec_commands`   | Shell execution              | `enabled`, `timeout_sec`, `allowed_dir`                    |
| `notifications`   | Timers/alarms                | `enabled`, `max_timer_hours`                               |
| `event_scheduler` | Proactive calendar reminders | `enabled`, `poll_interval_minutes`, `lead_times_minutes`   |
| `vision`          | Screen analysis              | `enabled`, `model` (gpt-4o), `max_tokens`                  |

#### Important Defaults

- LLM is **disabled** by default (`llm.enabled: false`). Wake-word with local STT and regex matching works with no API keys.
- Health monitor is **enabled** by default. Set `health_monitor.enabled: false` to turn it off.
- Smart home, vision, and exec commands are **disabled** by default.
- Semantic memory is **disabled** by default.

### Command Definitions: `commands.yaml`

Defines every recognised voice command as a YAML entry:

```yaml
- intent: open_app
  patterns:
    - "open {app}"
    - "launch {app}"
  action: apps.open_app
  slots:
    app: { type: string, required: true }
  response: "Opening {app}"
```

- `intent`: unique identifier
- `patterns`: natural language templates; `{slot_name}` becomes a named regex capture group
- `action`: dotted path resolved to `jarvis.actions.<module>.<function>`
- `slots`: type hints (used for documentation; runtime type coercion is minimal)
- `response`: template string spoken aloud; `{slot_name}` and `{result}` are interpolated

### Environment Variables

| Variable         | Used By                                           | Description                                                      |
| ---------------- | ------------------------------------------------- | ---------------------------------------------------------------- |
| `HF_TOKEN`       | `jarvis/brain/llm.py`                             | HuggingFace API token (alternative to `llm.api_token` in config) |
| `OPENAI_API_KEY` | `jarvis/brain/llm.py`, `jarvis/actions/vision.py` | OpenAI API key                                                   |

No other environment variables are read. Credentials for Google and Microsoft OAuth are stored via the keyring/encrypted-file mechanism, not environment variables.

### Persistent Data Paths

| Path                     | Contents                                                                   |
| ------------------------ | -------------------------------------------------------------------------- |
| `~/.jarvis/memory.db`    | SQLite: preferences, routines, phrase mappings, action log, OAuth accounts |
| `~/.jarvis/chroma/`      | ChromaDB vector store for semantic memory                                  |
| `~/.jarvis/credentials/` | AES-256-GCM encrypted OAuth tokens (fallback when keyring unavailable)     |
| `/tmp/jarvis.sock`       | Unix socket for HUD IPC (macOS)                                            |
| `\\.\pipe\jarvis`        | Windows named pipe for HUD IPC                                             |

### Build and Run Overview

**macOS:**

```bash
# Install (once)
./scripts/install.sh
# → creates .venv/, installs Python deps, builds hud/.build/release/JarvisHUD

# Run
./scripts/start.sh
# → starts python -m jarvis + JarvisHUD in background; Ctrl+C for clean shutdown
```

**Windows:**

```powershell
# Install (once)
.\scripts\install.ps1
# → creates .venv\, installs Python deps (including pywin32), builds WPF HUD

# Run
.\scripts\start.ps1
```

---

## 7. Development Guide (Internal)

### Local Setup

**Prerequisites:**

- macOS 14+ or Windows 10+
- Python 3.10+
- macOS: Xcode Command Line Tools (`xcode-select --install`)
- Windows: .NET SDK 8.0+
- Microphone access granted to Terminal / your IDE

**Steps:**

```bash
git clone <repo-url>
cd Jarvis
./scripts/install.sh          # macOS
# OR
.\scripts\install.ps1         # Windows

# Activate the virtual environment manually if needed
source .venv/bin/activate     # macOS/Linux
.venv\Scripts\activate        # Windows
```

On first run, `faster-whisper` will download the Whisper model (~150 MB for `base.en`) and `openwakeword` will download its pretrained models. Both are cached locally.

### Running Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

Individual test files cover:

- `test_tool_loop.py` — LLM tool-calling loop integration (mocked LLM client)
- `test_tools.py` — Individual tool implementations (web_search, read_file, run_code)
- `test_auth_storage.py` — OAuth credential persistence
- `test_calendar_service.py` — Calendar adapters (Google, Outlook)
- `test_exec_commands.py` — Shell execution safety checks and approval gate
- `test_health_monitor.py` — Metric sampling and threshold alerting
- `test_integrations_actions.py` — Calendar/email voice actions
- `test_memory_commands.py` — Semantic memory voice actions
- `test_monitor_actions.py` — Health monitor voice actions
- `test_notify.py` — Timer, alarm, reminder scheduling
- `test_semantic_memory.py` — ChromaDB store and recall
- `test_smarthome.py` — Smart home action dispatching

### Debugging

- All subsystems log under named loggers (`jarvis`, `jarvis.brain`, `jarvis.audio`, etc.). Set `logging.basicConfig(level=logging.DEBUG)` in `core.py` for verbose output.
- The IPC protocol is plain JSON. Connect to `/tmp/jarvis.sock` with `nc -U /tmp/jarvis.sock` (macOS) to inspect live state broadcasts.
- Run without the HUD by starting `python -m jarvis` directly; the assistant is fully functional without a connected HUD client.

### Coding Conventions

- **Action modules** are stateless functions with signature `(slot_kwargs) → str`. They receive only their declared slot values.
- **Context injection** (`set_*_context()`) is called once at startup by `core.py`. Never call it from action functions themselves.
- **Platform branching** uses `platform.system()` at the top of modules; branches are clearly labelled `Darwin` (macOS) and `Windows`.
- **Graceful degradation**: subsystems that fail to initialise must log a warning and allow the rest of the system to continue. Never raise from `__init__` in an optional subsystem.
- **No markdown in spoken responses**: the `Synthesizer` speaks raw text. Avoid bullet points, asterisks, or headers in `response` values or LLM prompts.

### Adding a New Voice Command

1. Add an entry to `commands.yaml`:
   ```yaml
   - intent: my_new_command
     patterns:
       - "do {something}"
     action: mymodule.my_action
     slots:
       something: { type: string, required: true }
     response: "Done: {something}"
   ```
2. Create `jarvis/actions/mymodule.py` with a `my_action(something: str) -> str` function.
3. No restart hooks or imports need to be modified — `CommandRegistry` loads all commands at startup and `ActionExecutor` resolves module paths dynamically.

### Adding a New LLM Tool

1. Implement the tool function in `jarvis/brain/tools.py` following the `web_search` pattern (accepts `**kwargs`, returns a plain string).
2. Add its name → callable mapping to `TOOL_DISPATCH` in `jarvis/brain/tool_executor.py`.
3. Add its JSON schema to `TOOL_SCHEMAS` in `jarvis/brain/tool_schemas.py`.
4. Add a `*_enabled` toggle to `config.yaml` and update `get_enabled_schemas()` in `tool_schemas.py` to respect it.

---

## 8. Non-Functional Aspects

### Performance

| Operation               | Typical Latency | Notes                                         |
| ----------------------- | --------------- | --------------------------------------------- |
| Wake-word detection     | ~0 ms           | Per-frame (80 ms window), runs inline         |
| Speech transcription    | 200–800 ms      | `faster-whisper base.en` on CPU with int8     |
| Regex intent match      | < 1 ms          | —                                             |
| Fuzzy intent match      | 5–20 ms         | Scales linearly with command count            |
| Action execution        | < 100 ms        | Most shell/system actions                     |
| Browser action          | 2–35 s          | Playwright navigation; longer timeout applied |
| LLM query (HuggingFace) | 1–5 s           | Network + model inference                     |
| LLM query (local)       | 0.5–3 s         | Depends on hardware                           |

- The `command_timeout` (default 5 s) caps total listening time after wake.
- `ActionExecutor` uses a thread pool of 2 workers. A slow action does not block the audio pipeline.

### Security

- **No credentials in config files**: API tokens should be set via environment variables (`HF_TOKEN`, `OPENAI_API_KEY`) or left blank (keyring-backed).
- **OAuth tokens**: stored in the system keyring or AES-256-GCM encrypted files at `0600` permissions. Never logged.
- **Shell execution blocklist**: hard-coded patterns reject commands that could cause irreversible damage (disk wipe, fork bomb, raw device writes) even with explicit user confirmation.
- **File read path safety** (`read_file` tool): resolved paths must be under home or configured workspace root; blocked paths include `~/.ssh`, `~/.aws`, `~/.gnupg`, `/etc`, `/var`.
- **TTS injection**: on Windows, TTS text is passed via `stdin` pipe (not command-line argument) to prevent argument injection.
- **IPC**: the Unix socket is created with `os.unlink` cleanup and is local-machine only. No authentication on the socket (any local process can connect). This is an accepted risk for a single-user desktop application.
- **Sensitive metadata filtering** in `SemanticMemory`: slot keys named `password`, `token`, or `secret` are never written to the vector store.

### Scalability and Reliability

JARVIS is a **single-user, single-machine** application. It is not designed for multi-user or server deployment. Reliability considerations:

- All background threads are daemon threads; a crash in one does not take down the main loop.
- The IPC server reconnects automatically if a HUD client disconnects.
- Health alerts are queued when the system is speaking and delivered when it returns to idle (no double-interruption).
- SQLite is used without WAL mode. Concurrent writes from daemon threads are serialised by `check_same_thread=False`; this is safe only because writes are infrequent. High-frequency logging could expose contention.

### Logging and Monitoring

- Python standard logging with format `%(asctime)s [%(name)s] %(levelname)s: %(message)s`.
- Default level: `INFO`. Change to `DEBUG` in `core.py` for detailed diagnostics.
- Every state transition is logged at `INFO`.
- Every intent match (or failure) is logged at `INFO` with phase and confidence.
- Action execution start and completion (or timeout/error) are logged at `INFO`/`ERROR`.
- The `action_log` table in `MemoryStore` provides a persistent history of executed intents.
- Live system metrics are broadcast to the HUD every 5 seconds by `StatsBroadcaster`.

---

## 9. Limitations & Known Gaps

### Current Limitations

1. **Single wake-word model**: Only one wake-word model can be active at a time. Switching requires a config change and restart.
2. **English-only**: `faster-whisper` is configured with `language: "en"` and uses the `.en` model variant. Non-English use requires config changes and a different model.
3. **No hot-reload of commands**: `commands.yaml` changes require a process restart. The `CommandRegistry` does not watch the file.
4. **Sequential action execution**: `ActionExecutor` has a pool of 2 workers but the main loop waits for each action to complete before returning to dormant. Parallel/background actions are not supported via voice commands.
5. **No persistent-awake timer**: The `persistent-awake` mode (mentioned in `core.py`) is partially implemented but its activation command and timeout behaviour are not visible in `commands.yaml`.
6. **IPC has no authentication**: Any local process can connect to the Unix socket and receive state broadcasts or interfere with the HUD. Acceptable for single-user desktop use; not suitable for multi-user environments.
7. **Windows TTS does not support chime differentiation**: The Windows `Synthesizer` uses `Console.Beep` for all chimes, which is less expressive than the macOS `.aiff` audio files.
8. **No error recovery for broken audio stream**: If `sounddevice` loses the microphone (e.g., device disconnected), the audio thread throws and the system must be restarted.
9. **Playwright browser session is not isolated**: The browser session is a module-level singleton. Concurrent LLM tool calls to `browser_action` would race; the lock in `browser.py` mitigates but does not fully prevent this.

### Technical Debt

- `commands.yaml` contains `# ── Calendar / Email Integrations` section that extends beyond line 300; the full set of calendar/email/smart home intents was not fully read during analysis. The intents documented above represent the visible subset.
- `jarvis/integrations/email_service.py` was not read during analysis. Its capabilities are inferred from `requirements.txt` and config but not verified.
- The `hud-win/` WPF animation implementation was not read in detail; its visual parity with the macOS HUD is assumed but not confirmed.
- No linting configuration (`.flake8`, `pyproject.toml`, `ruff.toml`) was found. Code style is consistent but not enforced by tooling.
- No CI/CD configuration was found (no `.github/workflows/`, no `Makefile`).

### Missing Documentation or Unclear Areas

- The `smart_home` config section is referenced in `config.py` but the full schema (Home Assistant token, Hue Bridge IP) is only documented in `jarvis/integrations/smarthome.py` docstrings, not in `config.yaml`.
- The `notifications` and `event_scheduler` config sections are injected at runtime but not present in the default `config.yaml` shown in the README. Users must add them manually.
- It is unclear whether `jarvis/__init__.py` exposes any public API surface; it was not read during analysis.

---

## 10. Appendix

### Glossary

| Term                    | Definition                                                                                               |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| **Wake word**           | A short phrase ("Hey Jarvis") used to activate the assistant from dormant state                          |
| **STT**                 | Speech-to-Text; converts microphone audio to a text string                                               |
| **TTS**                 | Text-to-Speech; synthesises spoken audio from a text string                                              |
| **Intent**              | A categorised interpretation of a user's utterance (e.g., `open_app`)                                    |
| **Slot**                | A variable extracted from a voice command pattern (e.g., `{app}` → "Chrome")                             |
| **LLM**                 | Large Language Model; used as a fallback for unrecognised utterances                                     |
| **Function calling**    | A protocol where an LLM requests the host to execute a tool and returns the result for further reasoning |
| **IPC**                 | Inter-Process Communication; the channel between the Python core and the native HUD                      |
| **HUD**                 | Heads-Up Display; the floating visual orb indicating assistant state                                     |
| **ChromaDB**            | An embedded vector database used for semantic (similarity-based) memory                                  |
| **OpenWakeWord**        | An open-source library for on-device wake-word detection                                                 |
| **faster-whisper**      | A CTranslate2-optimised implementation of OpenAI Whisper for local STT                                   |
| **RapidFuzz**           | A fast fuzzy string matching library implementing Levenshtein-based ratios                               |
| **Crest factor**        | Peak amplitude divided by RMS; high values distinguish percussive sounds (claps) from sustained noise    |
| **CIE 1931 xy**         | The Philips Hue colour space for light control; computed from sRGB via a linear transform                |
| **MSAL**                | Microsoft Authentication Library; used for Outlook/Graph OAuth                                           |
| **Named capture group** | A regex feature `(?P<name>...)` that labels matched substrings; used for slot extraction                 |

### Assumptions Made During Documentation

1. `hud-win/` animations are functionally equivalent to `hud/` macOS animations (not fully verified from source).
2. `jarvis/integrations/email_service.py` follows the same adapter pattern as `calendar_service.py` (inferred, not read).
3. The full `commands.yaml` (beyond line 300) contains additional calendar, email, smart home, browser, exec, notify, vision, and event scheduler intents consistent with the action modules that exist.
4. The Windows named pipe path is `\\.\pipe\jarvis` (inferred from the `IPCServer` and `IPCClient.cs` implementations; the exact name string was not confirmed in the Python server code).
5. `jarvis/__init__.py` is an empty package marker (common Python convention; not verified).

### Open Questions for Maintainers

1. **Persistent-awake mode**: What command activates it? Is there a timeout? The `self.awake` flag exists in `core.py` but no command in `commands.yaml` appears to set it.
2. **Hot-reload of commands**: Is there a planned mechanism to reload `commands.yaml` without restarting, e.g., via a voice command or file watcher?
3. **Multi-language support**: Is localisation a goal? The architecture currently assumes English throughout.
4. **Windows IPC pipe name**: Should the named pipe name be configurable via `config.yaml` (as the Unix socket path is), or is `\\.\pipe\jarvis` intentionally hardcoded?
5. **Action log retention**: The `action_log` table grows unboundedly. Is there a planned retention policy or archival strategy?
6. **Smart home config documentation**: The `smart_home` section is not in the default `config.yaml`. Should an example `smart_home` block be added to the shipped config with safe defaults?
7. **CI/CD**: Is a CI pipeline planned? A minimal test run on push would protect against regressions.
8. **Thread safety of SQLite**: `MemoryStore` uses `check_same_thread=False`. Is concurrent write access from multiple daemon threads (action logger, integrations, event scheduler) explicitly tested?
