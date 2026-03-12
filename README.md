# Enterprise Agent — Setup & Running Guide

## Quick Start 

### 1. Project Structure

```
enterprise-agent/
├── main.py                  # Entry Point with multiple modes of running
├──/ core
  ├── __init__               # Initializes core 
  ├── config.py              # Reads from config file
  ├── data_agent.py          # Defines the data agent class
  ├── models.py              # Defines the data classes used 
  ├── orchestrator.py        # Defines the orchestrator class
  ├── retrieval.py           # Retrieval index for few-shot example selection.
  ├── sql_validator.py       # Defines the validator class
  ├── tool_registry.py       # Tool matching for semantic first matching
  ├── user_agent.py          # Defines the user agent class
├──/ utils
  ├── __init__               # Initializes utils 
  ├── display.py             # Defines the rich output display
├── config.yaml              # Agent models, tools, schema, security
├── requirements.txt         # Python dependencies
├── .env                     # API key 
├── spider_text_sql 2.csv    # Data with text to SQL pairs
└── schema.sql               # (Optional) full database schema
```

### 2. Setup

```bash
# Create project directory
mkdir enterprise-agent && cd enterprise-agent

# Copy main.py, config.yaml, requirements.txt, and your CSV into this folder

mkdir core utils

# Copy all files in the correct folders 

# Create virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Set your API key
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" > .env
```

### 3. Run

```bash
# Interactive mode (recommended to start)
python main.py --interactive

# Single query
python main.py --query "Who are our top 10 customers by margin?"

# Run evaluation suite
python main.py --eval

# Default demo (runs two example queries)
python main.py
```

## What Happens When You Run It

**First run** will take 1-2 minutes to:
1. Load data pairs from CSV
2. Download the embedding model (~400MB for bge-base, cached after first download)
3. Embed all training queries and build the FAISS index

**Subsequent runs** still re-embed on startup (takes ~30 seconds). For production, you'd save the index to disk (see "Production Optimizations" below).

**Each query** then goes through:
```
You: "Who are our top 25 customers by margin this month?"
  ■ user_agent → intent_classified: type=ranking | entities=[customers, margin]
  ■ orchestrator → routing: semantic_first → sql_fallback
  ■ data_agent → tool_matched: orders.top_customers@2.1.0 (score: 0.78)
  ■ data_agent → params_extracted: {"period": "mtd", "n": 25}
  ■ data_agent → tool_invoked: semantic query executed
  ■ orchestrator → response_formatted

Route: semantic_first | Elapsed: 1,240ms | Cost: $0.003
```

```
You: "Find all orders over $10K with a discount above 15%"
  ■ user_agent → intent_classified: type=list_filter | entities=[orders, discount]
  ■ orchestrator → routing: no tool match → sql_fallback
  ■ data_agent → examples_retrieved: 5 similar queries found
  ■ data_agent → sql_generated:
    SELECT o.order_id, o.order_amount, oi.discount, c.customer_name
    FROM fct_orders o
    JOIN fct_order_items oi ON o.order_id = oi.order_id
    JOIN dim_customer c ON o.customer_id = c.customer_id
    WHERE o.order_amount > 10000
      AND oi.discount > 0.15
      AND o.order_status = 'completed'
    ORDER BY o.order_amount DESC
    LIMIT 100;
  ■ data_agent → validation_passed: Syntax ✓ | Security ✓

Route: sql_fallback | Elapsed: 3,800ms | Cost: $0.0045
```

## Customizing for Your Database

### Update the Schema
Edit `config.yaml` → `schema.inline` with your actual CREATE TABLE statements. Or point `schema.schema_file` to a .sql file:

```yaml
schema:
  dialect: "postgresql"
  schema_file: "my_warehouse_schema.sql"
```

Include column comments for ambiguous names — this significantly improves SQL accuracy.

### Add Your Tools
Each tool in `config.yaml` represents a trusted business query. Add tools for your common queries:

