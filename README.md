# Forward-Looking Equity Risk Premium Model
### Based on Damodaran (NYU Stern) 2-Stage Augmented DDM Methodology

---

## What This Model Does

This model computes the **implied Equity Risk Premium (ERP)** for the US market by solving for the discount rate that equates the current S&P 500 level with the present value of projected future cash flows.

The methodology is directly based on [Aswath Damodaran's implied ERP framework](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/RiskPrem.htm) from NYU Stern. It requires **no historical return data** and produces a **forward-looking, market-implied** estimate of the premium investors are demanding above the risk-free rate.

---

## The Math

```
S&P_level = Σ [CF_t / (1+r)^t]  for t = 1..5  +  TV / (1+r)^5

CF_1  = S&P_level × (div_yield + buyback_yield) × (1 + g_high)
CF_t  = CF_{t-1} × (1 + g_high)
TV    = CF_5 × (1 + g_stable) / (r - g_stable)

g_high   = analyst consensus 5-year earnings growth
g_stable = 10-year T-bond rate  [Damodaran's key assumption]
r        = solve numerically (Newton-Raphson + Brent's method fallback)

Implied ERP = r − T-bond rate
```

---

## Files

| File | Purpose |
|------|---------|
| `config.py` | All parameters, API keys, paths |
| `database.py` | SQLite persistence (inputs, computed ERPs, audit log) |
| `data_fetcher.py` | Free-tier data: Yahoo Finance + FRED API |
| `erp_calculator.py` | 2-stage DDM solver — the core math engine |
| `visualization.py` | Charts and text reports |
| `main.py` | CLI entry point |
| `seed_historical.py` | One-time historical seeder (1961–2025 from Damodaran's spreadsheet) |
| `histimpl_cache.xls` | Cached copy of Damodaran's histimpl.xls |

**Database:** Stored at `~/erp_model.db` by default. Override with `ERP_DB_PATH` env variable.

**Charts & exports:** Saved to `output/` directory.

---

## Browser Dashboard (Interactive)

For a browser-based dashboard with real-time charts and scenario analysis:

1. **Start the Flask API server:**
   ```bash
   python server.py
   ```

2. A browser tab opens automatically at `http://localhost:5001`. The
   dashboard talks to the local server over `/api/...` relative paths,
   so no separate page-open step is needed.

For troubleshooting, setup help, and API documentation, see **[FLASK_SERVER.md](FLASK_SERVER.md)**.

---

## Sharing With Colleagues

Two ready-made paths, depending on what your colleagues need.

### Option A — Read-only nightly snapshot (zero setup for the audience)

The repo already ships a static snapshot site at `docs/` and a nightly
workflow (`.github/workflows/snapshot.yml`) that refreshes all 9
markets and pushes the JSON to `docs/data/`.

To publish:

1. In GitHub, go to **Settings → Pages**.
2. Source: **Deploy from a branch**.
3. Branch: `main`, folder: `/docs`. Save.
4. After ~1 minute, your colleagues can open
   `https://<owner>.github.io/erp-model/` — no install, no terminal,
   always reflects the latest nightly snapshot.

The page includes an in-browser **scenario calculator**: viewers can
click any market card to load that market's inputs (index level, total
yield or trailing EPS, 5yr growth, 10yr risk-free), tweak them, and see
the implied ERP recompute live. The solver runs entirely client-side
(`docs/erp-solver.js`, a vanilla-JS port of the Damodaran 2-stage DDM),
so no data leaves the browser and the API is never exposed publicly.

Live data refresh isn't possible from the static page (the nightly
GitHub Actions workflow handles that); for on-demand refresh use
Option B below.

### Option B — Run the interactive server locally

Each colleague who needs scenario analysis or on-demand refresh runs:

```bash
git clone <repo-url> && cd erp-model
pip install -r requirements.txt
python seed_historical.py --market US
python server.py
```

The server binds to `0.0.0.0:5001` by default, so a single person on
the team LAN can also share their session: have colleagues open
`http://<that-machine-ip>:5001`. **Note:** there is no authentication
in front of the API — only do this on a trusted network.

For Windows / Linux colleagues: the `--auto-update` launchd toggle is
macOS-only, but everything else (live refresh, scenarios, history,
charts, CSV export) works cross-platform. For scheduled refreshes off
macOS, use the GitHub Actions snapshot workflow (Option A) or your
OS's native scheduler (Task Scheduler / cron) to run
`python main.py --update --all-markets`.

---

## Command-Line Usage (CLI)

For batch processing and scheduled updates, use the CLI:

### 1. Install dependencies

