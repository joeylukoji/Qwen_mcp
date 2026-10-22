# Qwen MCP: Local AI Excel Analyst

> Turn any Excel file into clean JSON and ask questions about it in plain language, 100% locally, with **Qwen 2.5** running on **Ollama**, exposed as an **MCP server** and a **web chatbot**.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-server-black)
![Ollama](https://img.shields.io/badge/Ollama-qwen2.5%3A3b-white)
![Flask](https://img.shields.io/badge/Flask-3-lightgrey)

Built for school administration data (grade sheets, class lists), but works on any spreadsheet: the header row is detected automatically and no column structure is assumed.

---

## ✨ Features

- **Generic Excel → JSON** for `.xlsx` / `.xls`, every sheet, with automatic header-row detection and NaN cleaning.
- **MCP server** (`excel_vers_json` tool) usable from Claude Desktop, Cursor, VS Code or any MCP client.
- **Multi-agent analysis pipeline** (Indexer → Searcher → Analyst) that only sends the relevant rows to a small model.
- **Batch processor** that sends large files to the LLM in chunks of `BATCH_SIZE` rows.
- **Web chatbot** (Flask) to upload a file and chat with it.
- **Fully local and private:** data never leaves your machine, with a local fallback summary when the LLM is unavailable.

## 🏗️ Architecture

```
              ┌──────────────────────┐
 MCP client ─▶│ mcp_server.py        │──▶ excel_vers_json (pandas)
 (Claude,     │  stdio MCP server    │
  Cursor…)    └──────────────────────┘

              ┌──────────────────────┐     ┌───────────────────────────────┐
 Browser ────▶│ web_server.py (Flask)│────▶│ 1. batch_processor.py         │
              │  /api/upload         │     │    (chunks of BATCH_SIZE rows)│
              │  /api/chatbot        │     │ 2. agents.py (multi-agent)    │
              │  /api/health         │     │ 3. simple mode (fallback)     │
              └──────────────────────┘     └───────────────┬───────────────┘
                                                           ▼
                                  Ollama · qwen2.5:3b (OpenAI-compatible API)
```

### Multi-agent pipeline (`agents.py`)

| Agent | Role |
|---|---|
| **AgentIndexeur** (Indexer) | Loads the file, detects the header row and builds an index: columns, types, statistics (mean, min, max, median, std), a stratified sample and unique values. |
| **AgentChercheur** (Searcher) | Reads the question and picks a strategy: `recherche_nom` (a specific person), `filtrage` (criteria), `echantillon` (sample) or `toutes_colonnes`. Names written in CAPITALS are detected without calling the LLM. |
| **AgentAnalyseur** (Analyst) | Sends only the selected rows plus global statistics to the LLM, within the context budget, with strict "never invent data" rules. |

The chatbot tries the **batch processor** first (when `mode_batch` is set or the message is long), then the **multi-agent** pipeline, then a **simple** mode.

---

## 🚀 Getting started

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/download) with the Qwen model:

```bash
ollama pull qwen2.5:3b
```

### Install

```bash
git clone https://github.com/joeylukoji/Qwen_mcp.git
cd Qwen_mcp
pip install -r requirements.txt
```

On Windows you can run `install.bat` instead.

### Run the web chatbot

```bash
python web_server.py      # or start_web.bat
```

Open http://localhost:5000, upload an Excel file and ask questions, for example:

- *"What is the class average?"*
- *"Show the grades of KABEYA JEAN"*
- *"How many students scored below 10?"*

### Use as an MCP server

Add this to your MCP client configuration (also in [`mcp.json`](mcp.json)), with the absolute path to `mcp_server.py`:

```json
{
  "mcpServers": {
    "excel-analyzer": {
      "command": "python",
      "args": ["C:/path/to/Qwen_mcp/mcp_server.py"],
      "env": { "PYTHONUNBUFFERED": "1" }
    }
  }
}
```

**Tool `excel_vers_json`**

| Argument | Type | Required | Description |
|---|---|---|---|
| `chemin_fichier` | string | yes | Absolute or relative path to the `.xlsx` / `.xls` file |
| `feuille` | string | no | Sheet name; all sheets if omitted |

Output for a single sheet:

```json
{
  "feuille": "Sheet1",
  "ligne_en_tete": 0,
  "colonnes": ["Nom", "Classe", "Math", "Physique"],
  "nombre_lignes": 42,
  "lignes": [{ "Nom": "…", "Classe": "…", "Math": 14, "Physique": null }]
}
```

---

## 🌐 HTTP API

| Method | Route | Body | Description |
|---|---|---|---|
| `POST` | `/api/upload` | multipart: `file`, optional `type_analyse` (default `auto`) | Uploads and analyses an Excel file (max 50 MB). Returns the analysis and `fichier_path`. |
| `POST` | `/api/chatbot` | JSON: `message`, optional `fichier_path`, `mode_batch` | Answers a question about the uploaded file. The response's `mode` says which pipeline answered. |
| `GET` | `/api/health` | | Status, Ollama URL and model. |

```bash
curl -F "file=@grades.xlsx" http://localhost:5000/api/upload

curl -H "Content-Type: application/json" \
     -d '{"message": "What is the class average?", "fichier_path": "uploads/grades.xlsx"}' \
     http://localhost:5000/api/chatbot
```

---

## ⚙️ Configuration

All settings are environment variables:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434/v1/chat/completions` | OpenAI-compatible chat endpoint (Ollama, LM Studio…) |
| `OLLAMA_MODEL` | `qwen2.5:3b` | Model name |
| `OLLAMA_TIMEOUT` | `120` | LLM request timeout (seconds) |
| `OLLAMA_CONTEXT_SIZE` | `32000` | Context size used to budget the prompt |
| `LM_STUDIO_CONTEXT_SIZE` | `168000` | Context size for the simple chatbot mode |
| `BATCH_SIZE` | `20` | Rows per chunk in the batch processor |
| `ENABLE_LLM` | `1` | `0` disables LLM calls (local summaries only) |
| `LLM_COOLDOWN_SECONDS` | `60` | Pause before retrying the LLM after a failure |
| `HOST` | `127.0.0.1` | Web server bind address |
| `PORT` | `5000` | Web server port |
| `FLASK_DEBUG` | `0` | `1` enables Flask debug mode (development only) |

Because the endpoint is OpenAI-compatible, you can point `OLLAMA_URL` to LM Studio or any compatible server and switch models with `OLLAMA_MODEL`.

---

## 📁 Project structure

| File | Purpose |
|---|---|
| `mcp_server.py` | MCP server, Excel → JSON conversion, header detection, Ollama client |
| `agents.py` | Multi-agent pipeline (Indexer, Searcher, Analyst) |
| `batch_processor.py` | Chunked processing of large files |
| `web_server.py` | Flask app and HTTP API |
| `templates/index.html` | Web chatbot UI |
| `convertiseur_excel_json.py` | Standalone Excel → JSON script |
| `analyser_fichier_*.py` | Example analysis scripts |
| `test_*.py` | Manual checks: header detection, generic files, LLM connection |
| `install.bat`, `start_web.bat` | Windows helpers |

## 🧪 Checks

```bash
python test_lm_studio.py        # LLM connection
python test_detection_auto.py   # header-row detection
python test_fichier_generique.py
```

## ⚠️ Notes

- The web server listens on `127.0.0.1` with debug off by default. Set `HOST=0.0.0.0` to expose it on your network, and never enable `FLASK_DEBUG=1` outside development.
- Spreadsheets may contain personal data (student grades). `uploads/` and Excel files are already in `.gitignore`.
- `inserer_en_base_par_lots` in `batch_processor.py` is a stub to adapt to your database.

## 🗺️ Roadmap

- More MCP tools (statistics, filtering, natural-language queries)
- Database export for batch results
- Automated test suite and CI

## 👤 Author

**Joy Lukoji**, Independent AI Researcher · AI & Software Engineering · [Portfolio](https://joyportfolio-six.vercel.app/)
