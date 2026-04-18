# Migration log

Tracks every schema change applied to `~/erp_model.db`. One section per
migration script in `migrations/`. Every migration is idempotent and
preceded by a backup to `~/erp_model.db.bak-preN`.

Rollback command template (all migrations):
```sh
mv ~/erp_model.db.bak-preN ~/erp_model.db
```

---

## 001_multi_market (Phase 0, 2026-04-18)

**Goal.** Add `market` to every data table (default `'US'`), prepare composite
primary keys, add provenance columns, and create the `update_runs` audit
table — without touching any Python call-site.

**Backup.** `cp ~/erp_model.db ~/erp_model.db.bak-pre0` before any ALTER.
**Rollback.** `mv ~/erp_model.db.bak-pre0 ~/erp_model.db`.

**Run.**
```sh
python migrations/001_multi_market.py                  # real run
python migrations/001_multi_market.py --dry-run        # report only
python migrations/001_multi_market.py --db /path.db    # explicit DB
```

### SQL diffs

#### `erp_inputs`

Added columns (via `ALTER TABLE … ADD COLUMN …`):

| Column         | Type     | Default |
|----------------|----------|---------|
| `market`       | TEXT     | `'US'` (NOT NULL) |
| `currency`     | TEXT     | `'USD'` (NOT NULL) |
| `index_source` | TEXT     | NULL |
| `rfr_source`   | TEXT     | NULL |
| `divy_source`  | TEXT     | NULL |
| `fetched_at`   | INTEGER  | NULL (backfilled from `updated_at`) |
| `stale_flag`   | INTEGER  | `0` (NOT NULL) |
| `quality_notes`| TEXT     | NULL |

Primary key rebuilt: `PRIMARY KEY (date)` → `PRIMARY KEY (date, market)`.
(SQLite can't `ALTER` a PK, so the table is rebuilt via rename + create +
`INSERT … SELECT` + drop. All within a single transaction.)

New indexes:
- `idx_inputs_market_date` on `(market, date DESC)` — latest-by-market.
- `idx_inputs_date` on `(date)` — cross-market slice at a date.

#### `erp_computations`

Added columns:

| Column          | Type | Default |
|-----------------|------|---------|
| `market`        | TEXT | `'US'` (NOT NULL) |
| `model_version` | TEXT | `'v1'` (NOT NULL) |

Primary key rebuilt: `(date, method)` → `(date, market, method)`.

New indexes: `idx_comp_market_date`, `idx_comp_date`.

#### `erp_forecasts`

Added column: `market TEXT NOT NULL DEFAULT 'US'`.
New index: `idx_fc_market_base` on `(market, base_date, scenario)`.

#### `erp_breakeven`

Added column: `market TEXT NOT NULL DEFAULT 'US'`.
New index: `idx_be_market_date` on `(market, date DESC)`.

#### `calculation_log`

Added columns: `market TEXT` (nullable — global events have NULL market),
`level TEXT NOT NULL DEFAULT 'INFO'`.
New index: `idx_log_market_date` on `(market, created_at DESC)`.

#### `update_runs` (new)

Audit one row per `update_markets.py` (or migration) invocation.

```sql
CREATE TABLE update_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    INTEGER NOT NULL,
    finished_at   INTEGER,
    markets       TEXT NOT NULL,      -- JSON array, e.g. ["US","UK"]
    status_json   TEXT NOT NULL,      -- JSON object, e.g. {"US":"ok"}
    git_sha       TEXT,
    model_version TEXT
);
```

### Deferred to Phase 1

Column renames (`sp500_level → index_level`, `tbond_10yr_rate → rfr_rate`,
`sp500_projected → index_projected`) are *not* applied here. They break
Python callers and so must land together with `database.py` / `server.py`
edits — that is Phase 1 work.

### Verification

After applying:

```sh
sqlite3 ~/erp_model.db ".schema erp_inputs"        # shows market column
sqlite3 ~/erp_model.db "SELECT COUNT(*) FROM erp_inputs;"     # = 68
sqlite3 ~/erp_model.db "SELECT COUNT(*) FROM erp_computations;"  # = 68
sqlite3 ~/erp_model.db "SELECT DISTINCT market FROM erp_inputs;" # = US
python3 server.py &        # server starts
curl -s http://127.0.0.1:5001/api/history | head -c 500   # returns 65y of points
```
