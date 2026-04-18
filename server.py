"""
ERP Model — Local Flask API Server
===================================
Exposes the ERP backend as a REST API so the browser-based
frontend can read and update data without any cloud service.

Start with:
  python3 server.py

Then open http://localhost:5001 in your browser.
"""

import sys
import os
import traceback
from datetime import date
from pathlib import Path

import webbrowser
from flask import Flask, jsonify, request, send_file, make_response

# Always resolve imports relative to THIS file's directory,
# regardless of what directory the user runs python3 from
THIS_DIR = Path(__file__).resolve().parent
os.chdir(THIS_DIR)
sys.path.insert(0, str(THIS_DIR))

from config import OUTPUT_DIR, DEFAULT_PAYOUT_RATIO
from database import (
    init_db, upsert_inputs, upsert_computation, upsert_forecast, upsert_breakeven,
    get_latest, get_history, get_forecasts, get_latest_breakeven, get_log, get_stats
)
from data_fetcher import fetch_all_inputs
from erp_calculator import (
    compute_erp, compute_erp_fcfe, compute_erp_ddm,
    forecast_erp, compute_breakeven_growth,
    NORMAL_ERP_LONGRUN, NORMAL_ERP_DECADE
)

app = Flask(__name__)

# ── Global error handlers — always return JSON, never HTML ─────────
@app.errorhandler(Exception)
def handle_exception(e):
    """Catch-all: return JSON so the frontend never gets an HTML error page."""
    import traceback as _tb
    return jsonify({"ok": False, "error": str(e),
                    "detail": _tb.format_exc()[-500:]}), 500

@app.errorhandler(404)
def handle_404(e):
    return jsonify({"ok": False, "error": "Not found"}), 404

@app.errorhandler(405)
def handle_405(e):
    return jsonify({"ok": False, "error": "Method not allowed"}), 405

init_db()

# ── Serve the dashboard at the root URL ────────────────────────────
DASHBOARD_FILE = THIS_DIR / "erp_dashboard.html"
ASSETS_DIR      = THIS_DIR / "assets"

def _nocache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

@app.get("/")
def serve_dashboard():
    """Serve the dashboard HTML."""
    if DASHBOARD_FILE.exists():
        return _nocache(make_response(send_file(str(DASHBOARD_FILE), mimetype="text/html")))
    return "<h1>erp_dashboard.html not found</h1>", 404

@app.get("/assets/<path:filename>")
def serve_asset(filename):
    """Serve JS/CSS assets for the dashboard."""
    asset_path = ASSETS_DIR / filename
    if asset_path.exists():
        mime = "text/javascript" if filename.endswith(".js") else "text/css"
        return _nocache(make_response(send_file(str(asset_path), mimetype=mime)))
    return _nocache(make_response(jsonify({"ok": False, "error": f"Asset not found: {filename}"}), 404))


# ── Helpers ────────────────────────────────────────────────────────

def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code

def _ok(data: dict):
    return jsonify({"ok": True, **data})


# ── Routes ─────────────────────────────────────────────────────────

@app.get("/api/status")
def status():
    """Health check — used by frontend to test connection."""
    return _ok({"message": "ERP model server is running", "date": date.today().isoformat()})


@app.get("/api/latest")
def latest():
    """Return the most recent computed ERP with all inputs."""
    method = request.args.get("method", "fcfe")
    row = get_latest(method=method)
    if row is None:
        return _err("No data in database. Run /api/update first.", 404)
    return _ok({"data": dict(row)})


@app.get("/api/history")
def history():
    """Return full time-series as a list of records."""
    start  = request.args.get("start", "1900-01-01")
    end    = request.args.get("end",   "2099-12-31")
    method = request.args.get("method", "fcfe")
    df = get_history(start, end, method=method)
    if df.empty:
        return _ok({"data": [], "count": 0})
    df["date"] = df["date"].astype(str)
    return _ok({"data": df.to_dict(orient="records"), "count": len(df)})


