from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol

from .models import (
    NormalizationDecision,
    NormalizationStatus,
    ParsedRow,
    TaxonomyConfig,
    TaxonomyFamily,
)

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-", "‑": "-"})
_PUNCTUATION_SPACING = re.compile(r"\s*([/&(),])\s*")


def normalize_text(value: str) -> str:
    """Normalize presentation differences without changing product meaning."""

    normalized = unicodedata.normalize("NFKC", value).translate(_DASHES)
    normalized = _PUNCTUATION_SPACING.sub(r"\1", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = " ".join(normalized.casefold().split())
    return normalized


@dataclass(frozen=True)
class AliasSuggestion:
    proposed_product_id: str
    rationale: str
    route: str


class AliasAssistant(Protocol):
    """Optional model boundary. Suggestions are review-only and never merge records."""

    def suggest(
        self,
        *,
        source_value: str,
        normalized_value: str,
        families: tuple[TaxonomyFamily, ...],
    ) -> AliasSuggestion | None: ...


def _family_id_for_name(normalized_name: str) -> str:
    digest = hashlib.sha256(normalized_name.encode("utf-8")).hexdigest()[:16]
    return f"family-{digest}"


def _alias_index(taxonomy: TaxonomyConfig) -> dict[str, TaxonomyFamily]:
    result: dict[str, TaxonomyFamily] = {}
    for family in taxonomy.families:
        for alias in (family.canonical_name, *family.aliases):
            key = normalize_text(alias)
            existing = result.get(key)
            if existing is not None and existing.product_id != family.product_id:
                raise ValueError(f"taxonomy alias {alias!r} belongs to multiple families")
            result[key] = family
    return result


def normalize_rows(
    rows: tuple[ParsedRow, ...],
    taxonomy: TaxonomyConfig,
    *,
    assistant: AliasAssistant | None = None,
    fuzzy_review_threshold: float = 0.82,
    peer_review_threshold: float = 0.95,
) -> tuple[NormalizationDecision, ...]:
    aliases = _alias_index(taxonomy)
    unknown_names = tuple(
        sorted(
            {
                normalize_text(row.product)
                for row in rows
                if row.parse_status == "parsed" and normalize_text(row.product) not in aliases
            }
        )
    )
    decisions: list[NormalizationDecision] = []

    for row in rows:
        if row.parse_status != "parsed":
            continue
        normalized_name = normalize_text(row.product)
        exact = aliases.get(normalized_name)
        model_route: str | None = None

        if exact is not None:
            family_id = exact.product_id
            canonical_name = exact.canonical_name
            category = exact.category
            forced = exact.forced_candidate
            status: NormalizationStatus = "normalized"
            method = "configured_alias"
        else:
            family_id = _family_id_for_name(normalized_name)
            canonical_name = normalized_name
            category = None
            forced = False
            status = "normalized"
            method = "deterministic_exact"

            review_suggestions: list[tuple[float, str, str]] = []
            for alias_key, family in aliases.items():
                ratio = SequenceMatcher(None, normalized_name, alias_key).ratio()
                if ratio >= fuzzy_review_threshold:
                    review_suggestions.append((ratio, alias_key, family.product_id))
            for other_name in unknown_names:
                if other_name == normalized_name:
                    continue
                ratio = SequenceMatcher(None, normalized_name, other_name).ratio()
                if ratio >= peer_review_threshold:
                    review_suggestions.append((ratio, other_name, _family_id_for_name(other_name)))
            if review_suggestions:
                closest_ratio, closest_key, closest_family_id = max(review_suggestions)
                status = "review_required"
                method = f"fuzzy_suggestion:{closest_family_id}:{closest_key}:{closest_ratio:.3f}"

            if assistant is not None:
                suggestion = assistant.suggest(
                    source_value=row.product,
                    normalized_value=normalized_name,
                    families=taxonomy.families,
                )
                if suggestion is not None:
                    status = "review_required"
                    method = f"model_suggestion:{suggestion.proposed_product_id}"
                    model_route = suggestion.route

        normalized_id = hashlib.sha256(
            f"{row.row_id}\0{taxonomy.version}\0{family_id}".encode()
        ).hexdigest()
        decisions.append(
            NormalizationDecision(
                normalized_id=normalized_id,
                row_id=row.row_id,
                family_id=family_id,
                canonical_name=canonical_name,
                category=category,
                forced_candidate=forced,
                normalized_name=normalized_name,
                normalization_status=status,
                normalization_method=method,
                normalization_version=taxonomy.version,
                model_route=model_route,
                observed_alias=row.product,
            )
        )

    return tuple(decisions)
