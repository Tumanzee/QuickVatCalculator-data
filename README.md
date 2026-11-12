# QuickVAT Rate Data

Automated VAT, GST, SST, and US state sales-tax data for the QuickVAT Calculator iOS app.

This repository contains only generated rate data and the updater script.

## Published endpoints

- Raw GitHub: `https://raw.githubusercontent.com/Tumanzee/QuickVatCalculator-data/main/rates.json`
- jsDelivr fallback: `https://cdn.jsdelivr.net/gh/Tumanzee/QuickVatCalculator-data@main/rates.json`

## Data sources

- Global VAT/GST rates (174): [VATEstimator](https://vatestimator.com/vat-rates)
- US state sales-tax rates: [ReceiptEdit](https://receiptedit.com/api/sales-tax) (API; GitHub dataset fallback)
- EU cross-check: [VATcomply](https://api.vatcomply.com/vat_rates) / European Commission

Rates are for reference only and may change. Verify with the local tax authority before filing.

## Updates

- GitHub Actions runs daily at `07:00 UTC`.
- Manual runs are available through `workflow_dispatch`.
- Generated output: `rates.json`.
- The updater validates country codes, rate ranges, US state coverage, and default state selection.
- Standard-rate moves of 10 percentage points or more are reported as warnings.

## Local run

```sh
python3 scripts/update_rates.py --output rates.json
```

To compare against the current published snapshot:

```sh
python3 scripts/update_rates.py --previous rates.json --output rates.json
```
