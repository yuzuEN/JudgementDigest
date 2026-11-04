"""Guarded legacy law matching, used only for empty main-verdict slots.

Matching routines adapted from f3adff7. Shared entry/context protection is current.
No Git history or audit snapshot is needed at runtime.
"""
import re
import structure_tasks as st
from structure_tasks import (LAW_RE, charge_name_key,
                             unique, specific_substantive_laws)
from law_frequency import ALIASES
from law_label_validation import TRAINING_LAW_RE, training_law_key

CHARGE_AFTER_LAW_RE = re.compile(r"之?([^，、；。]{2,80}罪)(?=[，、；。]|$)")
# Keep the legacy entry vocabulary; only the confirmed 各犯行 boundary is shared.
# Broader new entries belong to the precise matcher, not this case-level fallback.
CONCLUSION_CHARGE_RE = re.compile(r"(?:分別係犯|分別犯|係犯|各犯(?!行(?:時|為|[，。；、]|$))|均犯)")

def clean_law(match: re.Match) -> str:
    name = match.group(1)
    for marker in (
        "分別係犯", "分別犯", "係犯", "共同犯", "違反", "適用", "應依", "依",
        "該罪為", "無論以", "均係",
    ):
        name = name.rsplit(marker, 1)[-1]
    name = re.sub(r"^(?:附錄本案所犯法條全文)?(?:中華民國)?", "", name)
    return name + match.group(0).split(match.group(1), 1)[1]

def extract_laws(reason: str, applicable_laws: str, facts: str = "") -> list[str]:
    found = []
    for text, conclusions_only in ((reason, True), (facts, True), (applicable_laws, False)):
        passages = [
            sentence for sentence in re.split(r"[。；]", text)
            if not conclusions_only or CONCLUSION_CHARGE_RE.search(sentence)
            or ("違反" in sentence and "罪" in sentence)
        ]
        found = specific_substantive_laws([
            clean_law(match) for passage in passages for match in LAW_RE.finditer(passage)
        ])
        if found:
            break
    return unique(found)

def laws_in_text(text: str) -> list[str]:
    """保留片段內明載法條的出現順序。"""
    return specific_substantive_laws([clean_law(match) for match in LAW_RE.finditer(text)])

def legacy_matched_laws(charge: str, standardized: str, main_clause: str,
                 reason: str, facts: str, applicable_laws: str,
                 normalizer=None) -> tuple[list[str], str]:
    """優先回傳同罪名法條，無結果時退回案件層級法條。"""
    direct = laws_in_text(st.conviction_context(main_clause))
    if direct:
        return direct, "主文同子句"
    excluded_laws = set()
    terms = unique(term for term in (charge, standardized, standardized.removesuffix("罪")) if len(term) >= 2)
    for source_name, text, conclusions_only in (
        ("理由", reason, True), ("事實", facts, True), ("適用法條", applicable_laws, False),
    ):
        for passage in re.split(r"[。；]", text):
            if (conclusions_only and not CONCLUSION_CHARGE_RE.search(passage)
                    and not ("違反" in passage and "罪" in passage)):
                continue
            pairs = law_charge_pairs(passage, charge_hint=charge)
            exact_laws = unique(
                law for law, candidate in pairs if charge_name_key(candidate) == charge_name_key(charge)
            )
            paired_laws = exact_laws or unique(
                law for law, candidate in pairs
                if normalizer and standardized and normalizer(candidate) == standardized
            )
            if paired_laws:
                return paired_laws, source_name
            # 已配到其他罪的法條不可因同句出現主文罪名而全部回收。
            if pairs:
                excluded_laws.update(laws_in_text(passage))
                continue
            related_by_text = any(term in passage for term in terms)
            related_by_class = bool(
                normalizer and standardized
                and any(normalizer(candidate) == standardized for candidate in charges_after_laws(passage))
            )
            if not (related_by_text or related_by_class) or "罪" not in passage:
                continue
            laws = laws_in_text(passage)
            if len(laws) == 1:
                return laws, source_name
            # 無法拆清多法條與罪名時留空，也不能再由案件備援收回。
            excluded_laws.update(laws)
    fallback = extract_laws(reason, applicable_laws, facts)
    fallback = [law for law in fallback if not any(
        law == excluded or law.startswith(excluded) or excluded.startswith(law)
        for excluded in excluded_laws
    )]
    if fallback:
        return fallback, "案件法條備援"
    return [], ""

