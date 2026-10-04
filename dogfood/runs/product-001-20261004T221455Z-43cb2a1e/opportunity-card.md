# MAKHANA / FOXNUT

**Artifact class:** Hermes/Menta routed replay narrative

**Decision gate:** TEST

Replaying the analyst, validator, and scout inputs in narrative-only mode, no ODOP metric that would move the product-001 (makhana / foxnut) decision is resolved. Every gated transform — demand, repeat purchase, margin, supplier depth, regulatory risk, shelf stability, shipping, competition, brandability, and search/social velocity — is reported as a missing transform, and the validator verdict is UNKNOWN. The economics input still only provides three unquoted sensitivity scenarios whose contribution-margin range is not reliable enough to change the deterministic snapshot, which therefore stays at TEST with overall_score null, evidence_coverage 0.0, confidence_band none, and no spend beyond the stated ceiling.

## Market

Makhana has U.S. marketplace presence across search and category pages, but those pages mix raw and ready-to-eat products, duplicates, and sponsored cards. The approved deduplicated brand-share or concentration transform is missing, so true competitive density cannot be established.

Evidence: mk-ev-003-amazon-snapshot, mk-ev-005-walmart-category

## Demand

No reproducible U.S. time series, sales panel, conversion series, or approved demand-proxy series was captured. Marketplace presence and APEDA mentions do not establish U.S. demand.

Evidence: mk-ev-002-apeda-dashboard

## Competition

Result pages combine raw and ready-to-eat SKUs including established brands, duplicates, and sponsored placements, but no approved deduplicated share or concentration transform exists, so no reliable brand concentration or whitespace conclusion can be drawn.

Evidence: mk-ev-003-amazon-snapshot, mk-ev-005-walmart-category

## Supply

Multiple suppliers claim private-label and export capability, but no independent entity verification, quote, certificate, COA, sample, or on-time performance record exists. Supplier depth remains an unresolved gap.

Evidence: mk-ev-007-bihari-bites, mk-ev-008-purnia-supplier

## Economics

The base DTC order is four 1 oz packs; across the LOW, BASE, and HIGH sensitivity scenarios contribution margin before payment processing is roughly $2.00 to $3.80, with DTC payment processing further reducing it by 2.9 percent plus $0.30 per order. Every cost input is a deliberately broad sensitivity assumption, not a supplier, freight, customs, or fulfillment quote, so the margin is not reliable enough to support a decision.

Evidence: mk-ev-002-apeda-dashboard, mk-ev-003-amazon-snapshot, mk-ev-004-whole-foods-asha, mk-ev-007-bihari-bites

## Regulatory friction

General import duties are identifiable, but the exact regulatory formula is unresolved: exact HTS classification, tariff stack, APHIS treatment, food facility status, FSVP importer obligation, and food-label claims under FSMA still need to be checked against FDA importing, FSVP, and labeling rules.

Evidence: mk-ev-011-fda-importing-food, mk-ev-012-fsvp, mk-ev-013-fda-labeling

## Product

The proposed product is a 1 oz pack of roasted makhana sold as a four-pack DTC order. Physical research supports fragility and low density but no finished, seasoned product shelf-life study or supplier specification tied to the proposed package was obtained.

Evidence: mk-ev-009-food-fragility-study

## Brandability

There is no approved brandability transform or trademark/domain clearance. The three exploratory names each carry descriptive, prior-use, terminology, or semantic risk, so no cleared name exists yet.

Evidence: mk-ev-015-name-screen

## Content potential

An existing media business can speak to audience reach, but no reproducible U.S. engagement or conversion series was captured and observed recipes, videos, and anecdotes cannot be converted from mention counts into demand.

Evidence: mk-ev-014-lotus-eaters-use

## Deterministic result

- Score: unscored
- Evidence coverage: 0.0%
- Validator: UNKNOWN
- Gate: TEST
- Maximum spend: $150.00
- Score snapshot: `58aae5d307fd5adef2dcc862f05c471b02a1fee2d073b50130a193719c2ee282`

## Strongest case against

Every metric that gates a market-entry decision remains a missing transform backed by broad cost assumptions, unverified suppliers, and unresolved import regulations, the validator verdict is UNKNOWN, and the deterministic snapshot stays at TEST with overall_score null. There is therefore no reliable basis to promote product-001, only enough residual fragility and unverified cost to justify further cheap verification.

## Top 5 unknowns

