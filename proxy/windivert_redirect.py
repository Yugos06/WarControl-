"""
WarControl — WinDivert network interceptor
==========================================

Trois modes :

  observe  Capture et log tout le trafic UDP vers/depuis les IPs NationsGlory
           (filtre ciblé, pas "udp" brut). Le jeu continue normalement.
           Utile pour découvrir les IPs/ports des sous-serveurs (home → DELTA).

  tap      Copie chaque payload UDP NG vers le proxy local via un socket UDP
           sans modifier le paquet original. Le jeu continue normalement.
           C'est le mode principal pour l'analyse en temps réel.

  redirect Réécrit la destination des paquets Minecraft → NG vers le proxy local.
           Plus intrusif, à utiliser seulement si tap ne suffit pas.

Prérequis : pydivert installé + exécution en administrateur.
"""
from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set

try:
    import pydivert  # type: ignore
except ImportError:  # pragma: no cover
    pydivert = None

# Port d'écoute du tap dans le proxy (distinct du 19132 RakNet)
TAP_PORT = 19133

# Plage de ports Bedrock typiquement utilisée par NationsGlory (hub + sous-serveurs)
NG_PORT_MIN = 19100
NG_PORT_MAX = 19200


@dataclass(frozen=True)
class Settings:
    target_host: str
    target_port: int
    proxy_host: str
    proxy_port: int
    tap_port: int
    mode: str
    log_path: Path


@dataclass
class State:
    """État mutable partagé entre les callbacks."""
    packet_count: int = 0
    ng_packet_count: int = 0
    discovered_ips: Set[str] = field(default_factory=set)
    discovered_ports: Set[int] = field(default_factory=set)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"{ts} {message}\n"
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    print(f"[windivert] {message}", flush=True)


# ---------------------------------------------------------------------------
# Filtres WinDivert
# ---------------------------------------------------------------------------

def _build_filter(target_ip: str) -> str:
    """
    Filtre ciblé sur l'IP NationsGlory résolue ET la plage de ports connue.
    Évite de capturer tout UDP du système (Wi-Fi, DNS, Steam, etc.).
    On capture dans les deux sens : Minecraft→NG et NG→Minecraft.
    """
    ip_filter = f"ip.SrcAddr == {target_ip} or ip.DstAddr == {target_ip}"
    port_range = (
        f"(udp.SrcPort >= {NG_PORT_MIN} and udp.SrcPort <= {NG_PORT_MAX})"
        f" or (udp.DstPort >= {NG_PORT_MIN} and udp.DstPort <= {NG_PORT_MAX})"
    )
    return f"udp and ({ip_filter}) and ({port_range})"


# ---------------------------------------------------------------------------
# Helpers réseau
# ---------------------------------------------------------------------------

def _resolve_target(host: str, log_path: Path) -> str | None:
    try:
        ip = socket.gethostbyname(host)
        _log(log_path, f"resolved {host} -> {ip}")
        return ip
    except socket.gaierror as exc:
        _log(log_path, f"dns_error host={host} err={exc}")
        return None


