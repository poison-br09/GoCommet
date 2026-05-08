from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logger import get_logger
from app.schemas.routing import RouterDecision
from app.schemas.validation import FieldValidation

log = get_logger(__name__)
openai_client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())

_ROUTER_SYSTEM = """\
You are an amendment-request email drafting agent for a trade-document processing system. \
Your sole task is to produce a structured amendment decision containing a professional \
email to the Shipping Unit requesting corrections to a shipping document.\
"""


def _route_from_validation_results(validation_results: list[FieldValidation]) -> str:
    statuses = {item.status for item in validation_results}
    if "mismatch" in statuses:
        return "draft_amendment"
    if "uncertain" in statuses:
        return "flag_for_review"
    return "auto_approve"


def _flagged(validation_results: list[FieldValidation]) -> list[FieldValidation]:
    return [item for item in validation_results if item.status != "match"]


def _build_amendment_email(validation_results: list[FieldValidation]) -> str:
    discrepancy_lines = "\n".join(
        f'  - {item.field_name}: found "{item.found_value}" - expected "{item.expected_value}" ({item.status})'
        for item in _flagged(validation_results)
    )
    return (
        "Subject: Amendment Request - Shipping Document Discrepancy\n\n"
        "Dear Shipping Unit,\n\n"
        "We have reviewed the submitted shipping document set and identified the following "
        "items that require correction or confirmation before approval:\n\n"
        f"{discrepancy_lines}\n\n"
        "Please issue corrected documents or confirm the uncertain values at your earliest convenience.\n\n"
        "Thank you for your prompt attention to this matter.\n\n"
        "GoComet Trade Compliance Team"
    )


def _fallback_amendment_decision(validation_results: list[FieldValidation]) -> RouterDecision:
    mismatched_fields = ", ".join(item.field_name for item in _flagged(validation_results))
    return RouterDecision(
        decision="draft_amendment",
        reasoning=f"The field(s) {mismatched_fields} require correction or confirmation before approval.",
        draft_email=_build_amendment_email(validation_results),
    )


async def run_router(validation_results: list[FieldValidation]) -> RouterDecision:
    expected_decision = _route_from_validation_results(validation_results)
    log.info(
        "router  START  |  pre_decision=%s  inputs=%s",
        expected_decision,
        [{"field": r.field_name, "status": r.status} for r in validation_results],
    )

    if expected_decision == "auto_approve":
        decision = RouterDecision(decision="auto_approve", reasoning="All validation checks matched.", draft_email=None)
        log.info("router  DONE  |  decision=auto_approve")
        return decision

    if expected_decision == "flag_for_review":
        uncertain_fields = [item.field_name for item in validation_results if item.status == "uncertain"]
        decision = RouterDecision(
            decision="flag_for_review",
            reasoning=(
                "Manual review required because these fields are uncertain: "
                f"{', '.join(uncertain_fields)}."
            ),
            draft_email=_build_amendment_email(validation_results),
        )
        log.info("router  DONE  |  decision=flag_for_review  uncertain_fields=%s", uncertain_fields)
        return decision

    mismatched = [item for item in validation_results if item.status == "mismatch"]
    mismatch_data = "\n".join(
        f'  • {item.field_name}: found "{item.found_value}" — expected "{item.expected_value}"'
        for item in mismatched
    )
    _ROUTER_USER = f"""\
A shipping document has been validated. The following fields do not match the required values:

{mismatch_data}

Using the discrepancies above, produce a structured amendment request.

━━━ OUTPUT REQUIREMENTS ━━━

decision
  Must be exactly "draft_amendment". Do not change this value under any circumstances.

reasoning
  1–2 sentences. Explicitly name each mismatched field and state that a corrected document \
is required. Do not use generic language like "some fields mismatched".

draft_email
  Compose a professional amendment request email to the Shipping Unit using the discrepancy \
data above. Requirements:
  - Subject line: "Amendment Request — Shipping Document Discrepancy"
  - Open with: "Dear Shipping Unit,"
  - State that the document was reviewed and discrepancies were found against contractual requirements.
  - List each discrepancy from the data above, one per line, in this exact format:
      • [field_name]: found "[found_value]" — expected "[expected_value]"
  - Request that a corrected document be issued at the earliest convenience.
  - Close with: "Thank you for your prompt attention to this matter."
  - Sign off as: "GoComet Trade Compliance Team"
  - Body must be under 200 words.
  - No apologies, filler phrases, or commentary beyond the structure above.\
"""

    log.info("router  OpenAI_CALL  |  model=gpt-4o-mini  mismatched_fields=%s", [m.field_name for m in mismatched])

    try:
        response = await openai_client.responses.parse(
            model="gpt-4o-mini",
            input=[
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user", "content": _ROUTER_USER},
            ],
            text_format=RouterDecision,
            temperature=0.0,
            max_output_tokens=600,
        )
    except Exception as exc:
        log.exception("router  OpenAI_FAIL  |  falling back to template email: %s", exc)
        return _fallback_amendment_decision(validation_results)

    routing_decision = response.output_parsed
    if routing_decision is None:
        log.warning("router  OpenAI_EMPTY  |  falling back to template email")
        return _fallback_amendment_decision(validation_results)

    result = RouterDecision(
        decision="draft_amendment",
        reasoning=routing_decision.reasoning,
        draft_email=routing_decision.draft_email or _build_amendment_email(validation_results),
    )
    log.info(
        "router  DONE  |  decision=draft_amendment  reasoning=%r  draft_email_chars=%d",
        result.reasoning,
        len(result.draft_email or ""),
    )
    log.debug("router  DRAFT_EMAIL  |\n%s", result.draft_email)
    return result
