import pandas as pd


def preprocess(features_dict):
    row = {
        "presmpt_prce": features_dict.get("presmpt_prce", features_dict.get("presmptPrce", 0)),
        "presmptPrce": features_dict.get("presmptPrce", features_dict.get("presmpt_prce", 0)),
        "cntrctCnclsMthdNm": features_dict.get("cntrctCnclsMthdNm", ""),
        "bidMethdNm": features_dict.get("bidMethdNm", ""),
        "ntceInsttNm": (
            features_dict.get("ntceInsttNm")
            or features_dict.get("ntce_instt_nm")
            or features_dict.get("agency_name")
            or features_dict.get("dminstt_nm")
            or ""
        ),
        "lower_rate": features_dict.get("lower_rate"),
        "category": features_dict.get("category", ""),
        "title": features_dict.get("title") or features_dict.get("bid_ntce_nm") or "",
        "bid_ntce_nm": features_dict.get("bid_ntce_nm", ""),
    }
    return pd.DataFrame([row])
