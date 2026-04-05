from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import pydivert  # type: ignore
except ImportError:  # pragma: no cover - depends on local install
    pydivert = None


@dataclass(frozen=True)
class Settings:
    target_host: str
    target_port: int
    proxy_host: str
    proxy_port: int
    mode: str
    log_path: Path
    max_packets: int


def _log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{timestamp} {message}\n")


def _build_filter(mode: str, port: int) -> str:
    if mode == "observe":
        return "udp"
    return f"udp and (udp.DstPort == {port} or udp.SrcPort == {port})"


def _make_settings(args: argparse.Namespace) -> Settings:
    state_dir = Path(os.getenv("APPDATA", ".")) / "WarControl"
    log_path = state_dir / "windivert.log"
    return Settings(
        target_host=args.target_host,
        target_port=args.target_port,
        proxy_host=args.proxy_host,
        proxy_port=args.proxy_port,
        mode=args.mode,
        log_path=log_path,
        max_packets=args.max_packets,
    )


def run(settings: Settings) -> int:
    if pydivert is None:
        _log(settings.log_path, "pydivert_missing")
        print("[windivert] pydivert is not installed.", file=sys.stderr)
        return 2

    target_ip = socket.gethostbyname(settings.target_host)
    _log(
        settings.log_path,
        f"observer_started mode={settings.mode} target={target_ip}:{settings.target_port} proxy={settings.proxy_host}:{settings.proxy_port}",
    )

    if settings.mode != "observe":
        _log(settings.log_path, f"mode_not_implemented mode={settings.mode}")
        print(
            "[windivert] redirect mode is intentionally not enabled yet; "
            "this scaffold only observes system traffic safely.",
            file=sys.stderr,
        )
        return 3

    packet_count = 0
    with pydivert.WinDivert(_build_filter(settings.mode, settings.target_port)) as w:  # pragma: no cover - Windows-only
        for packet in w:
            packet_count += 1
            if packet_count <= settings.max_packets:
                direction = "outbound" if packet.is_outbound else "inbound"
                src = f"{packet.src_addr}:{packet.src_port}"
                dst = f"{packet.dst_addr}:{packet.dst_port}"
                _log(settings.log_path, f"{direction} {src} -> {dst}")
            w.send(packet)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="WarControl WinDivert observer scaffold")
    parser.add_argument("--target-host", default="bedrock.nationsglory.fr")
    parser.add_argument("--target-port", type=int, default=19132)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=19132)
    parser.add_argument("--mode", choices=["observe", "redirect"], default="observe")
    parser.add_argument("--max-packets", type=int, default=500)
    args = parser.parse_args()
    settings = _make_settings(args)
    return run(settings)


if __name__ == "__main__":
    raise SystemExit(main())
