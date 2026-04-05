# WarControl Collector

Collects Minecraft client log events and sends them to the WarControl API.

## Usage

```bash
python agent.py --edition auto --api-url http://127.0.0.1:8000 --api-key YOUR_KEY --server NationGlory --source PlayerName
```

## Windows 11

On Windows 11, `--edition auto` checks Java and Bedrock log locations before falling back.

Common log paths:

- Java launcher: `%USERPROFILE%\.minecraft\logs\latest.log`
- Bedrock roaming install: `%APPDATA%\Minecraft Bedrock\logs\latest.log`
- Bedrock UWP install: `%LOCALAPPDATA%\Packages\Microsoft.MinecraftUWP_8wekyb3d8bbwe\LocalState\logs\latest.log`

If auto-detection misses, force the path:

```powershell
python agent.py --edition java --log-path "$env:USERPROFILE\.minecraft\logs\latest.log"
```

```powershell
python agent.py --edition bedrock --log-path "$env:APPDATA\Minecraft Bedrock\logs\latest.log"
```

Offline events are buffered on Windows in `%APPDATA%\WarControl\outbox.jsonl`.

## Notes

- `--edition` can be `auto`, `java`, or `bedrock`.
- `--send-all` will forward every log line as `type=log`.
- If the API is offline, events are buffered locally and retried on next send.
- You can set environment variables instead of flags:
  - `WARCONTROL_API_URL`
  - `WARCONTROL_API_KEY`
  - `WARCONTROL_LOG_PATH`
  - `WARCONTROL_SERVER`
  - `WARCONTROL_SOURCE`
  - `WARCONTROL_EDITION`

## Java client log path (Linux)

Default path for the official launcher:
- Linux Java: `/home/<username>/.minecraft/logs/latest.log`
