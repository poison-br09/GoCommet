import asyncio
import base64
import mimetypes
import re
from pathlib import Path

import httpx
from mistralai.client import Mistral, models
from openai import AsyncOpenAI

from app.core.config import settings
from app.core.logger import get_logger
from app.schemas.extraction import ExtractionOutput

log = get_logger(__name__)

openai_client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())
mistral_client = Mistral(
    api_key=settings.mistral_api_key.get_secret_value(),
    timeout_ms=120_000,
)

_TABLE_REF = re.compile(r'\[([^\]]+\.md)\]\([^\)]+\)')
_NETWORK_RETRY_DELAYS = (1.0, 2.0, 4.0)


async def _with_network_retries(operation_name: str, awaitable_factory):
    last_exc: Exception | None = None
    for attempt, delay in enumerate((0.0, *_NETWORK_RETRY_DELAYS), start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            return await awaitable_factory()
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_exc = exc
            log.warning(
                "%s  NETWORK_RETRY  |  attempt=%d/%d  error=%s",
                operation_name,
                attempt,
                len(_NETWORK_RETRY_DELAYS) + 1,
                exc,
            )

    raise RuntimeError(
        f"{operation_name} failed after retries. Check internet/DNS connectivity "
        f"from the backend process and verify MISTRAL_API_KEY. Last error: {last_exc}"
    ) from last_exc


def _inline_tables(page_markdown: str, images: list) -> str:
    """Replace [tbl-X.md](tbl-X.md) placeholders with the actual markdown table content."""
    table_map: dict[str, str] = {}
    for img in images or []:
        if img.id and img.id.endswith(".md") and img.image_base64:
            try:
                table_map[img.id] = base64.b64decode(img.image_base64).decode("utf-8")
                log.debug("Mistral OCR  TABLE_DECODED  |  id=%s  chars=%d", img.id, len(table_map[img.id]))
            except Exception as exc:
                log.warning("Mistral OCR  TABLE_DECODE_FAIL  |  id=%s  error=%s", img.id, exc)

    if not table_map:
        return page_markdown

    def _replace(match: re.Match) -> str:
        table_id = match.group(1)
        content = table_map.get(table_id)
        if content:
            log.debug("Mistral OCR  TABLE_INLINED  |  id=%s", table_id)
            return content
        log.warning("Mistral OCR  TABLE_MISSING  |  id=%s not found in response", table_id)
        return match.group(0)

    return _TABLE_REF.sub(_replace, page_markdown)


async def run_mistral_ocr(raw_document_path: str) -> str:
    document_path = Path(raw_document_path)
    if not document_path.is_file():
        raise FileNotFoundError(f"Document not found: {raw_document_path}")

    document_bytes = document_path.read_bytes()
    content_type = mimetypes.guess_type(document_path.name)[0] or "application/octet-stream"
    log.info(
        "Mistral OCR  UPLOAD  |  file=%s  size=%d bytes  content_type=%s",
        document_path.name, len(document_bytes), content_type,
    )

    uploaded_file = await _with_network_retries(
        "Mistral OCR upload",
        lambda: mistral_client.files.upload_async(
            file=models.File(
                file_name=document_path.name,
                content=document_bytes,
                content_type=content_type,
            ),
            purpose="ocr",
        ),
    )
    log.debug("Mistral OCR  FILE_ID  |  file_id=%s", uploaded_file.id)

    ocr_response = await _with_network_retries(
        "Mistral OCR process",
        lambda: mistral_client.ocr.process_async(
            model="mistral-ocr-latest",
            document={"type": "file", "file_id": uploaded_file.id},
            include_image_base64=True,  # required to retrieve embedded table content
        ),
    )

    pages_markdown: list[str] = []
    for page in sorted(ocr_response.pages, key=lambda p: p.index):
        images = page.images or []
        log.debug(
            "Mistral OCR  PAGE  |  page=%d  images=%d  table_refs=%s",
            page.index,
            len(images),
            _TABLE_REF.findall(page.markdown or ""),
        )
        for img in images:
            log.debug(
                "Mistral OCR  IMAGE  |  page=%d  id=%r  has_base64=%s",
                page.index, img.id, img.image_base64 is not None,
            )
        page_md = _inline_tables(page.markdown or "", images)
        if page_md.strip():
            pages_markdown.append(page_md.strip())

    markdown = "\n\n".join(pages_markdown)
    if not markdown:
        raise ValueError("Empty OCR response from Mistral")

    log.info(
        "Mistral OCR  DONE    |  pages=%d  markdown_chars=%d",
        len(ocr_response.pages), len(markdown),
    )
    log.debug("Mistral OCR  MARKDOWN_PREVIEW  |  %s", markdown[:1000])
    return markdown


_EXTRACTION_SYSTEM = """\
You are a trade-document data extraction specialist. You parse shipping documents \
(bills of lading, commercial invoices, packing lists) that have been converted to \
markdown via OCR. Your job is to extract a fixed set of fields, apply normalization \
rules exactly, and return a confidence score that honestly reflects extraction quality.

Never fabricate a value. If a field is genuinely absent from the document, return null. \
If a value is present but ambiguous, return null and reflect that uncertainty in the \
confidence score.\
"""

_EXTRACTION_USER = """\
Extract the fields below from the trade document. Apply every normalization rule exactly.

Each field (except global_confidence_score and line_items) must be returned as an object:
  {{ "value": <extracted string or null>, "confidence": <float 0.0–1.0> }}

Per-field confidence guide:
  • 0.90–1.00 : value is explicitly present and unambiguous in the document
  • 0.60–0.89 : required reasonable inference (abbreviation expansion, dense table, partial text)
  • 0.00–0.59 : ambiguous, partially inferred, or you are uncertain this is the right field
  Set confidence to null only if value is null and no relevant content appeared at all.

Return null value (with low confidence) for any field absent from the document — do not fabricate.

━━━ FIELDS ━━━

consignee_name
  • Full legal name of the consignee (receiver of goods) as written. Do not abbreviate or modify.
  • On invoices this may be labelled "TO", "Bill To", or "Consignee". Use the recipient's name, not the sender's.

hs_code
  • Harmonized System commodity code. Keep digits and dots exactly as written (e.g. "8471.30").
  • If multiple HS codes appear (one per line item), extract the first one.
  • If presented as a range (e.g. "4001 - 4017"), extract the range as written.

port_of_loading
  • Full port or city name where the shipment originates.
  • Expand recognised port abbreviations: "SHA" → "Shanghai", "HKG" → "Hong Kong", "USLAX"/"LA" → "Los Angeles", "SGSIN" → "Singapore", etc.
  • Return the city name only — no country codes, port codes, or qualifiers.
  • Not all document types include this field — return null if absent.

port_of_discharge
  • Full port or city name of the destination. Apply the same expansion rules as port_of_loading.
  • Return the city name only.
  • Not all document types include this field — return null if absent.

incoterms
  • Canonical 3-letter uppercase Incoterms code. If spelled out ("Cost, Insurance and Freight") normalise to the code ("CIF").
  • May appear as a table column header or in a cell — look across the full document.
  • Return null if no standard Incoterms code can be identified.

description_of_goods
  • A combined summary of all product or cargo names from the line-item table or cargo description section.
  • Do NOT use the "Reason for exportation", shipment purpose, or customs category (e.g. "Exhibition", "Gift", "Samples") — those are not descriptions of goods.
  • If multiple line items exist, join their descriptions with ", ".

gross_weight
  • Total gross weight of the entire shipment including value and unit as written (e.g. "1 500 KG").
  • If the document has separate net weight and gross/total weight columns, use the gross or total weight column.
  • Use the TOTAL row value if present, not individual line item weights. Do not convert units.

invoice_number
  • Primary invoice or B/L reference number as written.
  • If multiple appear, prefer the one labelled "Invoice No.", "B/L No.", or equivalent.

line_items
  • Extract every product or cargo line item from the document as a structured list.
  • For each line item capture all available fields: description, quantity, hs_code, origin, incoterms, unit_price, currency, net_weight, gross_weight.
  • Set a field to null if it is not present for that line item.
  • If the document has no line-item table (e.g. a plain bill of lading with one cargo description), return null.

global_confidence_score  (float 0.0 – 1.0)
  • Your honest assessment of how reliably the extracted values represent the actual document.
  • 0.90 – 1.00 : All or nearly all fields are clearly and unambiguously present; document is fully legible.
  • 0.60 – 0.89 : Some fields required reasonable inference (abbreviation expansion, reading from dense tables) or a small number are null despite the document being generally legible.
  • 0.00 – 0.59 : Document is degraded (heavy OCR noise, missing pages, rotated text) OR multiple key fields are absent or uncertain.

━━━ RULES ━━━
1. Values in tables, column headers, stamps, or embedded labels count as explicitly present.
2. Standard abbreviations (port codes, incoterms long-form) may be normalised as described above; all other fields use the document's exact wording.
3. The confidence score reflects extraction reliability only — not whether values match any expected standard.

Document:
{markdown}\
"""


async def run_structured_extraction(markdown: str) -> ExtractionOutput:
    log.info("OpenAI extraction  START  |  markdown_chars=%d  model=gpt-4o-mini", len(markdown))

    response = await openai_client.responses.parse(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": _EXTRACTION_SYSTEM},
            {"role": "user", "content": _EXTRACTION_USER.format(markdown=markdown)},
        ],
        text_format=ExtractionOutput,
        temperature=0.0,
        max_output_tokens=1500,
    )

    extracted_data = response.output_parsed
    if extracted_data is None:
        raise ValueError("Empty extraction response from OpenAI")

    field_confidences = {
        f: getattr(extracted_data, f).confidence
        for f in ("consignee_name", "hs_code", "port_of_loading", "port_of_discharge",
                  "incoterms", "description_of_goods", "gross_weight", "invoice_number")
    }
    log.info(
        "OpenAI extraction  DONE   |  global_confidence=%s  per_field=%s  data=%s",
        extracted_data.global_confidence_score,
        field_confidences,
        extracted_data.model_dump_json(),
    )
    return extracted_data


async def run_extractor_cascade(raw_document_path: str) -> tuple[str, ExtractionOutput]:
    log.info("extractor_cascade  START  |  path=%s", raw_document_path)
    mistral_markdown = await run_mistral_ocr(raw_document_path)
    extracted_data = await run_structured_extraction(mistral_markdown)
    log.info("extractor_cascade  DONE")
    return mistral_markdown, extracted_data
