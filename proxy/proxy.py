from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric.ec import (
        ECDH,
        SECP384R1,
        EllipticCurvePublicKey,
        generate_private_key,
    )
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_der_public_key,
    )
    _CRYPTO_AVAILABLE = True
except ImportError:
    _CRYPTO_AVAILABLE = False

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TARGET_HOST = "bedrock.nationsglory.fr"
DEFAULT_TARGET_PORT = 19132
DEFAULT_LISTEN_HOST = "127.0.0.1"
DEFAULT_LISTEN_PORT = 19132
# Port sur lequel le proxy écoute les copies envoyées par WinDivert (mode tap)
TAP_LISTEN_PORT = 19133

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

# RakNet reliability → number of extra header bytes before payload
_RELIABILITY_EXTRA = {0: 0, 1: 3, 2: 3, 3: 7, 4: 7, 5: 3, 6: 7, 7: 7}


# ---------------------------------------------------------------------------
# Stdlib helpers
# ---------------------------------------------------------------------------

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
    # Correction mojibake : chaîne UTF-8 mal décodée en latin-1 (ex: Ã© → é)
    # On tente un ré-encodage latin-1 → décodage UTF-8
    try:
        fixed = raw.encode("latin-1").decode("utf-8")
        if fixed != raw:
            raw = fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass

    value = raw.replace("\x00", " ").replace("\n", " ").replace("\r", " ").strip()
    value = re.sub(r"\s+", " ", value)
    replacements = {
        "é": "e", "è": "e", "ê": "e", "à": "a", "ù": "u",
        "ç": "c", "ô": "o", "î": "i", "ï": "i", "ü": "u", "ö": "o", "â": "a",
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


# ---------------------------------------------------------------------------
# Reverse-engineered transport layer
# IMPORTANT:
# - Keep this section stable unless you are actively debugging protocol details.
# - Higher-level parsing/logging/tests should be preferred over editing this block.
# ---------------------------------------------------------------------------

def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    for i in range(5):
        b = data[pos + i]
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            return result, i + 1
    raise ValueError("varint too long")


def _write_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            b |= 0x80
        out.append(b)
        if not value:
            break
    return bytes(out)


def raknet_extract_payloads(
    data: bytes,
    frag_buf: dict[int, dict[int, bytes]],
) -> list[bytes]:
    if not data or not (0x80 <= data[0] <= 0x8F):
        return []
    results: list[bytes] = []
    pos = 4  # skip ID (1B) + sequence number (3B LE)
    try:
        while pos < len(data):
            flags = data[pos]; pos += 1
            reliability = (flags >> 5) & 0x07
            has_split = bool(flags & 0x10)
            length_bits = struct.unpack_from(">H", data, pos)[0]; pos += 2
            length_bytes = (length_bits + 7) // 8
            pos += _RELIABILITY_EXTRA.get(reliability, 0)
            split_count = split_id = split_index = None
            if has_split:
                split_count = struct.unpack_from(">I", data, pos)[0]; pos += 4
                split_id    = struct.unpack_from(">H", data, pos)[0]; pos += 2
                split_index = struct.unpack_from(">I", data, pos)[0]; pos += 4
            payload = data[pos: pos + length_bytes]; pos += length_bytes
            if has_split and split_id is not None and split_count is not None and split_index is not None:
                bucket = frag_buf.setdefault(split_id, {})
                bucket[split_index] = payload
                if len(bucket) == split_count:
                    full = b"".join(bucket[i] for i in range(split_count))
                    del frag_buf[split_id]
                    results.append(full)
            else:
                results.append(payload)
    except (struct.error, IndexError):
        pass
    return results


# ---------------------------------------------------------------------------
# Reverse-engineered MCPE batch decoder
# IMPORTANT: treat as protocol-critical code.
# ---------------------------------------------------------------------------

def mcpe_decode_batch(payload: bytes) -> list[tuple[int, bytes]]:
    if not payload or payload[0] != 0xFE:
        return []
    try:
        raw = zlib.decompress(payload[1:])
    except zlib.error:
        return []
    packets: list[tuple[int, bytes]] = []
    pos = 0
    try:
        while pos < len(raw):
            pkt_len, n = _read_varint(raw, pos); pos += n
            pkt = raw[pos: pos + pkt_len]; pos += pkt_len
            if pkt:
                packets.append((pkt[0], pkt))
    except Exception:
        pass
    return packets


def _rebuild_mcpe_batch(pkt_body: bytes) -> bytes:
    inner = _write_varint(len(pkt_body)) + pkt_body
    return b"\xfe" + zlib.compress(inner)


# ---------------------------------------------------------------------------
# MCPE packet parsers
# Safe area for event extraction tweaks, but avoid changing binary offsets casually.
# ---------------------------------------------------------------------------

def _parse_mcpe_text(pkt: bytes) -> str | None:
    try:
        pos = 1  # skip ID
        text_type = pkt[pos]; pos += 1
        pos += 1  # needs_translation bool
        if text_type in (1, 7):  # CHAT or WHISPER has source name first
            src_len, n = _read_varint(pkt, pos); pos += n
            pos += src_len
        msg_len, n = _read_varint(pkt, pos); pos += n
        return pkt[pos: pos + msg_len].decode("utf-8", errors="replace")
    except Exception:
        return None


def _parse_mcpe_playerlist(pkt: bytes) -> list[dict]:
    results = []
    try:
        pos = 1  # skip ID
        action = pkt[pos]; pos += 1
        count, n = _read_varint(pkt, pos); pos += n
        for _ in range(count):
            try:
                uuid_bytes = pkt[pos: pos + 16]; pos += 16
                uuid_hex = uuid_bytes.hex()
                if action == 1:  # REMOVE — only UUID
                    results.append({"action": "remove", "uuid": uuid_hex, "username": None})
                    continue
                # ADD: entity_unique_id (int64 LE zigzag), entity_runtime_id (varint),
                #      platform_chat_id (string), username (string)
                pos += 8  # entity unique id
                _, n = _read_varint(pkt, pos); pos += n  # entity runtime id
                plat_len, n = _read_varint(pkt, pos); pos += n
                pos += plat_len  # platform chat id
                name_len, n = _read_varint(pkt, pos); pos += n
                username = pkt[pos: pos + name_len].decode("utf-8", errors="replace")
                results.append({"action": "add", "uuid": uuid_hex, "username": username})
                # Skip the rest of the entry (skin data etc.) — stop here per iteration
                # We'll break after first successful add to avoid skin parsing hazards
                break
            except Exception:
                break
    except Exception:
        pass
    return results


# ---------------------------------------------------------------------------
# Reverse-engineered crypto helpers (guarded by _CRYPTO_AVAILABLE)
# IMPORTANT: this block is part of the manual reverse-engineering path.
# ---------------------------------------------------------------------------

def _b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def _jwt_header(token: str) -> dict:
    return json.loads(_b64url_decode(token.split(".")[0]))


def _jwt_payload(token: str) -> dict:
    return json.loads(_b64url_decode(token.split(".")[1]))


def _ec_pub_key_to_der_b64(priv_key) -> str:
    pub = priv_key.public_key()
    der = pub.public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


def _sign_jwt(priv_key, header: dict, payload: dict) -> str:
    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    h = b64url(json.dumps(header, separators=(",", ":")).encode())
    p = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h}.{p}".encode()
    sig_der = priv_key.sign(signing_input, ECDSA(hashes.SHA384()))
    r, s = decode_dss_signature(sig_der)
    sig_bytes = r.to_bytes(48, "big") + s.to_bytes(48, "big")
    return f"{h}.{p}.{b64url(sig_bytes)}"


