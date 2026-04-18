# Flask API Server Guide

This guide explains how to run the local Flask API server and connect the browser-based dashboard.

---

## Quick Start

### 1. Start the Flask server

```bash
python server.py
```

You should see:
```
╔══════════════════════════════════════════════════╗
║    ERP Model Server  →  http://localhost:5001    ║
║    Open erp_dashboard.html in your browser       ║
║    Press Ctrl+C to stop                          ║
╚══════════════════════════════════════════════════╝

 * Running on http://127.0.0.1:5001
```

### 2. Open the dashboard

Open `erp_dashboard.html` in your web browser. The HTML file will automatically connect to the server at `http://localhost:5001`.

If you see a green banner saying "Connected to ERP server at localhost:5001", the connection is working.

---

## Troubleshooting

### "Cannot reach server" error

**Cause:** The Flask server is not running on port 5001.

**Solution:**
1. Make sure `python server.py` is running in a terminal
2. Do not close the terminal where the server is running
3. Check that nothing else is using port 5001:
   ```bash
   lsof -i :5001   # macOS/Linux
   netstat -ano | findstr :5001   # Windows
   ```

### "Connection refused" error

**Cause:** The server crashed or wasn't started properly.

**Solution:**
1. Check the terminal where you ran `python server.py` for error messages
2. Make sure you're in the correct directory: `/sessions/eager-upbeat-darwin/mnt/ERP Model/`
3. Try again: `python server.py`

### Browser shows blank page or console errors

**Cause:** The HTML file may not have loaded properly, or JavaScript is disabled.

**Solution:**
1. Ensure JavaScript is enabled in your browser
2. Open the browser's Developer Tools (F12 or Cmd+Option+I)
3. Check the Console tab for error messages
4. Refresh the page (Ctrl+R or Cmd+R)

### Server runs but dashboard shows "Waiting…" forever

**Cause:** Usually a CORS (Cross-Origin Resource Sharing) issue if opening the HTML from `file://` protocol.

**Solution:**
1. The server is configured to allow file:// origins (Origin: null)
2. Try a hard refresh: Ctrl+Shift+R (Windows/Linux) or Cmd+Shift+R (Mac)
3. Clear browser cache and try again
4. If still failing, check the browser console (F12) for specific error messages

---

## API Endpoints

All endpoints are at `http://localhost:5001/api/`:

### GET Endpoints

| Endpoint | Purpose | Example Response |
|----------|---------|-----------------|
| `/api/status` | Health check | `{"ok": true, "message": "...", "date": "2026-04-11"}` |
| `/api/latest` | Most recent computation | `{"ok": true, "data": {...}}` |
| `/api/history?start=2020-01-01&end=2025-12-31` | Time-series data with optional date filters | `{"ok": true, "data": [...], "count": 65}` |
| `/api/stats` | Summary statistics (mean, std, min, max ERP) | `{"ok": true, "count": 65, "mean_erp": 0.0432, ...}` |
| `/api/log` | Audit log of recent changes | `{"ok": true, "data": [...]}` |

### POST Endpoints

#### `/api/compute` — Manual scenario calculation

No data fetch; uses inputs you provide.

**Request body:**
```json
{
  "sp500": 6845.5,
  "total_yield": 0.029,
  "growth": 0.105,
  "tbond": 0.0418,
  "date": "2026-04-11"  // optional
}
```

**Response:**
```json
{
  "ok": true,
  "implied_r": 0.0816,
  "implied_erp": 0.0399,
  "cash_flows": [219.36, 242.40, ...],
  "terminal_value": 8565.12,
  "pv_stage1": 1061.15,
  "pv_terminal": 5786.54,
  "solver_method": "newton",
  "solver_iterations": 4
}
```

#### `/api/update` — Fetch live data and compute

Fetches current market data, then computes the implied ERP.

**Optional request body:**
```json
{
  "buyback": 0.025,      // override buyback yield (e.g., 2.5%)
  "growth": 0.08,        // override analyst growth estimate
  "as_of": "2026-04-11"  // use specific date (defaults to today)
}
```

**Response:** Same as `/api/compute` plus the fetched inputs.

---

## CORS Configuration

