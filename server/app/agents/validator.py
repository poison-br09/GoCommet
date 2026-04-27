import json
import re

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.config import settings
from app.core.logger import get_logger
from app.schemas.extraction import ExtractionOutput
from app.schemas.validation import FieldValidation

log = get_logger(__name__)
openai_client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())

CUSTOMER_RULE_SET: dict[str, str] = {
    "port_of_discharge": "Los Angeles",
    "incoterms": "CIF",
}

LOW_CONFIDENCE_THRESHOLD = 0.6


class _ValidationOutput(BaseModel):
    results: list[FieldValidation]


_VALIDATOR_SYSTEM = """\
You are a trade document compliance validator. Your job is to check specific fields \
extracted from a shipping document against a customer's contractual requirements and \
determine whether each field matches, mismatches, or is uncertain.\
"""


def _build_validator_prompt(
    field_lines: str,
    confidence: float | None,
) -> str:
    return f"""\
Check the extracted fields below against the contractual requirements and return a \
validation status for each field.

━━━ EXTRACTED FIELDS vs REQUIREMENTS ━━━

{field_lines}

Global extraction confidence score: {confidence}

━━━ STATUS DEFINITIONS ━━━

"match"
  The found value clearly satisfies the required value, accounting for acceptable variations:
  - Port names: treat common abbreviations and qualifiers as equivalent to the city name —
    "USLAX", "LA", "LA/LB", "Port of Los Angeles", "Los Angeles, CA" all match "Los Angeles".
  - Minor differences in spacing, punctuation, or casing do not constitute a mismatch.

"mismatch"
  The found value is present and clearly does not satisfy the required value.

"uncertain"
  Use when:
  - The found value is null or empty.
  - The per-field extraction confidence is below {LOW_CONFIDENCE_THRESHOLD} — the extractor \
was not confident enough in this specific field to trust it.
  - The value is ambiguous and cannot be reliably compared to the requirement.

━━━ OUTPUT RULES ━━━
- Return exactly one result per field listed above.
- Set found_value and expected_value exactly as provided in the field list above.
- Do not add, remove, or rename fields.\
"""


# ── deterministic fallback ────────────────────────────────────────────────────

def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.lower())).strip()


def _location_matches(found: str, expected: str) -> bool:
    nf, ne = _normalize(found), _normalize(expected)
    return nf == ne or nf.startswith(f"{ne} ")


def _field_matches(field_name: str, found: str, expected: str) -> bool:
    if field_name in {"port_of_loading", "port_of_discharge"}:
        return _location_matches(found, expected)
    return _normalize(found) == _normalize(expected)


def _deterministic_validate(extraction: ExtractionOutput) -> list[FieldValidation]:
    results: list[FieldValidation] = []
    for field_name, expected_value in CUSTOMER_RULE_SET.items():
        field_obj = getattr(extraction, field_name)
        found_value = field_obj.value
        field_confidence = field_obj.confidence
        low_confidence = (
            (field_confidence is not None and field_confidence < LOW_CONFIDENCE_THRESHOLD)
            or (extraction.global_confidence_score is not None
                and extraction.global_confidence_score < LOW_CONFIDENCE_THRESHOLD)
        )
        if found_value is None or low_confidence:
            status = "uncertain"
        elif _field_matches(field_name, found_value, expected_value):
            status = "match"
        else:
            status = "mismatch"
        results.append(FieldValidation(
            field_name=field_name,
            status=status,
            found_value=found_value,
            expected_value=expected_value,
        ))
    return results


# ── main agent ────────────────────────────────────────────────────────────────

async def run_validator(extraction: ExtractionOutput) -> list[FieldValidation]:
    log.info(
        "validator  START  |  global_confidence=%s  model=gpt-4o-mini",
        extraction.global_confidence_score,
    )

    field_lines = "\n".join(
        f'  • {field}: found {json.dumps(getattr(extraction, field).value)}'
        f'  (extraction confidence: {getattr(extraction, field).confidence})'
        f'  —  required "{required}"'
        for field, required in CUSTOMER_RULE_SET.items()
    )

    try:
        response = await openai_client.responses.parse(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": _VALIDATOR_SYSTEM},
                {"role": "user", "content": _build_validator_prompt(field_lines, extraction.global_confidence_score)},
            ],
            text_format=_ValidationOutput,
            temperature=0.0,
            max_output_tokens=400,
        )
    except Exception as exc:
        log.exception("validator  LLM_FAIL  |  falling back to deterministic: %s", exc)
        return _deterministic_validate(extraction)

    output = response.output_parsed
    if output is None or not output.results:
        log.warning("validator  LLM_EMPTY  |  falling back to deterministic")
        return _deterministic_validate(extraction)

    validation_results = output.results
    for r in validation_results:
        log.info(
            "validator  FIELD  |  field=%s  found=%r  expected=%r  status=%s",
            r.field_name, r.found_value, r.expected_value, r.status,
        )

    log.info(
        "validator  DONE   |  results=%s",
        [{"field": r.field_name, "status": r.status} for r in validation_results],
    )
    return validation_results
