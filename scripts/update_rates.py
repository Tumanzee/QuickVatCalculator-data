#!/usr/bin/env python3
"""Build QuickVAT's normalized tax-rate dataset.

Sources:
- VATEstimator global VAT/GST rates (67 countries)
- ReceiptEdit US state sales-tax rates (50 states)
- VATcomply EU standard rates (cross-check only)

The output is a single JSON document consumed by the iOS app. The script is
intentionally dependency-free so it can run in a stock GitHub Actions runner.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

VATE_URL = "https://vatestimator.com/api/v1/rates.json"
US_URL = "https://receiptedit.com/api/sales-tax"
EU_URL = "https://api.vatcomply.com/vat_rates"

USER_AGENT = "QuickVAT-Rate-Updater/1.0 (+https://github.com/Tumanzee/QuickVatCalculator)"

def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def flag_for(code: str) -> str:
    if len(code) != 2 or not code.isalpha():
        return "🌍"
    return "".join(chr(0x1F1E6 + ord(char) - ord("A")) for char in code.upper())


def number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def normalize_tax_type(code: str, raw: Optional[str]) -> str:
    if code == "US":
        return "Sales Tax"
    if code == "MY":
        return "SST"
    if not raw:
        return "VAT"
    value = raw.strip()
    if value.upper() in {"GST/HST", "GST"}:
        return value.upper()
    if value.upper() == "SERVICE TAX":
        return "SST"
    if value.upper() == "SALES TAX":
        return "Sales Tax"
    return "VAT"


def choose_standard_rate(entry: Dict[str, Any]) -> Optional[float]:
    direct = number(entry.get("standard_rate"))
    if direct is not None:
        return direct
    rates = entry.get("rates") or []
    for role in ("primary_calculator", "standard", "additional"):
        for rate in rates:
            if rate.get("role") == role:
                value = number(rate.get("rate_percent")) or number(rate.get("rate"))
                if value is not None:
                    return value
    values = [
        number(rate.get("rate_percent")) or number(rate.get("rate"))
        for rate in rates
    ]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def make_notes(
    tax_type: str,
    standard_rate: float,
    reduced_rates: Iterable[float],
    zero_rate: bool,
) -> str:
    if tax_type == "Sales Tax":
        return "Sales tax varies by state. State base rate shown; local taxes may apply."
    reduced = list(reduced_rates)
    lower = sorted(rate for rate in reduced if rate < standard_rate)
    higher = sorted(rate for rate in reduced if rate > standard_rate)
    parts: List[str] = []
    if lower:
        parts.append("Reduced: " + " / ".join(format_rate(rate) for rate in lower))
    if higher:
        parts.append("Other: " + " / ".join(format_rate(rate) for rate in higher))
    if zero_rate:
        parts.append("Zero: 0%")
    if not parts:
        return f"{tax_type} standard rate"
    return " • ".join(parts)


def format_rate(rate: float) -> str:
    text = f"{rate:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"


def build_global_countries(global_payload: Dict[str, Any], eu_payload: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    eu_rates = {
        item.get("country_code"): number(item.get("standard_rate"))
        for item in eu_payload
        if item.get("country_code")
    }
    countries: List[Dict[str, Any]] = []

    for entry in global_payload.get("rates", []):
        code = str(entry.get("code", "")).upper()
        if len(code) != 2:
            continue

        standard_rate = choose_standard_rate(entry)
        if standard_rate is None:
            warnings.append(f"{code}: no usable standard rate; skipped")
            continue

        rates = entry.get("rates") or []
        active_rates = []
        for rate in rates:
            value = number(rate.get("rate_percent"))
            if value is None:
                value = number(rate.get("rate"))
            if value is None:
                continue
            active_rates.append({**rate, "_value": value})

        standard_detail = next(
            (rate for rate in active_rates if rate.get("role") == "standard"),
            None,
        )
        if standard_detail is None:
            standard_detail = next(
                (rate for rate in active_rates if rate["_value"] == standard_rate),
                active_rates[0] if active_rates else None,
            )

        tax_type = normalize_tax_type(
            code,
            standard_detail.get("tax_type") if standard_detail else None,
        )

        other_rates: List[float] = []
        zero_rate = False
        rate_details: List[Dict[str, Any]] = []
        for rate in active_rates:
            value = rate["_value"]
            label = str(rate.get("label") or rate.get("role") or "Rate")
            role = str(rate.get("role") or "additional")
            if value == 0:
                zero_rate = True
            elif value != standard_rate and value not in other_rates:
                other_rates.append(value)
            rate_details.append(
                {
                    "label": label,
                    "rate": value,
                    "taxType": normalize_tax_type(code, rate.get("tax_type")),
                    "role": role,
                }
            )
        reduced_rates = sorted(rate for rate in other_rates if rate < standard_rate)

        eu_rate = eu_rates.get(code)
        if eu_rate is not None and abs(eu_rate - standard_rate) > 0.01:
            warnings.append(
                f"{code}: VATcomply standard {eu_rate}% differs from VATEstimator {standard_rate}%"
            )

        source_url = entry.get("official_source_url") or entry.get("page_url")
        updated = entry.get("last_verified") or global_payload.get("meta", {}).get("last_updated")
        effective_from = standard_detail.get("effective_from") if standard_detail else None

        countries.append(
            {
                "name": entry.get("country") or code,
                "code": code,
                "flag": flag_for(code),
                "currencyCode": entry.get("currency_code") or "",
                "currencySymbol": entry.get("currency") or "",
                "standardRate": standard_rate,
                "reducedRates": reduced_rates,
                "zeroRate": zero_rate,
                "notes": make_notes(tax_type, standard_rate, other_rates, zero_rate),
                "taxType": tax_type,
                "rateDetails": rate_details,
                "regions": [],
                "defaultRegionCode": None,
                "regionLabel": None,
                "effectiveFrom": effective_from,
                "lastVerified": updated,
                "sourceName": entry.get("source_name"),
                "sourceURL": source_url,
            }
        )

    return countries, warnings


def build_us(us_payload: Dict[str, Any]) -> Dict[str, Any]:
    regions: List[Dict[str, Any]] = []
    for state in us_payload.get("states", []):
        code = str(state.get("code", "")).upper()
        rate = number(state.get("state_sales_tax_pct"))
        combined = number(state.get("avg_combined_sales_tax_pct"))
        if len(code) != 2 or rate is None:
            continue
        note = f"State base rate. Average combined rate: {format_rate(combined)}." if combined is not None else "State base rate."
        regions.append(
            {
                "code": code,
                "name": state.get("name") or code,
                "rate": rate,
                "combinedRate": combined,
                "notes": note,
                "sourceURL": state.get("official_source"),
            }
        )
    regions.sort(key=lambda item: item["name"])
    default_region = next((region["code"] for region in regions if region["code"] == "CA"), None)
    if default_region is None and regions:
        default_region = regions[0]["code"]

    return {
        "name": "United States",
        "code": "US",
        "flag": flag_for("US"),
        "currencyCode": "USD",
        "currencySymbol": "$",
        "standardRate": 0.0,
        "reducedRates": [],
        "zeroRate": False,
        "notes": "No federal VAT. Select a state to use its base sales-tax rate; local taxes vary.",
        "taxType": "Sales Tax",
        "rateDetails": [],
        "regions": regions,
        "defaultRegionCode": default_region,
        "regionLabel": "State",
        "effectiveFrom": us_payload.get("rates_as_of"),
        "lastVerified": us_payload.get("last_updated"),
        "sourceName": "ReceiptEdit state rates",
        "sourceURL": US_URL,
    }


def validate(countries: List[Dict[str, Any]]) -> None:
    if len(countries) < 60:
        raise ValueError(f"Expected at least 60 countries, got {len(countries)}")
    codes = [country["code"] for country in countries]
    if len(codes) != len(set(codes)):
        raise ValueError("Duplicate country codes in output")
    for country in countries:
        rate = country["standardRate"]
        if not isinstance(rate, (int, float)) or rate < 0 or rate > 100:
            raise ValueError(f"{country['code']}: invalid standard rate {rate!r}")
        for region in country["regions"]:
            region_rate = region["rate"]
            if not isinstance(region_rate, (int, float)) or region_rate < 0 or region_rate > 100:
                raise ValueError(f"{country['code']}/{region['code']}: invalid region rate")
    us = next((country for country in countries if country["code"] == "US"), None)
    if us is None or len(us["regions"]) < 50:
        raise ValueError("US dataset must include at least 50 states")


def compare_previous(countries: List[Dict[str, Any]], previous_path: Optional[Path]) -> List[str]:
    if previous_path is None or not previous_path.exists():
        return []
    try:
        previous = json.loads(previous_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"Could not read previous snapshot: {error}"]
    old = {item["code"]: item for item in previous.get("countries", [])}
    warnings: List[str] = []
    for country in countries:
        before = old.get(country["code"])
        if not before:
            continue
        old_rate = number(before.get("standardRate"))
        new_rate = country["standardRate"]
        if old_rate is not None and new_rate is not None and abs(old_rate - new_rate) >= 10:
            warnings.append(
                f"{country['code']}: standard rate moved from {old_rate}% to {new_rate}% since the previous snapshot"
            )
    return warnings


def build_dataset(global_payload: Dict[str, Any], us_payload: Dict[str, Any], eu_payload: List[Dict[str, Any]]) -> Dict[str, Any]:
    countries, warnings = build_global_countries(global_payload, eu_payload)
    countries.append(build_us(us_payload))
    countries.sort(key=lambda item: item["name"])
    validate(countries)

    global_meta = global_payload.get("meta", {})
    sources = [
        {
            "name": "VATEstimator",
            "url": "https://vatestimator.com/vat-rates",
            "license": global_meta.get("license") or "Free to use with attribution",
            "updatedAt": global_meta.get("last_updated"),
        },
        {
            "name": "ReceiptEdit",
            "url": US_URL,
            "license": us_payload.get("attribution") or "Free to use with attribution",
            "updatedAt": us_payload.get("last_updated"),
        },
        {
            "name": "VATcomply / European Commission",
            "url": EU_URL,
            "license": "EU VAT rates cross-check",
            "updatedAt": None,
        },
    ]

    return {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "sources": sources,
        "warnings": warnings,
        "countries": countries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("QuickVAT/Resources/rates.json"),
        help="Where to write the normalized dataset",
    )
    parser.add_argument(
        "--previous",
        type=Path,
        default=None,
        help="Optional previous snapshot used for anomaly warnings",
    )
    args = parser.parse_args()

    try:
        global_payload = fetch_json(VATE_URL)
        us_payload = fetch_json(US_URL)
        eu_payload = fetch_json(EU_URL)
        dataset = build_dataset(global_payload, us_payload, eu_payload)
        dataset["warnings"].extend(compare_previous(dataset["countries"], args.previous))
        validate(dataset["countries"])
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        print(f"Rate update failed: {error}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    for warning in dataset["warnings"]:
        print(f"WARNING: {warning}", file=sys.stderr)
    print(
        f"Wrote {len(dataset['countries'])} countries "
        f"({len(next(country for country in dataset['countries'] if country['code'] == 'US')['regions'])} US states) "
        f"to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
