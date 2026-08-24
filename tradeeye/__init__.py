"""TradeEye package."""


def main(*args, **kwargs):
    """Load the analysis entry point lazily to keep service imports independent."""
    from .app import main as analysis_main

    return analysis_main(*args, **kwargs)


__all__ = ["main"]
