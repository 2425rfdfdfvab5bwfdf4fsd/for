"""
Risk/Reward Validator — Task 07-03.

Performs an independent final check that the calculated R:R ratio meets the
configured minimum threshold.  Separation from SLTPCalculator ensures no
single code path can inadvertently bypass the R:R constraint.
"""

from app.config import Config
from app.database.models import RRValidationResult, SLTPResult
from app.logger import get_logger

logger = get_logger(__name__)


class RRValidator:
    """
    Independent R:R validator — the last structural check before sizing.

    Usage:
        validator = RRValidator(config)
        result = validator.validate(sltp_result)
        if not result.approved:
            log_rejection(result.reason)
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    def validate(self, sltp_result: SLTPResult) -> RRValidationResult:
        """
        Verify that the SLTPResult's R:R ratio meets the minimum threshold.

        Logic:
            actual_rr = sltp_result.tp2_pips / sltp_result.sl_pips
            if actual_rr < MIN_RR_RATIO: REJECTED

        Args:
            sltp_result: Output of SLTPCalculator.calculate().

        Returns:
            RRValidationResult — approved=False when the ratio is below threshold.
        """
        required_rr = self._config.MIN_RR_RATIO

        # Guard: zero or negative SL pips cannot produce a meaningful ratio
        if sltp_result.sl_pips <= 0.0:
            logger.warning(
                "RRValidator: sl_pips=%.4f is not positive — rejected",
                sltp_result.sl_pips,
            )
            return RRValidationResult(
                approved=False,
                actual_rr=0.0,
                required_rr=required_rr,
                reason="ZERO_SL_PIPS",
            )

        actual_rr = sltp_result.tp2_pips / sltp_result.sl_pips
        actual_rr = round(actual_rr, 4)

        if actual_rr < required_rr:
            logger.info(
                "RRValidator: REJECTED | actual_rr=%.2f < required=%.2f",
                actual_rr, required_rr,
            )
            return RRValidationResult(
                approved=False,
                actual_rr=actual_rr,
                required_rr=required_rr,
                reason="INSUFFICIENT_RR",
            )

        logger.debug(
            "RRValidator: APPROVED | actual_rr=%.2f >= required=%.2f",
            actual_rr, required_rr,
        )
        return RRValidationResult(
            approved=True,
            actual_rr=actual_rr,
            required_rr=required_rr,
            reason=None,
        )
