# WarControl Collector

Collects Minecraft client log events and sends them to the WarControl API.

## Usage

```bash
python3 agent.py --edition bedrock --api-url http://127.0.0.1:8000 --api-key YOUR_KEY --server NationGlory --source PlayerName
```

If auto-detection misses, force the path:

```bash
python3 agent.py --edition bedrock --log-path "C:\\Users\\<username>\\AppData\\Roaming\\Minecraft Bedrock\\logs\\latest.log"
```

## Notes

- `--edition` can be `auto`, `java`, or `bedrock`.
- `--send-all` will forward every log line as `type=log`.
- If the API is offline, events are buffered in `~/.warcontrol/outbox.jsonl` and retried on next send.
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

Windows Bedrock paths (depends on the Minecraft build):
- `%APPDATA%\\Minecraft Bedrock\\logs\\latest.log`
- `%LOCALAPPDATA%\\Packages\\Microsoft.MinecraftUWP_8wekyb3d8bbwe\\LocalState\\logs\\latest.log`