```yaml
- name: "finance.monthly_burn_rate"
  version: "1.0.0"
  summary: "Monthly cash burn rate by department"
  inputs:
    period: { type: string, default: last_3m }
    department: { type: string, default: all }
  semantic_binding:
    metrics: [burn_rate, spend]
    dimensions: [department, time]
  keywords: [burn rate, spend, cost, expenses, budget, monthly spend]
  access_control:
    roles: [finance_team, executive]
  sql_fallback: |
    SELECT department, DATE_TRUNC('month', txn_date) AS month,
           SUM(amount) AS burn_rate
    FROM fct_transactions
    WHERE txn_type = 'expense'
    GROUP BY 1, 2
    ORDER BY month, burn_rate DESC
```

### Adjust Models
If you want to reduce costs during development, swap Opus for Sonnet in the data agent:

```yaml
models:
  data_agent:
    model: "claude-sonnet-4-5-20250929"    # cheaper for testing
    max_tokens: 2048
    temperature: 0
```

Switch back to `claude-opus-4-6` for production accuracy.

## Production Optimizations

### 1. Persist the FAISS Index
Avoid re-embedding on every startup:

```python
# Save after first build
faiss.write_index(index, "training_index.faiss")
np.save("training_embeddings.npy", embeddings)

# Load on subsequent runs
index = faiss.read_index("training_index.faiss")
```

### 2. Add Caching
Cache Opus responses for repeated queries:

```python
import hashlib, shelve

def cached_generate(query, cache_path="sql_cache"):
    key = hashlib.sha256(query.lower().strip().encode()).hexdigest()
    with shelve.open(cache_path) as cache:
        if key in cache:
            return cache[key]
        result = generate_sql(query)  # Opus API call
        cache[key] = result
        return result
```

### 3. Connect to Your Database
Add actual execution after SQL generation:

```python
import psycopg2  # or your DB driver

def execute_sql(sql: str, conn_string: str) -> dict:
    conn = psycopg2.connect(conn_string)
    cur = conn.cursor()
    cur.execute(f"EXPLAIN {sql}")  # Validate query plan first
    plan = cur.fetchall()
    cur.execute(sql)               # Execute
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    conn.close()
    return {"columns": columns, "rows": rows, "row_count": len(rows)}
```

### 4. Add the Feedback Loop
Log user corrections to improve over time:

```python
def log_correction(original_query, bad_sql, corrected_sql, csv_path="corrections.csv"):
    """When a user says 'that SQL is wrong', log the correction."""
    pd.DataFrame([{
        "text_query": original_query,
        "sql_command": corrected_sql,
        "source": "user_correction",
        "timestamp": datetime.now().isoformat()
    }]).to_csv(csv_path, mode="a", header=not os.path.exists(csv_path), index=False)
    # Periodically merge corrections into main training data and rebuild index
```

## Cost Estimates

| Usage Pattern | Queries/Day | Route Split | Est. Daily Cost |
|--------------|-------------|-------------|----------------|
| Light (dev/testing) | 50 | 60% tool / 40% SQL | ~$0.50 |
| Moderate (team of analysts) | 500 | 50% tool / 50% SQL | ~$4-6 |
| Heavy (org-wide) | 5,000 | 40% tool / 60% SQL | ~$35-50 |

Tool-matched queries cost ~$0.002 (only the User Agent Sonnet call). SQL fallback queries cost ~$0.004-0.008 (Sonnet + Opus calls). The routing optimization means your most common queries (which should be covered by tools) are the cheapest.

## Troubleshooting

**"ModuleNotFoundError: sentence_transformers"**
→ Make sure you activated your venv: `source venv/bin/activate`

**First run is slow (~2 min)**
→ Normal — downloading embedding model + building FAISS index. See "Persist the FAISS Index" above.

**"AuthenticationError" from Anthropic**
→ Check your `.env` file has `ANTHROPIC_API_KEY=sk-ant-...` (no quotes around the key).

**SQL validation fails on valid queries**
→ The blocked patterns use word-boundary matching but may false-positive on column names like `updated_at`. Adjust `security.blocked_sql_patterns` in config.yaml.

**Low tool match rates**
→ Add more keywords to your tool manifests. The matcher uses keyword overlap — more keywords = better recall.