The server is configured to accept requests from:
- **file://** URLs (when you open erp_dashboard.html directly in a browser)
- **http://localhost:*** (any localhost port)
- **http://127.0.0.1:*** (localhost IP)
- **Any origin** (CORS headers include `Access-Control-Allow-Origin: *`)

This is configured in `server.py`:
```python
CORS(app, origins="*", allow_headers=["Content-Type"], supports_credentials=False)
```

---

## Database

- Location: `~/erp_model.db` (your home directory)
- Format: SQLite3
- Seeded with: 65 years of annual data (1961–2025)

Access the database:
```bash
sqlite3 ~/erp_model.db
```

View tables:
```sql
.tables
.schema computations
SELECT * FROM computations ORDER BY date DESC LIMIT 1;
```

---

## Custom Port

To run the server on a different port (e.g., 8000):

```bash
python server.py 8000
```

Then update the dashboard's API endpoint. Currently it's hardcoded to `http://localhost:5001` in `erp_dashboard.html`. To change it, edit `/erp-dashboard/src/api.ts`:

```typescript
const BASE = "http://localhost:8000/api";  // Change 5001 to your port
```

Then rebuild the bundle:
```bash
cd /sessions/eager-upbeat-darwin/erp-dashboard
bash /sessions/eager-upbeat-darwin/mnt/.claude/skills/web-artifacts-builder/scripts/bundle-artifact.sh
cp bundle.html /sessions/eager-upbeat-darwin/mnt/ERP\ Model/erp_dashboard.html
```

---

## Logging & Debugging

### Check recent server logs

The server prints all HTTP requests to the terminal:
```
127.0.0.1 - - [11/Apr/2026 19:45:01] "GET /api/status HTTP/1.1" 200 -
127.0.0.1 - - [11/Apr/2026 19:45:08] "POST /api/compute HTTP/1.1" 200 -
```

### View database audit log

```bash
python main.py --log
```

### Enable Flask debug mode

For development, you can enable debug mode:
```python
# In server.py, line 219, change:
app.run(host="0.0.0.0", port=port, debug=True)  # debug=True
```

**Warning:** Never enable debug mode in production. It allows arbitrary code execution.

---

## Architecture

```
erp_dashboard.html  (browser, opens as file://)
         │
         │ fetch() to http://localhost:5001/api/*
         │
    server.py (Flask)
         │
         ├── database.py (SQLite at ~/erp_model.db)
         ├── data_fetcher.py (Yahoo Finance + FRED API)
         └── erp_calculator.py (solver engine)
```

The React app in the HTML bundle is fully self-contained and requires no build step to modify the dashboard UI. To change the API endpoint or add new API calls, edit `/erp-dashboard/src/api.ts` and rebuild.

---

## Development Workflow

### Make changes to the React app

1. Edit files in `/erp-dashboard/src/`
2. Rebuild the bundle:
   ```bash
   cd /erp-dashboard
   bash /sessions/eager-upbeat-darwin/mnt/.claude/skills/web-artifacts-builder/scripts/bundle-artifact.sh
   ```
3. Copy to the ERP Model folder:
   ```bash
   cp /erp-dashboard/bundle.html /sessions/eager-upbeat-darwin/mnt/ERP\ Model/erp_dashboard.html
   ```
4. Reload the dashboard in your browser (Ctrl+R)

### Make changes to the Flask server

1. Edit `server.py`
2. Restart the server (press Ctrl+C and run `python server.py` again)
3. Reload the dashboard in your browser

### Add a new API endpoint

1. Add a route in `server.py`:
   ```python
   @app.get("/api/mynewendpoint")
   def my_endpoint():
       return _ok({"data": "value"})
   ```
2. Add a client function in `/erp-dashboard/src/api.ts`:
   ```typescript
   myNewEndpoint: () => apiFetch("/mynewendpoint")
   ```
3. Use it in the React component
4. Rebuild the bundle and restart the server

---

## Performance Notes

- All data is stored locally in SQLite; no cloud calls except to Yahoo Finance and FRED
- The solver runs in ~1–5 ms per computation
- The server can handle 100+ concurrent requests easily (it's a development server)
- For production, use a WSGI server like Gunicorn: `gunicorn -b 0.0.0.0:5001 server:app`

---

## License & Attribution

This model is based on Aswath Damodaran's published methodology from NYU Stern. See the main README.md for full attribution.
