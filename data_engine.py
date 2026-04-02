import tushare as ts
import pandas as pd
import os
from config import config

# 初始化
ts.set_token(config.TUSHARE_TOKEN)
pro = ts.pro_api()

def get_clean_data(code):
    """抓取数据、计算指标并清洗"""
    try:
        # 1. 获取基础信息
        base_info = pro.stock_basic(ts_code=code, fields='name')
        name = base_info.iloc[0]['name'] if not base_info.empty else "未知"
        
        # 2. 获取行情
        df = pro.daily(ts_code=code, limit=30)
        if df.empty: return None
        df = df.sort_values('trade_date')
        
        # 3. 计算 MA
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        
        # 4. 调试模式存档 (三板斧之二)
        if config.DEBUG_MODE:
            os.makedirs("debug_data", exist_ok=True)
            df.to_csv(f"debug_data/{code}_debug.csv", index=False, encoding='utf_8_sig')
            
        return {"name": name, "df": df, "latest": df.iloc[-1], "prev": df.iloc[-2]}
    except Exception as e:
        print(f"❌ 数据引擎异常({code}): {e}")
        return None