@app.get("/api/stats")
def stats():
    """Return summary statistics across all history."""
    method = request.args.get("method", "fcfe")
    df = get_history(method=method)
    if df.empty:
        # Try any method
        df = get_history()
    if df.empty:
        return _err("No history available.", 404)

    erp = df["implied_erp"]
    row = get_latest(method=method)
    current_pctile = float((erp < row["implied_erp"]).mean()) if row else None

    return _ok({
        "count": int(len(df)),
        "mean_erp":  float(erp.mean()),
        "std_erp":   float(erp.std()),
        "min_erp":   float(erp.min()),
        "max_erp":   float(erp.max()),
        "min_year":  str(df.loc[erp.idxmin(), "date"])[:4],
        "max_year":  str(df.loc[erp.idxmax(), "date"])[:4],
        "current_percentile": current_pctile,
        "normal_erp_longrun": NORMAL_ERP_LONGRUN,
        "normal_erp_decade":  NORMAL_ERP_DECADE,
    })


@app.post("/api/update")
def update():
    """
    Fetch latest market data and compute new ERP.
    Accepts optional JSON body:
      {
        "buyback": 0.025,
        "growth": 0.08,
        "as_of": "2024-06-30",
        "method": "fcfe",          // "fcfe" (default) or "ddm"
        "trailing_eps": 271.52,    // override if known
        "payout_ratio": 0.7785     // override if needed
      }
    """
    body = request.get_json(silent=True) or {}
    buyback        = body.get("buyback")
    growth         = body.get("growth")
    as_of          = body.get("as_of")
    method         = body.get("method", "fcfe")
    eps_override   = body.get("trailing_eps")
    payout_override = body.get("payout_ratio", DEFAULT_PAYOUT_RATIO)

    try:
        inputs = fetch_all_inputs(
            as_of=as_of,
            buyback_override=float(buyback) if buyback is not None else None,
            growth_override=float(growth) if growth is not None else None,
            method=method,
        )
    except Exception as e:
        return _err(f"Data fetch failed: {e}", 502)

    if eps_override is not None:
        inputs["trailing_eps"] = float(eps_override)

    # Store inputs
    upsert_inputs(
        dt=inputs["date"],
        sp500=inputs["sp500_level"],
        div_yield=inputs["dividend_yield"],
        buyback_yield=inputs["buyback_yield"],
        growth=inputs["analyst_5yr_growth"],
        tbond=inputs["tbond_10yr_rate"],
        source=inputs.get("method", "auto"),
        trailing_eps=inputs.get("trailing_eps"),
        payout_ratio=payout_override,
        year1_growth=inputs.get("year1_growth"),
        year2_growth=inputs.get("year2_growth"),
        growth_source=inputs.get("growth_source"),
    )

    # Compute ERP
    try:
        if method == "fcfe":
            trailing_eps = inputs.get("trailing_eps")
            if trailing_eps is None:
                return _err("FCFE method requires trailing_eps. Provide it manually or use method=ddm", 400)
            result = compute_erp_fcfe(
                dt=inputs["date"],
                sp500_level=inputs["sp500_level"],
                trailing_eps=trailing_eps,
                analyst_growth=inputs["analyst_5yr_growth"],
                tbond_rate=inputs["tbond_10yr_rate"],
                payout_ratio=payout_override,
                year1_growth=inputs.get("year1_growth"),
                year2_growth=inputs.get("year2_growth"),
            )
        else:
            result = compute_erp_ddm(
                dt=inputs["date"],
                sp500_level=inputs["sp500_level"],
                total_yield=inputs["total_yield"],
                growth_high=inputs["analyst_5yr_growth"],
                tbond_rate=inputs["tbond_10yr_rate"],
                ramped=True,
            )
    except Exception as e:
        return _err(f"Solver failed: {e}", 500)

    upsert_computation(
        dt=result.date,
        r=result.implied_r,
        erp=result.implied_erp,
        pv1=result.pv_stage1,
        tv=result.terminal_value,
        pv_tv=result.pv_terminal,
        iterations=result.solver_iterations,
        method_solver=result.solver_method,
        method_model=result.method,
        annual_growth_rates=result.annual_growth_rates,
        cash_flows=result.cash_flows,
    )

    return _ok({
        "inputs": inputs,
        "result": {
            "date":               result.date,
            "method":             result.method,
            "implied_r":          result.implied_r,
            "implied_erp":        result.implied_erp,
            "pv_stage1":          result.pv_stage1,
            "terminal_value":     result.terminal_value,
            "pv_terminal":        result.pv_terminal,
            "cash_flows":         result.cash_flows,
            "annual_growth_rates": result.annual_growth_rates,
            "solver_method":      result.solver_method,
            "solver_iterations":  result.solver_iterations,
        },
    })


