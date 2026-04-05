from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TARGET_HOST = "bedrock.nationsglory.fr"
DEFAULT_TARGET_PORT = 19132
DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 19132

TEXT_PATTERNS = [
    ("kill", re.compile(r"^(?P<killer>.+?) a tue (?P<victim>.+)$", re.IGNORECASE)),
    ("kill", re.compile(r"^(?P<killer>.+?) killed (?P<victim>.+)$", re.IGNORECASE)),
    ("join", re.compile(r"^(?P<player>.+?) a rejoint la partie$", re.IGNORECASE)),
    ("join", re.compile(r"^(?P<player>.+?) joined the game$", re.IGNORECASE)),
    ("leave", re.compile(r"^(?P<player>.+?) a quitte la partie$", re.IGNORECASE)),
    ("leave", re.compile(r"^(?P<player>.+?) left the game$", re.IGNORECASE)),
    ("chat", re.compile(r"^<(?P<player>[^>]+)> (?P<message>.+)$")),
]

NOISE_PATTERNS = (
    "raknet",
    "commonsystem",
    "playstatus",
    "resourcepacks",
    "modalformrequest",
    "serverauth",
)
RAW_LOG_LIMIT = 250
PACKET_LOG_LIMIT = 400


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_spool_dir() -> str:
    if os.name == "nt":
        appdata = os.getenv("APPDATA")
        if appdata:
            return os.path.join(appdata, "WarControl")
    return os.path.expanduser("~/.warcontrol")


def _post_events(api_url: str, api_key: str | None, events: list[dict]) -> None:
    url = api_url.rstrip("/") + "/ingest"
    data = json.dumps({"events": events}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "WarControlProxy/1.0"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"Unexpected status {response.status}")


