from tradeeye.config import Settings
from tradeeye.portfolio_app import main
from tradeeye.services.portfolio import SettlementResult
from tradeeye.services.trading import MarketDataUnavailable


def settings(token=""):
    return Settings(
        tushare_token=token,
        feishu_webhook="",
        debug_mode=True,
        my_stocks=[],
        allowed_exchanges=("SH", "SZ", "BJ"),
    )


class Provider:
    pass


def test_main_requires_token_only_when_default_provider_is_needed():
    assert main(settings=settings(token="")) == 1


def test_main_success_and_idempotent_no_signal_result_return_zero():
    calls = []

    def settler(provider, as_of=None):
        calls.append((provider, as_of))
        return SettlementResult("20260807", 0, 0, 0, ())

    assert main(settings=settings(), provider=Provider(), as_of="20260807", settler=settler) == 0
    assert calls[0][1] == "20260807"


def test_main_supplier_failure_returns_one():
    def settler(provider, as_of=None):
        raise MarketDataUnavailable("global failure")

    assert main(settings=settings(), provider=Provider(), settler=settler) == 1