def law_charge_pairs(text: str, charge_hint: str = "") -> list[tuple[str, str]]:
    """把罪名前連續法條歸給該罪，並在下一個罪名後重新開始配對。"""
    pairs = []
    pending_laws = []
    # 省略「罪」只用已知主文罪名作錨點，不把法條後任意敘述當新罪名。
    name = charge_name_key(charge_hint)
    hinted_charge = re.compile(
        rf"之?(?:共同)?({re.escape(name)})(?:罪(?:嫌)?)?(?=[，、；。]|$)"
    ) if len(name) >= 2 else None
    law_matches = list(LAW_RE.finditer(text))
    for index, law_match in enumerate(law_matches):
        law = clean_law(law_match)
        if not law.startswith(("刑事訴訟法", "刑法施行法")):
            pending_laws.append(law)
        segment_end = law_matches[index + 1].start() if index + 1 < len(law_matches) else len(text)
        segment = text[law_match.end():segment_end].rstrip("及與暨")
        charge_match = CHARGE_AFTER_LAW_RE.match(segment)
        if charge_match:
            charge = charge_match.group(1).removeprefix("共同")
            pairs.extend((law, charge) for law in pending_laws)
            pending_laws = []
        elif hinted_charge and hinted_charge.match(segment):
            pairs.extend((law, charge_hint) for law in pending_laws)
            pending_laws = []
        elif not re.fullmatch(r"[，、及與暨]*(?:準用)?", segment):
            # 遇到未解析的罪名／敘述就停止承接，避免把前罪法條掛到後罪。
            pending_laws = []
    return pairs

def charges_after_laws(text: str) -> list[str]:
    """回傳同一片段內各法條所對應的明載罪名。"""
    return unique(charge for _, charge in law_charge_pairs(text))

def citation(raw):
    """Compare full law/article/subarticle identities; optional units remain optional."""
    text = st.compact(raw)
    match = TRAINING_LAW_RE.fullmatch(text)
    if not match:
        return None
    law = ALIASES.get(match['law'], match['law'])
    tail = st.law_citation_key(text[match.end('law'):])
    parts = re.fullmatch(r'第(\d+)條(?:之(\d+))?(?:第(\d+)項)?(?:第(\d+)款)?', tail)
    return (law, *parts.groups()) if parts else None

def overlaps(left, right):
    return bool(left and right and left[:3] == right[:3]
                and all(a is None or b is None or a == b for a, b in zip(left[3:], right[3:])))

def try_fallback(args, state):
    charge, standard, clause, reason, facts, applicable = args[:6]
    extra = args[7]
    normalizer = args[6]
    audit = dict(charge=charge, legacy_raw=[], legacy_source='', reasons=[], evidence=[])
    if not clause:
        audit['reasons'] = ['no_main_verdict_offense']
        return [], audit
    if state['candidates']:
        audit['reasons'] = ['new_candidate_ambiguity']
        return [], audit
    sources = st.law_matching_sources(reason, facts, applicable, extra)
    accepted = {}; blocked = []; paired = []
    for label, text, conclusions_only, allowed in sources:
        if allowed is not None:
            continue  # No new relaxation of attachment adoption in fallback.
        passages = list(st.conviction_passages(text, conclusions_only))
        accepted[label] = '。'.join(passages)
        for passage in passages:
            paired.extend(st.law_charge_pairs(passage, charge_hint=charge))
        for sentence in re.split(r'[。；]', text):
            if not (st.REJECTED_CONVICTION_RE.search(sentence) or st.PROSECUTION_CLAIM_RE.search(sentence)):
                continue
            rejected = sentence
            for passage in st.conviction_passages(sentence, False):
                rejected = rejected.replace(passage, '', 1)
            blocked.extend(st.laws_in_text(rejected))
    # Use the old matcher on the new accepted court text, retaining the new main slot.
    # shortcut: legacy case-level candidates can still mix articles across offenses;
    # retain provenance and the fixed-sample error report until a pairing fix is authorized.
    laws, source = legacy_matched_laws(charge, normalizer(charge), clause,
                                  accepted.get('理由', ''), accepted.get('事實', ''),
                                  accepted.get('適用法條', ''), normalizer)
    audit.update(legacy_raw=laws, legacy_source=source)
    if not laws:
        audit['reasons'] = ['legacy_no_match_in_accepted_court_text']
        return [], audit
    if any(training_law_key(law)[1] for law in laws):
        audit['reasons'].append('legacy_unparsed_law_string')
    for law in laws:
        identity = citation(law)
        if any(overlaps(identity, citation(other)) for other in blocked):
            audit['reasons'].append('law_in_rejected_claim_or_negative_passage')
        if any(overlaps(identity, citation(other)) for other in state['incomplete_parallel_laws']):
            audit['reasons'].append('new_incomplete_parallel_assignment')
        if any(overlaps(identity, citation(other)) and not st.charge_matches_law(charge, name, other)
               for other, name in paired):
            audit['reasons'].append('new_parsed_different_offense')
        for label, text in accepted.items():
            for passage in text.split('。'):
                if any(overlaps(identity, citation(other)) for other in st.laws_in_text(passage)):
                    audit['evidence'].append(dict(law=law, source=label, passage=passage))
    audit['reasons'] = st.unique(audit['reasons'])
    return ([] if audit['reasons'] else laws), audit
