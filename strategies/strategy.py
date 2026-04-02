import os
import yaml

def check_signals(data):
    """
    升级版策略逻辑：多维度评分系统 (Scoring System)
    基于 Tushare 数据源提供的 MA20, MA5, VOL 等指标进行量化评分
    """
    # 如果数据结构不完整，直接返回无效
    if not data or 'latest' not in data or 'prev' not in data:
        return {"score": 0, "status": "【数据缺失】", "detail": "无法获取行情", "vol_ratio": 0}

    latest = data['latest']
    prev = data['prev']
    
    # --- 1. 基础数据准备 ---
    # 防止除以零报错
    prev_vol = prev.get('vol', 0)
    vol_ratio = latest['vol'] / prev_vol if prev_vol > 0 else 0 
    
    pct_chg = latest.get('pct_chg', 0)
    close = latest.get('close', 0)
    open_price = latest.get('open', 0)
    ma20 = latest.get('ma20', 0)
    ma5 = latest.get('ma5', 0)
    
    score = 0
    reasons = []

    # --- 2. 核心：主力洗盘判定 (核心奖励) ---
    # 条件 A：缩量 (成交量小于昨日 70%)
    is_shrink = vol_ratio <= 0.7 and vol_ratio > 0
    # 条件 B：均线支撑 (股价在 20 日线上 3% 以内，属于有效回踩)
    # 注意：ma20 必须大于 0 才有意义
    is_on_support = ma20 > 0 and (close >= ma20) and (close <= ma20 * 1.03)

    if is_shrink and is_on_support:
        score += 50
        reasons.append("精准回踩20日线并缩量")
    elif is_shrink:
        score += 20
        reasons.append("量能萎缩")
    elif is_on_support:
        score += 20
        reasons.append("回踩支撑区")

    # --- 3. 趋势强度判定 (追加奖励) ---
    if ma5 > ma20 and ma20 > 0:
        score += 20
        reasons.append("多头趋势中")
    
    if close > open_price:
        score += 10
        reasons.append("K线收阳")

    # --- 4. 风险项 (惩罚分) ---
    if pct_chg < -4:
        score -= 60
        reasons.append("大阴线破位(危险)")

    # --- 5. 最终评价输出 ---
    if score >= 70:
        status = "【高分/洗盘确认】"
    elif score >= 40:
        status = "【观察/疑似洗盘】"
    else:
        status = "【暂无机会】"

    return {
        "score": score,
        "status": status,
        "detail": " + ".join(reasons) if reasons else "波动平淡",
        "vol_ratio": round(vol_ratio, 2)
    }

def load_yaml_config(strategy_name="shrink_pullback"):
    """预留：如果你未来想从 YAML 加载参数，可以用这个函数"""
    current_dir = os.path.dirname(__file__)
    yaml_path = os.path.join(current_dir, f"{strategy_name}.yaml")
    if os.path.exists(yaml_path):
        with open(yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}