@app.post("/api/compute")
def compute_manual():
    """
    Compute ERP from manually supplied inputs (no data fetch, no save).
    Useful for scenario analysis.

    Body (DDM):  { sp500, total_yield, growth, tbond, method="ddm" }
    Body (FCFE): { sp500, trailing_eps, growth, tbond, payout_ratio?, method="fcfe" }
    """
    body = request.get_json(silent=True) or {}
    method = body.get("method", "ddm")
    dt = body.get("date", date.today().isoformat())

    try:
        if method == "fcfe":
            required = ["sp500", "trailing_eps", "growth", "tbond"]
            missing = [k for k in required if k not in body]
            if missing:
                return _err(f"Missing fields for FCFE: {missing}")
            result = compute_erp_fcfe(
                dt=dt,
                sp500_level=float(body["sp500"]),
                trailing_eps=float(body["trailing_eps"]),
                analyst_growth=float(body["growth"]),
                tbond_rate=float(body["tbond"]),
                payout_ratio=float(body.get("payout_ratio", DEFAULT_PAYOUT_RATIO)),
                year1_growth=float(body["year1_growth"]) if "year1_growth" in body else None,
                year2_growth=float(body["year2_growth"]) if "year2_growth" in body else None,
            )
        else:
            required = ["sp500", "total_yield", "growth", "tbond"]
            missing = [k for k in required if k not in body]
            if missing:
                return _err(f"Missing fields for DDM: {missing}")
            result = compute_erp_ddm(
                dt=dt,
                sp500_level=float(body["sp500"]),
                total_yield=float(body["total_yield"]),
                growth_high=float(body["growth"]),
                tbond_rate=float(body["tbond"]),
                ramped=True,
            )
    except Exception as e:
        return _err(f"Solver failed: {traceback.format_exc()}", 500)

    return _ok({
        "method":              result.method,
        "implied_r":           result.implied_r,
        "implied_erp":         result.implied_erp,
        "cash_flows":          result.cash_flows,
        "annual_growth_rates": result.annual_growth_rates,
        "terminal_value":      result.terminal_value,
        "pv_stage1":           result.pv_stage1,
        "pv_terminal":         result.pv_terminal,
        "solver_method":       result.solver_method,
        "solver_iterations":   result.solver_iterations,
    })


@app.post("/api/forecast")
def run_forecast():
    """
    Generate forward ERP projections under base/bull/bear scenarios.

    Body:
    {
      "sp500": 5881.63,
      "eps": 271.52,
      "tbond": 0.0418,
      "growth": 0.105,
      "horizon": 5,          // years ahead (default 5)
      "payout_ratio": 0.7785,
      "save": true           // save to DB (default true)
    }

    Returns scenario projections for display on the forecast chart.
    """
    body = request.get_json(silent=True) or {}

    # Use current values from DB if not provided
    latest = get_latest(method="fcfe") or get_latest(method="ddm") or {}

    sp500   = float(body.get("sp500",   latest.get("sp500_level", 5000)))
    eps     = float(body.get("eps",     latest.get("trailing_eps") or sp500 / 21.0))
    tbond   = float(body.get("tbond",   latest.get("tbond_10yr_rate", 0.045)))
    growth  = float(body.get("growth",  latest.get("analyst_5yr_growth", 0.08)))
    horizon = int(body.get("horizon", 5))
    payout  = float(body.get("payout_ratio", DEFAULT_PAYOUT_RATIO))
    save    = body.get("save", True)

    try:
        scenarios = forecast_erp(
            base_sp500=sp500,
            base_eps=eps,
            base_tbond=tbond,
            base_growth=growth,
            horizon_years=horizon,
            payout_ratio=payout,
        )
    except Exception as e:
        return _err(f"Forecast failed: {e}", 500)

    base_date = date.today().isoformat()
    if save:
        for scenario_name, points in scenarios.items():
            upsert_forecast(base_date, scenario_name, points)

    return _ok({
        "base_date": base_date,
        "scenarios": scenarios,
        "inputs": {
            "sp500": sp500,
            "eps": eps,
            "tbond": tbond,
            "growth": growth,
            "horizon": horizon,
            "payout_ratio": payout,
        }
    })


