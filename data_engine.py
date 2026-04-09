from tradeeye.config import load_settings
from tradeeye.services.data import get_clean_data as _get_clean_data


def get_clean_data(code: str):
    return _get_clean_data(code, load_settings())
