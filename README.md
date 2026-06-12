# CAD MCP Platform

A **Windows-native** orchestration platform that controls **AutoCAD** through the COM API, exposes operations via a **FastAPI REST API** and a **browser UI**, and integrates with **MCP clients** (Cursor, Claude Desktop, Windsurf) through a dedicated **Model Context Protocol (MCP)** server layer.

The system is designed for **P&ID-style workflows**: insert instrument symbols from JSON templates, move/rotate/delete them, route **orthogonal pipes** between instruments, and optionally drive the same operations through **natural language** using **Google Gemini** with deterministic fallbacks.

---

## What this project does

| Capability | Description |
|------------|-------------|
| **AutoCAD COM control** | Connect to a running AutoCAD session; no headless drawing engine |
| **Logical entity model** | Symbols and pipes are tracked as `SYM_*` / `PIPE_*` handles, not raw COM handles |
| **Symbol library** | Vector templates in `symbol_templates.json`, rendered by `symbol_renderer.py` |
| **Orthogonal piping** | Center-to-center L-shaped routes on the `PIPES` layer |
| **REST + Web UI** | `main.py` + `static/` for manual operations |
| **AI agent** | `/agent/chat` plans tool sequences (Gemini + validation + execution) |
| **MCP server** | `cad_mcp` package exposes the same CAD tools to external MCP hosts over **stdio** |

---

## System requirements

| Requirement | Notes |
|-------------|--------|
| **OS** | Windows (COM automation) |
| **Python** | 3.11+ recommended |
| **AutoCAD** | Installed and typically running (attach via COM) |
| **Optional** | Google API key for Gemini planner (`GOOGLE_API_KEY` or `GEMINI_API_KEY`) |

---

## Quick start

### 1. Install dependencies

```powershell
cd D:\LTTSTechgium\MCP
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment (optional, for AI)

Create a `.env` file in the project root:

```env
GOOGLE_API_KEY=your_key_here
# Optional overrides:
# GEMINI_MODEL=gemini-flash-latest
```

Without an API key, the agent still runs using **deterministic fallback plans** (limited NL understanding).

### 3. Start the REST API and web UI

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open in a browser:

```
http://127.0.0.1:8000/
```

Use **Connect**, insert symbols, select entities, move/rotate/delete, and connect pipes (start/end handles).

### 4. Start the MCP server (for Cursor / Claude Desktop)

From the project root (so `entity_manager` and templates resolve correctly):

```powershell
python -m cad_mcp
```

Or:

```powershell
python run_cad_mcp.py
```

Configure your MCP client to launch this process with **cwd** set to the repository root. Example shape (client-specific):

```json
{
  "mcpServers": {
    "cad-mcp": {
      "command": "python",
      "args": ["-m", "cad_mcp"],
      "cwd": "D:\\LTTSTechgium\\MCP"
    }
  }
}
```

**Important:** MCP uses **stdio** for JSON-RPC. Runtime logs go to **stderr**; do not print debug text to stdout in the MCP process.

---

## Repository layout (high level)

```
MCP/
├── main.py                 # FastAPI application
├── entity_manager.py       # Thread-safe façade over AutoCADController
├── autocad_controller.py   # COM engine, registry, sync, XData, pipes
├── pipe_router.py          # Orthogonal pipe routing
├── symbol_renderer.py      # Template → AutoCAD geometry
├── symbol_templates.json   # Symbol definitions + connection ports metadata
├── schemas.py              # Pydantic models (REST + EntityMetadata)
├── agent_engine.py         # Gemini planner + chat synthesis
├── agent_tools.py          # Tool implementations + LLM schemas
├── tool_registry.py        # Tool name → function dispatch
├── execution_engine.py     # Multi-step plan execution
├── plan_validator.py       # Plan validation/normalization
├── agent_context.py        # CAD context for prompts
├── agent_memory.py         # Conversation + tool history
├── symbol_aliases.py       # Natural language → symbol keys
├── static/                 # Browser UI (HTML/JS/CSS)
├── cad_mcp/                # MCP adapter layer (stdio, tools, resources, prompts)
│   ├── runtime/
│   │   ├── bridge.py       # FastMCP singleton
│   │   ├── tools.py        # MCP tool wrappers
│   │   ├── resources.py    # Read-only MCP resources
│   │   ├── prompts.py      # Reusable prompt templates
│   │   ├── discovery.py    # Dynamic manifest for clients
│   │   └── capabilities.py # Capability negotiation
│   ├── transport/          # stdio (and websocket placeholder)
│   └── adapters/           # JSON serialization, execution envelopes
└── requirements.txt
```

For a **full technical breakdown**, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## REST API overview

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Web UI (`static/index.html`) |
| `GET` | `/status` | Connection status |
| `POST` | `/connect` | Connect to AutoCAD |
| `GET` | `/entities` | List tracked entities (syncs modelspace first) |
| `GET` | `/entities/{handle}` | Single entity metadata |
| `GET` | `/symbols/available` | Symbol names from templates |
| `POST` | `/symbols` | Insert symbol (`SymbolInsertRequest`) |
| `POST` | `/entities/move` | Move by logical handle |
| `POST` | `/entities/rotate` | Rotate |
| `POST` | `/entities/delete` | Delete |
| `POST` | `/pipes/connect` | Connect two handles with orthogonal pipe |
| `GET` | `/count` | Entity count |
| `GET` | `/drawing/details` | Document/layers/blocks summary |
| `POST` | `/agent/chat` | Natural-language CAD operations |

---

## MCP tools (external clients)

Registered on the shared FastMCP instance (`cad_mcp/runtime/bridge.py`):

| Tool | Purpose |
|------|---------|
| `insert_symbol` | Insert symbol at coordinates |
| `move_entity` | Move entity by delta |
| `rotate_entity` | Rotate around base point |
| `delete_entity` | Delete by handle |
| `connect_pipe` | Orthogonal pipe between two handles |
| `get_entities` | List entities |
| `count_entities` | Count by type/symbol |
| `find_entity` | Search by block name |
| `drawing_details` | Drawing metadata |

MCP **resources** (read-only URIs) include `cad://entities`, `cad://pipes`, `cad://drawing`, `cad://layers`, `cad://symbols`, `cad://selection/current`, and templates `cad://entity/{handle}`, `cad://pipe/{handle}`, `cad://layer/{name}`.

