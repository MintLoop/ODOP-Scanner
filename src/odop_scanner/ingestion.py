from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
import shutil
import urllib.request
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import ParsedRow, ParseStatus, SourceDocument

_STATE_HEADING = re.compile(r"^\s*(?P<number>\d{1,2})\.\s*(?P<state>[A-Z][A-Z &-]+)\s*$")
_NUMBERED_ROW = re.compile(r"^\s*(?P<number>\d{1,3})\.?\s+(?P<body>\S.*)?$")
_HEADER_MARKERS = ("sl. no.", "si. no.", "s.no.", "sl.no.")


@dataclass
class _PendingRow:
    sequence: int
    state: str
    page: int
    district_parts: list[str]
    product_parts: list[str]
    raw_lines: list[str]


@dataclass(frozen=True)
class IngestionResult:
    document: SourceDocument
    rows: tuple[ParsedRow, ...]


def _collapse(value: str) -> str:
    return " ".join(value.split())


def _row_id(
    source_id: str,
    page: int | None,
    reference: str,
    raw_text: str,
) -> str:
    identity = f"{source_id}\0{page}\0{reference}\0{raw_text}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _finish_pending(pending: _PendingRow, source_id: str, ingested_at: datetime) -> ParsedRow:
    district = _collapse(" ".join(pending.district_parts))
    product = _collapse(" ".join(pending.product_parts))
    raw_text = "\n".join(pending.raw_lines)
    problems: list[str] = []
    if not pending.state:
        problems.append("state missing")
    if not district:
        problems.append("district missing")
    if not product:
        problems.append("product missing")
    if district.count("(") != district.count(")"):
        problems.append("district parentheses unbalanced")
    if product.count("(") != product.count(")"):
        problems.append("product parentheses unbalanced")
    status: ParseStatus = "malformed" if problems else "parsed"
    reference = f"page:{pending.page};state:{pending.state};row:{pending.sequence}"
    return ParsedRow(
        row_id=_row_id(source_id, pending.page, reference, raw_text),
        source_id=source_id,
        state=pending.state,
        district=district,
        product=product,
        source_page=pending.page,
        source_reference=reference,
        raw_text=raw_text,
        parse_status=status,
        parse_error="; ".join(problems) or None,
        ingested_at=ingested_at,
    )


def _infer_product_column(lines: list[str]) -> int | None:
    """Infer the layout-text boundary using repeated row padding.

    The official PDF centers district values, so the start position varies, while the
    padding run ends at a stable product column. An occasional multi-word district with
    extra internal spacing is an outlier and cannot defeat the page mode.
    """

    gap_intervals: list[tuple[int, int]] = []
    for line in lines:
        if _STATE_HEADING.match(line):
            continue
        match = _NUMBERED_ROW.match(line)
        if match is None or match.group("body") is None:
            continue
        body_start = match.start("body")
        gap = re.search(r" {2,}", line[body_start:])
        if gap is None:
            continue
        gap_start = body_start + gap.start()
        gap_end = body_start + gap.end()
        if line[gap_end:].strip():
            gap_intervals.append((gap_start, gap_end))
    if not gap_intervals:
        return None
    first_column = min(start for start, _ in gap_intervals)
    last_column = max(end for _, end in gap_intervals)
    coverage = {
        column: sum(start <= column <= end for start, end in gap_intervals)
        for column in range(first_column, last_column + 1)
    }
    best_coverage = max(coverage.values())
    best_columns = [column for column, count in coverage.items() if count == best_coverage]
    return best_columns[-1]


def parse_official_layout_pages(
    pages: list[str],
    *,
    source_id: str,
    ingested_at: datetime,
    page_number_offset: int = 0,
) -> tuple[ParsedRow, ...]:
    rows: list[ParsedRow] = []
    state = ""
    product_column: int | None = None

    for page_number, page_text in enumerate(pages, start=page_number_offset + 1):
        lines = page_text.splitlines()
        heading_indexes = [
            index for index, line in enumerate(lines) if _STATE_HEADING.match(line) is not None
        ]
        prefix_end = heading_indexes[0] if heading_indexes else len(lines)
        prefix_column = _infer_product_column(lines[:prefix_end])
        if prefix_column is not None:
            product_column = prefix_column
        section_columns: dict[int, int | None] = {}
        for position, heading_index in enumerate(heading_indexes):
            section_end = (
                heading_indexes[position + 1] if position + 1 < len(heading_indexes) else len(lines)
            )
            section_columns[heading_index] = _infer_product_column(
                lines[heading_index + 1 : section_end]
            )
        pending: _PendingRow | None = None

        def flush() -> None:
            nonlocal pending
            if pending is not None:
                rows.append(_finish_pending(pending, source_id, ingested_at))
                pending = None

        for line_index, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            heading = _STATE_HEADING.match(line)
            if heading is not None:
                flush()
                state = _collapse(heading.group("state"))
                product_column = section_columns[line_index]
                continue
            lowered = stripped.casefold()
            if lowered.startswith(_HEADER_MARKERS):
                flush()
                continue
            if lowered.startswith("total"):
                flush()
                continue
            if "odop list of" in lowered:
                continue
            if stripped.isdigit():
                # Page folios can fall inside a pending table row in layout extraction.
                continue

            numbered = _NUMBERED_ROW.match(line)
            if numbered is not None and numbered.group("body") is not None:
                if not state:
                    continue
                flush()
                sequence = int(numbered.group("number"))
                body_start = numbered.start("body")
                if product_column is None:
                    district_text = line[body_start:].strip()
                    product_text = ""
                else:
                    district_text = line[body_start:product_column].strip()
                    product_text = line[product_column:].strip()
                pending = _PendingRow(
                    sequence=sequence,
                    state=state,
                    page=page_number,
                    district_parts=[district_text] if district_text else [],
                    product_parts=[product_text] if product_text else [],
                    raw_lines=[line],
                )
                continue

            if pending is not None and product_column is not None:
                district_text = line[:product_column].strip()
                product_text = line[product_column:].strip()
                if pending.product_parts and re.search(r" {2,}", stripped) is None:
                    # Wrapped products sometimes shift left of the inferred table boundary.
                    district_text = ""
                    product_text = stripped
                if district_text:
                    pending.district_parts.append(district_text)
                if product_text:
                    pending.product_parts.append(product_text)
                pending.raw_lines.append(line)

        flush()

    return tuple(rows)


