from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def check_signals(data: dict[str, Any]) -> dict[str, Any]:
    if not data or "latest" not in data or "prev" not in data:
        return {
            "score": 0,
            "status": "\u3010\u6570\u636e\u7f3a\u5931\u3011",
            "detail": "\u65e0\u6cd5\u83b7\u53d6\u884c\u60c5",
            "vol_ratio": 0,
        }

    latest = data["latest"]
    prev = data["prev"]

    prev_vol = prev.get("vol", 0)
    vol_ratio = latest["vol"] / prev_vol if prev_vol > 0 else 0

    pct_chg = latest.get("pct_chg", 0)
    close = latest.get("close", 0)
    open_price = latest.get("open", 0)
    ma20 = latest.get("ma20", 0)
    ma5 = latest.get("ma5", 0)

    score = 0
    reasons: list[str] = []

    is_shrink = vol_ratio <= 0.7 and vol_ratio > 0
    is_on_support = ma20 > 0 and close >= ma20 and close <= ma20 * 1.03

    if is_shrink and is_on_support:
        score += 50
        reasons.append("\u7cbe\u51c6\u56de\u8e29 20 \u65e5\u7ebf\u4e14\u7f29\u91cf")
    elif is_shrink:
        score += 20
        reasons.append("\u91cf\u80fd\u840e\u7f29")
    elif is_on_support:
        score += 20
        reasons.append("\u56de\u8e29\u652f\u6491\u533a")

    if ma5 > ma20 and ma20 > 0:
        score += 20
        reasons.append("\u591a\u5934\u8d8b\u52bf\u4e2d")

    if close > open_price:
        score += 10
        reasons.append("K \u7ebf\u6536\u9633")

    if pct_chg < -4:
        score -= 60
        reasons.append("\u5927\u9634\u7ebf\u7834\u4f4d\uff08\u5371\u9669\uff09")

    if score >= 70:
        status = "\u3010\u9ad8\u5206\u6d17\u76d8\u786e\u8ba4\u3011"
    elif score >= 40:
        status = "\u3010\u89c2\u5bdf\u3011\u7591\u4f3c\u6d17\u76d8"
    else:
        status = "\u3010\u6682\u65e0\u673a\u4f1a\u3011"

    return {
        "score": score,
        "status": status,
        "detail": " + ".join(reasons) if reasons else "\u6ce2\u52a8\u5e73\u6de1",
        "vol_ratio": round(vol_ratio, 2),
    }


def load_yaml_config(strategy_name: str = "shrink_pullback") -> dict[str, Any]:
    yaml_path = Path(__file__).with_name(f"{strategy_name}.yaml")
    if yaml_path.exists():
        with yaml_path.open("r", encoding="utf-8") as file_obj:
            return yaml.safe_load(file_obj)
    return {}
