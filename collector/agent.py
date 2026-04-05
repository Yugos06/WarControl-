from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_SPOOL_DIR = os.path.expanduser("~/.warcontrol")

JAVA_PATTERNS = [
    ("kill", re.compile(r"^(?P<victim>.+?) a été tué par (?P<killer>.+)$")),
    ("kill", re.compile(r"^(?P<victim>.+?) was slain by (?P<killer>.+)$")),
    ("join", re.compile(r"^(?P<player>.+?) a rejoint la partie$")),
    ("join", re.compile(r"^(?P<player>.+?) joined the game$")),
    ("leave", re.compile(r"^(?P<player>.+?) a quitté la partie$")),
    ("leave", re.compile(r"^(?P<player>.+?) left the game$")),
    ("chat", re.compile(r"^<(?P<player>[^>]+)> (?P<message>.+)$")),
]

BEDROCK_PATTERNS = [
    (
        "join",
        re.compile(r"^Player connected: (?P<player>[^,]+), xuid: (?P<xuid>\\d+)$"),
    ),
    (
        "leave",
        re.compile(
            r"^Player disconnected: (?P<player>[^,]+), xuid: (?P<xuid>\\d+)$"
        ),
    ),
    ("chat", re.compile(r"^Chat: <(?P<player>[^>]+)> (?P<message>.+)$")),
    ("chat", re.compile(r"^Chat: (?P<player>[^:]+): (?P<message>.+)$")),
]


@dataclass
class Settings:
    api_url: str
    api_key: str | None
    log_path: str
    server: str | None
    source: str | None
    edition: str
    patterns: list[tuple[str, re.Pattern[str]]]
    send_all: bool
    batch_size: int
    flush_seconds: float
    from_start: bool
    spool_path: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_line(line: str) -> str:
    line = line.strip()
    if "]: " in line:
        line = line.split("]: ", 1)[1]
    elif "] " in line:
        line = line.split("] ", 1)[1]
    return line


def parse_line(line: str, settings: Settings) -> dict | None:
    normalized = normalize_line(line)
    for event_type, pattern in settings.patterns:
        match = pattern.match(normalized)
        if not match:
            continue
        data = match.groupdict()
        actor = None
        target = None
        message = normalized
        if event_type == "kill":
            actor = data.get("killer")
            target = data.get("victim")
        elif event_type == "join":
            actor = data.get("player")
        elif event_type == "leave":
            actor = data.get("player")
        elif event_type == "chat":
            actor = data.get("player")
        return {
            "ts": _now_iso(),
            "type": event_type,
            "message": message,
            "actor": actor,
            "target": target,
            "server": settings.server,
            "source": settings.source,
            "raw": line.strip(),
        }

    if settings.send_all and normalized:
        return {
            "ts": _now_iso(),
            "type": "log",
            "message": normalized,
            "actor": None,
            "target": None,
            "server": settings.server,
            "source": settings.source,
            "raw": line.strip(),
        }

    return None


def default_log_path(edition: str) -> str:
    edition = edition.lower()
    if edition == "java":
        return os.path.expanduser("~/.minecraft/logs/latest.log")
    if edition == "bedrock":
        candidates: list[tuple[str, str]] = []
        appdata = os.getenv("APPDATA")
        if appdata:
            appdata_dir = os.path.join(appdata, "Minecraft Bedrock", "logs")
            candidates.append((appdata_dir, os.path.join(appdata_dir, "latest.log")))
        local_appdata = os.getenv("LOCALAPPDATA")
        if local_appdata:
            local_dir = os.path.join(
                local_appdata,
                "Packages",
                "Microsoft.MinecraftUWP_8wekyb3d8bbwe",
                "LocalState",
                "logs",
            )
            candidates.append((local_dir, os.path.join(local_dir, "latest.log")))
        for log_dir, log_path in candidates:
            if os.path.isdir(log_dir):
                return log_path
        for _, log_path in candidates:
            if os.path.exists(log_path):
                return log_path
        if candidates:
            return candidates[0][1]
        return "latest.log"
    if os.name == "nt":
        return default_log_path("bedrock")
    return default_log_path("java")