# ---------------------------------------------------------------------------
# Encryption session (AES-256-CFB8 stream)
# IMPORTANT: do not refactor blindly around cipher state.
# ---------------------------------------------------------------------------

class EncryptionSession:
    def __init__(self, key: bytes, iv: bytes) -> None:
        cipher = Cipher(algorithms.AES(key), modes.CFB8(iv), backend=default_backend())
        self._decryptor = cipher.decryptor()
        self.active = True

    def decrypt(self, ciphertext: bytes) -> bytes:
        return self._decryptor.update(ciphertext)


# ---------------------------------------------------------------------------
# MITM key exchange state machine
# IMPORTANT: this is the most fragile part of the proxy implementation.
# ---------------------------------------------------------------------------

class MITMKeyExchange:
    STATE_WAITING_LOGIN         = "waiting_login"
    STATE_WAITING_S2C_HANDSHAKE = "waiting_s2c_hs"
    STATE_WAITING_C2S_HANDSHAKE = "waiting_c2s_hs"
    STATE_ENCRYPTED             = "encrypted"
    STATE_FAILED                = "failed"

    def __init__(self) -> None:
        self._proxy_server_key = generate_private_key(SECP384R1(), default_backend())
        self._proxy_client_key = generate_private_key(SECP384R1(), default_backend())
        self.state = self.STATE_WAITING_LOGIN
        self._server_pub_key: EllipticCurvePublicKey | None = None
        self._client_pub_key: EllipticCurvePublicKey | None = None
        self._server_salt: bytes | None = None
        self._proxy_salt: bytes = os.urandom(16)
        self.server_session: EncryptionSession | None = None
        self.client_session: EncryptionSession | None = None
        self._packets_since_login = 0

    def intercept_login(self, pkt_body: bytes) -> bytes:
        pos = 3  # skip ID (1B) + protocol version (2B)
        chain_len, n = _read_varint(pkt_body, pos); pos += n
        chain_raw = pkt_body[pos: pos + chain_len].decode("utf-8"); pos += chain_len
        skin_len, n = _read_varint(pkt_body, pos); pos += n
        skin_raw = pkt_body[pos: pos + skin_len]

        chain_obj = json.loads(chain_raw)
        jwts = chain_obj["chain"]
        last_jwt = jwts[-1]
        last_payload = _jwt_payload(last_jwt)
        last_header = _jwt_header(last_jwt)

        # Extract real client public key
        raw_pub = base64.b64decode(last_payload["identityPublicKey"])
        self._client_pub_key = load_der_public_key(raw_pub, default_backend())

        # Swap in proxy client-side public key
        proxy_pub_b64 = _ec_pub_key_to_der_b64(self._proxy_client_key)
        last_payload["identityPublicKey"] = proxy_pub_b64
        last_header["x5u"] = proxy_pub_b64
        new_last_jwt = _sign_jwt(self._proxy_client_key, last_header, last_payload)
        chain_obj["chain"][-1] = new_last_jwt
        new_chain_raw = json.dumps(chain_obj, separators=(",", ":")).encode("utf-8")

        out = bytearray()
        out += pkt_body[:3]
        out += _write_varint(len(new_chain_raw))
        out += new_chain_raw
        out += _write_varint(len(skin_raw))
        out += skin_raw
        self.state = self.STATE_WAITING_S2C_HANDSHAKE
        print("[proxy] Login intercepted — client pub key swapped", flush=True)
        return bytes(out)

    def intercept_s2c_handshake(self, pkt_body: bytes) -> bytes:
        pos = 1  # skip ID
        jwt_len, n = _read_varint(pkt_body, pos); pos += n
        jwt_str = pkt_body[pos: pos + jwt_len].decode("utf-8")

        header  = _jwt_header(jwt_str)
        payload = _jwt_payload(jwt_str)

        # Server public key + salt
        server_pub_der = base64.b64decode(header["x5u"])
        self._server_pub_key = load_der_public_key(server_pub_der, default_backend())
        raw_salt = _b64url_decode(payload["salt"]) if "salt" in payload else base64.b64decode(payload.get("salt", ""))

        # Derive proxy ↔ server session key
        shared_x = self._proxy_server_key.exchange(ECDH(), self._server_pub_key)
        km = hashlib.sha256(shared_x + raw_salt).digest()
        self.server_session = EncryptionSession(km[:32], km[:16])

        # Build fake S2C handshake for client
        proxy_pub_b64 = _ec_pub_key_to_der_b64(self._proxy_client_key)
        fake_salt_b64 = base64.urlsafe_b64encode(self._proxy_salt).rstrip(b"=").decode()
        fake_header = {"alg": "ES384", "x5u": proxy_pub_b64}
        fake_payload = {"salt": fake_salt_b64}
        fake_jwt = _sign_jwt(self._proxy_client_key, fake_header, fake_payload)
        fake_jwt_bytes = fake_jwt.encode("utf-8")

        # Derive proxy ↔ client session key
        assert self._client_pub_key is not None
        shared_x_c = self._proxy_client_key.exchange(ECDH(), self._client_pub_key)
        km_c = hashlib.sha256(shared_x_c + self._proxy_salt).digest()
        self.client_session = EncryptionSession(km_c[:32], km_c[:16])

        self.state = self.STATE_WAITING_C2S_HANDSHAKE
        print("[proxy] S2C handshake intercepted — session keys derived", flush=True)

        out = bytearray()
        out.append(0x03)
        out += _write_varint(len(fake_jwt_bytes))
        out += fake_jwt_bytes
        return bytes(out)

    def tick(self) -> None:
        """Call once per received packet to detect handshake timeout."""
        if self.state in (self.STATE_WAITING_S2C_HANDSHAKE, self.STATE_WAITING_C2S_HANDSHAKE):
            self._packets_since_login += 1
            if self._packets_since_login > 200:
                print("[proxy] handshake timeout — falling back to text scan", flush=True)
                self.state = self.STATE_FAILED


