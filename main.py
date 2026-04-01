import os
import time
import requests
import tushare as ts

# 1. 密钥配置
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "").strip()
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()

# 2. 股票清单
MY_STOCKS = ["601880.SH", "600157.SH", "603010.SH", "002372.SZ", "600905.SH"]

# 初始化 Tushare
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def fetch_tushare_data(code):
    try:
        # --- 优化点：增加 fields 参数，只取我们需要的那一行 ---
        # 很多时候 stock_basic 需要较多积分，如果这里报错，请检查 Tushare 积分
        base_info = pro.stock_basic(ts_code=code, fields='name')
        name = base_info.iloc[0]['name'] if not base_info.empty else "未知股票"
        
        # 获取日线行情
        df = pro.daily(ts_code=code, limit=1)
        if not df.empty:
            it = df.iloc[0]
            # 这里一定要包含 "名称:{name}"，Dify 才能根据提示词抓取到
            return f"代码:{code}, 名称:{name}, 日期:{it['trade_date']}, 现价:{it['close']}, 涨跌幅:{it['pct_chg']}%"
    except Exception as e:
        print(f"❌ Tushare 数据获取异常 ({code}): {e}")
    return None

def get_dify_analysis(stock_data):
    url = "https://api.dify.ai/v1/workflows/run"
    headers = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "inputs": {"stock_data": stock_data},
        "response_mode": "blocking",
        "user": "github_actions"
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=60)
        # 增加解析保护，防止 Dify 返回非 200 状态码
        if res.status_code == 200:
            return res.json().get('data', {}).get('outputs', {}).get('text', '分析内容为空')
        else:
            return f"Dify 接口错误: {res.status_code}"
    except Exception as e:
        return f"分析请求失败: {e}"

def push_to_feishu(content):
    import datetime
    today = datetime.date.today().strftime('%Y-%m-%d')
    # 稍微润色一下标题
    payload = {
        "msg_type": "text", 
        "content": {"text": f"📊 {today} 个股复盘汇总报告：\n\n{content}"}
    }
    requests.post(FEISHU_WEBHOOK, json=payload)

def main():
    all_reports = []
    print(f"🚀 任务开始，共 {len(MY_STOCKS)} 只股票")
    
    for code in MY_STOCKS:
        data = fetch_tushare_data(code)
        if data:
            analysis = get_dify_analysis(data)
            # --- 优化点：因为 Dify 提示词里我们要求了输出【名称 (代码)】，
            # 所以这里不需要再加 "📌 {code}" 了，直接添加 analysis 即可
            all_reports.append(analysis)
            print(f"✅ {code} 分析完成")
            time.sleep(1.5) # 稍微增加延迟，保证稳定性

    # 合并发送
    if all_reports:
        # 用两个换行连接，配合 Dify 提示词里的 --- 分隔线
        final_msg = "\n\n".join(all_reports)
        push_to_feishu(final_msg)
        print(f"🎊 汇总推送成功！")

if __name__ == "__main__":
    main()
