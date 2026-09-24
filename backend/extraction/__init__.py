import logging

from backend.config import Settings, get_settings

log = logging.getLogger(__name__)


def get_extractor(settings: Settings | None = None):
    """LayoutLMv3 if a checkpoint is configured and loadable, else the rule-based baseline."""
    from backend.extraction.heuristic import HeuristicExtractor

    s = settings or get_settings()
    if s.layoutlm_model_path:
        try:
            from backend.extraction.layoutlm import LayoutLMv3Extractor
            return LayoutLMv3Extractor(s.layoutlm_model_path)
        except Exception as e:  # noqa: BLE001
            log.warning("LayoutLMv3 unavailable (%s); using heuristic extractor", e)
    return HeuristicExtractor()
