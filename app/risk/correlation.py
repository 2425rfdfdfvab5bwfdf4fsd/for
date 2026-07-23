"""
Correlation Filter — Task 07-06.

Blocks new trades when existing open positions create excessive directional
exposure across correlated currency pairs.

Correlation rules (CHG-015):
  EURUSD + GBPUSD: HIGHLY CORRELATED — same direction blocked (hard rule)
  EURUSD + USDJPY: INVERSELY CORRELATED — configurable (default: allow)
  GBPUSD + USDJPY: configurable (default: allow)
  SAME PAIR: ALWAYS blocked — no two positions in the same symbol

All rules are driven by config — no hardcoded logic beyond the structural pair
knowledge embedded in the correlation map.
"""

from __future__ import annotations

from typing import Optional

from app.config import Config
from app.database.models import CorrelationCheckResult, Position
from app.logger import get_logger

logger = get_logger(__name__)


class CorrelationFilter:
    """
    Checks whether a proposed trade is correlated with any open position.

    Usage:
        filt = CorrelationFilter(config)
        result = filt.check(proposed_signal, open_positions)
        if not result.allowed:
            reject_trade(result.reason)
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._correlation_map = self._build_correlation_map(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        proposed_signal,            # TradeSetup or any object with .symbol and .direction
        open_positions: list,       # list[Position]
    ) -> CorrelationCheckResult:
        """
        Check whether the proposed trade creates correlated exposure.

        Logic:
          1. Same symbol already open → always blocked.
          2. For each open position, check if (open.symbol, open.direction)
             appears in the correlation map for (proposed.symbol, proposed.direction).
          3. If correlated positions >= MAX_CORRELATED_POSITIONS → blocked.

        Args:
            proposed_signal: Signal/setup with .symbol and .direction attributes.
            open_positions:  List of currently open Position objects.

        Returns:
            CorrelationCheckResult — allowed=False with reason when blocked.
        """
        proposed_symbol = proposed_signal.symbol
        proposed_dir = proposed_signal.direction
        max_corr = self._config.MAX_CORRELATED_POSITIONS

        correlated_count = 0
        first_correlated: Optional[str] = None

        for pos in open_positions:
            # Rule 1: same symbol already open
            if pos.symbol == proposed_symbol:
                logger.info(
                    "CorrelationFilter: SAME_PAIR_OPEN | %s already has an open %s position",
                    proposed_symbol, pos.direction,
                )
                return CorrelationCheckResult(
                    allowed=False,
                    correlated_with=pos.symbol,
                    reason="SAME_PAIR_OPEN",
                )

            # Rule 2: check correlation map
            corr_key = (proposed_symbol, proposed_dir)
            blocking_pair = (pos.symbol, pos.direction)
            if blocking_pair in self._correlation_map.get(corr_key, set()):
                correlated_count += 1
                if first_correlated is None:
                    first_correlated = pos.symbol
                logger.debug(
                    "CorrelationFilter: correlated pair found | proposed=%s %s | blocking=%s %s",
                    proposed_symbol, proposed_dir, pos.symbol, pos.direction,
                )

        if correlated_count >= max_corr:
            logger.info(
                "CorrelationFilter: CORRELATED_POSITION | %s %s blocked by %s "
                "correlated_count=%d >= max=%d",
                proposed_symbol, proposed_dir, first_correlated,
                correlated_count, max_corr,
            )
            return CorrelationCheckResult(
                allowed=False,
                correlated_with=first_correlated,
                reason="CORRELATED_POSITION",
            )

        return CorrelationCheckResult(allowed=True, reason=None)

    # ------------------------------------------------------------------
    # Correlation map builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_correlation_map(config: Config) -> dict:
        """
        Build a dict mapping (symbol, direction) → set of blocking (symbol, direction) pairs.

        Structural rules (hard):
          EURUSD BUY  ↔ GBPUSD BUY   (same USD direction)
          EURUSD SELL ↔ GBPUSD SELL

        Configurable rules:
          EURUSD + USDJPY: controlled by BLOCK_USDJPY_WITH_EURUSD
          GBPUSD + USDJPY: controlled by BLOCK_USDJPY_WITH_GBPUSD
        """
        # Hard structural rules — EURUSD/GBPUSD
        cmap: dict = {
            ("EURUSD", "BUY"):  {("GBPUSD", "BUY")},
            ("EURUSD", "SELL"): {("GBPUSD", "SELL")},
            ("GBPUSD", "BUY"):  {("EURUSD", "BUY")},
            ("GBPUSD", "SELL"): {("EURUSD", "SELL")},
        }

        # Optional USDJPY correlation blocking
        if config.BLOCK_USDJPY_WITH_EURUSD:
            # EURUSD LONG + USDJPY LONG = same USD exposure (USD weakens in both)
            cmap[("EURUSD", "BUY")].add(("USDJPY", "BUY"))
            cmap[("EURUSD", "SELL")].add(("USDJPY", "SELL"))
            cmap.setdefault(("USDJPY", "BUY"), set()).add(("EURUSD", "BUY"))
            cmap.setdefault(("USDJPY", "SELL"), set()).add(("EURUSD", "SELL"))

        if config.BLOCK_USDJPY_WITH_GBPUSD:
            cmap[("GBPUSD", "BUY")].add(("USDJPY", "BUY"))
            cmap[("GBPUSD", "SELL")].add(("USDJPY", "SELL"))
            cmap.setdefault(("USDJPY", "BUY"), set()).add(("GBPUSD", "BUY"))
            cmap.setdefault(("USDJPY", "SELL"), set()).add(("GBPUSD", "SELL"))

        return cmap
