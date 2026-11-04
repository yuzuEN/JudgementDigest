"""Shared full-citation validation for extraction and training eligibility."""
import re
from law_frequency import LAW_ARTICLE_RE, extract_law_keys
from structure_tasks import LAW_REFERENCE_NAMES, NUM, chinese_number

# Validate the entire citation, not a recognized law hidden inside leftover prose.
# This uses the existing law-name parser, not normalize.LAW_WHITELIST's frequency list.
TRAINING_LAW_RE = re.compile(
    LAW_ARTICLE_RE.pattern + rf'(?:之[{NUM}]+)?(?:第[{NUM}]+項)?(?:第[{NUM}]+款)?'
)


def training_law_key(raw):
    """Return a parseable main-article key or an audit reason; never guess a law name."""
    if not isinstance(raw, str) or not raw.strip():
        return None, 'empty_or_invalid_law_string'
    text = re.sub(r'\s+', '', raw)
    if text.startswith(LAW_REFERENCE_NAMES) or text.startswith('條例第'):
        return None, 'unresolved_law_reference'
    if not TRAINING_LAW_RE.fullmatch(text):
        reason = 'law_string_residue' if extract_law_keys(text) else 'unrecognized_law_name_or_format'
        return None, reason
    if any(chinese_number(number) <= 0 for number in re.findall(rf'[{NUM}]+', text)):
        return None, 'invalid_law_number'
    return extract_law_keys(text)[0], None

