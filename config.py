import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # 基础密钥
    TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
    DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
    FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
    
    # 模式开关：只要 .env 里没有显式写 DEBUG_MODE=False，本地就默认是 True
    DEBUG_MODE = os.getenv("DEBUG_MODE", "True").lower() == "true"
    
    # 股票池
    MY_STOCKS = ["601880.SH", "600157.SH", "603010.SH", "002372.SZ", "600905.SH", "600009.SH"]

config = Config()