def _load_outbox(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _save_outbox(path: Path, events: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def _flush_events(api_url: str, api_key: str | None, spool_path: Path, events: list[dict]) -> None:
    pending = _load_outbox(spool_path)
    pending.extend(events)
    if not pending:
        return
    try:
        _post_events(api_url, api_key, pending)
        if spool_path.exists():
            spool_path.unlink()
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"[proxy] failed to send events: {exc}", file=sys.stderr, flush=True)
        _save_outbox(spool_path, pending)


def _normalize_text(raw: str) -> str:
    value = raw.replace("\x00", " ").replace("\n", " ").replace("\r", " ").strip()
    value = re.sub(r"\s+", " ", value)
    replacements = {
        "é": "e",
        "è": "e",
        "ê": "e",
        "à": "a",
        "ù": "u",
        "ç": "c",
        "ô": "o",
        "î": "i",
        "ï": "i",
        "ü": "u",
        "ö": "o",
        "â": "a",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst).replace(src.upper(), dst.upper())
    return value


def _extract_text_candidates(payload: bytes) -> list[str]:
    chunks: list[str] = []
    for encoding in ("utf-8", "utf-16-le", "latin-1"):
        try:
            text = payload.decode(encoding, errors="ignore")
        except LookupError:
            continue
        chunks.extend(re.findall(r"[ -~\u00a0-\u024f]{6,}", text))
    cleaned: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        value = _normalize_text(chunk)
        lower = value.lower()
        if len(value) < 6:
            continue
        if any(noise in lower for noise in NOISE_PATTERNS):
            continue
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def _classify_text(message: str, server: str, source: str) -> dict | None:
    for event_type, pattern in TEXT_PATTERNS:
        match = pattern.match(message)
        if not match:
            continue
        data = match.groupdict()
        actor = data.get("player") or data.get("killer")
        target = data.get("victim")
        return {
            "ts": _now_iso(),
            "type": event_type,
            "message": message,
            "actor": actor,
            "target": target,
            "server": server,
            "source": source,
            "raw": message,
        }
    if "guerre" in message.lower() or "raid" in message.lower():
        return {
            "ts": _now_iso(),
            "type": "war_alert",
            "message": message,
            "actor": None,
            "target": None,
            "server": server,
            "source": source,
            "raw": message,
        }
    return None


class BedrockProxy:
    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        target_host: str,
        target_port: int,
        api_url: str,
        api_key: str | None,
        server: str,
        source: str,
        spool_path: Path,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.target_addr = (socket.gethostbyname(target_host), target_port)
        self.api_url = api_url
        self.api_key = api_key
        self.server = server
        self.source = source
        self.spool_path = spool_path
        self.client_addr: tuple[str, int] | None = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((listen_host, listen_port))
        self.sock.settimeout(1.0)
        self._seen_messages: dict[str, float] = {}
        self._running = True
        self.raw_log_path = spool_path.parent / "proxy-raw.log"
        self.packet_log_path = spool_path.parent / "proxy-packets.log"
        self._raw_log_count = 0
        self._packet_log_count = 0
        self._client_packets = 0
        self._server_packets = 0

    def serve_forever(self) -> None:
        print(
            f"[proxy] listening on {self.listen_host}:{self.listen_port} -> "
            f"{self.target_addr[0]}:{self.target_addr[1]}",
            flush=True,
        )
        self._emit_system_event("proxy_ready", f"Proxy listening on {self.listen_host}:{self.listen_port}")
        while self._running:
            try:
                payload, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                self._expire_seen()
                continue
            except OSError:
                break
            if addr == self.target_addr:
                self._server_packets += 1
                self._log_packet("server", payload, addr)
                if self.client_addr:
                    self.sock.sendto(payload, self.client_addr)
                self._ingest_payload(payload, direction="server")
            else:
                self.client_addr = addr
                self._client_packets += 1
                self._log_packet("client", payload, addr)
                self.sock.sendto(payload, self.target_addr)
                self._ingest_payload(payload, direction="client")

    def close(self) -> None:
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass

    def _emit_system_event(self, event_type: str, message: str) -> None:
        event = {
            "ts": _now_iso(),
            "type": event_type,
            "message": message,
            "actor": None,
            "target": None,
            "server": self.server,
            "source": self.source,
            "raw": message,
        }
        _flush_events(self.api_url, self.api_key, self.spool_path, [event])

    def _ingest_payload(self, payload: bytes, direction: str) -> None:
        candidates = _extract_text_candidates(payload)
        events: list[dict] = []
        for text in candidates:
            key = f"{direction}:{text}"
            now = time.time()
            if now - self._seen_messages.get(key, 0) < 8:
                continue
            self._seen_messages[key] = now
            event = _classify_text(text, self.server, self.source)
            if event is not None:
                events.append(event)
            elif direction == "server":
                self._log_raw_candidate(text)
        if events:
            for event in events:
                print(f"[proxy] event {event['type']}: {event['message']}", flush=True)
            _flush_events(self.api_url, self.api_key, self.spool_path, events)

    def _expire_seen(self) -> None:
        now = time.time()
        self._seen_messages = {k: v for k, v in self._seen_messages.items() if now - v < 30}

    def _log_raw_candidate(self, text: str) -> None:
        if self._raw_log_count >= RAW_LOG_LIMIT:
            return
        self.raw_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.raw_log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{_now_iso()} RAW {text}\n")
        self._raw_log_count += 1

    def _log_packet(self, direction: str, payload: bytes, addr: tuple[str, int]) -> None:
        if self._packet_log_count >= PACKET_LOG_LIMIT:
            return
        first_byte = payload[0] if payload else -1
        preview = payload[:16].hex(" ")
        self.packet_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.packet_log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{_now_iso()} {direction.upper()} from={addr[0]}:{addr[1]} size={len(payload)} "
                f"first_byte={first_byte} hex={preview}\n"
            )
        self._packet_log_count += 1


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WarControl Bedrock UDP proxy")
    parser.add_argument("--listen-host", default=DEFAULT_LISTEN_HOST)
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT)
    parser.add_argument("--target-host", default=DEFAULT_TARGET_HOST)
    parser.add_argument("--target-port", type=int, default=DEFAULT_TARGET_PORT)
    parser.add_argument("--api-url", default=os.getenv("WARCONTROL_API_URL", DEFAULT_API_URL))
    parser.add_argument("--api-key", default=os.getenv("WARCONTROL_API_KEY"))
    parser.add_argument("--server", default=os.getenv("WARCONTROL_SERVER", "NationGlory"))
    parser.add_argument("--source", default=os.getenv("WARCONTROL_SOURCE", os.getenv("USERNAME", "bedrock-proxy")))
    parser.add_argument("--spool-dir", default=os.getenv("WARCONTROL_SPOOL_DIR", _default_spool_dir()))
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    spool_path = Path(args.spool_dir) / "proxy-outbox.jsonl"
    proxy = BedrockProxy(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        target_host=args.target_host,
        target_port=args.target_port,
        api_url=args.api_url,
        api_key=args.api_key,
        server=args.server,
        source=args.source,
        spool_path=spool_path,
    )
    stop_event = threading.Event()

    def _handle_exit(*_args: object) -> None:
        stop_event.set()
        proxy.close()

    try:
        proxy.serve_forever()
    except KeyboardInterrupt:
        _handle_exit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