# ---------------------------------------------------------------------------
# BedrockProxy
# ---------------------------------------------------------------------------

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
        self._mitm: MITMKeyExchange | None = MITMKeyExchange() if _CRYPTO_AVAILABLE else None
        self._frag_buf: dict[str, dict[int, dict[int, bytes]]] = {"client": {}, "server": {}}
        self._uuid_to_username: dict[str, str] = {}
        if _CRYPTO_AVAILABLE:
            print("[proxy] MCPE decryption enabled (cryptography available)", flush=True)
        else:
            print("[proxy] WARNING: cryptography not installed — falling back to text scan", flush=True)

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

            if self._mitm is not None:
                self._mitm.tick()

            if addr == self.target_addr:
                self._server_packets += 1
                self._log_packet("server", payload, addr)
                if self.client_addr:
                    forward = self._try_rewrite_packet(payload, "server")
                    self.sock.sendto(forward if forward is not None else payload, self.client_addr)
                self._dispatch(payload, "server")
            else:
                self.client_addr = addr
                self._client_packets += 1
                self._log_packet("client", payload, addr)
                forward = self._try_rewrite_packet(payload, "client")
                self.sock.sendto(forward if forward is not None else payload, self.target_addr)
                self._dispatch(payload, "client")

    def serve_tap(self, tap_host: str = "127.0.0.1", tap_port: int = TAP_LISTEN_PORT) -> None:
        """
        Ecoute les copies de paquets envoyees par WinDivert mode tap.
        Format : [4B ip_src as uint32 big-endian][2B port_src][payload UDP brut]
        Lance dans un thread separe en parallele de serve_forever.
        """
        import struct as _struct
        tap_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tap_sock.bind((tap_host, tap_port))
        tap_sock.settimeout(1.0)
        print(f"[proxy] tap listener on {tap_host}:{tap_port}", flush=True)
        while self._running:
            try:
                data, _ = tap_sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(data) < 6:
                continue
            src_ip_int, src_port = _struct.unpack_from("!IH", data, 0)
            payload = data[6:]
            src_ip = socket.inet_ntoa(_struct.pack("!I", src_ip_int))
            direction = "server" if src_ip != "127.0.0.1" else "client"
            self._dispatch(payload, direction)
        tap_sock.close()


    def _dispatch(self, payload: bytes, direction: str) -> None:
        mitm = self._mitm
        if mitm is not None and mitm.state == MITMKeyExchange.STATE_ENCRYPTED:
            self._process_encrypted_direction(payload, direction)
        else:
            self._ingest_payload(payload, direction=direction)

    def close(self) -> None:
        self._running = False
        try:
            self.sock.close()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # MITM rewriting
    # IMPORTANT: keep packet rewrite logic isolated from UI/logging changes.
    # ------------------------------------------------------------------

    def _try_rewrite_packet(self, payload: bytes, direction: str) -> bytes | None:
        mitm = self._mitm
        if mitm is None or mitm.state == MITMKeyExchange.STATE_FAILED:
            return None
        if mitm.state == MITMKeyExchange.STATE_ENCRYPTED:
            return None

        frag_peek = self._frag_buf.setdefault("_rewrite", {})
        encap_list = raknet_extract_payloads(payload, frag_peek)
        for encap in encap_list:
            packets = mcpe_decode_batch(encap)
            for pkt_id, pkt_body in packets:
                if (
                    pkt_id == 0x01
                    and direction == "client"
                    and mitm.state == MITMKeyExchange.STATE_WAITING_LOGIN
                ):
                    try:
                        new_pkt = mitm.intercept_login(pkt_body)
                        rebuilt = self._rebuild_raknet(payload, encap, pkt_body, new_pkt)
                        return rebuilt
                    except Exception as exc:
                        print(f"[proxy] Login intercept error: {exc}", file=sys.stderr, flush=True)
                        mitm.state = MITMKeyExchange.STATE_FAILED

                elif (
                    pkt_id == 0x03
                    and direction == "server"
                    and mitm.state == MITMKeyExchange.STATE_WAITING_S2C_HANDSHAKE
                ):
                    try:
                        new_pkt = mitm.intercept_s2c_handshake(pkt_body)
                        rebuilt = self._rebuild_raknet(payload, encap, pkt_body, new_pkt)
                        return rebuilt
                    except Exception as exc:
                        print(f"[proxy] S2C handshake error: {exc}", file=sys.stderr, flush=True)
                        mitm.state = MITMKeyExchange.STATE_FAILED

                elif (
                    pkt_id == 0x04
                    and direction == "client"
                    and mitm.state == MITMKeyExchange.STATE_WAITING_C2S_HANDSHAKE
                ):
                    mitm.state = MITMKeyExchange.STATE_ENCRYPTED
                    print("[proxy] encryption active — MITM key exchange complete", flush=True)
                    self._emit_system_event(
                        "proxy_encryption",
                        "MCPE encryption handshake intercepted — decryption active",
                    )
        return None

    def _rebuild_raknet(
        self,
        dgram: bytes,
        old_encap: bytes,
        old_pkt: bytes,
        new_pkt: bytes,
    ) -> bytes | None:
        try:
            new_batch = _rebuild_mcpe_batch(new_pkt)
            offset = dgram.find(old_encap, 4)
            if offset == -1:
                return None
            old_len_bytes = struct.pack(">H", len(old_encap) * 8)
            new_len_bytes = struct.pack(">H", len(new_batch) * 8)
            len_field_offset = dgram.rfind(old_len_bytes, 4, offset)
            if len_field_offset == -1:
                return None
            result = bytearray(dgram)
            result[len_field_offset: len_field_offset + 2] = new_len_bytes
            result[offset: offset + len(old_encap)] = new_batch
            return bytes(result)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Encrypted packet processing
    # IMPORTANT: safe to extend logging around this block, not inside crypto flow.
    # ------------------------------------------------------------------

    def _process_encrypted_direction(self, payload: bytes, direction: str) -> None:
        mitm = self._mitm
        if mitm is None:
            return
        session = mitm.client_session if direction == "client" else mitm.server_session
        if session is None or not session.active:
            return
        encap_list = raknet_extract_payloads(payload, self._frag_buf[direction])
        for encap in encap_list:
            try:
                plain = session.decrypt(encap)
            except Exception:
                session.active = False
                return
            packets = mcpe_decode_batch(plain)
            for pkt_id, pkt_body in packets:
                try:
                    self._handle_decrypted_mcpe(pkt_id, pkt_body, direction)
                except Exception:
                    pass

    def _handle_decrypted_mcpe(self, pkt_id: int, pkt_body: bytes, direction: str) -> None:
        if pkt_id == 0x09:
            msg = _parse_mcpe_text(pkt_body)
            if not msg:
                return
            msg = _normalize_text(msg)
            key = f"dec:{direction}:{msg}"
            now = time.time()
            if now - self._seen_messages.get(key, 0) < 8:
                return
            self._seen_messages[key] = now
            event = _classify_text(msg, self.server, self.source)
            if event:
                print(f"[proxy] [decrypted] {event['type']}: {event['message']}", flush=True)
                _flush_events(self.api_url, self.api_key, self.spool_path, [event])

        elif pkt_id == 0x25:
            entries = _parse_mcpe_playerlist(pkt_body)
            events: list[dict] = []
            for entry in entries:
                if entry["action"] == "add" and entry["username"]:
                    self._uuid_to_username[entry["uuid"]] = entry["username"]
                    event = _classify_text(
                        f"{entry['username']} a rejoint la partie",
                        self.server,
                        self.source,
                    )
                    if event:
                        events.append(event)
                elif entry["action"] == "remove":
                    username = self._uuid_to_username.get(entry["uuid"])
                    if username:
                        event = _classify_text(
                            f"{username} a quitte la partie",
                            self.server,
                            self.source,
                        )
                        if event:
                            events.append(event)
            if events:
                for ev in events:
                    print(f"[proxy] [decrypted] {ev['type']}: {ev['message']}", flush=True)
                _flush_events(self.api_url, self.api_key, self.spool_path, events)

    # ------------------------------------------------------------------
    # Fallback text scan
    # Preferred place for non-protocol improvements (classification/logging/tests).
    # ------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
    parser.add_argument(
        "--tap-port",
        type=int,
        default=int(os.getenv("WARCONTROL_TAP_PORT", str(TAP_LISTEN_PORT))),
        help="Port local sur lequel ecouter les copies WinDivert (mode tap). 0 = desactive.",
    )
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

    # Lancer le recepteur tap dans un thread dedie si active
    if args.tap_port:
        tap_thread = threading.Thread(
            target=proxy.serve_tap,
            kwargs={"tap_host": "127.0.0.1", "tap_port": args.tap_port},
            daemon=True,
            name="proxy-tap",
        )
        tap_thread.start()

    def _handle_exit(*_args: object) -> None:
        proxy.close()

    try:
        proxy.serve_forever()
    except KeyboardInterrupt:
        _handle_exit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
