import numpy as np
import pandas as pd


def _safe_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if np.isfinite(number) else float(default)


def preprocess(features_dict):
    title = features_dict.get("title") or features_dict.get("bid_ntce_nm") or ""
    agency = (
        features_dict.get("agency_name")
        or features_dict.get("dminstt_nm")
        or features_dict.get("ntce_instt_nm")
        or "전국"
    )
    mode = str(features_dict.get("scenario_mode") or features_dict.get("mode") or "2")
    if mode not in {"1", "2", "3"}:
        mode = "2"

    return pd.DataFrame(
        [
            {
                "title": str(title),
                "agency_name": str(agency),
                "presmpt_prce": max(_safe_float(features_dict.get("presmpt_prce"), 0.0), 0.0),
                "scenario_mode": mode,
                "category": str(features_dict.get("category") or ""),
            }
        ]
    )
