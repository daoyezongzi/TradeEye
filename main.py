import os
import time
import requests
import tushare as ts

# 1. 密钥配置
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "").strip()
DIFY_API_KEY = os.environ.get("DIFY_API_KEY", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()

# 2. 股票清单
MY_STOCKS = ["601880.SH", "600157.SH", "603010.SH", "002372.SZ", "600905.SH", "600009.SH"]

# 初始化 Tushare
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

def fetch_tushare_data(code):
    try:
        # 1. 获取基本信息（名称）
        base_info = pro.stock_basic(ts_code=code, fields='name')
        name = base_info.iloc[0]['name'] if not base_info.empty else "未知股票"
        
        # 2. 获取最近 30 天日线行情（计算 20 日均线需要足够样本）
        df = pro.daily(ts_code=code, limit=30)
        if df.empty: return None
        
        # 按日期正序排列（算均线必须从旧到新）
        df = df.sort_values('trade_date')
        
        # 计算均线 (MA)
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()
        
        # 获取最新一天的行情数据
        latest = df.iloc[-1]
        prev = df.iloc[-2] # 前一天数据，用于对比成交量
        
        # 3. 获取换手率 (从 daily_basic 接口获取)
        basic_df = pro.daily_basic(ts_code=code, limit=1, fields='turnover_rate')
        turnover = basic_df.iloc[0]['turnover_rate'] if not basic_df.empty else "未知"
        
        # 4. 判断成交量变化（放量还是缩量）
        vol_ratio = latest['vol'] / prev['vol']
        vol_status = "放量" if vol_ratio >= 1.5 else "缩量" if vol_ratio <= 0.7 else "平量"

        # --- 组装增强版数据包 ---
        # 在 fetch_tushare_data 函数内部，找到组装 data_str 的地方：

        # 提取更多参考价格
        low_price = latest['low']   # 今日最低价（通常作为即时支撑）
        high_price = latest['high'] # 今日最高价（通常作为即时压力）
        prev_low = prev['low']     # 昨日最低价
        
        # --- 修改后的增强版数据包 ---
        data_str = (
            f"名称:{name}({code}), 现价:{latest['close']}, 涨跌:{latest['pct_chg']}%, "
            f"MA5:{round(latest['ma5'], 2)}, MA20:{round(latest['ma20'], 2)}, "
            f"今日高低:[{high_price}, {low_price}], 昨日低点:{prev_low}, "  # 新增参考位
            f"成交量:{vol_status}(量比{round(vol_ratio, 2)}), 换手率:{turnover}"
        )

        return data_str
    except Exception as e:
        print(f"❌ 数据抓取异常 ({code}): {e}")
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
