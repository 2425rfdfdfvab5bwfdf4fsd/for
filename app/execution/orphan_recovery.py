"""
Orphan Position Recovery — Phase 09, Task 09-05.

Detects MT5 positions that have no corresponding database record (orphans)
and handles them according to the configured ORPHAN_POLICY.

Called once on bot startup, before the main loop begins.

Policies (ORPHAN_POLICY in .env):
    alert  (default) — log CRITICAL, record as 'untracked', alert operator
    adopt            — reconstruct parameters and insert into trades table
    close            — market-close the orphan position

Usage:
    recovery = OrphanPositionRecovery(config)
    report = recovery.scan_on_startup(mt5_positions, db_open_trades)
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from app.config import Config
from app.database.models import OrphanReport, Position
from app.logger import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mt5():
    return sys.modules.get("MetaTrader5")


class OrphanPositionRecovery:
    """
    Scans for MT5 positions with no matching DB record and resolves them.

    Only positions with magic == MAGIC_NUMBER are considered bot-owned.
    External positions (different magic) are always skipped.
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_on_startup(
        self,
        mt5_positions: list,
        db_open_trades: list,
    ) -> OrphanReport:
        """
        Compare MT5 positions against DB open trades and handle orphans.

        Parameters
        ----------
        mt5_positions:  Live MT5 position objects from positions_get().
        db_open_trades: Open trade records from the database.

        Returns an OrphanReport summarising what was found and done.
        """
        report = OrphanReport()

        # Build set of DB-tracked tickets
        db_tickets: set[int] = set()
        for trade in db_open_trades:
            ticket = (
                trade.get("mt5_ticket") if isinstance(trade, dict)
                else getattr(trade, "mt5_ticket", None)
            )
            if ticket is not None:
                db_tickets.add(ticket)

        # Find orphan positions
        orphans: list = []
        for pos in mt5_positions:
            # Skip positions not belonging to this bot
            if getattr(pos, "magic", None) != self._config.MAGIC_NUMBER:
                continue
            ticket = getattr(pos, "ticket", None)
            if ticket not in db_tickets:
                orphans.append(pos)

        report.orphan_positions = list(orphans)

        if not orphans:
            logger.info("OrphanRecovery: startup scan complete — no orphan positions found")
            report.action_taken = "none"
            return report

        # Apply policy to each orphan
        policy = self._config.ORPHAN_POLICY.lower()
        report.action_taken = policy

        for pos in orphans:
            ticket = getattr(pos, "ticket", None)
            symbol = getattr(pos, "symbol", "?")
            volume = getattr(pos, "volume", 0.0)
            pos_type = getattr(pos, "type", -1)
            direction = "BUY" if pos_type == 0 else "SELL" if pos_type == 1 else "UNKNOWN"

            logger.critical(
                "ORPHAN POSITION DETECTED: ticket=%s symbol=%s direction=%s volume=%.2f — "
                "policy=%s",
                ticket, symbol, direction, volume, policy,
            )

            if policy == "adopt":
                self._adopt_orphan(pos, report)
            elif policy == "close":
                self._close_orphan(pos, report)
            else:
                # Default: alert
                self._alert_orphan(pos, report)

        logger.critical(
            "OrphanRecovery: %d orphan(s) found — adopted=%d flagged=%d policy=%s",
            len(orphans),
            len(report.adopted),
            len(report.flagged),
            policy,
        )
        return report

    # ------------------------------------------------------------------
    # Policy handlers
    # ------------------------------------------------------------------

    def _alert_orphan(self, pos, report: OrphanReport) -> None:
        """
        Alert policy: log CRITICAL, flag for human review.
        Does NOT close or auto-manage the position.
        """
        ticket = getattr(pos, "ticket", None)
        symbol = getattr(pos, "symbol", "?")

        logger.critical(
            "ORPHAN ALERT: ticket=%s symbol=%s — operator must manually resolve via MT5 terminal. "
            "No new trades will be placed for %s until resolved.",
            ticket, symbol, symbol,
        )
        report.flagged.append(pos)

    def _adopt_orphan(self, pos, report: OrphanReport) -> None:
        """
        Adopt policy: reconstruct Position from MT5 data for bot management.
        Parameters are best-effort from the live position fields.
        """
        ticket = getattr(pos, "ticket", None)
        symbol = getattr(pos, "symbol", "")
        pos_type = getattr(pos, "type", -1)
        direction = "BUY" if pos_type == 0 else "SELL" if pos_type == 1 else "UNKNOWN"
        lot_size = getattr(pos, "volume", 0.0)

        reconstructed = Position(
            symbol=symbol,
            direction=direction,
            lot_size=lot_size,
            ticket=ticket or 0,
        )

        logger.warning(
            "ORPHAN ADOPTED: ticket=%s symbol=%s direction=%s volume=%.2f — "
            "parameters are RECONSTRUCTED (not original bot parameters)",
            ticket, symbol, direction, lot_size,
        )
        report.adopted.append(reconstructed)

    def _close_orphan(self, pos, report: OrphanReport) -> None:
        """
        Close policy: send a market order to close the orphan position.
        Logs full details and flags the position regardless of outcome.
        """
        mt5 = _mt5()
        ticket = getattr(pos, "ticket", None)
        symbol = getattr(pos, "symbol", "?")
        volume = getattr(pos, "volume", 0.0)
        pos_type = getattr(pos, "type", -1)

        # Opposite order type to close
        close_type = 1 if pos_type == 0 else 0  # BUY→SELL, SELL→BUY

        logger.warning(
            "ORPHAN CLOSE: attempting market close of ticket=%s symbol=%s volume=%.2f",
            ticket, symbol, volume,
        )

        try:
            tick = mt5.symbol_info_tick(symbol)
            close_price = getattr(tick, "bid", 0.0) if pos_type == 0 else getattr(tick, "ask", 0.0)

            close_request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": close_type,
                "position": ticket,
                "price": close_price,
                "magic": self._config.MAGIC_NUMBER,
                "comment": "OrphanClose",
            }
            result = mt5.order_send(close_request)
            if result and getattr(result, "retcode", 0) == 10009:
                logger.warning(
                    "ORPHAN CLOSED: ticket=%s symbol=%s close_price=%.5f",
                    ticket, symbol, close_price,
                )
            else:
                logger.critical(
                    "ORPHAN CLOSE FAILED: ticket=%s retcode=%s — manual intervention required",
                    ticket,
                    getattr(result, "retcode", "N/A") if result else "None",
                )
        except Exception as exc:
            logger.critical(
                "ORPHAN CLOSE EXCEPTION: ticket=%s error=%s — manual intervention required",
                ticket, exc,
            )

        report.flagged.append(pos)