@app.get("/api/forecasts")
def get_forecast_data():
    """Return stored forecast data."""
    base_date = request.args.get("base_date")
    scenario  = request.args.get("scenario")
    df = get_forecasts(base_date=base_date, scenario=scenario)
    if df.empty:
        return _ok({"data": [], "count": 0})
    return _ok({"data": df.to_dict(orient="records"), "count": len(df)})


@app.post("/api/breakeven")
def run_breakeven():
    """
    Compute the earnings growth needed to earn the "normal" ERP.

    Body:
    {
      "sp500": 5881.63,        // optional, uses latest from DB
      "eps": 271.52,           // optional, uses latest from DB
      "tbond": 0.0418,         // optional, uses latest from DB
      "method": "longrun",     // "longrun" (default), "decade", or "custom"
      "target_erp": 0.045,     // required if method="custom"
      "save": true
    }
    """
    body = request.get_json(silent=True) or {}

    latest = get_latest(method="fcfe") or get_latest(method="ddm") or {}

    sp500  = float(body.get("sp500",  latest.get("sp500_level", 5000)))
    eps    = float(body.get("eps",    latest.get("trailing_eps") or sp500 / 21.0))
    tbond  = float(body.get("tbond",  latest.get("tbond_10yr_rate", 0.045)))
    method = body.get("method", "longrun")
    target = float(body["target_erp"]) if "target_erp" in body else None
    save   = body.get("save", True)

    try:
        result = compute_breakeven_growth(
            sp500_level=sp500,
            trailing_eps=eps,
            tbond_rate=tbond,
            target_erp=target,
            normal_erp_method=method,
        )
    except Exception as e:
        return _err(f"Breakeven computation failed: {e}", 500)

    if save:
        upsert_breakeven(
            dt=date.today().isoformat(),
            sp500=sp500,
            eps=eps,
            tbond=tbond,
            breakeven_growth=result["breakeven_growth"],
            normal_erp=result["normal_erp"],
            normal_erp_method=method,
            interpretation=result.get("interpretation", ""),
        )

    return _ok(result)


@app.get("/api/breakeven")
def get_breakeven_data():
    """Return the most recent breakeven computation."""
    row = get_latest_breakeven()
    if row is None:
        return _err("No breakeven data. Run POST /api/breakeven first.", 404)
    return _ok({"data": row})


@app.get("/api/log")
def log():
    """Return recent audit log entries."""
    limit = int(request.args.get("limit", 100))
    df = get_log(limit)
    df["created_at"] = df["created_at"].astype(str)
    return _ok({"data": df.to_dict(orient="records")})


# ── Entry Point ────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5001
    url = f"http://localhost:{port}"
    print(f"""
  ╔══════════════════════════════════════════════════════╗
  ║    ERP Model Server running                          ║
  ║                                                      ║
  ║    ★  Open in browser:  {url:<28s} ║
  ║                                                      ║
  ║    Press Ctrl+C to stop                              ║
  ╚══════════════════════════════════════════════════════════╝
""")
    webbrowser.open(url)
    app.run(host="0.0.0.0", port=port, debug=False)
