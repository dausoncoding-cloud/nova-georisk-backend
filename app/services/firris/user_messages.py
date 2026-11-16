"""Plan 4.2 (small part): which run failures may be shown to users verbatim.

Only FIRRISQualityError messages that exactly match an allow-listed, plain-language pattern are
surfaced in a task's error_summary. Everything else keeps the generic message; the raw exception
stays server-side in error_message.
"""
from __future__ import annotations

import re

GENERIC_FAILURE = "Analysis execution failed. Please retry or contact support with the request ID."
_DAY = r"\d{1,2}(?: (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)(?: \d{4})?)?"
_LAST = r"\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}"
ALLOWED = (
    # P6: inclusive wording ("between 21 and 22 May 2024", "on 21 May 2024"), see app/services/reporting/dates.py.
    re.compile(rf"No Sentinel-1 scene over the area (?:between {_DAY} and {_LAST}|on {_LAST})\."),
    re.compile(r"The target and baseline windows must each contain Sentinel-1 passes from exactly one relative orbit, "
               r"the same in both \(target: (?:[0-9]+(?:, [0-9]+)*|none); baseline: (?:[0-9]+(?:, [0-9]+)*|none)\)\."),
    re.compile(r"Valid pixel coverage \d+\.\d{2}% is below the configured \d+\.\d{2}% threshold\.?"),
)


def public_error_summary(error: BaseException) -> str:
    from app.services.gee.firris_pipeline import FIRRISQualityError

    message = str(error)
    if isinstance(error, FIRRISQualityError) and any(pattern.fullmatch(message) for pattern in ALLOWED):
        return message
    return GENERIC_FAILURE
