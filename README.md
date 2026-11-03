# QuickVAT Rate Data

Automated VAT, GST, SST, and US state sales-tax data for the QuickVAT Calculator iOS app.

This repository contains only generated rate data and the updater script. The app reads `rates.json` from the public raw GitHub URL or the jsDelivr fallback.

## Data sources

- Global VAT/GST rates: [VATEstimator](https://vatestimator.com/vat-rates)
- US state sales-tax rates: [ReceiptEdit](https://receiptedit.com/api/sales-tax)
- EU cross-check: [VATcomply](https://api.vatcomply.com/vat_rates) / European Commission

Rates are for reference only and may change. Verify with the local tax authority before filing.

## Updates

- GitHub Actions runs daily at `07:00 UTC`.
- Manual runs are available through `workflow_dispatch`.
- Generated output: `rates.json`.
- The updater validates country codes, rate ranges, US state coverage, and default state selection.
- Large changes are reported as warnings in the generated JSON.

## Local run

```sh
python3 scripts/update_rates.py --output rates.json
```

To compare against the current published snapshot:

```sh
python3 scripts/update_rates.py --previous rates.json --output rates.json
```