```bash
pip install yfinance fredapi scipy matplotlib pandas xlrd
```

### 2. (Optional) Get a free FRED API key

Register at https://fred.stlouisfed.org/docs/api/api_key.html — takes 30 seconds.
Without it, the 10-year Treasury rate falls back to Yahoo Finance's `^TNX`.

```bash
export FRED_API_KEY="your_key_here"
```

### 3. Seed historical data (one time only)

```bash
python seed_historical.py
```

This loads 65 years of annual data (1961–2025) from Damodaran's published spreadsheet into your local database.

---

## Usage

### Update with latest market data

```bash
python main.py --update
```

Fetches current S&P 500 level, dividend yield, 10-year T-bond rate, and analyst growth estimates, then computes and stores the implied ERP.

### Print current ERP report

```bash
python main.py --report
```

### Generate charts

```bash
python main.py --plot
```

Saves two PNGs to `output/`:
- `erp_history.png` — Implied ERP over time with mean/σ bands
- `inputs_dashboard.png` — 4-panel view of all input variables

### Full workflow (recommended for monthly updates)

```bash
python main.py --update --report --plot --export
```

### Override specific inputs

```bash
# Use a specific buyback yield (e.g. when S&P publishes quarterly buyback data)
python main.py --update --buyback 0.025

# Override analyst growth estimate
python main.py --update --growth 0.08

# Backfill a specific date
python main.py --update --as-of 2024-06-30

# Both overrides
python main.py --update --buyback 0.022 --growth 0.075
```

### Validate solver against Damodaran's 1999 published example

```bash
python main.py --validate
```

Expected output:
```
Dividends only: Implied ERP = 2.09%  (Damodaran: ~2.10%)
```

### View database history

```bash
python main.py --history     # last 20 records
python main.py --log         # audit trail
python main.py --export      # save to output/erp_history.csv
```

---

## Data Sources (All Free)

| Input | Source | Notes |
|-------|---------|-------|
| S&P 500 level | Yahoo Finance `^GSPC` | Real-time |
| Dividend yield | Yahoo Finance `SPY` | Trailing 12-month |
| 10-yr T-bond rate | FRED `DGS10` (primary) | Requires free API key |
| 10-yr T-bond rate | Yahoo Finance `^TNX` (fallback) | No key needed |
| Analyst 5yr growth | Yahoo Finance `SPY` / top holdings | Proxied from ETF/constituent data |
| Buyback yield | Configurable default (2.0%) | S&P publishes quarterly; override with `--buyback` |

---

## Update Cadence

Damodaran updates his model **annually** (as of January 1). You can run this model:

- **Monthly** — captures rate moves and yield changes, lower signal
- **Quarterly** — good balance; aligns with earnings season
- **Annually** — matches Damodaran's own update frequency for direct comparison

---

## Interpreting the Output

| ERP Level | Interpretation |
|-----------|---------------|
| < 3% | Market is expensive relative to bonds; low margin of safety |
| 3–4% | Below historical average (~4.3% since 1961) |
| 4–5% | Near historical average — fairly priced |
| 5–6% | Above average — market offers above-average risk compensation |
| > 6% | High — historically associated with market stress or dislocation |

**Historical stats (1961–2025):**
- Mean ERP: ~4.3%
- Std Dev: ~1.4%
- Min: ~1.6% (1998 — dot-com peak)
- Max: ~8.2% (2008 — financial crisis)

---

## Known Limitations

1. **Buyback yield** — the hardest input. S&P publishes actual buyback data quarterly (for free via their website), but it lags by a quarter. The default 2% is conservative. Override with `--buyback` when you have the actual figure.

2. **Analyst growth estimates** — proxied from Yahoo Finance's SPY/constituent data. Damodaran uses a proprietary consensus from FactSet. Deviations of 1–3% in the growth input translate to ~20–50bp ERP difference.

3. **Model assumes market is correctly priced** — this is an implied, not a predicted, ERP. If the market is irrationally priced, the model reflects that.

4. **Stable growth = risk-free rate** — Damodaran's key assumption. This ties the terminal value directly to the T-bond rate and is appropriate for a mature, developed market.

5. **DDM vs FCFE** — Damodaran's primary published number uses an FCFE-based model (net income × payout ratio). Our model uses the DDM (dividends + buybacks). Expect our ERP to be 20–50bp below his published figure for recent years.

---

## Reference

Damodaran, A. "Equity Risk Premiums: Determinants, Estimation and Implications."  
https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/RiskPrem.htm  
Updated annually at: https://pages.stern.nyu.edu/~adamodar/pc/datasets/histimpl.xls
