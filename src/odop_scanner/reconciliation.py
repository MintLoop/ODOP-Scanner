from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

from .models import (
    HumanReviewStatus,
    ParsedRow,
    ReconciliationDataset,
    ReconciliationDiff,
    ReconciliationResult,
    ReconciliationStatus,
)

MAKHANA_DISTRICTS = (
    "Araria",
    "Darbhanga",
    "Katihar",
    "Madhubani",
    "Saharsa",
    "Supaul",
)


def normalize_identity(value: str) -> str:
    """Normalize only presentation differences in state/district identity."""

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    normalized = re.sub(r"(?<=\w)[‐‑‒–—-](?=\w)", "", normalized)
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def normalize_product_for_comparison(value: str) -> str:
    """Normalize formatting, never aliases or product-family semantics."""

    normalized = unicodedata.normalize("NFKC", value).casefold().replace("&", " and ")
    normalized = re.sub(r"(?<=\w)[‐‑‒–—-](?=\w)", "", normalized)
    normalized = re.sub(r"[/|,;:()\[\]{}]+", " ", normalized)
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _comparison_id(
    comparison_version: str,
    config_sha256: str,
    baseline: ReconciliationDataset,
    newer: ReconciliationDataset,
) -> str:
    identity = "\0".join(
        (
            comparison_version,
            config_sha256,
            baseline.source_version,
            baseline.document.content_sha256,
            newer.source_version,
            newer.document.content_sha256,
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def _diff_id(
    comparison_id: str,
    identity_key: tuple[str, str],
    baseline_rows: Iterable[ParsedRow],
    newer_rows: Iterable[ParsedRow],
    status: ReconciliationStatus,
) -> str:
    row_ids = sorted(
        [f"baseline:{row.row_id}" for row in baseline_rows]
        + [f"newer:{row.row_id}" for row in newer_rows]
    )
    identity = "\0".join((comparison_id, *identity_key, status, *row_ids))
    return hashlib.sha256(identity.encode()).hexdigest()


def _index_rows(rows: Iterable[ParsedRow]) -> dict[tuple[str, str], list[ParsedRow]]:
    indexed: dict[tuple[str, str], list[ParsedRow]] = defaultdict(list)
    for row in rows:
        if row.parse_status == "parsed":
            indexed[(normalize_identity(row.state), normalize_identity(row.district))].append(row)
    return indexed


def _joined_products(rows: list[ParsedRow]) -> str | None:
    products = sorted({row.product for row in rows}, key=str.casefold)
    return " | ".join(products) if products else None


def _make_diff(
    *,
    comparison_id: str,
    comparison_version: str,
    baseline: ReconciliationDataset,
    newer: ReconciliationDataset,
    identity_key: tuple[str, str],
    baseline_rows: list[ParsedRow],
    newer_rows: list[ParsedRow],
    conflict_type: str,
    proposed_status: ReconciliationStatus,
) -> ReconciliationDiff:
    display = baseline_rows[0] if baseline_rows else newer_rows[0]
    human_status: HumanReviewStatus = "not_required" if proposed_status == "same" else "pending"
    return ReconciliationDiff(
        diff_id=_diff_id(comparison_id, identity_key, baseline_rows, newer_rows, proposed_status),
        comparison_id=comparison_id,
        comparison_version=comparison_version,
        baseline_source_version=baseline.source_version,
        newer_source_version=newer.source_version,
        baseline_source_sha256=baseline.document.content_sha256,
        newer_source_sha256=newer.document.content_sha256,
        state=display.state,
        district=display.district,
        baseline_product=_joined_products(baseline_rows),
        newer_product=_joined_products(newer_rows),
        baseline_row_ids=tuple(sorted(row.row_id for row in baseline_rows)),
        newer_row_ids=tuple(sorted(row.row_id for row in newer_rows)),
        baseline_locators=tuple(sorted(row.source_reference for row in baseline_rows)),
        newer_locators=tuple(sorted(row.source_reference for row in newer_rows)),
        conflict_type=conflict_type,
        proposed_status=proposed_status,
        human_review_status=human_status,
    )


def reconcile_datasets(
    baseline: ReconciliationDataset,
    newer: ReconciliationDataset,
    *,
    comparison_version: str,
    config_sha256: str,
) -> ReconciliationResult:
    comparison_id = _comparison_id(comparison_version, config_sha256, baseline, newer)
    baseline_index = _index_rows(baseline.rows)
    newer_index = _index_rows(newer.rows)
    diffs: list[ReconciliationDiff] = []

    for identity_key in sorted(set(baseline_index) | set(newer_index)):
        baseline_rows = baseline_index.get(identity_key, [])
        newer_rows = newer_index.get(identity_key, [])
        if len(baseline_rows) > 1 or len(newer_rows) > 1:
            conflict_type = "duplicate_district_identity"
            status: ReconciliationStatus = "ambiguous"
        elif not baseline_rows:
            conflict_type = "district_added_in_newer_source"
            status = "added"
        elif not newer_rows:
            conflict_type = "district_missing_from_newer_source"
            status = "removed"
        elif normalize_product_for_comparison(
            baseline_rows[0].product
        ) == normalize_product_for_comparison(newer_rows[0].product):
            conflict_type = "product_unchanged"
            status = "same"
        else:
            conflict_type = "product_changed"
            status = "changed"
        diffs.append(
            _make_diff(
                comparison_id=comparison_id,
                comparison_version=comparison_version,
                baseline=baseline,
                newer=newer,
                identity_key=identity_key,
                baseline_rows=baseline_rows,
                newer_rows=newer_rows,
                conflict_type=conflict_type,
                proposed_status=status,
            )
        )

    for side, dataset in (("baseline", baseline), ("newer", newer)):
        for row in dataset.rows:
            if row.parse_status == "parsed":
                continue
            baseline_rows = [row] if side == "baseline" else []
            newer_rows = [row] if side == "newer" else []
            identity_key = (f"malformed:{side}", row.row_id)
            diffs.append(
                _make_diff(
                    comparison_id=comparison_id,
                    comparison_version=comparison_version,
                    baseline=baseline,
                    newer=newer,
                    identity_key=identity_key,
                    baseline_rows=baseline_rows,
                    newer_rows=newer_rows,
                    conflict_type=f"malformed_{side}_row",
                    proposed_status="ambiguous",
                )
            )

    diffs.sort(
        key=lambda diff: (
            normalize_identity(diff.state),
            normalize_identity(diff.district),
            diff.proposed_status,
            diff.diff_id,
        )
    )
    return ReconciliationResult(
        comparison_id=comparison_id,
        comparison_version=comparison_version,
        config_sha256=config_sha256,
        baseline_source_version=baseline.source_version,
        newer_source_version=newer.source_version,
        baseline_source_sha256=baseline.document.content_sha256,
        newer_source_sha256=newer.document.content_sha256,
        diffs=tuple(diffs),
    )


def makhana_checks(results: Iterable[ReconciliationResult]) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    expected = {normalize_identity(district): district for district in MAKHANA_DISTRICTS}
    for result in results:
        by_district = {
            normalize_identity(diff.district): diff
            for diff in result.diffs
            if normalize_identity(diff.state) == "bihar"
            and normalize_identity(diff.district) in expected
        }
        for district_key, district in expected.items():
            diff = by_district.get(district_key)
            checks.append(
                {
                    "newer_source_version": result.newer_source_version,
                    "state": "BIHAR",
                    "district": district,
                    "baseline_product": diff.baseline_product if diff else None,
                    "newer_product": diff.newer_product if diff else None,
                    "proposed_status": diff.proposed_status if diff else "ambiguous",
                    "baseline_locators": list(diff.baseline_locators) if diff else [],
                    "newer_locators": list(diff.newer_locators) if diff else [],
                }
            )
    return checks
