# WarControl Web

## Run (dev)

```bash
cd web
npm install
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev
```

```powershell
cd web
npm install
$env:NEXT_PUBLIC_API_URL="http://127.0.0.1:8000"
npm run dev
```

## Notes

- Update `NEXT_PUBLIC_API_URL` to point to your FastAPI server.
- The UI pulls `/events` and `/stats` every 3 seconds.