---

## AI agent flow (summary)

1. User message → `AIAgent.process_message` (`agent_engine.py`).
2. Build **CAD context** summary (`agent_context.py`).
3. **Plan** with Gemini (or deterministic fallback): JSON `ExecutionPlan` with steps.
4. **Validate** plan (`plan_validator.py`): tool names, args, symbols, `$stepN` references.
5. **Execute** via `ExecutionEngine` → `tool_registry.execute_tool` → same paths as REST.
6. Optional **layout finalization**: skip micro-moves after successful insert + route.

Tool schemas live in `agent_tools.TOOL_SCHEMAS` and are shared conceptually with MCP tool parameter names.

---

## Key design principles

1. **Single CAD façade** — `entity_manager.py` is the only module REST, agent tools, and MCP tools should use for mutations (not COM directly).
2. **Logical handles** — Multi-primitive symbols are one `SYM_*` entity; pipes are `PIPE_*` with segment primitives.
3. **XData persistence** — Primitives carry JSON metadata (`DIGIPID` app) for recovery after sync.
4. **Center-based routing** — Pipes connect using stable symbol **insertion/center** points (see `connection_point_for` in `autocad_controller.py`).
5. **Thin MCP layer** — `cad_mcp` wraps existing runtime; no duplicated CAD logic.
6. **Logging to stderr for MCP** — Keeps stdio JSON-RPC clean for MCP clients.

---

## Verification scripts

Optional phase verification utilities (write reports under `verification/`):

```powershell
python verify_phase6.py
python verify_phase9_stdio.py
python verify_final_status.py
```

---

## Related documentation

| Document | Contents |
|----------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Deep technical architecture, data flows, modules, COM/sync/MCP details |
| [ARCHITECTURE_AND_IMPLEMENTATION.md](ARCHITECTURE_AND_IMPLEMENTATION.md) | Earlier implementation-focused guide (partial overlap) |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Developer-oriented notes |
| [PLAN_VALIDATION_LAYER.md](PLAN_VALIDATION_LAYER.md) | Plan validator behavior |
| [GEMINI_HALLUCINATIONS_AND_CORRECTIONS.md](GEMINI_HALLUCINATIONS_AND_CORRECTIONS.md) | Known LLM pitfalls and mitigations |

---

## Limitations (current)

- **Windows + AutoCAD only** — COM is not portable.
- **Single-user COM** — Serialized via `RLock`; not designed for high concurrency.
- **MCP websocket transport** — Placeholder/scaffold; **stdio** is the supported external transport.
- **Gemini optional** — Planner quality depends on API availability; fallbacks are rule-based.
- **No full DXF/P&ID import** — Symbols come from `symbol_templates.json`, not from live DXF block libraries (unless mirrored in templates).

---

## License / status

Internal/prototype codebase. Confirm licensing and deployment policies with your organization before production use.
