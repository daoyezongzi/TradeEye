import os
import time
import requests
import tushare as ts

# 1. 密钥配置 (从 GitHub Secrets 读取)
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "").strip()
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()

# 2. 股票清单 (Tushare 格式)
MY_STOCKS = ["601880.SH", "600157.SH", "603010.SH", "002372.SZ", "600905.SH"]

# 初始化 Tushare
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def fetch_tushare_data(code):
    try:
        # 获取基础信息（为了拿名称）
        base_info = pro.stock_basic(ts_code=code, fields='name')
        name = base_info.iloc[0]['name'] if not base_info.empty else "未知股票"
        
        # 获取日线行情
        df = pro.daily(ts_code=code, limit=1)
        if not df.empty:
            it = df.iloc[0]
            # --- 关键修改：把名称加进去 ---
            return f"代码:{code}, 名称:{name}, 日期:{it['trade_date']}, 现价:{it['close']}, 涨跌幅:{it['pct_chg']}%"
    except Exception as e:
        print(f"❌ Tushare 错误 ({code}): {e}")
    return None

def get_dify_analysis(stock_data):
    """调用 Dify 获取 AI 分析"""
    url = "https://api.dify.ai/v1/workflows/run"
    headers = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "inputs": {"stock_data": stock_data},
        "response_mode": "blocking",
        "user": "bot"
    }
    res = requests.post(url, json=payload, headers=headers)
    return res.json().get('data', {}).get('outputs', {}).get('text', '分析失败')

def push_to_feishu(content):
    """目标 1：发送合并后的消息"""
    payload = {"msg_type": "text", "content": {"text": f"📊 每日个股复盘汇总：\n\n{content}"}}
    requests.post(FEISHU_WEBHOOK, json=payload)

def main():
    all_reports = []
    print(f"🚀 任务开始，共 {len(MY_STOCKS)} 只股票")
    
    for code in MY_STOCKS:
        data = fetch_tushare_data(code)
        if data:
            analysis = get_dify_analysis(data)
            all_reports.append(f"📌 {code}\n{analysis}")
            print(f"✅ {code} 分析完成")
            time.sleep(1) # 避开频率限制

# 目标 1：在这里进行合并
    if all_reports:
        # 修改点：将原来的双重横线 "\n\n--------------------\n\n" 
        # 改为简单的两个换行 "\n\n"，因为 Dify 的输出里已经自带了 ---
        final_msg = "\n\n".join(all_reports)
        
        # 发送汇总消息
        push_to_feishu(final_msg)
        print(f"🎊 成功汇总 {len(all_reports)} 只股票分析并推送到飞书！")

if __name__ == "__main__":
    main()
