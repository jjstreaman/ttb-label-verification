"""Deterministic matching rules.

Fuzzy matching is used for free-text descriptive fields where human judgment
tolerates formatting differences (the "STONE'S THROW" vs "Stone's Throw"
case a senior agent flagged in stakeholder interviews). The government
warning statement is checked with strict, exact text comparison instead,
because partial or reworded reproductions are exactly what agents are
trained to reject -- an LLM's fuzzy judgment is the wrong tool for a hard
compliance boundary, so that check is deterministic, auditable code.
"""

import re

from rapidfuzz import fuzz

from models import ApplicationData, ExtractedLabel, FieldResult

FUZZY_MATCH_THRESHOLD = 88
ABV_TOLERANCE_PERCENT = 0.3

# 27 CFR 16.21 -- identical wording is mandatory on all alcohol beverage labels.
REQUIRED_WARNING_TEXT = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should "
    "not drink alcoholic beverages during pregnancy because of the risk of "
    "birth defects. (2) Consumption of alcoholic beverages impairs your "
    "ability to drive a car or operate machinery, and may cause health "
    "problems."
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_loose(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9%.]+", " ", text)
    return _normalize_whitespace(text)


def _fuzzy_field(name: str, submitted: str, extracted: str) -> FieldResult:
    score = fuzz.token_sort_ratio(_normalize_loose(submitted), _normalize_loose(extracted))
    return FieldResult(
        field=name,
        submitted=submitted,
        extracted=extracted,
        match=score >= FUZZY_MATCH_THRESHOLD,
        method="fuzzy",
        detail=f"similarity {score:.0f}/100 (threshold {FUZZY_MATCH_THRESHOLD})",
    )


def _abv_value(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1))
    match = re.search(r"(\d+(?:\.\d+)?)\s*proof", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 2
    return None


def _match_abv(submitted: str, extracted: str) -> FieldResult:
    sub_val = _abv_value(submitted)
    ext_val = _abv_value(extracted)
    if sub_val is None or ext_val is None:
        # Couldn't parse a number out of one side -- fall back to text comparison
        # rather than silently passing/failing.
        return _fuzzy_field("alcohol_content", submitted, extracted)

    within_tolerance = abs(sub_val - ext_val) <= ABV_TOLERANCE_PERCENT
    return FieldResult(
        field="alcohol_content",
        submitted=submitted,
        extracted=extracted,
        match=within_tolerance,
        method="numeric_tolerance",
        detail=f"{sub_val}% vs {ext_val}% (tolerance ±{ABV_TOLERANCE_PERCENT}%)",
    )


def _match_country_of_origin(submitted: str, extracted: str) -> FieldResult:
    norm_sub = _normalize_loose(submitted)
    norm_ext = _normalize_loose(extracted)

    if not norm_sub and not norm_ext:
        return FieldResult(
            field="country_of_origin",
            submitted=submitted,
            extracted=extracted,
            match=True,
            method="fuzzy",
            detail="Not applicable on either side (expected for domestic products).",
        )

    # Containment, not a straight ratio: labels commonly print "Product of
    # Italy" or "Made in Italy" while the application just says "Italy" --
    # token_sort_ratio penalizes that length mismatch even though the
    # country itself matches exactly.
    if norm_sub and norm_sub in norm_ext:
        return FieldResult(
            field="country_of_origin",
            submitted=submitted,
            extracted=extracted,
            match=True,
            method="fuzzy",
            detail="Submitted country found in label text.",
        )
    return _fuzzy_field("country_of_origin", submitted, extracted)


def _match_warning(extracted_text: str, heading_caps_bold: bool) -> FieldResult:
    # Case-insensitive: many real labels print the entire statement in caps
    # as a style choice, which is compliant. The regulation's all-caps
    # requirement applies specifically to the "GOVERNMENT WARNING:" heading
    # (checked separately via heading_caps_bold) -- comparing the full body
    # case-sensitively would reject correct labels on casing alone, when
    # what actually must be exact is the wording and punctuation.
    normalized_extracted = _normalize_whitespace(extracted_text).lower()
    normalized_required = _normalize_whitespace(REQUIRED_WARNING_TEXT).lower()

    text_matches = normalized_extracted == normalized_required
    ok = text_matches and heading_caps_bold

    if not extracted_text.strip():
        detail = "No warning statement detected on label."
    elif not text_matches:
        detail = "Warning text does not match the required statement verbatim."
    elif not heading_caps_bold:
        detail = "Warning text matches, but 'GOVERNMENT WARNING:' heading is not all-caps and bold."
    else:
        detail = "Exact match."

    return FieldResult(
        field="warning_statement",
        submitted=REQUIRED_WARNING_TEXT,
        extracted=extracted_text,
        match=ok,
        method="exact",
        detail=detail,
    )


def verify_fields(application: ApplicationData, extracted: ExtractedLabel) -> list[FieldResult]:
    return [
        _fuzzy_field("brand_name", application.brand_name, extracted.brand_name),
        _fuzzy_field("class_type", application.class_type, extracted.class_type),
        _match_abv(application.alcohol_content, extracted.alcohol_content),
        _fuzzy_field("net_contents", application.net_contents, extracted.net_contents),
        _fuzzy_field("name_and_address", application.name_and_address, extracted.name_and_address),
        _match_country_of_origin(application.country_of_origin, extracted.country_of_origin),
        _match_warning(extracted.warning_statement_text, extracted.warning_heading_is_caps_bold),
    ]


def overall_verdict(results: list[FieldResult]) -> str:
    if all(r.match for r in results):
        return "PASS"
    if not any(r.match for r in results):
        return "FAIL"
    return "NEEDS REVIEW"
