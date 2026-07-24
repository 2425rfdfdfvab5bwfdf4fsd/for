"""
Repository classes for the MT5 Automated Forex Trading Bot.

All database access from business logic must go through these repositories.
Never write raw SQL outside this file.

Pattern:
    - Each repository wraps one domain (trades, rejected signals, etc.)
    - All methods log errors and re-raise as DatabaseError
    - All queries are parameterised (no f-string SQL ever)
    - The Repositories facade wires everything together

Usage:
    from app.database.database import DatabaseManager
    from app.database.repositories import Repositories

    db = DatabaseManager(config)
    db.initialize()
    repos = Repositories(db)

    repos.trades.create(trade)
    open_trades = repos.trades.get_open_trades()
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.database.database import DatabaseManager, DatabaseError
from app.database.models import (
    DailyRiskState,
    PerformanceSnapshot,
    RejectedSignal,
    RejectionEntry,
    SystemEvent,
    Trade,
    TradeJournalEntry,
)
from app.logger import get_logger

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _bool_to_int(value: bool) -> int:
    return 1 if value else 0


# ===========================================================================
# TradeRepository
# ===========================================================================

class TradeRepository:
    """CRUD operations for the trades table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create(self, trade: Trade) -> None:
        """Insert a new trade record."""
        sql = """
            INSERT INTO trades (
                trade_id, symbol, direction,
                entry_price, sl_price, tp_price,
                lot_size, risk_pct,
                confluence_score, quality_grade,
                market_regime, session,
                h4_bias, h1_structure, m15_setup, m5_confirmation,
                liquidity_event, order_block_used, fvg_used,
                spread_at_entry, atr_at_entry, rr_ratio,
                entry_time, exit_time, exit_reason,
                profit_loss, r_multiple,
                mt5_ticket, magic_number,
                status, partial_closed, created_at, updated_at
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?, ?
            )
        """
        params = (
            trade.trade_id, trade.symbol, trade.direction,
            trade.entry_price, trade.sl_price, trade.tp_price,
            trade.lot_size, trade.risk_pct,
            trade.confluence_score, trade.quality_grade,
            trade.market_regime, trade.session,
            trade.h4_bias, trade.h1_structure, trade.m15_setup, trade.m5_confirmation,
            _bool_to_int(trade.liquidity_event),
            _bool_to_int(trade.order_block_used),
            _bool_to_int(trade.fvg_used),
            trade.spread_at_entry, trade.atr_at_entry, trade.rr_ratio,
            trade.entry_time, trade.exit_time, trade.exit_reason,
            trade.profit_loss, trade.r_multiple,
            trade.mt5_ticket, trade.magic_number,
            trade.status, _bool_to_int(trade.partial_closed),
            trade.created_at, trade.updated_at,
        )
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
            logger.debug("Trade created: %s %s %s", trade.trade_id, trade.symbol, trade.direction)
        except DatabaseError:
            logger.error("Failed to create trade %s", trade.trade_id)
            raise

    def get_by_id(self, trade_id: str) -> Optional[Trade]:
        """Return a single trade by its UUID, or None if not found."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM trades WHERE trade_id = ?", (trade_id,)
            )
            row = cursor.fetchone()
            return self._row_to_trade(row) if row else None
        except DatabaseError:
            logger.error("Failed to fetch trade %s", trade_id)
            return None

    def get_open_trades(self) -> list[Trade]:
        """Return all trades with status='OPEN'."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM trades WHERE status = ? ORDER BY entry_time ASC",
                ("OPEN",),
            )
            return [self._row_to_trade(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch open trades")
            return []

    def get_by_symbol(self, symbol: str) -> list[Trade]:
        """Return all trades for a given symbol."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM trades WHERE symbol = ? ORDER BY entry_time DESC",
                (symbol,),
            )
            return [self._row_to_trade(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch trades for symbol %s", symbol)
            return []

    def get_by_date(self, date: str) -> list[Trade]:
        """Return all trades opened on a given date (YYYY-MM-DD)."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM trades WHERE entry_time LIKE ? ORDER BY entry_time ASC",
                (f"{date}%",),
            )
            return [self._row_to_trade(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch trades for date %s", date)
            return []

    def mark_partial_closed(self, trade_id: str) -> None:
        """
        Persist partial_closed=True for a trade after a confirmed partial close.

        Called immediately after the MT5 partial-close order is accepted so that
        subsequent process_all() cycles cannot re-trigger the partial close.
        """
        try:
            self._db.execute(
                "UPDATE trades SET partial_closed = 1, updated_at = ? WHERE trade_id = ?",
                (_now_iso(), trade_id),
            )
            self._db.get_connection().commit()
            logger.debug("Trade %s marked partial_closed=True", trade_id)
        except DatabaseError:
            logger.error("Failed to mark partial_closed for trade %s", trade_id)
            raise

    def update_status(self, trade_id: str, status: str) -> None:
        """Update the status of a trade."""
        try:
            self._db.execute(
                "UPDATE trades SET status = ?, updated_at = ? WHERE trade_id = ?",
                (status, _now_iso(), trade_id),
            )
            self._db.get_connection().commit()
            logger.debug("Trade %s status → %s", trade_id, status)
        except DatabaseError:
            logger.error("Failed to update status for trade %s", trade_id)
            raise

    def close_trade(
        self,
        trade_id: str,
        exit_time: str,
        exit_reason: str,
        profit_loss: float,
        r_multiple: float,
    ) -> None:
        """Mark a trade as closed and record outcome data."""
        try:
            self._db.execute(
                """
                UPDATE trades
                   SET status = 'CLOSED',
                       exit_time = ?,
                       exit_reason = ?,
                       profit_loss = ?,
                       r_multiple = ?,
                       updated_at = ?
                 WHERE trade_id = ?
                """,
                (exit_time, exit_reason, profit_loss, r_multiple, _now_iso(), trade_id),
            )
            self._db.get_connection().commit()
            logger.debug(
                "Trade closed: %s | PnL=%.2f | R=%.2f | reason=%s",
                trade_id, profit_loss, r_multiple, exit_reason,
            )
        except DatabaseError:
            logger.error("Failed to close trade %s", trade_id)
            raise

    def get_all_closed(self) -> list[Trade]:
        """Return all closed trades ordered by exit time descending."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM trades WHERE status = 'CLOSED' ORDER BY exit_time DESC"
            )
            return [self._row_to_trade(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch closed trades")
            return []

    def count_trades_today(self, date: str) -> int:
        """Return the number of trades opened on the given date (YYYY-MM-DD)."""
        try:
            cursor = self._db.execute(
                "SELECT COUNT(*) FROM trades WHERE entry_time LIKE ?",
                (f"{date}%",),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        except DatabaseError:
            logger.error("Failed to count today's trades")
            return 0

    def get_recent_trades(self, limit: int = 20) -> list[Trade]:
        """Return the most recent N trades ordered by entry_time descending."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM trades ORDER BY entry_time DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_trade(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch recent trades")
            return []

    # ------------------------------------------------------------------
    # Internal conversion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_trade(row) -> Trade:
        """Convert a sqlite3.Row to a Trade dataclass instance."""
        d = dict(row)
        return Trade(
            trade_id=d["trade_id"],
            symbol=d["symbol"],
            direction=d["direction"],
            entry_price=d["entry_price"],
            sl_price=d["sl_price"],
            tp_price=d["tp_price"],
            lot_size=d["lot_size"],
            risk_pct=d["risk_pct"],
            confluence_score=d["confluence_score"],
            quality_grade=d["quality_grade"],
            market_regime=d.get("market_regime", ""),
            session=d.get("session", ""),
            h4_bias=d.get("h4_bias", ""),
            h1_structure=d.get("h1_structure", ""),
            m15_setup=d.get("m15_setup", ""),
            m5_confirmation=d.get("m5_confirmation", ""),
            liquidity_event=bool(d.get("liquidity_event", 0)),
            order_block_used=bool(d.get("order_block_used", 0)),
            fvg_used=bool(d.get("fvg_used", 0)),
            spread_at_entry=d.get("spread_at_entry", 0.0),
            atr_at_entry=d.get("atr_at_entry", 0.0),
            rr_ratio=d.get("rr_ratio", 0.0),
            entry_time=d["entry_time"],
            exit_time=d.get("exit_time"),
            exit_reason=d.get("exit_reason"),
            profit_loss=d.get("profit_loss"),
            r_multiple=d.get("r_multiple"),
            mt5_ticket=d.get("mt5_ticket"),
            magic_number=d.get("magic_number", 0),
            status=d["status"],
            partial_closed=bool(d.get("partial_closed", 0)),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )


# ===========================================================================
# RejectedSignalRepository
# ===========================================================================

class RejectedSignalRepository:
    """CRUD operations for the rejected_signals table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create(self, signal: RejectedSignal) -> None:
        """Insert a rejected signal record."""
        sql = """
            INSERT INTO rejected_signals (
                signal_id, symbol, direction,
                confluence_score, failed_conditions, session,
                spread_at_time, rr_ratio,
                news_active, risk_blocked,
                rejection_reason, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            signal.signal_id, signal.symbol, signal.direction,
            signal.confluence_score, signal.failed_conditions, signal.session,
            signal.spread_at_time, signal.rr_ratio,
            _bool_to_int(signal.news_active), _bool_to_int(signal.risk_blocked),
            signal.rejection_reason, signal.timestamp,
        )
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
            logger.debug(
                "Rejected signal saved: %s %s score=%d",
                signal.symbol, signal.direction, signal.confluence_score,
            )
        except DatabaseError:
            logger.error("Failed to save rejected signal %s", signal.signal_id)
            raise

    def get_by_date(self, date: str) -> list[RejectedSignal]:
        """Return all rejected signals for a given date (YYYY-MM-DD)."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM rejected_signals WHERE timestamp LIKE ? ORDER BY timestamp ASC",
                (f"{date}%",),
            )
            return [self._row_to_signal(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch rejected signals for date %s", date)
            return []

    def get_recent(self, limit: int = 50) -> list[RejectedSignal]:
        """Return the most recent N rejected signals."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM rejected_signals ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [self._row_to_signal(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch recent rejected signals")
            return []

    @staticmethod
    def _row_to_signal(row) -> RejectedSignal:
        d = dict(row)
        return RejectedSignal(
            signal_id=d["signal_id"],
            symbol=d["symbol"],
            direction=d["direction"],
            confluence_score=d["confluence_score"],
            failed_conditions=d.get("failed_conditions", "[]"),
            session=d.get("session", ""),
            spread_at_time=d.get("spread_at_time", 0.0),
            rr_ratio=d.get("rr_ratio", 0.0),
            news_active=bool(d.get("news_active", 0)),
            risk_blocked=bool(d.get("risk_blocked", 0)),
            rejection_reason=d.get("rejection_reason", ""),
            timestamp=d["timestamp"],
        )


# ===========================================================================
# DailyRiskRepository
# ===========================================================================

class DailyRiskRepository:
    """CRUD operations for the daily_risk_state table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def get_or_create(self, date: str, starting_balance: float) -> DailyRiskState:
        """
        Return today's risk state, creating a fresh one if it doesn't exist.

        Args:
            date:             YYYY-MM-DD broker date string.
            starting_balance: Account balance at the start of the day.
        """
        existing = self.get(date)
        if existing is not None:
            return existing

        state = DailyRiskState(
            date=date,
            starting_balance=starting_balance,
        )
        self._insert(state)
        return state

    def _insert(self, state: DailyRiskState) -> None:
        sql = """
            INSERT INTO daily_risk_state (
                date, starting_balance, trade_count, consecutive_losses,
                realized_pnl, daily_loss_pct, trading_blocked, block_reason,
                last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            state.date, state.starting_balance, state.trade_count,
            state.consecutive_losses, state.realized_pnl, state.daily_loss_pct,
            _bool_to_int(state.trading_blocked), state.block_reason,
            state.last_updated,
        )
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
        except DatabaseError:
            logger.error("Failed to insert DailyRiskState for %s", state.date)
            raise

    def update(self, state: DailyRiskState) -> None:
        """Persist all fields of a DailyRiskState back to the database."""
        state.last_updated = _now_iso()
        sql = """
            UPDATE daily_risk_state
               SET starting_balance   = ?,
                   trade_count        = ?,
                   consecutive_losses = ?,
                   realized_pnl       = ?,
                   daily_loss_pct     = ?,
                   trading_blocked    = ?,
                   block_reason       = ?,
                   last_updated       = ?
             WHERE date = ?
        """
        params = (
            state.starting_balance, state.trade_count, state.consecutive_losses,
            state.realized_pnl, state.daily_loss_pct,
            _bool_to_int(state.trading_blocked), state.block_reason,
            state.last_updated, state.date,
        )
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
        except DatabaseError:
            logger.error("Failed to update DailyRiskState for %s", state.date)
            raise

    def get(self, date: str) -> Optional[DailyRiskState]:
        """Return the DailyRiskState for a given date, or None."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM daily_risk_state WHERE date = ?", (date,)
            )
            row = cursor.fetchone()
            return self._row_to_state(row) if row else None
        except DatabaseError:
            logger.error("Failed to fetch DailyRiskState for %s", date)
            return None

    def increment_trade_count(self, date: str) -> None:
        """Atomically increment the trade count for the given date."""
        try:
            self._db.execute(
                """
                UPDATE daily_risk_state
                   SET trade_count = trade_count + 1, last_updated = ?
                 WHERE date = ?
                """,
                (_now_iso(), date),
            )
            self._db.get_connection().commit()
        except DatabaseError:
            logger.error("Failed to increment trade_count for %s", date)
            raise

    def increment_consecutive_losses(self, date: str) -> None:
        """Atomically increment the consecutive loss count."""
        try:
            self._db.execute(
                """
                UPDATE daily_risk_state
                   SET consecutive_losses = consecutive_losses + 1, last_updated = ?
                 WHERE date = ?
                """,
                (_now_iso(), date),
            )
            self._db.get_connection().commit()
        except DatabaseError:
            logger.error("Failed to increment consecutive_losses for %s", date)
            raise

    def reset_consecutive_losses(self, date: str) -> None:
        """Reset consecutive losses to 0 (after a winning trade)."""
        try:
            self._db.execute(
                """
                UPDATE daily_risk_state
                   SET consecutive_losses = 0, last_updated = ?
                 WHERE date = ?
                """,
                (_now_iso(), date),
            )
            self._db.get_connection().commit()
        except DatabaseError:
            logger.error("Failed to reset consecutive_losses for %s", date)
            raise

    def set_trading_blocked(self, date: str, reason: str) -> None:
        """Block trading for the remainder of the day with a reason."""
        try:
            self._db.execute(
                """
                UPDATE daily_risk_state
                   SET trading_blocked = 1, block_reason = ?, last_updated = ?
                 WHERE date = ?
                """,
                (reason, _now_iso(), date),
            )
            self._db.get_connection().commit()
            logger.warning("Trading blocked for %s: %s", date, reason)
        except DatabaseError:
            logger.error("Failed to block trading for %s", date)
            raise

    @staticmethod
    def _row_to_state(row) -> DailyRiskState:
        d = dict(row)
        return DailyRiskState(
            date=d["date"],
            starting_balance=d["starting_balance"],
            trade_count=d.get("trade_count", 0),
            consecutive_losses=d.get("consecutive_losses", 0),
            realized_pnl=d.get("realized_pnl", 0.0),
            daily_loss_pct=d.get("daily_loss_pct", 0.0),
            trading_blocked=bool(d.get("trading_blocked", 0)),
            block_reason=d.get("block_reason"),
            last_updated=d["last_updated"],
        )


# ===========================================================================
# SystemEventRepository
# ===========================================================================

class SystemEventRepository:
    """Write-only log of system events (start/stop, errors, limit hits)."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def log_event(
        self,
        event_type: str,
        message: str,
        severity: str = "INFO",
    ) -> None:
        """Insert a new system event record."""
        sql = """
            INSERT INTO system_events (event_id, event_type, message, severity, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (_new_uuid(), event_type, message, severity, _now_iso())
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
        except DatabaseError:
            logger.error(
                "Failed to log system event type=%s severity=%s", event_type, severity
            )
            # Do NOT re-raise — event logging must never crash the bot

    def get_recent(self, limit: int = 100) -> list[dict]:
        """Return the most recent N system events as plain dicts."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM system_events ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch recent system events")
            return []

    def get_by_type(self, event_type: str, limit: int = 50) -> list[dict]:
        """Return recent events of a specific type."""
        try:
            cursor = self._db.execute(
                """
                SELECT * FROM system_events
                 WHERE event_type = ?
                 ORDER BY timestamp DESC
                 LIMIT ?
                """,
                (event_type, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch system events by type %s", event_type)
            return []


# ===========================================================================
# PerformanceRepository
# ===========================================================================

class PerformanceRepository:
    """CRUD operations for the performance_snapshots table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def save_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        """Insert or replace a performance snapshot."""
        sql = """
            INSERT OR REPLACE INTO performance_snapshots (
                snapshot_id, date, balance, equity,
                total_trades, wins, losses,
                win_rate, profit_factor, expectancy, max_drawdown,
                snapshot_type, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            snapshot.snapshot_id, snapshot.date, snapshot.balance, snapshot.equity,
            snapshot.total_trades, snapshot.wins, snapshot.losses,
            snapshot.win_rate, snapshot.profit_factor, snapshot.expectancy,
            snapshot.max_drawdown, snapshot.snapshot_type, snapshot.created_at,
        )
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
            logger.debug(
                "Performance snapshot saved: %s %s", snapshot.snapshot_type, snapshot.date
            )
        except DatabaseError:
            logger.error("Failed to save performance snapshot %s", snapshot.snapshot_id)
            raise

    def get_snapshots(
        self, snapshot_type: str, limit: int = 30
    ) -> list[PerformanceSnapshot]:
        """Return recent snapshots of a given type (DAILY/WEEKLY/MONTHLY)."""
        try:
            cursor = self._db.execute(
                """
                SELECT * FROM performance_snapshots
                 WHERE snapshot_type = ?
                 ORDER BY date DESC
                 LIMIT ?
                """,
                (snapshot_type, limit),
            )
            return [self._row_to_snapshot(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch performance snapshots type=%s", snapshot_type)
            return []

    def get_latest(self, snapshot_type: str) -> Optional[PerformanceSnapshot]:
        """Return the most recent snapshot of a given type, or None."""
        snapshots = self.get_snapshots(snapshot_type, limit=1)
        return snapshots[0] if snapshots else None

    @staticmethod
    def _row_to_snapshot(row) -> PerformanceSnapshot:
        d = dict(row)
        return PerformanceSnapshot(
            snapshot_id=d["snapshot_id"],
            date=d["date"],
            balance=d["balance"],
            equity=d["equity"],
            total_trades=d.get("total_trades", 0),
            wins=d.get("wins", 0),
            losses=d.get("losses", 0),
            win_rate=d.get("win_rate", 0.0),
            profit_factor=d.get("profit_factor", 0.0),
            expectancy=d.get("expectancy", 0.0),
            max_drawdown=d.get("max_drawdown", 0.0),
            snapshot_type=d.get("snapshot_type", "DAILY"),
            created_at=d["created_at"],
        )


# ===========================================================================
# RejectionJournalRepository
# ===========================================================================

class RejectionJournalRepository:
    """CRUD operations for the rejection_journal_entries table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create(self, entry: RejectionEntry) -> None:
        """Insert a new rejection entry."""
        sql = """
            INSERT INTO rejection_journal_entries (
                id, timestamp_utc, symbol, direction,
                confluence_score, rejection_category, rejection_detail,
                factor_breakdown, session, spread_pips
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            entry.id, entry.timestamp_utc, entry.symbol, entry.direction,
            entry.confluence_score, entry.rejection_category, entry.rejection_detail,
            entry.factor_breakdown, entry.session, entry.spread_pips,
        )
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
            logger.debug(
                "Rejection entry saved: %s %s score=%.1f category=%s",
                entry.symbol, entry.direction, entry.confluence_score,
                entry.rejection_category,
            )
        except DatabaseError:
            logger.error("Failed to save rejection entry %s", entry.id)
            raise

    def get_by_date(self, date: str) -> list[RejectionEntry]:
        """Return all rejection entries whose timestamp_utc starts with date (YYYY-MM-DD)."""
        try:
            cursor = self._db.execute(
                """
                SELECT * FROM rejection_journal_entries
                 WHERE timestamp_utc LIKE ?
                 ORDER BY timestamp_utc ASC
                """,
                (f"{date}%",),
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch rejection entries for date %s", date)
            return []

    def get_by_category(self, category: str, limit: int = 100) -> list[RejectionEntry]:
        """Return recent rejection entries for a specific category."""
        try:
            cursor = self._db.execute(
                """
                SELECT * FROM rejection_journal_entries
                 WHERE rejection_category = ?
                 ORDER BY timestamp_utc DESC
                 LIMIT ?
                """,
                (category, limit),
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch rejections by category %s", category)
            return []

    def get_near_misses(self, date: str, min_score: float, max_score: float) -> list[RejectionEntry]:
        """Return CONFLUENCE_TOO_LOW rejections within a score band for a given date."""
        try:
            cursor = self._db.execute(
                """
                SELECT * FROM rejection_journal_entries
                 WHERE timestamp_utc LIKE ?
                   AND confluence_score >= ?
                   AND confluence_score < ?
                 ORDER BY confluence_score DESC
                """,
                (f"{date}%", min_score, max_score),
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch near-miss rejections for date %s", date)
            return []

    def get_missed_trades_for_date(
        self, date: str, min_score: float, categories: tuple
    ) -> list[RejectionEntry]:
        """
        Return high-scoring rejections blocked by risk limits on a given date.

        Args:
            date:       YYYY-MM-DD string matched as prefix of timestamp_utc.
            min_score:  Minimum confluence score to qualify as a missed trade.
            categories: Tuple of rejection_category strings that count as blocks.

        Returns:
            List of RejectionEntry objects ordered by confluence_score descending.
        """
        if not categories:
            return []
        placeholders = ",".join("?" * len(categories))
        sql = f"""
            SELECT * FROM rejection_journal_entries
             WHERE timestamp_utc LIKE ?
               AND confluence_score >= ?
               AND rejection_category IN ({placeholders})
             ORDER BY confluence_score DESC
        """
        try:
            cursor = self._db.execute(sql, (f"{date}%", min_score, *categories))
            return [self._row_to_entry(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error(
                "Failed to fetch missed trades for date %s min_score=%.1f", date, min_score
            )
            return []

    def get_missed_trades_for_range(
        self, date_from: str, date_to: str, min_score: float, categories: tuple
    ) -> list[RejectionEntry]:
        """
        Return high-scoring risk-blocked rejections across a date range.

        Args:
            date_from:  YYYY-MM-DD start date (inclusive).
            date_to:    YYYY-MM-DD end date (inclusive, matched as prefix + 'Z').
            min_score:  Minimum confluence score to qualify.
            categories: Tuple of rejection_category strings that count as blocks.

        Returns:
            List of RejectionEntry objects ordered by timestamp_utc ascending.
        """
        if not categories:
            return []
        placeholders = ",".join("?" * len(categories))
        sql = f"""
            SELECT * FROM rejection_journal_entries
             WHERE timestamp_utc >= ?
               AND timestamp_utc < ?
               AND confluence_score >= ?
               AND rejection_category IN ({placeholders})
             ORDER BY timestamp_utc ASC
        """
        try:
            cursor = self._db.execute(
                sql,
                (f"{date_from}T00:00:00", f"{date_to}T23:59:59.999999Z", min_score, *categories),
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error(
                "Failed to fetch missed trades for range %s–%s", date_from, date_to
            )
            return []

    def count_by_category_for_date(self, date: str) -> dict[str, int]:
        """Return a dict of {category: count} for all rejections on a given date."""
        try:
            cursor = self._db.execute(
                """
                SELECT rejection_category, COUNT(*) as cnt
                  FROM rejection_journal_entries
                 WHERE timestamp_utc LIKE ?
                 GROUP BY rejection_category
                """,
                (f"{date}%",),
            )
            return {row["rejection_category"]: row["cnt"] for row in cursor.fetchall()}
        except DatabaseError:
            logger.error("Failed to count rejections by category for date %s", date)
            return {}

    @staticmethod
    def _row_to_entry(row) -> RejectionEntry:
        d = dict(row)
        return RejectionEntry(
            id=d["id"],
            timestamp_utc=d["timestamp_utc"],
            symbol=d["symbol"],
            direction=d["direction"],
            confluence_score=d["confluence_score"],
            rejection_category=d["rejection_category"],
            rejection_detail=d.get("rejection_detail", ""),
            factor_breakdown=d.get("factor_breakdown", "{}"),
            session=d.get("session", ""),
            spread_pips=d.get("spread_pips", 0.0),
        )


# ===========================================================================
# TradeJournalRepository
# ===========================================================================

class TradeJournalRepository:
    """CRUD operations for the trade_journal_entries table."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create(self, entry: TradeJournalEntry) -> None:
        """Insert a new journal entry (open trade state)."""
        sql = """
            INSERT INTO trade_journal_entries (
                id, symbol, direction,
                entry_price, exit_price, sl_price, tp1_price, tp2_price,
                lot_size, risk_amount,
                pnl, pnl_pct, r_multiple,
                confluence_score, quality_grade, factor_breakdown,
                entry_time_utc, exit_time_utc, duration_minutes,
                exit_reason, management_events,
                slippage_pips, execution_ticket,
                session, mode, notes,
                created_at, updated_at
            ) VALUES (
                ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?
            )
        """
        params = (
            entry.id, entry.symbol, entry.direction,
            entry.entry_price, entry.exit_price, entry.sl_price,
            entry.tp1_price, entry.tp2_price,
            entry.lot_size, entry.risk_amount,
            entry.pnl, entry.pnl_pct, entry.r_multiple,
            entry.confluence_score, entry.quality_grade, entry.factor_breakdown,
            entry.entry_time_utc, entry.exit_time_utc, entry.duration_minutes,
            entry.exit_reason, entry.management_events,
            entry.slippage_pips, entry.execution_ticket,
            entry.session, entry.mode, entry.notes,
            entry.created_at, entry.updated_at,
        )
        try:
            self._db.execute(sql, params)
            self._db.get_connection().commit()
            logger.debug(
                "Journal entry created: %s %s %s ticket=%s",
                entry.id, entry.symbol, entry.direction, entry.execution_ticket,
            )
        except DatabaseError:
            logger.error("Failed to create journal entry %s", entry.id)
            raise

    def update_exit(
        self,
        entry_id: str,
        exit_price: float,
        exit_time_utc: str,
        exit_reason: str,
        pnl: float,
        pnl_pct: float,
        r_multiple: float,
        duration_minutes: float,
    ) -> None:
        """Persist exit data after a trade closes."""
        try:
            self._db.execute(
                """
                UPDATE trade_journal_entries
                   SET exit_price       = ?,
                       exit_time_utc    = ?,
                       exit_reason      = ?,
                       pnl              = ?,
                       pnl_pct          = ?,
                       r_multiple       = ?,
                       duration_minutes = ?,
                       updated_at       = ?
                 WHERE id = ?
                """,
                (
                    exit_price, exit_time_utc, exit_reason,
                    pnl, pnl_pct, r_multiple, duration_minutes,
                    _now_iso(), entry_id,
                ),
            )
            self._db.get_connection().commit()
            logger.debug(
                "Journal entry exited: %s pnl=%.2f R=%.2f", entry_id, pnl, r_multiple
            )
        except DatabaseError:
            logger.error("Failed to update exit for journal entry %s", entry_id)
            raise

    def update_management_events(
        self, entry_id: str, management_events_json: str
    ) -> None:
        """Replace the management_events JSON blob for an entry."""
        try:
            self._db.execute(
                """
                UPDATE trade_journal_entries
                   SET management_events = ?,
                       updated_at        = ?
                 WHERE id = ?
                """,
                (management_events_json, _now_iso(), entry_id),
            )
            self._db.get_connection().commit()
            logger.debug("Management events updated for journal entry %s", entry_id)
        except DatabaseError:
            logger.error(
                "Failed to update management events for journal entry %s", entry_id
            )
            raise

    def get_by_id(self, entry_id: str) -> Optional[TradeJournalEntry]:
        """Return a single journal entry by ID, or None."""
        try:
            cursor = self._db.execute(
                "SELECT * FROM trade_journal_entries WHERE id = ?", (entry_id,)
            )
            row = cursor.fetchone()
            return self._row_to_entry(row) if row else None
        except DatabaseError:
            logger.error("Failed to fetch journal entry %s", entry_id)
            return None

    def get_by_date(self, date: str) -> list[TradeJournalEntry]:
        """Return all journal entries whose entry_time_utc starts with date (YYYY-MM-DD)."""
        try:
            cursor = self._db.execute(
                """
                SELECT * FROM trade_journal_entries
                 WHERE entry_time_utc LIKE ?
                 ORDER BY entry_time_utc ASC
                """,
                (f"{date}%",),
            )
            return [self._row_to_entry(row) for row in cursor.fetchall()]
        except DatabaseError:
            logger.error("Failed to fetch journal entries for date %s", date)
            return []

    @staticmethod
    def _row_to_entry(row) -> TradeJournalEntry:
        d = dict(row)
        return TradeJournalEntry(
            id=d["id"],
            symbol=d["symbol"],
            direction=d["direction"],
            entry_price=d["entry_price"],
            exit_price=d.get("exit_price"),
            sl_price=d["sl_price"],
            tp1_price=d["tp1_price"],
            tp2_price=d["tp2_price"],
            lot_size=d["lot_size"],
            risk_amount=d["risk_amount"],
            pnl=d.get("pnl"),
            pnl_pct=d.get("pnl_pct"),
            r_multiple=d.get("r_multiple"),
            confluence_score=d["confluence_score"],
            quality_grade=d["quality_grade"],
            factor_breakdown=d.get("factor_breakdown", "{}"),
            entry_time_utc=d["entry_time_utc"],
            exit_time_utc=d.get("exit_time_utc"),
            duration_minutes=d.get("duration_minutes"),
            exit_reason=d.get("exit_reason"),
            management_events=d.get("management_events", "[]"),
            slippage_pips=d.get("slippage_pips"),
            execution_ticket=d.get("execution_ticket"),
            session=d.get("session", ""),
            mode=d.get("mode", "DEMO"),
            notes=d.get("notes", ""),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )


# ===========================================================================
# Repositories — facade
# ===========================================================================

class Repositories:
    """
    Facade providing unified access to all repository classes.

    Usage:
        repos = Repositories(db)
        repos.trades.create(trade)
        repos.system_events.log_event("STARTED", "Bot started", "INFO")
    """

    def __init__(self, db: DatabaseManager) -> None:
        self.trades = TradeRepository(db)
        self.rejected_signals = RejectedSignalRepository(db)
        self.daily_risk = DailyRiskRepository(db)
        self.system_events = SystemEventRepository(db)
        self.performance = PerformanceRepository(db)
        self.trade_journal = TradeJournalRepository(db)
        self.rejection_journal = RejectionJournalRepository(db)