def _parse_csv_rows(
    raw_text: str,
    *,
    source_id: str,
    ingested_at: datetime,
) -> tuple[ParsedRow, ...]:
    rows: list[ParsedRow] = []
    reader = csv.DictReader(io.StringIO(raw_text))
    expected = {"state", "district", "product"}
    if reader.fieldnames is None or not expected.issubset(
        {name.strip().casefold() for name in reader.fieldnames}
    ):
        raise ValueError("CSV source requires state, district, and product headers")
    key_map = {name.strip().casefold(): name for name in reader.fieldnames}
    for index, item in enumerate(reader, start=2):
        state = str(item.get(key_map["state"], "") or "").strip()
        district = str(item.get(key_map["district"], "") or "").strip()
        product = str(item.get(key_map["product"], "") or "").strip()
        raw = json.dumps(item, ensure_ascii=False, sort_keys=True)
        problems = [
            name
            for name, value in (("state", state), ("district", district), ("product", product))
            if not value
        ]
        reference = f"csv-row:{index}"
        rows.append(
            ParsedRow(
                row_id=_row_id(source_id, None, reference, raw),
                source_id=source_id,
                state=state,
                district=district,
                product=product,
                source_page=None,
                source_reference=reference,
                raw_text=raw,
                parse_status="malformed" if problems else "parsed",
                parse_error=f"missing: {', '.join(problems)}" if problems else None,
                ingested_at=ingested_at,
            )
        )
    return tuple(rows)


def _parse_json_rows(
    raw_text: str,
    *,
    source_id: str,
    ingested_at: datetime,
) -> tuple[ParsedRow, ...]:
    payload: Any = json.loads(raw_text)
    if not isinstance(payload, list):
        raise ValueError("JSON source must be a list of records")
    csv_buffer = io.StringIO()
    writer = csv.DictWriter(csv_buffer, fieldnames=["state", "district", "product"])
    writer.writeheader()
    for item in payload:
        if not isinstance(item, dict):
            writer.writerow({"state": "", "district": "", "product": ""})
        else:
            writer.writerow(
                {
                    "state": item.get("state", ""),
                    "district": item.get("district", ""),
                    "product": item.get("product", ""),
                }
            )
    return _parse_csv_rows(csv_buffer.getvalue(), source_id=source_id, ingested_at=ingested_at)


def _extract_text(path: Path) -> tuple[str, list[str]]:
    suffix = path.suffix.casefold()
    if suffix == ".pdf":
        reader = PdfReader(path)
        pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
        raw_text = "\n".join(
            f"\n--- PAGE {index} ---\n{text}" for index, text in enumerate(pages, 1)
        )
        return raw_text, pages
    raw_text = path.read_text(encoding="utf-8-sig")
    return raw_text, raw_text.split("\f")


def download_source(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "ODOP-Scanner/0.1 (+internal research)"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - configured source URL
        destination.write_bytes(response.read())
    return destination


def ingest_path(
    path: Path,
    *,
    source_name: str,
    source_url: str | None,
    source_date: date | None,
    raw_directory: Path,
    ingested_at: datetime | None = None,
    pdf_page_start: int | None = None,
    pdf_page_end: int | None = None,
) -> IngestionResult:
    timestamp = ingested_at or datetime.now(UTC)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    suffix = path.suffix.casefold() or ".bin"
    stored_path = raw_directory / f"{digest}{suffix}"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    if not stored_path.exists():
        shutil.copyfile(path, stored_path)

    raw_text, pages = _extract_text(path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    document = SourceDocument(
        source_id=digest,
        source_name=source_name,
        source_url=source_url,
        source_date=source_date,
        ingested_at=timestamp,
        content_sha256=digest,
        storage_path=stored_path.resolve(),
        media_type=media_type,
        raw_text=raw_text,
    )

    if suffix == ".csv":
        rows = _parse_csv_rows(raw_text, source_id=digest, ingested_at=timestamp)
    elif suffix == ".json":
        rows = _parse_json_rows(raw_text, source_id=digest, ingested_at=timestamp)
    else:
        page_start = pdf_page_start or 1
        page_end = pdf_page_end or len(pages)
        if page_start < 1 or page_end < page_start or page_end > len(pages):
            raise ValueError(
                f"invalid PDF page range {page_start}-{page_end} for {len(pages)} pages"
            )
        rows = parse_official_layout_pages(
            pages[page_start - 1 : page_end],
            source_id=digest,
            ingested_at=timestamp,
            page_number_offset=page_start - 1,
        )
    return IngestionResult(document=document, rows=rows)


def with_source_id(rows: tuple[ParsedRow, ...], source_id: str) -> tuple[ParsedRow, ...]:
    """Test helper for rebinding parsed rows while retaining deterministic row hashes."""

    rebound: list[ParsedRow] = []
    for row in rows:
        rebound.append(
            replace(
                row,
                source_id=source_id,
                row_id=_row_id(source_id, row.source_page, row.source_reference, row.raw_text),
            )
        )
    return tuple(rebound)
