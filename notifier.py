from tradeeye.config import load_settings
from tradeeye.services.notifier import send_report as _send_report


def send_report(content: str) -> bool:
    return _send_report(content, load_settings())
