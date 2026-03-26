"""
Database Manager — PostgreSQL setup and seeding.

Creates the schema on first run, seeds with realistic sample data,
and exposes a single execute() method for query execution downstream.

Follows the same lazy-init pattern as RetrievalIndex: setup() is called
once by Orchestrator.initialize() and skips seeding if tables already exist.

Connection
----------
Non-sensitive settings (host, port, dbname, user) live in config.yaml.
The password is read from the DB_PASSWORD environment variable, which
should be set in your .env file (loaded by main.py via dotenv).
"""

import os
import re
import random
from datetime import datetime, timedelta

import psycopg2
import psycopg2.extras
from rich.console import Console

from core.config import Config

console = Console()

# psycopg2 uses %(name)s for named parameters.
# The rest of the system (tool fallbacks, generated SQL) uses :name style.
# This regex converts at execute() time — it is a driver adapter, not a
# dialect translation, and stays unchanged when moving to any environment.
#
# The negative lookbehind (?<!:) is essential: without it, the regex would
# match the second colon in PostgreSQL ::date casts, turning ::date into
# :%(date)s which breaks the query. The lookbehind ensures we only match
# a single leading colon, never the second colon of a :: cast.
_RE_NAMED_PARAM = re.compile(r"(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)")


class DatabaseManager:
    def __init__(self, config: Config):
        self.config = config
        db_cfg = config.database
        self.host     = db_cfg.get("host",   "localhost")
        self.port     = db_cfg.get("port",   5432)
        self.dbname   = db_cfg.get("dbname", "enterprise")
        self.user     = db_cfg.get("user",   "postgres")
        self.password = os.environ.get("DB_PASSWORD", "")
        self.conn: psycopg2.extensions.connection = None
        self._ready = False

    # ── Initialization ────────────────────────────────────────────

    def setup(self):
        """
        Entry point called by Orchestrator.initialize().

        Connects to PostgreSQL, creates tables if they don't exist,
        and seeds sample data on first run (detected by empty fct_orders).
        """
        if self._ready:
            return

        console.log(
            f"[bold blue]▸ Database Manager[/] — connecting to "
            f"{self.user}@{self.host}:{self.port}/{self.dbname}..."
        )

        try:
            self.conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
            )
            self.conn.autocommit = False
        except psycopg2.OperationalError as e:
            raise RuntimeError(
                f"Could not connect to PostgreSQL at {self.host}:{self.port}. "
                f"Is the database running? (docker compose up -d)\n\nOriginal error: {e}"
            ) from e

        self._create_schema()

        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM fct_orders")
            row_count = cur.fetchone()[0]

        if row_count == 0:
            self._seed()
            console.log(f"[bold green]✓ Database seeded:[/] {self.dbname}")
        else:
            console.log(
                f"[bold green]✓ Database ready:[/] {self.dbname} "
                f"({row_count:,} existing orders)"
            )

        self._ready = True

    def _create_schema(self):
        """
        Create all tables and indexes if they don't already exist.

        Uses IF NOT EXISTS so this is safe to run on every startup —
        it's a no-op when the schema is already in place.
        """
        ddl = """
        CREATE TABLE IF NOT EXISTS dim_customer (
            customer_id   SERIAL PRIMARY KEY,
            customer_name VARCHAR(100) NOT NULL,
            segment       VARCHAR(50)  NOT NULL,
            region        VARCHAR(50)  NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dim_product (
            product_id   SERIAL PRIMARY KEY,
            product_name VARCHAR(100)  NOT NULL,
            category     VARCHAR(50)   NOT NULL,
            unit_price   DECIMAL(10,2) NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fct_orders (
            order_id         SERIAL PRIMARY KEY,
            customer_id      INT           NOT NULL REFERENCES dim_customer(customer_id),
            order_amount     DECIMAL(12,2) NOT NULL,
            cogs             DECIMAL(12,2) NOT NULL,
            order_status     VARCHAR(20)   NOT NULL,
            order_timestamp  TIMESTAMP     NOT NULL
        );

        CREATE TABLE IF NOT EXISTS fct_order_items (
            order_id   INT           NOT NULL REFERENCES fct_orders(order_id),
            product_id INT           NOT NULL REFERENCES dim_product(product_id),
            quantity   INT           NOT NULL,
            discount   DECIMAL(5,2)  NOT NULL DEFAULT 0.0,
            PRIMARY KEY (order_id, product_id)
        );

        CREATE INDEX IF NOT EXISTS idx_orders_customer
            ON fct_orders(customer_id);
        CREATE INDEX IF NOT EXISTS idx_orders_timestamp
            ON fct_orders(order_timestamp);
        CREATE INDEX IF NOT EXISTS idx_orders_status
            ON fct_orders(order_status);
        CREATE INDEX IF NOT EXISTS idx_items_product
            ON fct_order_items(product_id);
        """
        with self.conn.cursor() as cur:
            cur.execute(ddl)
        self.conn.commit()
        console.log("  → Schema ready (4 tables, 4 indexes)")

    def _seed(self):
        """
        Populate all tables with realistic sample data.

        Volumes match a typical mid-size enterprise:
          50   customers  (mix of segments and regions)
          25   products   (across 5 categories)
          2000 orders     (spread across the past 12 months)
          ~5   items per order on average
        """
        random.seed(42)   # reproducible data

        # ── dim_customer ─────────────────────────────────────────
        segments = ["Enterprise", "SMB", "Consumer"]
        regions  = ["NA", "EU", "APAC", "LATAM"]
        first_names = [
            "Acme", "Globex", "Initech", "Umbrella", "Cyberdyne",
            "Soylent", "Stark", "Wayne", "Oscorp", "Massive",
            "Pinnacle", "Apex", "Nexus", "Vertex", "Zenith",
            "Atlas", "Horizon", "Meridian", "Solstice", "Vanguard",
        ]
        last_names = [
            "Corp", "Industries", "Group", "Holdings", "Partners",
            "Solutions", "Systems", "Technologies", "Ventures", "Dynamics",
        ]
        customers = [
            (f"{random.choice(first_names)} {random.choice(last_names)}",
             random.choice(segments),
             random.choice(regions))
            for _ in range(50)
        ]
        with self.conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO dim_customer (customer_name, segment, region) VALUES %s",
                customers,
            )
        console.log(f"  → {len(customers)} customers seeded")

        # ── dim_product ──────────────────────────────────────────
        catalogue = [
            ("Analytics Suite",    "Software",  1200.00),
            ("Data Connector",     "Software",   450.00),
            ("Cloud Storage Pro",  "Software",   299.00),
            ("API Gateway",        "Software",   799.00),
            ("ML Platform",        "Software",  3500.00),
            ("Laptop Pro 15",      "Hardware",  1899.00),
            ("Workstation Elite",  "Hardware",  3200.00),
            ("Server Rack Unit",   "Hardware",  8500.00),
            ("Network Switch 48p", "Hardware",  1100.00),
            ("UPS 2000VA",         "Hardware",   650.00),
            ("Support Basic",      "Services",   199.00),
            ("Support Premium",    "Services",   599.00),
            ("Implementation",     "Services",  4500.00),
            ("Training Package",   "Services",   899.00),
            ("Consulting Day",     "Services",  1500.00),
            ("Desk Chair Ergo",    "Furniture",  450.00),
            ("Standing Desk",      "Furniture",  799.00),
            ("Monitor 32in 4K",    "Furniture",  699.00),
            ("Conference Table",   "Furniture", 1200.00),
            ("Storage Cabinet",    "Furniture",  350.00),
            ("Office Bundle S",    "Bundles",   2499.00),
            ("Office Bundle M",    "Bundles",   4999.00),
            ("Office Bundle L",    "Bundles",   8999.00),
            ("Starter Pack",       "Bundles",    999.00),
            ("Enterprise Pack",    "Bundles",  14999.00),
        ]
        with self.conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO dim_product (product_name, category, unit_price) VALUES %s",
                catalogue,
            )
        console.log(f"  → {len(catalogue)} products seeded")

        # ── fct_orders + fct_order_items ─────────────────────────
        # Fetch the auto-assigned IDs so foreign keys are correct
        with self.conn.cursor() as cur:
            cur.execute("SELECT product_id, unit_price FROM dim_product ORDER BY product_id")
            # psycopg2 returns DECIMAL columns as Python Decimal objects.
            # Convert to float here because downstream arithmetic (discount,
            # cogs multiplier) uses floats, and Decimal + float raises TypeError.
            products = [(pid, float(price)) for pid, price in cur.fetchall()]
            cur.execute("SELECT customer_id FROM dim_customer ORDER BY customer_id")
            customer_ids = [r[0] for r in cur.fetchall()]

        statuses = ["completed", "completed", "completed", "pending", "cancelled"]
        now      = datetime.now()
        orders   = []
        items    = []

        for _ in range(2000):
            customer_id = random.choice(customer_ids)
            days_ago    = min(int(random.expovariate(1 / 90)), 365)
            ts = now - timedelta(
                days=days_ago,
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            status       = random.choice(statuses)
            chosen       = random.sample(products, k=random.randint(1, 8))
            order_amount = 0.0
            cogs_total   = 0.0
            line_items   = []

            for pid, unit_price in chosen:
                qty      = random.randint(1, 10)
                discount = round(random.choice([0, 0, 0, 0.05, 0.10, 0.15, 0.20]), 2)
                line_val = unit_price * qty * (1 - discount)
                order_amount += line_val
                cogs_total   += line_val * random.uniform(0.45, 0.70)
                line_items.append((pid, qty, discount))

            orders.append((customer_id, round(order_amount, 2), round(cogs_total, 2), status, ts))
            items.append(line_items)

        # Insert orders and capture generated order_ids.
        # fetch=True is critical: without it, execute_values batches inserts
        # into pages (default page_size=100) and RETURNING only captures the
        # last page. With fetch=True, psycopg2 accumulates RETURNING results
        # from ALL pages, so we get all 2000 order_ids for the item insert.
        with self.conn.cursor() as cur:
            returned = psycopg2.extras.execute_values(
                cur,
                """INSERT INTO fct_orders
                   (customer_id, order_amount, cogs, order_status, order_timestamp)
                   VALUES %s RETURNING order_id""",
                orders,
                fetch=True,
            )
            order_ids = [r[0] for r in returned]

        # Insert order items using the returned order_ids
        flat_items = [
            (order_id, pid, qty, discount)
            for order_id, line_items in zip(order_ids, items)
            for pid, qty, discount in line_items
        ]
        with self.conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                "INSERT INTO fct_order_items (order_id, product_id, quantity, discount) VALUES %s",
                flat_items,
            )

        self.conn.commit()
        console.log(f"  → {len(orders):,} orders seeded ({len(flat_items):,} line items)")

    # ── Query execution ───────────────────────────────────────────

    def execute(self, sql: str, params: dict = None) -> list[dict]:
        """
        Execute a validated SELECT query and return rows as a list of dicts.

        Converts :name parameter style (used throughout config.yaml and
        generated SQL) to psycopg2's %(name)s style before execution.
        This is a driver adapter, not a dialect change.

        The negative lookbehind in _RE_NAMED_PARAM ensures ::date style
        PostgreSQL casts are never touched during this conversion.

        Args:
            sql:    Validated SQL string (SELECT or WITH only)
            params: Optional named parameters (:name style)

        Returns:
            List of row dicts, capped at security.max_rows_returned
        """
        if not self._ready:
            raise RuntimeError("DatabaseManager.setup() must be called before execute()")

        params   = params or {}
        max_rows = self.config.security.get("max_rows_returned", 10_000)

        # :name → %(name)s  (psycopg2 named parameter syntax)
        # Negative lookbehind prevents touching ::date, ::integer etc.
        adapted_sql = _RE_NAMED_PARAM.sub(r"%(\1)s", sql)

        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(adapted_sql, params)
            rows = cur.fetchmany(max_rows)

        return [dict(row) for row in rows]

    def close(self):
        """Close the database connection. Call on shutdown."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self._ready = False