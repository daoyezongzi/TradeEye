# TradeEye

TradeEye is a stock review automation script. It fetches daily market data from Tushare, applies a local scoring strategy, sends the cleaned context to Dify for deeper analysis, and delivers the final summary to Feishu.

## Project Layout

- `tradeeye/`: main package with app, config, services, and strategies
- `main.py`: compatibility entrypoint for local runs and GitHub Actions
- `recommend_main.py`: entrypoint for daily top-pick recommendation workflow
- `tests/`: basic unit tests for config, app flow, and strategy logic
- `.github/workflows/TradeEye-1.0.0.yml`: scheduled automation workflow

## Quick Start

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python recommend_main.py
python main.py
```

## Environment Variables

- `TUSHARE_TOKEN`: Tushare API token
- `DIFY_API_KEY`: Dify workflow API key
- `FEISHU_WEBHOOK`: Feishu bot webhook URL
- `DIFY_BASE_URL`: Dify API base URL, defaults to `https://api.dify.ai/v1`
- `DEBUG_MODE`: when `true`, writes debug CSV files and prints reports locally
- `MY_STOCKS`: comma-separated stock codes
- `ALLOWED_EXCHANGES`: comma-separated exchange filters such as `SH,SZ` or `SH,SZ,BJ`
- `RECOMMENDER_INDUSTRIES`: optional comma-separated industries for long-value filter, e.g. `半导体,电力设备`

For the recommendation workflow, Dify should define an input variable named `recommendations_json`.

## Testing

```bash
pytest
```

## Automation

GitHub Actions runs the workflow on weekdays and can also be triggered manually from the Actions tab.
