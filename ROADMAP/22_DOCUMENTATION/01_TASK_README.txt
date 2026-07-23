================================================================================
TASK ID:     22-01
TASK NAME:   README and Project Context Files
PHASE:       22 — Documentation
================================================================================

OBJECTIVE:
    Create README.md as the primary project documentation, plus all AI agent
    context files (AI_RULES.md, ARCHITECTURE.md, CODE_STANDARDS.md,
    TRADING_RULES.md, RISK_MANAGEMENT.md) that future AI coding agents
    will read before making any changes.

CONTEXT:
    These files serve dual purpose:
    1. Human documentation
    2. AI agent context files (replit.md / AI_RULES.md for Replit Agent)

DEPENDENCIES:
    - All phases 02–21 complete

FILES TO CREATE:
    README.md
    AI_RULES.md
    ARCHITECTURE.md
    CODE_STANDARDS.md
    TRADING_RULES.md
    RISK_MANAGEMENT.md
    replit.md               (Replit Agent context — already started in Phase 02)

FILES FORBIDDEN TO MODIFY:
    app/
    ROADMAP/

--------------------------------------------------------------------------------
README.md CONTENT:
--------------------------------------------------------------------------------

    # MT5 Automated Forex Trading Bot

    Fully automated, deterministic SMC/ICT-inspired Forex trading system
    for MetaTrader 5 on Windows.

    ## What It Does
    ## Features
    ## System Requirements
    ## Quick Start (3 steps)
    ## Configuration
    ## Running the Bot
    ## Monitoring
    ## Backtesting
    ## Safety & Risk Warning
    ## Support & Troubleshooting
    ## License

--------------------------------------------------------------------------------
AI_RULES.md CONTENT:
--------------------------------------------------------------------------------

    # AI Coding Agent Rules

    Rules for any AI agent (Replit Agent or other) working on this project.

    ## MANDATORY READING BEFORE ANY CHANGE
    1. Read this file completely
    2. Read ARCHITECTURE.md
    3. Read CODE_STANDARDS.md
    4. Read ROADMAP/00_MASTER_ROADMAP.txt
    5. Read ROADMAP/00_PROJECT_STATUS.txt

    ## CORE RULES
    1. One task at a time — use the task files in ROADMAP/
    2. Never modify files outside the task's FILES TO MODIFY list
    3. Never skip tests
    4. Never enable LIVE_TRADING without explicit user instruction
    5. Never commit .env or credentials
    6. All strategy logic must be deterministic
    7. Run tests after every change
    8. Update ROADMAP/00_PROJECT_STATUS.txt after completing a task

    ## FORBIDDEN ACTIONS
    - Never hardcode credentials
    - Never modify ROADMAP/ files (except 00_PROJECT_STATUS.txt)
    - Never skip the risk engine
    - Never bypass the confluence check
    - Never set LIVE_TRADING=true

    ## CONTEXT FILES (read in this order)
    1. AI_RULES.md (this file)
    2. ARCHITECTURE.md
    3. CODE_STANDARDS.md
    4. TRADING_RULES.md
    5. RISK_MANAGEMENT.md
    6. ROADMAP/00_PROJECT_STATUS.txt (current phase)

--------------------------------------------------------------------------------
ARCHITECTURE.md CONTENT:
--------------------------------------------------------------------------------

    # System Architecture

    ## Component Overview (with dependencies)
    ## Data Flow Diagram
    ## Database Schema Overview
    ## Configuration System
    ## Logging Architecture
    ## Security Architecture
    ## Key Design Decisions (with rationale)

--------------------------------------------------------------------------------
CODE_STANDARDS.md CONTENT:
--------------------------------------------------------------------------------

    # Code Standards

    ## Python Style
    ## Type Hints (required on all public methods)
    ## Docstrings (required on all classes and public methods)
    ## Error Handling
    ## Logging (levels, format)
    ## Testing (requirements)
    ## Configuration (how to add new settings)

--------------------------------------------------------------------------------
TRADING_RULES.md CONTENT:
--------------------------------------------------------------------------------

    # Trading Rules

    ## Strategy Logic (algorithmic definitions)
    ## Entry Conditions
    ## Confluence Factors and Weights
    ## Session Windows
    ## Timeframe Analysis Order (H4 → H1 → M15 → M5)
    ## Trade Management Rules (BE, partial, trail)
    ## Position Limits

--------------------------------------------------------------------------------
RISK_MANAGEMENT.md CONTENT:
--------------------------------------------------------------------------------

    # Risk Management Rules

    ## Position Sizing Formula
    ## Daily Loss Limit
    ## Consecutive Loss Protection
    ## Correlation Rules
    ## Margin Safety
    ## Live Trading Additional Guards
    ## *** NEVER MODIFY RISK PARAMETERS WITHOUT BACKTESTING ***

ACCEPTANCE CRITERIA:
    [ ] README.md complete with all sections
    [ ] AI_RULES.md defines all forbidden actions
    [ ] ARCHITECTURE.md describes system clearly
    [ ] CODE_STANDARDS.md defines coding conventions
    [ ] TRADING_RULES.md defines all strategy rules algorithmically
    [ ] RISK_MANAGEMENT.md defines all risk rules

DEFINITION OF DONE:
    [ ] All 6 files created
    [ ] ROADMAP/00_PROJECT_STATUS.txt updated

NEXT TASK: 22-02 — TASK_USER_GUIDE.txt
================================================================================
