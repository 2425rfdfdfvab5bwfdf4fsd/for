---
name: mt5-next-task
description: Automates the MT5 Forex Trading Bot task workflow. Use when the user says "continue", "next task", "implement next", or any similar instruction to advance the roadmap. Reads project status, finds the next task, builds the master prompt, and implements it — no manual prompt-filling required.
---

# MT5 Next-Task Automation Skill

Automates the entire manual loop the user used to do by hand:
1. Check status → find next task
2. Fill MASTER_AGENT_PROMPT.txt
3. Implement strictly following task file instructions
4. Test, review, document

**Trigger phrases:** "continue", "next task", "cantinue", "implement next task", "do the next phase task"

---

## Step 1 — Orient (always first, never skip)

Read these files in order before touching anything:

1. `ROADMAP/00_PROJECT_STATUS.txt` — find the **Current Phase** and **Recommended Action** lines at the bottom (OVERALL PROJECT METRICS section). These tell you exactly which task file to open next.
2. `replit.md` — user preferences and project overview
3. `AI_RULES.md` — hard constraints for this project
4. `ARCHITECTURE.md` — system structure
5. The **Phase Overview** file for the current phase (e.g. `ROADMAP/11_AUTOMATION/01_PHASE_OVERVIEW.txt`)
6. The **task file** identified in step 1 (e.g. `ROADMAP/11_AUTOMATION/05_TASK_AUTO_RECOVERY.txt`)

If the codebase has diverged from what the task file says, **trust the codebase**.

---

## Step 2 — Announce Before Acting

After reading, post a single short message:

```
**Task [ID] — [TASK NAME]**
Phase [N] — [Phase Name]

Files to create: [list]
Files to modify: [list]
Files forbidden: [list from task file]
Baseline tests: [N] (from status tracker)

Implementing now.
```

Do not ask for permission. Do not wait for confirmation. Begin immediately.

---

## Step 3 — Implement

Follow the task file **exactly**. The task files contain detailed step-by-step requirements — treat them as law.

Key rules (from `AI_RULES.md` — always enforced):
- **NEVER** modify files outside the scope listed in the task file
- **NEVER** hardcode numeric values — all from `app/config.py`
- **NEVER** use `print()` — use `logger = get_logger(__name__)`
- **NEVER** import `MetaTrader5` outside `app/mt5/` — always mock in tests
- **NEVER** add packages to `requirements.txt` unless the task file explicitly says to
- **ALWAYS** mock MetaTrader5 in all tests (MT5 is Windows-only; Replit is Linux)
- **ALWAYS** use `datetime.now(timezone.utc)` — never `utcnow()`
- **ALWAYS** use `tmp_path` for file I/O in tests — never touch `data/`

Code style — follow patterns in existing `app/automation/` files:
- Module docstring at top
- `from __future__ import annotations`
- `logger = get_logger(__name__)` at module level
- All configurable values from `Config`
- Every exception caught and logged — no silent failures
- Type annotations on all public methods

---

## Step 4 — Test & Fix

Run focused tests first, then the full suite:

```bash
# Focused (new tests only)
python -m pytest tests/test_automation/test_<new_module>.py -v --tb=short

# Full suite (zero regressions required)
python -m pytest tests/ -v --tb=short 2>&1 | tail -20
```

Required behavior:
- All task-file-required test cases must exist and pass
- Full suite must pass with **zero** new failures
- On failure: identify root cause → fix → re-run. Never skip or hide a failure.
- The only acceptable warnings are the 2 pre-existing deprecation warnings in `app/mt5/account.py`

---

## Step 5 — Review Checklist

Before declaring done, verify every item:

- [ ] Only in-scope files were created/modified
- [ ] No unused or circular imports
- [ ] Every exception is caught and logged — no silent failures
- [ ] No hardcoded values — all from `Config`
- [ ] All task-file acceptance criteria are met
- [ ] Full test suite passes with zero regressions
- [ ] `python -m py_compile <file>` passes for every new file

---

## Step 6 — Document & Update

Update **only** these two files (no others):

**`ROADMAP/00_PROJECT_STATUS.txt`** — update the Phase 11 section:
- Add the new task entry with `[✓] COMPLETE (YYYY-MM-DD)`
- List files created/modified
- Update test count
- Change `Next Action` to the next task file
- Update `Last Updated` and `Updated By` header lines
- Update OVERALL PROJECT METRICS: test count, current phase/task

**`replit.md`** — update test count in the `How to Run on Replit` section.

Do **NOT** modify `MASTER_AGENT_PROMPT.txt` or any ROADMAP task files.

---

## Step 7 — Final Report

Deliver this exact report format:

```
### Completed
[What was built and why it satisfies the task objective — 2–4 sentences]

### Files Created / Modified
| File | Description |
|------|-------------|
| ...  | ...         |

### Test Results
[X/X new tests pass · Y/Y total (zero regressions) · list any warnings]

### Acceptance Criteria
[✓] [criterion from task file]
[✓] [criterion from task file]
...

### Known Issues
[Deferred items or caveats — "None" if clean]

### Next Task
Phase [N] — Task [ID] — ROADMAP/[PATH]/[FILE].txt
```

Do **not** start the next task unless the user explicitly asks.

---

## How the Status File Works

The `ROADMAP/00_PROJECT_STATUS.txt` file has two key sections:

**PHASE STATUS OVERVIEW table** (near top) — shows `[✓]` / `[~]` / `[ ]` per phase.

**OVERALL PROJECT METRICS** (near bottom) — has:
```
Current Phase:        11 — AUTOMATION (tasks 11-01–11-04 complete; next: 11-05 AUTO_RECOVERY)
Recommended Action:   Open ROADMAP/11_AUTOMATION/05_TASK_AUTO_RECOVERY.txt
```

Always use the `Recommended Action` line as the single source of truth for which file to open next.

---

## Phase Transition

When a task file says `NEXT TASK: Begin Phase N`, the current phase is complete. After finishing and documenting:

1. Mark the phase `[✓] COMPLETE` in the status overview table
2. Open the next phase's `01_PHASE_OVERVIEW.txt` and read it
3. Identify the first task file in that phase
4. Report: "Phase N complete. Ready for Phase N+1 — [name]. Say 'continue' to start."

---

## Example — What "continue" triggers

User says: **"cantinue"**

Agent does:
1. Reads `ROADMAP/00_PROJECT_STATUS.txt` → sees next task is `11-05 AUTO_RECOVERY`
2. Reads `ROADMAP/11_AUTOMATION/05_TASK_AUTO_RECOVERY.txt`
3. Reads `replit.md`, `AI_RULES.md`, `ARCHITECTURE.md`
4. Announces: "Task 11-05 — Auto Recovery. Implementing now."
5. Implements `app/automation/auto_recovery.py` + tests
6. Runs tests → all pass
7. Updates `ROADMAP/00_PROJECT_STATUS.txt` and `replit.md`
8. Delivers final report
9. Stops — does NOT start task 11-06 or Phase 12
