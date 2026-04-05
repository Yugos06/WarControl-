# WarControl API

## Run (dev)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
WARCONTROL_INGEST_KEY=change-me uvicorn api.main:app --reload
```

## Env

- `WARCONTROL_DB_PATH` (default: `data/warcontrol.db`)
- `WARCONTROL_INGEST_KEY` (required unless `WARCONTROL_ALLOW_OPEN_INGEST=1`)
- `WARCONTROL_ALLOW_OPEN_INGEST` (set to `1` for local testing)
- `WARCONTROL_WEB_ORIGINS` (comma-separated, default: `*`)