1. Actual landed cost (factory, packaging, freight, duty, and import overhead) has no supplier, freight, custom-house, or fulfillment quote; the scenarios are broad assumptions, not facts.
2. No reproducible U.S. demand, sales, conversion, or repeat-purchase series exists to pair with the three margin scenarios.
3. Exact import regulatory formula — HTS classification, tariff stack, APHIS treatment, FSVP importer, food facility status, and label claims — is unresolved.
4. No independent supplier entity verification, certificate, COA, sample, or on-time performance record exists for any makhana supplier.
5. No finished-product shelf-life study tied to the proposed four-pack package, no commercial package dimensions, and no damage or breakage data.

## Top 5 risks

1. UnVerifier landed cost makes the contribution-margin scenarios unreliable as a basis for a decision.
2. Lack of demand and repeat-purchase evidence means monthly contribution cannot be turned into cash without finding real buyers.
3. Import regulatory exposure under FSVP, FDA, customs, the tariff stack, and labeling is unidentified and could block entry or force expensive rework.
4. Unproven supplier depth combined with the roasting fragility of makhana raises breakage and spoilage risk that no scenario prices in.
5. No cleared name exists; the exploratory options carry descriptive, prior-use, terminology, and semantic brandability risks.

## Next experiment

Request one landed-cost quote (factory, packaging, freight, duty, import overhead) plus an HTS or custom-house ruling for one verified supplier and the specific four-pack package, then reprice the LOW, BASE, and HIGH scenarios before trusting any contribution margin, using mk-ev-002-apeda-dashboard, mk-ev-007-bihari-bites, and mk-ev-011-fda-importing-food as the reference.

## Evidence index

- `mk-ev-001-apeda-market-study` — [APEDA Indian Makhana Market Study](https://apeda.gov.in/sites/default/files/study_reports/Makhana_Report_English.pdf) (accepted)
- `mk-ev-002-apeda-dashboard` — [APEDA Makhana Monthly Dashboard](https://apeda.gov.in/sites/default/files/2025-12/MIC_Monthly_dashboard_Makhana_15122025.pdf) (accepted)
- `mk-ev-003-amazon-snapshot` — [Amazon US search results for makhana](https://www.amazon.com/s?k=makhana) (accepted)
- `mk-ev-004-whole-foods-asha` — [Whole Foods Market AshaPops turmeric garlic product page](https://www.wholefoodsmarket.com/grocery/product/turmeric-garlic%20popped%20water%20lily%20seeds%2C%201%20oz-b07hwpykl3) (accepted)
- `mk-ev-005-walmart-category` — [Walmart US phool makhana search page](https://www.walmart.com/c/kp/phool-makhana) (accepted)
- `mk-ev-006-asha-brand` — [AshaPops brand site](https://ashapops.com/) (unverified)
- `mk-ev-007-bihari-bites` — [Bihari Bites bulk and private-label makhana pages](https://biharibites.com/) (unverified)
- `mk-ev-008-purnia-supplier` — [Purnia Makhana private-label and export pages](https://purniamakhana.com/) (unverified)
- `mk-ev-009-food-fragility-study` — [Peer-reviewed study of Euryale ferox roasting properties](https://link.springer.com/article/10.1186/s43014-021-00081-x) (accepted)
- `mk-ev-010-amazon-fees` — [Amazon US selling plan and referral fee schedule](https://sell.amazon.com/pricing) (accepted)
- `mk-ev-011-fda-importing-food` — [FDA Importing Food Products into the United States](https://www.fda.gov/food/food-imports-exports/importing-food-products-united-states) (accepted)
- `mk-ev-012-fsvp` — [FDA Foreign Supplier Verification Programs final rule](https://www.fda.gov/food/food-safety-modernization-act-fsma/fsma-final-rule-foreign-supplier-verification-programs-fsvp-importers-food-humans-and-animals) (accepted)
- `mk-ev-013-fda-labeling` — [FDA Food Labeling Guide](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/guidance-industry-food-labeling-guide) (accepted)
- `mk-ev-014-lotus-eaters-use` — [Lotus Eaters existing media business](https://lotuseaters.com/) (accepted)
- `mk-ev-015-name-screen` — [Exploratory makhana name screen](https://tmsearch.uspto.gov/) (unverified)
- `mk-ev-016-amazon-fba-fees` — [Amazon 2026 US FBA fulfillment fee schedule](https://sellercentral.amazon.com/help/hub/reference/external/GABBX6GZPA8MSZGW?itemid=211&locale=en-us) (accepted)

_Narrative roles did not write score inputs or gate outputs._