def _make_tap_socket(proxy_host: str, tap_port: int) -> socket.socket:
    """Socket UDP local utilisé pour envoyer les copies de paquets au proxy."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect((proxy_host, tap_port))
    return sock


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _run_observe(settings: Settings, target_ip: str) -> int:
    """
    Observe : capture et log le trafic NG sans le modifier.
    Particulièrement utile pour voir toutes les IPs/ports utilisés lors du
    handoff home → DELTA.
    """
    state = State()
    wf = _build_filter(target_ip)
    _log(settings.log_path, f"observe_filter={wf!r}")

    with pydivert.WinDivert(wf) as w:  # pragma: no cover
        for packet in w:
            state.packet_count += 1
            is_ng = (packet.src_addr == target_ip or packet.dst_addr == target_ip)

            if is_ng:
                state.ng_packet_count += 1
                direction = "S→C" if packet.is_inbound else "C→S"
                src = f"{packet.src_addr}:{packet.src_port}"
                dst = f"{packet.dst_addr}:{packet.dst_port}"
                size = len(packet.udp.payload) if packet.udp else 0

                # Log chaque nouveau couple IP:port découvert
                sig = f"{packet.src_addr}:{packet.src_port}"
                if sig not in state.discovered_ips:
                    state.discovered_ips.add(sig)
                    _log(settings.log_path, f"new_endpoint {direction} {src} -> {dst}")

                if state.ng_packet_count % 100 == 0:
                    _log(
                        settings.log_path,
                        f"stats total={state.packet_count} ng={state.ng_packet_count} "
                        f"endpoints={len(state.discovered_ips)}",
                    )

            # Toujours renvoyer le paquet — le jeu ne doit pas être perturbé
            w.send(packet)

    return 0


def _run_tap(settings: Settings, target_ip: str) -> int:
    """
    Tap : copie chaque payload UDP NG vers le proxy local (TAP_PORT) via un
    socket UDP distinct. Le paquet original est renvoyé intact → jeu OK.

    Format du message envoyé au proxy :
      [4B big-endian : ip src as int][2B : src_port][payload]
    Cela permet au proxy de savoir d'où vient le paquet.
    """
    state = State()
    wf = _build_filter(target_ip)
    _log(settings.log_path, f"tap_filter={wf!r} tap_dst={settings.proxy_host}:{settings.tap_port}")

    try:
        tap_sock = _make_tap_socket(settings.proxy_host, settings.tap_port)
    except OSError as exc:
        _log(settings.log_path, f"tap_socket_error err={exc}")
        return 4

    errors = 0
    with pydivert.WinDivert(wf) as w:  # pragma: no cover
        for packet in w:
            state.packet_count += 1
            try:
                if packet.udp and packet.udp.payload:
                    # Préfixe : IP source (4B) + port source (2B)
                    src_ip_int = struct.unpack("!I", socket.inet_aton(packet.src_addr))[0]
                    header = struct.pack("!IH", src_ip_int, packet.src_port)
                    tap_sock.send(header + bytes(packet.udp.payload))
                    state.ng_packet_count += 1

                    # Log les nouveaux endpoints (découverte des sous-serveurs DELTA)
                    sig = f"{packet.src_addr}:{packet.src_port}"
                    if sig not in state.discovered_ips:
                        state.discovered_ips.add(sig)
                        direction = "S→C" if packet.is_inbound else "C→S"
                        _log(
                            settings.log_path,
                            f"new_endpoint {direction} {packet.src_addr}:{packet.src_port}"
                            f" -> {packet.dst_addr}:{packet.dst_port}",
                        )
            except Exception as exc:  # pragma: no cover
                errors += 1
                if errors <= 10:
                    _log(settings.log_path, f"tap_error err={exc}")

            # CRITIQUE : toujours renvoyer le paquet original
            w.send(packet)

    tap_sock.close()
    return 0


def _run_redirect(settings: Settings, target_ip: str) -> int:
    """
    Redirect : réécrit la destination Minecraft→NG vers le proxy local.
    ⚠️  Modifie les paquets — le proxy doit être opérationnel avant de lancer ce mode.
    Les paquets NG→Minecraft ne sont pas modifiés (le proxy répond directement).
    """
    state = State()
    wf = _build_filter(target_ip)
    _log(settings.log_path, f"redirect_filter={wf!r} proxy={settings.proxy_host}:{settings.proxy_port}")

    proxy_ip_bytes = socket.inet_aton(settings.proxy_host)

    with pydivert.WinDivert(wf) as w:  # pragma: no cover
        for packet in w:
            state.packet_count += 1
            is_outbound = packet.is_outbound

            if is_outbound and packet.udp:
                # Minecraft → NG : réécrire vers proxy
                orig_dst = f"{packet.dst_addr}:{packet.dst_port}"
                packet.dst_addr = settings.proxy_host
                packet.udp.dst_port = settings.proxy_port

                sig = orig_dst
                if sig not in state.discovered_ips:
                    state.discovered_ips.add(sig)
                    _log(settings.log_path, f"redirect_new_dst orig={orig_dst} -> proxy={settings.proxy_host}:{settings.proxy_port}")

            # Recalcul des checksums et envoi
            w.send(packet, recalculate_checksum=True)

    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(settings: Settings) -> int:
    if pydivert is None:
        print("[windivert] ERREUR : pydivert n'est pas installé.", file=sys.stderr)
        print("  → pip install pydivert", file=sys.stderr)
        _log(settings.log_path, "pydivert_missing")
        return 2

    target_ip = _resolve_target(settings.target_host, settings.log_path)
    if target_ip is None:
        return 1

    _log(
        settings.log_path,
        f"start mode={settings.mode} target={target_ip}:{settings.target_port} "
        f"proxy={settings.proxy_host}:{settings.proxy_port} tap_port={settings.tap_port}",
    )

    if settings.mode == "observe":
        return _run_observe(settings, target_ip)
    elif settings.mode == "tap":
        return _run_tap(settings, target_ip)
    elif settings.mode == "redirect":
        return _run_redirect(settings, target_ip)

    _log(settings.log_path, f"unknown_mode mode={settings.mode}")
    return 1


def _make_settings(args: argparse.Namespace) -> Settings:
    state_dir = Path(os.getenv("APPDATA", ".")) / "WarControl"
    return Settings(
        target_host=args.target_host,
        target_port=args.target_port,
        proxy_host=args.proxy_host,
        proxy_port=args.proxy_port,
        tap_port=args.tap_port,
        mode=args.mode,
        log_path=state_dir / "windivert.log",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="WarControl WinDivert interceptor")
    parser.add_argument("--target-host", default="bedrock.nationsglory.fr")
    parser.add_argument("--target-port", type=int, default=19132)
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=19132)
    parser.add_argument("--tap-port", type=int, default=TAP_PORT)
    parser.add_argument(
        "--mode",
        choices=["observe", "tap", "redirect"],
        default="observe",
        help=(
            "observe: log uniquement (sans modifier les paquets) | "
            "tap: copie les payloads vers le proxy (recommandé) | "
            "redirect: réécrit la destination (avancé)"
        ),
    )
    args = parser.parse_args()
    return run(_make_settings(args))


if __name__ == "__main__":
    raise SystemExit(main())
