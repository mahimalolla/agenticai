# Enterprise Data Agent — Technical Documentation

---

## Table of Contents

1. [Setting Things Up](#1-setting-things-up)
2. [Configuration (config.yaml)](#2-configuration-configyaml)
3. [Auxiliary Classes](#3-auxiliary-classes)
4. [Agents](#4-agents)
5. [Connecting Everything](#5-connecting-everything)

---

## 1. Setting Things Up

### Imports

| Import | Purpose |
|--------|---------|
| `json` | Parsing API responses |
| `hashlib` | Generating SQL fingerprints for auditing |
| `argparse` | Command-line flags |
| `re` | Regex in SQL validation |
| `dataclass` | Defining clean data structures |
| `yaml` | Reading config.yaml |
| `anthropic` | Official SDK for calling Claude |
| `numpy` & `faiss` | Vector math and similarity search |
| `pandas` | Loading the CSV training data |
| `sqlparse` | Validating SQL syntax |
| `sentence_transformers` | Running the embedding model |
| `dotenv` | Loading the API key from .env |
| `rich` | Making terminal output easier to read |

`load_dotenv()` loads the API key from the `.env` file and makes it available to the Anthropic SDK.

---

## 2. Configuration (config.yaml)

### 2.1 Model Assignments

**`models:`** — Top-level key. This section tells each agent which Claude model to use. The `Config` class reads this with `config.models`, and each agent pulls its own sub-key.

**`user_agent`** — Uses `claude-sonnet-4-5-20250929` (Claude Sonnet 4.5). Sonnet is chosen here because intent classification is a lightweight NLU task, cheaper and faster than Opus. Max tokens is set to 512. Temperature is set to 0 for fully deterministic behavior.

**`data_agent`** — Uses `claude-opus-4-6` (Claude Opus 4.6). Handles tool parameter extraction and SQL generation for fallback, the two tasks where accuracy matters most. Max tokens is set to 2048, since SQL strings can be long. Temperature is set to 0 for fully deterministic behavior.

**`orchestrator`** — Uses `claude-sonnet-4-5-20250929` (Claude Sonnet 4.5) again. No heavy reasoning needed here, so a lightweight model works well. In most cases the orchestrator does not actually make API calls, but this can be extended later. Max tokens is set to 1024. Temperature is set to 0 for fully deterministic behavior.

### 2.2 Retrieval Settings

Defines the model used for embeddings, the training data path (provided by the user), the number of similar examples to retrieve (`top_k`), and the minimum cosine similarity score needed to include an example. All of these parameters can be tweaked and optimized.

### 2.3 Routing Configuration

Defines how the orchestrator chooses whether to match a tool or generate SQL:

- **`match_threshold`** — Minimum score needed to consider a tool match.
- **`ambiguity_score`** — In production, the model could ask users for clarification. Right now it continues with a warning.
- **`fallback_strategy`** — Set to `"sql"`, meaning SQL generation via Opus. This can be changed to other strategies in the future.

### 2.4 Security Rules

Sets SQL validation rules enforced by the `SQLValidator`:

- **`max_rows_returned`** — Hard cap at 10,000 rows.
- **`blocked_sql_patterns`** — A list of keywords that will never be executed (`DELETE`, `UPDATE`, `DROP`, etc.).
- **`force_limit`** — Set to `true`, ensuring a `LIMIT` clause is added if one doesn't exist.
- **`default_limit`** — Set to 100.

### 2.5 Database Schema

The database schema that gets injected into every Opus SQL generation prompt. Opus can only reference tables and columns defined here. Different databases will have different schemas, the one defined in the config is a sample. The schema can also be defined in its own file (`schema.sql`) for readability.

### 2.6 Tools

Defines the tools used for semantic-first matching. Currently 5 tools are defined, but more can be added. Each tool provides the following information:

- **`name`** — Namespaced identifier (e.g., `orders.top_customers`)
- **`version`** — Semantic version (e.g., `2.1.0`)
- **`summary`** — Human-readable description
- **`inputs`** — Parameters the tool accepts, with type, enum values, defaults, and constraints
- **`outputs`** — Expected return structure for the orchestrator
- **`semantic_binding`** — Metrics and dimensions the tool operates on
- **`keywords`** — Words/phrases that signal relevance to this tool
- **`access_control`** — Which user roles can invoke the tool
- **`sql_fallback`** — The hardcoded SQL template that runs when the tool is matched (new SQL is NOT generated every time)

---

## 3. Auxiliary Classes

### 3.1 Data Classes

#### `Route` (Enum)

Defines the three possible paths a query can follow:

- **`SEMANTIC_FIRST`** — A tool handled the query.
- **`SQL_FALLBACK`** — Opus generated the SQL.
- **`ESCALATE`** — Neither could solve it.

Using an Enum ensures only these three types are ever passed.

#### `Intent`

What the User Agent produces. Takes the raw English question and breaks it into structured fields:

- **`query_type`** — Type of question (ranking, trend, filter, etc.)
- **`entities`** — Business objects mentioned (customers, orders, margins, etc.)
- **`time_period`** — The time range relevant to the query
- **`constraints`** — Any applicable filters
- **`confidence`** — A float (0–1) telling the orchestrator whether to ask clarifying questions

`field(default_factory=list)` is used to create mutable defaults, otherwise all instances would share one list.

#### `ToolMatch`

Wraps the result when the Data Agent finds a matching tool:

- **`name`** and **`version`** — From the tool manifest.
- **`score`** — Match confidence (0 to 1).
- **`manifest`** — The full tool definition.
- **`params`** — Filled later with extracted parameter values.

#### `TraceStep`

Every action is logged as a `TraceStep` object. This is the audit trail — it records:

- **Which** agent performed the action
- **What** action was taken
- **Details** of what happened
- **Timestamp** of when it occurred

This makes the system fully traceable, you can reconstruct exactly what happened for every query.

#### `AgentResponse`

The final output of the entire pipeline. Contains: status, route taken, unique request ID, the generated SQL, evidence metadata, the full trace, API cost, and elapsed time.

---

### 3.2 Config Loader

**`__init__`** — `yaml.safe_load(f)` reads config.yaml and converts it to a Python dictionary. The entire file is stored in `self._cfg`.

**`@property` methods** — Each `@property` creates a clean accessor for a section of the config (e.g., `config.models`, `config.tools`).

**`schema` property** — Checks if a `schema_file` exists. If yes, reads the schema from that file; otherwise uses the inline schema from config.yaml. Useful for larger, more specific schemas.

**Safety checks** — The code verifies that the `models` section exists in the config (required to run). Other sections like `tools` can be omitted, which results in SQL fallback being the only path.

---

### 3.3 Retrieval Index

**`__init__`** — Sets everything to `None` / `False`. Data and models are NOT loaded here, this prevents expensive loading on every instantiation (lazy loading pattern).

**`load()` — CSV** — `pd.read_csv` loads the training data. Basic data cleaning removes empty or `NULL` rows.

**`load()` — Embeddings** — `SentenceTransformer('BAAI/bge-base-en-v1.5')` downloads and loads the embedding model, which converts English text into vectors where semantically similar sentences produce similar vectors.

**`load()` — FAISS Index** — `self.embedder.encode(...)` converts all queries in the dataset into vectors at once (batch processing). `normalize_embeddings=True` normalizes each vector to unit length. `IndexFlatIP` creates an inner product search index. `index.add()` stores all vectors. With this preprocessing done, each new query can be compared against all 8,034 training pairs in milliseconds.

**`retrieve()`** — Called when the SQL fallback path needs similar examples. Checks if the index is loaded, encodes the user's query into a vector, then calls `index.search()` to find the k nearest neighbors. Returns matching training pairs with similarity scores. `min_similarity` filters out poor matches.

---

### 3.4 Tool Registry

**`__init__`** — Loads pre-defined tool configs from the YAML file and sets the matching threshold. For example: if threshold = 0.15, the tool must match at least 15% of its signals to be considered.

**`match()` — Overview** — The core of semantic-first routing. For each registered tool, calculates a match score against the user's query using two factors: keyword overlap and semantic binding match. The tool with the highest score above the threshold wins.

**`match()` — Keyword Scoring** — Each tool has a list of keywords (e.g., `[top, best, customer, ...]`). The function counts how many keywords appear in the user's query and returns it as a percentage. `max(len(kws), 1)` prevents division by zero when a tool has no keywords.

**`match()` — Semantic Binding** — Uses the structured output from the User Agent, specifically the intent's entity list (e.g., `['customers', 'margin']`). This list is compared against each tool's declared metrics and dimensions. This catches cases where the exact words aren't present but the meaning matches (e.g., "revenue" in the intent matches even if the user said "total sales").

**`match()` — Scoring** — Takes a weighted sum: 60% keyword score + 40% semantic binding score. Returns a `ToolMatch` if a match is found above the threshold. Returns `None` if the best match is below threshold, which triggers the SQL fallback path.

**`get_tool()`** — Simple lookup by name. Returns a specific tool's manifest.

---

### 3.5 SQL Validator

**`__init__`** — Loads the security config: blocked patterns (`DELETE`, `DROP`, `UPDATE`, etc.) and LIMIT requirements.

**`validate()` — Blocked Patterns** — `re.search(rf'\b{pattern}\b', sql_upper)` uses word-boundary matching. Catches `DROP TABLE` but not a column named `drop_date`. Blocks any hallucinated write operations.

**`validate()` — LIMIT Check** — Prevents runaway queries by ensuring a `LIMIT` clause exists. This is a warning, not an error, the query is still valid, just modified with an appended `LIMIT`.

**`validate()` — Syntax** — `sqlparse.parse(sql)` breaks the SQL into tokens and checks basic structure. Catches malformed SQL before it reaches the database.

**Return Value** — Returns a dictionary with:

- **`valid`** — Boolean: is the SQL safe to execute?
- **`errors`** — Any blockers that prevent execution
- **`warnings`** — Non-fatal issues (e.g., LIMIT added)
- **`cleaned_sql`** — The validated (and possibly modified) SQL

---

## 4. Agents

### 4.1 User Agent

**`__init__`** — Uses the Anthropic client and loads user_agent model config (currently Sonnet 4.5, 512 max tokens, temperature = 0). Temperature 0 is important for consistency.

**`classify()` — Prompt** — Asks Sonnet to convert the user's English question into structured JSON. The instruction `"Respond only with a JSON object (no markdown, no backticks)"` ensures the API returns parseable JSON.

**`classify()` — API Call** — `self.client.messages.create(...)` is the actual Anthropic API call. Sends the prompt to Sonnet and receives a response. `resp.content[0].text` extracts the text from the first content block. `.replace('```json', '')` is a safety measure in case the model wraps the JSON in markdown fences.

**`classify()` — Parsing** — `json.loads(raw)` converts the JSON string into a Python dict. Each field is mapped into the `Intent` dataclass using `.get()` with defaults for any missing fields. Even if Sonnet omits a field, the resulting `Intent` object is still valid.

**`classify()` — Error Handling** — Everything is enclosed in a `try` block. If the API call fails or Sonnet returns invalid JSON, the error is caught, logged to the trace, and a low-confidence default `Intent` is returned. The low confidence tells the orchestrator that classification might be unreliable. The system degrades gracefully instead of crashing.

---

### 4.2 Data Agent

**`__init__`** — Takes the Anthropic client, the config, the tool registry, and the retrieval index (for SQL fallback). Also creates its own `SQLValidator` instance.

#### Parameter Extraction

**`extract_params()` — Purpose** — Once a tool is matched, its input parameters need to be filled. For example: `"Top 25 customers by margin this month"` requires `{period: 'mtd', n: 25}`. This method uses Opus to extract parameters from the query.

**`extract_params()` — Prompt** — Shows Opus the tool's input schema (parameter names, types, enums, defaults) and the user's query. Asks it to return a JSON mapping. This could be done with regex, but using Opus is easier and more reliable for complex extractions.

**`extract_params()` — Fallback** — If the Opus call fails for any reason, uses defaults from the tool schema and basic regex extraction instead of crashing.

#### Tool Execution Path

**`execute_tool()` — Overview** — The happy path. Tool matches the query --> extract parameters --> build invocation request --> execute. All steps are traced.

**Invocation Format** — The invocation dict contains: tool name with version, inputs, and user context (`user_id`, `region_whitelist`). In production, this would be sent to your actual tool runtime.

**Current Execution** — Returns the tool's SQL template from the manifest. In production, this gets swapped with actual database execution. The response structure contains: status, metadata (route, elapsed_ms), and evidence (manifest, semantic_objects).

**Return Pattern** — Every method returns `(result_dict, trace_list)`. This lets the orchestrator collect traces from all agents into one unified audit trail.

#### SQL Fallback Path

**`generate_sql()`** — When no tool matches, this method fetches similar examples from the training data, builds a constrained prompt, calls Opus, validates the output, and returns structured results.

**Retrieval** — `self.retrieval.retrieve(query)` calls the `RetrievalIndex`. Embeds the query, finds the 5 most similar training pairs via FAISS, and returns them with similarity scores. These become the few-shot examples that teach Opus the SQL patterns.

**System Prompt Construction** — The prompt has three parts:

1. **DATABASE SCHEMA** — So Opus knows what tables and columns exist
2. **RULES** — To constrain behavior (explicit JOINs, no hallucination, etc.)
3. **SIMILAR PAST QUERIES** — The retrieved training pairs showing how the SQL patterns work

**API Call** — `system=system_prompt` is separate from `messages`. The system prompt sets Opus's role and context; the user message is just the question. `temperature=0` ensures deterministic, reproducible SQL.

**Validation** — Before returning, the SQL passes through the `SQLValidator`. If any blocked patterns are found, the query is rejected. See the SQL Validator section above for details.

**Evidence & Cost Tracking** — `sql_fingerprint` detects identical queries without storing the full SQL. `examples_used` and `top_example_similarity` indicate how well the retrieval worked. Token counts and cost are calculated using Opus pricing ($15/M input, $75/M output at current rates).

---

### 4.3 Orchestrator Agent

**`__init__`** — Creates all components: loads config, creates the Anthropic client (reads API key from `.env`), builds the retrieval index, tool registry, user agent, and data agent. One client is shared across all agents.

**`initialize()`** — Separated from `__init__` because loading the FAISS index takes approximately one minute. The orchestrator is always created immediately, but heavy resources are only loaded when needed. The `_initialized` flag ensures this runs only once.

#### Processing Pipeline

**`process()` — Step 1: Request Setup** — Starts a timer, creates an empty trace list, generates a unique `request_id` using a hash of the query and timestamp. `user_context` would come from your auth system in production; defaults are used for now.

**`process()` — Step 2: Intent Classification** — Calls the User Agent to classify the intent. Receives an `Intent` object and trace steps. Steps are appended to the master trace.

**`process()` — Step 3: Routing** — The orchestrator logs the routing strategy, then asks the Tool Registry to find a match. This is the main decision point.

**`process()` — Step 4: Access Control** — If a tool matches, checks permissions before executing. The tool's `access_control.roles` is compared against the user's roles. Adds an extra layer of security.

**`process()` — Step 5: Execution** — Two possible branches:

1. **Tool matched** --> `execute_tool()`
2. **No match** --> `generate_sql()`

Both return `(result, trace)`. Both are wrapped in an `AgentResponse` object.

**`process()` — Step 6: Response Assembly** — Combines everything into one object: status, route taken, request_id, full data, SQL (if generated), evidence, complete trace from all agents, API cost, and elapsed time. Everything needed for debugging, auditing, and display is in one place.

---

### 4.4 Main Entry Point

**Argparse Setup** — Defines four command-line flags:

| Flag | Short | Purpose |
|------|-------|---------|
| `--interactive` | `-i` | Starts the REPL loop |
| `--eval` | `-e` | Runs the test suite |
| `--query` | `-q` | Processes a single query |
| `--config` | `-c` | Points to a different config file |

**Orchestrator Creation** — `Orchestrator(args.config)` creates the entire agent system. Heavy resource loading happens only when `.initialize()` is called.

**Interactive Mode** — An infinite loop that reads user input, processes it through the full pipeline, and displays results. `console.input()` shows a colored prompt. Empty inputs are skipped. `'exit'` / `'quit'` / `'q'` exits the loop.

**Single Query Mode** — Processes one query and exits. Useful for scripting.

**Default Mode** — Runs two demo queries that exercise both paths, one that matches a tool and one that triggers SQL generation.

---

## 5. Connecting Everything

When you type `python main.py -i` and enter a query, the following call chain executes:

```
main()
 └─ Orchestrator.__init__()
     └─ Creates all agents + loads config

 └─ Orchestrator.initialize()
     └─ RetrievalIndex.load()
         └─ Embeds 8,034 training pairs into FAISS index

 └─ Orchestrator.process(query)
     │
     ├─ UserAgent.classify()
     │   └─ Sonnet API --> Intent
     │
     ├─ ToolRegistry.match()
     │   └─ Keyword + semantic scoring
     │
     ├─ IF tool matched:
     │   └─ DataAgent.execute_tool()
     │       └─ extract_params() --> Opus API --> result
     │
     ├─ IF no tool:
     │   └─ DataAgent.generate_sql()
     │       ├─ Retrieve similar examples from training data
     │       ├─ Opus API --> SQL
     │       └─ SQLValidator.validate() --> security check
     │
     └─ AgentResponse
         └─ Assembled with full trace, evidence, cost, and timing
```