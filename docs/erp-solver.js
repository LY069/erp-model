/*
 * ERP Solver — vanilla-JS port of erp_calculator.py
 *
 * Implements the Damodaran 2-stage augmented DDM:
 *   index = Σ CF_t/(1+r)^t  +  TV/(1+r)^n
 *   CF_t  = base_cf × Π(1+g_i) for i=1..t
 *   TV    = CF_n × (1+g_stable) / (r - g_stable)
 *   g_stable = rfr (Damodaran's key assumption)
 *
 * Solver: Brent's method (R. P. Brent, 1973). Robust, no derivative.
 * Reference Python: erp_calculator.py:303-342 _solve_for_r,
 *                   erp_calculator.py:425-474 compute_erp_ddm.
 *
 * Exposes window.ERPSolver = { computeDdm, buildGrowthSchedule, projectCashFlows }.
 */
(function () {
  "use strict";

  var PROJECTION_YEARS = 5;
  var ANALYST_YEARS = 2;
  var SOLVER_TOL = 1e-8;
  var SOLVER_MAXITER = 200;
  var BRACKET_LOW = 0.001;
  var BRACKET_HIGH = 0.50;

  // ── Year-by-year growth ramp ──────────────────────────────────────
  // Years 1..analystYears: hold analyst growth. Then linearly ramp to rfr by year n.
  // Mirrors build_growth_schedule (erp_calculator.py:161-201).
  function buildGrowthSchedule(analystGrowth, rfr, n, analystYears) {
    n = n || PROJECTION_YEARS;
    analystYears = analystYears == null ? ANALYST_YEARS : analystYears;
    var rates = [];
    var rampYears = n - analystYears;
    for (var t = 1; t <= n; t++) {
      if (t <= analystYears) {
        rates.push(analystGrowth);
      } else {
        var frac = (t - analystYears) / rampYears;
        rates.push(analystGrowth + frac * (rfr - analystGrowth));
      }
    }
    return rates;
  }

  // CF_t = base × Π(1+g_i)  — project_cash_flows (erp_calculator.py:231-247).
  function projectCashFlows(baseCf, growthRates) {
    var out = [];
    var factor = 1.0;
    for (var i = 0; i < growthRates.length; i++) {
      factor *= 1 + growthRates[i];
      out.push(baseCf * factor);
    }
    return out;
  }

  // f(r) = PV(stage1) + PV(terminal) - index_level  → solve for 0.
  // _objective (erp_calculator.py:254-274).
  function objective(r, indexLevel, cashFlows, gStable) {
    if (r <= gStable) return 1e12;
    var n = cashFlows.length;
    var pv = 0.0;
    for (var t = 1; t <= n; t++) {
      pv += cashFlows[t - 1] / Math.pow(1 + r, t);
    }
    var cfN = cashFlows[n - 1];
    var tv = (cfN * (1 + gStable)) / (r - gStable);
    pv += tv / Math.pow(1 + r, n);
    return pv - indexLevel;
  }

  // ── Brent's method ─────────────────────────────────────────────────
  // Standard implementation. Returns {root, iterations}. Throws on
  // un-bracketed input or non-convergence.
  function brentq(f, a, b, tol, maxIter) {
    tol = tol || SOLVER_TOL;
    maxIter = maxIter || SOLVER_MAXITER;
    var fa = f(a);
    var fb = f(b);
    if (fa * fb > 0) {
      throw new Error("brentq: root not bracketed (f(a)=" + fa + ", f(b)=" + fb + ")");
    }
    if (Math.abs(fa) < Math.abs(fb)) {
      var tmp = a; a = b; b = tmp;
      tmp = fa; fa = fb; fb = tmp;
    }
    var c = a, fc = fa;
    var d = b - a, e = d;
    for (var iter = 0; iter < maxIter; iter++) {
      if (fb === 0 || Math.abs(b - a) < tol) {
        return { root: b, iterations: iter };
      }
      var s;
      if (fa !== fc && fb !== fc) {
        // Inverse quadratic interpolation
        s =
          (a * fb * fc) / ((fa - fb) * (fa - fc)) +
          (b * fa * fc) / ((fb - fa) * (fb - fc)) +
          (c * fa * fb) / ((fc - fa) * (fc - fb));
      } else {
        // Secant
        s = b - (fb * (b - a)) / (fb - fa);
      }
      var mid = (3 * a + b) / 4;
      var useBisect =
        !((s > Math.min(mid, b) && s < Math.max(mid, b))) ||
        (Math.abs(s - b) >= Math.abs(b - c) / 2) ||
        (Math.abs(b - c) < tol);
      if (useBisect) {
        s = (a + b) / 2;
        d = e = b - a;
      } else {
        e = d;
        d = b - s;
      }
      var fs = f(s);
      c = b; fc = fb;
      if (fa * fs < 0) {
        b = s; fb = fs;
      } else {
        a = s; fa = fs;
      }
      if (Math.abs(fa) < Math.abs(fb)) {
        var t = a; a = b; b = t;
        t = fa; fa = fb; fb = t;
      }
    }
    throw new Error("brentq: did not converge in " + maxIter + " iterations");
  }

  function solveForR(indexLevel, cashFlows, gStable) {
    var lo = Math.max(gStable + 0.001, BRACKET_LOW);
    var hi = BRACKET_HIGH;
    var res = brentq(
      function (r) { return objective(r, indexLevel, cashFlows, gStable); },
      lo, hi
    );
    return res;
  }

  // Detailed schedule when year1/year2 are known separately.
  // Mirrors build_growth_schedule_detailed (erp_calculator.py:204-224).
  function buildGrowthScheduleDetailed(y1, y2, rfr, n) {
    n = n || PROJECTION_YEARS;
    var rates = [y1, y2];
    var rampYears = n - 2;
    for (var i = 1; i <= rampYears; i++) {
      var frac = i / rampYears;
      rates.push(y2 + frac * (rfr - y2));
    }
    return rates.slice(0, n);
  }

  // ── FCFE entry point ───────────────────────────────────────────────
  // Mirrors compute_erp_fcfe (erp_calculator.py:349-418). Used by non-US
  // markets where trailing_eps is computed (UK, EU, JP, KR, IN, TW, CN, ...).
  // If year1Growth/year2Growth are given, uses the detailed schedule
  // (matches the snapshot reproduction exactly).
  function computeFcfe(opts) {
    var indexLevel = +opts.indexLevel;
    var trailingEps = +opts.trailingEps;
    var growthHigh = +opts.growthHigh;
    var rfr = +opts.rfr;
    var payoutRatio = opts.payoutRatio != null ? +opts.payoutRatio : 0.7785;
    if (!(indexLevel > 0)) throw new Error("indexLevel must be > 0");
    if (!isFinite(trailingEps)) throw new Error("trailingEps must be a number");
    if (!isFinite(growthHigh)) throw new Error("growthHigh must be a number");
    if (!isFinite(rfr)) throw new Error("rfr must be a number");

    var gStable = rfr;
    var baseCf = trailingEps * payoutRatio;
    var growthRates;
    if (opts.year1Growth != null && opts.year2Growth != null
        && isFinite(opts.year1Growth) && isFinite(opts.year2Growth)) {
      growthRates = buildGrowthScheduleDetailed(+opts.year1Growth, +opts.year2Growth, rfr);
    } else {
      growthRates = buildGrowthSchedule(growthHigh, rfr);
    }
    var cashFlows = projectCashFlows(baseCf, growthRates);
    var solved = solveForR(indexLevel, cashFlows, gStable);
    var r = solved.root;

    var pvStage1 = 0;
    for (var t = 1; t <= cashFlows.length; t++) {
      pvStage1 += cashFlows[t - 1] / Math.pow(1 + r, t);
    }
    var cfN = cashFlows[cashFlows.length - 1];
    var tv = (cfN * (1 + gStable)) / (r - gStable);
    var pvTerminal = tv / Math.pow(1 + r, cashFlows.length);

    return {
      impliedR: r,
      impliedErp: r - rfr,
      indexLevel: indexLevel,
      method: "fcfe",
      trailingEps: trailingEps,
      payoutRatio: payoutRatio,
      baseCashFlow: baseCf,
      growthHigh: growthHigh,
      rfr: rfr,
      growthRates: growthRates,
      cashFlows: cashFlows,
      terminalValue: tv,
      pvStage1: pvStage1,
      pvTerminal: pvTerminal,
      solverIterations: solved.iterations
    };
  }

  // ── DDM entry point ────────────────────────────────────────────────
  // Mirrors compute_erp_ddm (erp_calculator.py:425-474). Used by markets
  // (notably US, seeded from Damodaran's annual XLS) where trailing_eps
  // is not available — falls back to base_cf = index × total_yield.
  function computeDdm(opts) {
    var indexLevel = +opts.indexLevel;
    var totalYield = +opts.totalYield;
    var growthHigh = +opts.growthHigh;
    var rfr = +opts.rfr;
    var ramped = opts.ramped !== false;  // default true, matches Python
    if (!(indexLevel > 0)) throw new Error("indexLevel must be > 0");
    if (!isFinite(totalYield)) throw new Error("totalYield must be a number");
    if (!isFinite(growthHigh)) throw new Error("growthHigh must be a number");
    if (!isFinite(rfr)) throw new Error("rfr must be a number");

    var gStable = rfr;
    var baseCf = indexLevel * totalYield;
    var growthRates;
    if (ramped) {
      growthRates = buildGrowthSchedule(growthHigh, rfr);
    } else {
      growthRates = [];
      for (var i = 0; i < PROJECTION_YEARS; i++) growthRates.push(growthHigh);
    }
    var cashFlows = projectCashFlows(baseCf, growthRates);
    var solved = solveForR(indexLevel, cashFlows, gStable);
    var r = solved.root;

    var pvStage1 = 0;
    for (var t = 1; t <= cashFlows.length; t++) {
      pvStage1 += cashFlows[t - 1] / Math.pow(1 + r, t);
    }
    var cfN = cashFlows[cashFlows.length - 1];
    var tv = (cfN * (1 + gStable)) / (r - gStable);
    var pvTerminal = tv / Math.pow(1 + r, cashFlows.length);

    return {
      impliedR: r,
      impliedErp: r - rfr,
      indexLevel: indexLevel,
      method: "ddm",
      totalYield: totalYield,
      growthHigh: growthHigh,
      rfr: rfr,
      growthRates: growthRates,
      cashFlows: cashFlows,
      terminalValue: tv,
      pvStage1: pvStage1,
      pvTerminal: pvTerminal,
      solverIterations: solved.iterations
    };
  }

  // ── Self-test ──────────────────────────────────────────────────────
  // Damodaran 1999 published example (erp_calculator.py:790-799).
  // Inputs: S&P=1469.0, total_yield=0.0168, growth=0.10, rfr=0.065, ramped=False.
  // Expected ERP ≈ 2.10%.
  function selfTest() {
    var r = computeDdm({
      indexLevel: 1469.0,
      totalYield: 0.0168,
      growthHigh: 0.10,
      rfr: 0.065,
      ramped: false
    });
    var got = Math.round(r.impliedErp * 10000) / 100;
    var expected = 2.10;
    var ok = Math.abs(got - expected) < 0.10;
    var msg = "ERPSolver self-test: Damodaran 1999 → " + got + "%"
            + " (expected ~" + expected + "%) — " + (ok ? "PASS" : "FAIL");
    if (ok) {
      console.log(msg);
    } else {
      console.error(msg);
    }
    return ok;
  }

  window.ERPSolver = {
    computeDdm: computeDdm,
    computeFcfe: computeFcfe,
    buildGrowthSchedule: buildGrowthSchedule,
    buildGrowthScheduleDetailed: buildGrowthScheduleDetailed,
    projectCashFlows: projectCashFlows,
    brentq: brentq,
    selfTest: selfTest
  };

  // Run self-test on load so regressions surface in the browser console.
  try { selfTest(); } catch (e) { console.error("ERPSolver self-test threw:", e); }
})();
