from pathlib import Path


def test_positions_ui_includes_full_reference_csv_columns():
    app_js = Path(__file__).resolve().parents[1] / 'gui' / 'static' / 'app.js'
    text = app_js.read_text(encoding='utf-8')

    required = [
        "'Product'",
        "'Application'",
        "'Flow'",
        "'Trader'",
        "'Desk'",
        "'Account'",
        "'Client'",
        "'symbol'",
        "'exchange'",
        "'underlying'",
        "'Algo Strategy'",
        "'Currency'",
        "'Order Type'",
        "'Tif'",
        "'xr'",
        "'bvol'",
        "'bval'",
        "'bval_usd'",
        "'bfill'",
        "'bfillval'",
        "'bfillval_usd'",
        "'bopen'",
        "'bopenval'",
        "'bopenval_usd'",
        "'Bexposure'",
        "'svol'",
        "'sval'",
        "'sval_usd'",
        "'sfill'",
        "'sfillval'",
        "'sfillval_usd'",
        "'sopen'",
        "'sopenval'",
        "'sopenval_usd'",
        "'Sexposure'",
        "'Ssexposure'",
    ]

    missing = [name for name in required if name not in text]
    assert not missing, f"Missing CSV columns from Positions UI: {missing}"
