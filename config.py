import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # 基础密钥
    TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
    DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")
    FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
    
    # Dify 官方工作流 API 地址
    DIFY_BASE_URL = os.getenv("DIFY_BASE_URL", "https://api.dify.ai/v1")
    
    # 模式开关：只要环境变量 DEBUG_MODE 不等于 "false"，本地默认就是调试模式
    DEBUG_MODE = os.getenv("DEBUG_MODE", "True").lower() != "false"
    DEBUG_MODE = False
    
    # 股票池
    MY_STOCKS = ["601880.SH", "600157.SH", "603010.SH", "002372.SZ", "600905.SH", "600009.SH"]

config = Config()