def choose_patterns(edition: str) -> list[tuple[str, re.Pattern[str]]]:
    edition = edition.lower()
    if edition == "bedrock":
        return BEDROCK_PATTERNS + JAVA_PATTERNS
    if edition == "java":
        return JAVA_PATTERNS
    return JAVA_PATTERNS + BEDROCK_PATTERNS


def post_events(api_url: str, api_key: str | None, events: list[dict]) -> None:
    url = api_url.rstrip("/") + "/ingest"
    data = json.dumps({"events": events}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "WarControlAgent/1.0"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Unexpected status {response.status}")


def load_outbox(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    events = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def save_outbox(path: str, events: Iterable[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def flush_events(settings: Settings, buffer: list[dict]) -> list[dict]:
    pending = load_outbox(settings.spool_path)
    pending.extend(buffer)
    if not pending:
        return []
    try:
        post_events(settings.api_url, settings.api_key, pending)
        return []
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"[agent] failed to send events: {exc}", file=sys.stderr)
        save_outbox(settings.spool_path, pending)
        return []


def follow_file(path: str, from_start: bool) -> Iterable[str]:
    while not os.path.exists(path):
        print(f"[agent] waiting for log file: {path}")
        time.sleep(2)

    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        if not from_start:
            handle.seek(0, os.SEEK_END)

        while True:
            line = handle.readline()
            if line:
                yield line
                continue

            time.sleep(0.5)
            try:
                if os.path.getsize(path) < handle.tell():
                    handle.seek(0, os.SEEK_END)
            except FileNotFoundError:
                break


def build_settings(args: argparse.Namespace) -> Settings:
    api_url = args.api_url or os.getenv("WARCONTROL_API_URL", DEFAULT_API_URL)
    api_key = args.api_key or os.getenv("WARCONTROL_API_KEY")
    edition = (args.edition or os.getenv("WARCONTROL_EDITION", "auto")).lower()
    if edition not in {"auto", "java", "bedrock"}:
        edition = "auto"
    log_path = args.log_path or os.getenv(
        "WARCONTROL_LOG_PATH", default_log_path(edition)
    )
    server = args.server or os.getenv("WARCONTROL_SERVER")
    source = args.source or os.getenv("WARCONTROL_SOURCE")
    spool_dir = args.spool_dir or os.getenv("WARCONTROL_SPOOL_DIR", DEFAULT_SPOOL_DIR)
    spool_path = os.path.join(spool_dir, "outbox.jsonl")

    return Settings(
        api_url=api_url,
        api_key=api_key,
        log_path=os.path.expanduser(log_path),
        server=server,
        source=source,
        edition=edition,
        patterns=choose_patterns(edition),
        send_all=args.send_all,
        batch_size=args.batch_size,
        flush_seconds=args.flush_seconds,
        from_start=args.from_start,
        spool_path=spool_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="WarControl log collector")
    parser.add_argument("--log-path", help="Path to latest.log")
    parser.add_argument("--api-url", help="Base URL for WarControl API")
    parser.add_argument("--api-key", help="Ingest API key")
    parser.add_argument("--server", help="Server name (e.g. NationGlory)")
    parser.add_argument("--source", help="Source identifier (e.g. Discord user)")
    parser.add_argument(
        "--edition",
        choices=["auto", "java", "bedrock"],
        default=None,
        help="Log format edition (default: auto)",
    )
    parser.add_argument("--send-all", action="store_true", help="Send every log line as type=log")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size before flush")
    parser.add_argument("--flush-seconds", type=float, default=3.0, help="Max seconds before flush")
    parser.add_argument("--from-start", action="store_true", help="Read file from start")
    parser.add_argument("--spool-dir", help="Directory for offline spool")
    args = parser.parse_args()

    settings = build_settings(args)
    print(f"[agent] tailing {settings.log_path}")

    buffer: list[dict] = []
    last_flush = time.time()

    for line in follow_file(settings.log_path, settings.from_start):
        event = parse_line(line, settings)
        if event:
            buffer.append(event)

        now = time.time()
        if buffer and (len(buffer) >= settings.batch_size or now - last_flush >= settings.flush_seconds):
            buffer = flush_events(settings, buffer)
            last_flush = now

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
