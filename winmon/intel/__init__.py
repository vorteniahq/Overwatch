"""Intelligence layer — analysis primitives shared by monitors."""

from winmon.intel.process_analysis import (
    analyse_process, get_parent_chain, score_command_line,
    classify_signing, score_path,
)
from winmon.intel.attack_map import (
    ATTACK_TECHNIQUES, technique_name, technique_url,
)
from winmon.intel.friendly import friendly_summary
from winmon.intel.away_mode import maybe_escalate, SNOOP_CATEGORIES

__all__ = [
    "analyse_process", "get_parent_chain", "score_command_line",
    "classify_signing", "score_path",
    "ATTACK_TECHNIQUES", "technique_name", "technique_url",
    "friendly_summary",
    "maybe_escalate", "SNOOP_CATEGORIES",
]
