# ERP Model — Quick Start Guide

## 30 Second Setup

### Option A: Using bash script (recommended)
```bash
cd "/sessions/eager-upbeat-darwin/mnt/ERP Model"
./start_server.sh
```

### Option B: Direct Python
```bash
cd "/sessions/eager-upbeat-darwin/mnt/ERP Model"
python server.py
```

You should see:
```
╔══════════════════════════════════════════════════╗
║    ERP Model Server  →  http://localhost:5001    ║
║    Open erp_dashboard.html in your browser       ║
║    Press Ctrl+C to stop                          ║
╚══════════════════════════════════════════════════╝
```

## Open the Dashboard

**Open in your browser:** `erp_dashboard.html` (in the same directory)

Or open directly from file:
```
file:///sessions/eager-upbeat-darwin/mnt/ERP Model/erp_dashboard.html
```

You should see a **green banner** saying "Connected to ERP server at localhost:5001". If you see a red banner, the server isn't running — go back to Step 1.

## What You Can Do

- **View historical ERP** — 65 years of annual data (1961–2025)
- **See current metrics** — S&P 500, dividend yield, cost of equity, etc.
- **Update with live data** — Fetch current market prices with one click
- **Scenario analysis** — Change inputs and see implied ERP immediately
- **Download data** — Export history to CSV

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot reach server" | Make sure `python server.py` is still running. Don't close the terminal. |
| Blank page or no data | Hard refresh (Ctrl+Shift+R or Cmd+Shift+R), then wait a few seconds. |
| "Connection refused" | The server crashed. Check the terminal for error messages, then run `python server.py` again. |
| Want a different port | Run `python server.py 8000` to use port 8000. Then update `src/api.ts` and rebuild. |

## For Help

- **Dashboard setup:** See [FLASK_SERVER.md](FLASK_SERVER.md)
- **CLI & data science:** See [README.md](README.md)
- **API reference:** See [FLASK_SERVER.md#api-endpoints](FLASK_SERVER.md#api-endpoints)

## The Model

This is a browser-based **Damodaran 2-Stage Augmented DDM** model. It computes the **forward-looking Equity Risk Premium** by solving:

```
S&P_level = Σ [Cash_Flow_t / (1+r)^t] + Terminal_Value / (1+r)^5
```

for the discount rate `r`, then ERP = r − risk_free_rate.

**Data sources (all free):**
- S&P 500 level → Yahoo Finance
- Dividend yield → Yahoo Finance
- Analyst growth → Yahoo Finance
- 10-yr T-bond → FRED or Yahoo Finance
- Historical data → Damodaran's published spreadsheet

**Database:** SQLite at `~/erp_model.db` (seeded with 65 years)

---

**That's it!** You're ready to analyze equity risk premiums. Enjoy!
