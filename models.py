"""Shared data structures for label verification."""

from dataclasses import dataclass, field


@dataclass
class ApplicationData:
    """What the applicant submitted on the COLA application form."""

    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    name_and_address: str
    # Only required for imports (27 CFR) -- domestic products legitimately
    # have no country of origin printed anywhere, so this defaults empty
    # rather than being treated as always-required like the fields above.
    country_of_origin: str = ""


@dataclass
class ExtractedLabel:
    """What Claude read off the physical label image."""

    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str
    name_and_address: str
    warning_statement_text: str
    warning_heading_is_caps_bold: bool
    country_of_origin: str = ""
    notes: str = ""


@dataclass
class FieldResult:
    field: str
    submitted: str
    extracted: str
    match: bool
    method: str  # "fuzzy" | "exact" | "numeric_tolerance"
    detail: str = ""


@dataclass
class VerificationResult:
    filename: str
    overall: str  # "PASS" | "FAIL" | "NEEDS REVIEW" | "ERROR"
    fields: list[FieldResult] = field(default_factory=list)
    latency_seconds: float = 0.0
    error: str | None = None
