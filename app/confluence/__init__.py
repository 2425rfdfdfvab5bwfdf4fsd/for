"""
Confluence Engine — Phase 06

Public API:
    ConfluenceFactor        Enum of the ten scored factors
    ConfluenceScorer        Multi-factor scorer → ScoredSignal
    MarketContext           Supplemental data for the scorer
    TradeQualityClassifier  A+/A/B/REJECTED grade assignment
    SignalDeduplicator      Prevents duplicate scoring within a window
"""

from app.confluence.factors import ConfluenceFactor
from app.confluence.scorer import ConfluenceScorer, MarketContext
from app.confluence.quality_classifier import TradeQualityClassifier
from app.confluence.deduplication import SignalDeduplicator

__all__ = [
    "ConfluenceFactor",
    "ConfluenceScorer",
    "MarketContext",
    "TradeQualityClassifier",
    "SignalDeduplicator",
]
