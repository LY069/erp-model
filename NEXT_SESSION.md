# How to Start the Next Claude Session

This file is the bridge between Claude sessions. The project uses a `SHARED_NOTES.md` document as persistent memory. Claude has no memory between sessions, so every new conversation begins by reading that file.

---

## The opener template

Copy the block below (everything between the triple backticks) and paste it as the **first message** in a new Claude Code conversation. Replace the two `<...>` placeholders before sending.

```
Read /Users/yelintao/Work/DAA/Equity/ERP\ Model/SHARED_NOTES.md first — especially the Status Log at the bottom and the Consolidated Plan section.

We are at Phase <N>.
Last session ended with: <paste the most recent Status Log line>

Task this session: <copy the Scope + Exit criteria for Phase N from Agent 4's section, or from the 6-phase table in the Consolidated Plan>.

Constraints:
- Do not modify the Agent 1 / Agent 2 / Agent 3 / Agent 4 sections of SHARED_NOTES.md — they are historical contributions.
- Keep the app runnable at every commit — no broken states.
- Local-only; no cloud deploys, no API-key-dependent services.
- At the end of the session, append one Status Log line to SHARED_NOTES.md and verify the exit criterion by actually running the app.
```

---

## Step-by-step: starting a new Claude Code session

### Step 1 — Decide which phase you're on

Open `SHARED_NOTES.md`, scroll to the bottom (`## Status Log`), and read the last line. It tells you what phase just finished and what's next.

Today's starting point (after this planning session): **Phase 0** — git init, `.gitignore`, `markets_config.py` US stub, `migrations/001_multi_market.py`, run migration, confirm server still works.

### Step 2 — Open a fresh Claude Code conversation

Use `/clear` if you're continuing in the same window, or just open a new Claude Code session. **Do not** continue an old conversation across phases — the context window fills with outdated detail.

### Step 3 — Fill in the two placeholders

From the template above, fill in:

- **`<N>`** → the phase number you're about to work on (e.g., `0`, `1`, `2` …).
- **`<paste the most recent Status Log line>`** → literally copy the last line from the `## Status Log` section at the bottom of `SHARED_NOTES.md`. That line tells Claude what just happened.
- **`<copy the Scope + Exit criteria for Phase N>`** → from the Consolidated Plan's 6-phase table, grab the "Goal" and "Exit criterion" columns for that phase. For more detail, copy the matching Phase N bullet from Agent 4's section.

### Step 4 — Paste and send as the first message

Don't add small talk, don't add other context, don't attach files. Just the filled-in template. Claude will read `SHARED_NOTES.md`, orient itself, and proceed.

### Step 5 — Let Claude work the phase

Expect one phase per session. Phase 1 and Phase 4 may need two sessions — if the session hits its time limit or context fills up, stop there and start another session with Step 1.

### Step 6 — End-of-session ritual (important)

Before closing the session, tell Claude:

> "Append a Status Log line to `SHARED_NOTES.md` summarizing what we did this session, and confirm the phase exit criterion is met by running the app."

The Status Log format (from Agent 4 §3):

```
YYYY-MM-DD  PhaseN: <what was done>. Files touched: <list>. Next: <what to do next session>. Open: <unresolved questions>.
```

Without this, the next session has no idea what state the project is in.

---

## Worked example — opener for Phase 0 (your next session)

Paste this verbatim in a fresh Claude Code conversation to start Phase 0:

```
Read /Users/yelintao/Work/DAA/Equity/ERP\ Model/SHARED_NOTES.md first — especially the Status Log at the bottom and the Consolidated Plan section.

We are at Phase 0.
Last session ended with: 2026-04-17 Planning complete. All 4 agents contributed to SHARED_NOTES.md. Consolidated plan written. Dev server configured (.claude/launch.json), Flask running on port 5001. No code changes yet. Next: Phase 0 — git init, write .gitignore, markets_config.py US stub, migrations/001_multi_market.py, run migration on ~/erp_model.db, confirm server still works. Open: React source location (confirm /erp-dashboard/src/ exists before Phase 2).

Task this session: Phase 0 — Git + DB migration scaffold (backward-compatible).
Goal: repo under version control; schema gains `market` column with 'US' default; nothing user-visible changes.
Scope: git init, .gitignore, markets_config.py stub (US-only MarketSpec), migrations/001_multi_market.py (idempotent ALTER + composite PK rebuild per Agent 3 §2), CHANGELOG.md, MIGRATION.md. Back up ~/erp_model.db to ~/erp_model.db.bak-pre0 before any ALTER.
Exit criterion: `python server.py` still starts; dashboard still loads 65yr SP500 history; `sqlite3 ~/erp_model.db ".schema erp_inputs"` shows a `market` column; `git log --oneline` shows one commit.

Constraints:
- Do not modify the Agent 1 / Agent 2 / Agent 3 / Agent 4 sections of SHARED_NOTES.md — they are historical contributions.
- Keep the app runnable at every commit — no broken states.
- Local-only; no cloud deploys, no API-key-dependent services.
- At the end of the session, append one Status Log line to SHARED_NOTES.md and verify the exit criterion by actually running the app.
```

---

## Phase-by-phase quick reference

After Phase 0 the pattern is identical — only the Phase number, Goal, Scope, and Exit criterion change.

| Phase | Goal (one line) | Sessions |
|---|---|---|
| 0 | Git init + DB migration (US-only unchanged) | 1 |
| 1 | UK end-to-end through the backend | 1–2 |
| 2 | Frontend market switcher (no bundle rebuild) | 1–2 |
| 3 | Europe + Japan (config-only) | 1 |
| 4 | Korea, India, Taiwan, China (EM tier) | 2 |
| 5 | launchd auto-refresh + GitHub publication | 1 |

For the detailed Scope and Exit criterion of each phase, see **Agent 4 §1** in `SHARED_NOTES.md`, or the condensed table in the **Consolidated Plan** section.

---

## Things to do outside of Claude (don't burn a session on these)

Per Agent 4 §3, do these manually — they take under 5 minutes each:

- `git commit` and `git tag v0.phaseN` after each phase
- `python main.py --update` (routine data refresh)
- Inspecting `~/erp_model.db` with `sqlite3`
- Adding a single market row to `markets_config.py` (copy an existing entry, change constants)
- Approving the launchd plist in System Settings (Phase 5)
- `git push` to GitHub
