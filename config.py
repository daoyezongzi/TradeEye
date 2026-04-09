from tradeeye.config import load_settings


class Config:
    @property
    def TUSHARE_TOKEN(self) -> str:
        return load_settings().tushare_token

    @property
    def DIFY_API_KEY(self) -> str:
        return load_settings().dify_api_key

    @property
    def FEISHU_WEBHOOK(self) -> str:
        return load_settings().feishu_webhook

    @property
    def DIFY_BASE_URL(self) -> str:
        return load_settings().dify_base_url

    @property
    def DEBUG_MODE(self) -> bool:
        return load_settings().debug_mode

    @property
    def MY_STOCKS(self) -> list[str]:
        return load_settings().my_stocks


config = Config()
