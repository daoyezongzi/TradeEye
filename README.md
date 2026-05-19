# TradeEye

TradeEye is a stock review automation project with three workflows:

- `analysis`: stock review (local scoring + optional LLM explanation) -> Feishu push
- `recommend`: grouped candidate recommendation + LLM explanation -> Feishu push
- `news`: RSS finance digest -> Feishu push

## Fastest Path (Recommended)

For real usage, the main path is GitHub Actions.  
Local run is for debug/verification.

1. Clone repo.
2. Decide which stocks you want to track (`MY_STOCKS`).
3. Fill API/webhook config (`TUSHARE_TOKEN`, `LLM_API_KEY`, `FEISHU_WEBHOOK`).
4. Run one command.

## Local Deployment (Windows PowerShell)

### 1) Clone and install

```powershell
git clone <your-repo-url>
cd TradeEye
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

### 2) Create env file

```powershell
Copy-Item .env.example .env
```

Required values in `.env`:

- `TUSHARE_TOKEN`: market data token
- `LLM_API_KEY`: LLM API key
- `FEISHU_WEBHOOK`: Feishu bot webhook

Most important runtime configs:

- `MY_STOCKS`: comma-separated codes, for example `600157.SH,002372.SZ`
- `ALLOWED_EXCHANGES`: for example `SH,SZ,BJ`
- `LLM_BASE_URL`: default `https://api.deepseek.com`
- `LLM_MODEL`: default `deepseek-v4-flash`

### 3) Run workflows

```powershell
python main.py           # analysis
python recommend_main.py # recommend
python news_main.py      # news
```

Or one-click launcher:

```powershell
run_tradeeye.bat analysis
run_tradeeye.bat recommend
run_tradeeye.bat news
```

`run_tradeeye.bat` is local-only convenience. GitHub Actions does not use this file.

## GitHub Actions Deployment

If you only need scheduled/production runs, this is enough. You do not need `run_tradeeye.bat`.

This repo has two workflow files:

- `.github/workflows/TradeEye-1.0.0.yml` for `analysis` + `recommend`
- `.github/workflows/TradeEye-news-1.0.0.yml` for `news`

Set GitHub **Secrets**:

- `TUSHARE_TOKEN`
- `LLM_API_KEY`
- `FEISHU_WEBHOOK`

Optional GitHub **Variables**:

- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_TIMEOUT_SEC`
- `RECOMMENDER_INDUSTRIES`
- `NEWS_*` configs

### Built-in schedules

- `recommend`: `0 22 * * 0-4` (UTC), around China `06:00` weekdays
- `analysis`: `30 7 * * 1-5` (UTC), around China `15:30` weekdays
- `news`: `30 23 * * 0-4` (UTC), around China `07:30` weekdays

You can also run manually from GitHub Actions `workflow_dispatch`.

## Current Analysis Logic

`analysis` now uses a local score gate before LLM call:

- `score >= 70`: call LLM analysis
- `score < 70`: local template output only, skip LLM

This reduces API usage while preserving strong-signal explanations.

## Environment Variables

- `TUSHARE_TOKEN`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_TIMEOUT_SEC`
- `FEISHU_WEBHOOK`
- `DEBUG_MODE`
- `MY_STOCKS`
- `ALLOWED_EXCHANGES`
- `RECOMMENDER_INDUSTRIES`
- `NEWS_RSS_FEEDS`
- `NEWS_RSS_FEEDS_FILE`
- `NEWS_LOOKBACK_HOURS`
- `NEWS_MAX_ITEMS`
- `NEWS_INCLUDE_KEYWORDS`
- `NEWS_EXCLUDE_KEYWORDS`
- `NEWS_PUSH_WHEN_EMPTY`
- `NEWS_TEMPLATE_FILE`
- `UPLOAD_EXCLUDE_PATTERNS`

## Validation

```powershell
python -m pytest -q
```
