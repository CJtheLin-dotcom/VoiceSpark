#!/usr/bin/env python3
"""
Samsung Smart TV (Tizen) Web Remote Server
Zero-dependency implementation using Python Standard Library.
Supports:
- Local network auto-discovery of Samsung TVs (port 8001 REST API)
- Secure WebSocket (wss:// port 8002) & standard WebSocket (ws:// port 8001)
- Automatic pairing token persistence (saved to config.json)
- Persistent connection for millisecond key response
- Text input forwarding & Wake-on-LAN (WoL) power-on
"""

import base64
import concurrent.futures
import hashlib
import http.server
import json
import os
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
APP_NAME = "AntigravityRemote"
APP_NAME_B64 = base64.b64encode(APP_NAME.encode("utf-8")).decode("ascii")


def get_local_ip() -> str:
    """Detect the primary LAN IP of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tv_ip": "", "tv_mac": "", "tv_name": "", "tokens": {}}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def send_wol(mac_address: str) -> bool:
    """Send a Wake-on-LAN magic packet to wake up a standby Samsung TV."""
    if not mac_address:
        return False
    clean_mac = mac_address.replace(":", "").replace("-", "").strip()
    if len(clean_mac) != 12:
        return False
    try:
        mac_bytes = bytes.fromhex(clean_mac)
        magic_packet = b"\xff" * 6 + mac_bytes * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic_packet, ("255.255.255.255", 9))
            local_ip = get_local_ip()
            if "." in local_ip:
                subnet_bcast = ".".join(local_ip.split(".")[:3]) + ".255"
                sock.sendto(magic_packet, (subnet_bcast, 9))
        return True
    except Exception:
        return False


def probe_samsung_tv(ip: str, timeout: float = 0.6) -> dict | None:
    """Check if an IP hosts a Samsung TV on port 8001."""
    url = f"http://{ip}:8001/api/v2/"
    req = urllib.request.Request(url, headers={"User-Agent": "SamsungRemote/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            device = data.get("device", {})
            return {
                "ip": ip,
                "name": device.get("name") or data.get("name") or f"Samsung TV ({ip})",
                "model": device.get("modelName", "Unknown"),
                "mac": device.get("wifiMac", ""),
                "token_auth": device.get("TokenAuthSupport") == "true",
            }
    except Exception:
        return None


def discover_samsung_tvs() -> list[dict]:
    """Scan the local /24 subnet for Samsung Smart TVs."""
    local_ip = get_local_ip()
    if local_ip == "127.0.0.1" or "." not in local_ip:
        return []
    prefix = ".".join(local_ip.split(".")[:3])
    ips = [f"{prefix}.{i}" for i in range(1, 255) if f"{prefix}.{i}" != local_ip]
    found = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as executor:
        futures = {executor.submit(probe_samsung_tv, ip): ip for ip in ips}
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            if res:
                found.append(res)
    return found


class MinimalWebSocket:
    """Lightweight RFC 6455 WebSocket client built on Python's socket/ssl."""

    def __init__(self, host: str, port: int, path: str, use_ssl: bool = True, timeout: float = 15.0):
        self.host = host
        self.port = port
        self.path = path
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.sock: socket.socket | ssl.SSLSocket | None = None
        self.lock = threading.Lock()

    def connect(self) -> None:
        raw_sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        if self.use_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self.sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
        else:
            self.sock = raw_sock

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("WebSocket handshake closed prematurely")
            resp += chunk

        header_line = resp.split(b"\r\n", 1)[0].decode("ascii", errors="ignore")
        if "101" not in header_line:
            raise ConnectionError(f"WebSocket handshake failed: {header_line}")

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WebSocket closed while reading frame")
            buf += chunk
        return buf

    def recv_json(self) -> dict:
        while True:
            b1, b2 = self._recv_exact(2)
            opcode = b1 & 0x0F
            masked = (b2 & 0x80) != 0
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._recv_exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._recv_exact(8))[0]
            mask_key = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(length)
            if masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:  # Close
                raise ConnectionError("WebSocket closed by TV")
            if opcode == 0x9:  # Ping -> send Pong
                self._send_frame(payload, opcode=0xA)
                continue
            if opcode in (0x1, 0x2):  # Text or Binary
                return json.loads(payload.decode("utf-8", errors="ignore"))

    def _send_frame(self, payload: bytes, opcode: int = 0x1) -> None:
        with self.lock:
            if not self.sock:
                raise ConnectionError("Not connected")
            mask_key = os.urandom(4)
            header = bytearray([0x80 | opcode])
            length = len(payload)
            if length < 126:
                header.append(0x80 | length)
            elif length < 65536:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", length))
            header.extend(mask_key)
            masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            self.sock.sendall(bytes(header) + masked_payload)

    def send_json(self, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self._send_frame(data, opcode=0x1)

    def close(self) -> None:
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        self.sock = None


class SamsungTVController:
    """Manages persistent WebSocket connection and token pairing with Samsung TV."""

    def __init__(self):
        self.ws: MinimalWebSocket | None = None
        self.connected_ip: str = ""
        self.status: str = "disconnected"  # disconnected | pairing | connected | error
        self.last_error: str = ""
        self.lock = threading.Lock()

    def ensure_connected(self, tv_ip: str) -> tuple[bool, str]:
        with self.lock:
            if self.ws and self.connected_ip == tv_ip and self.status == "connected":
                return True, "Connected"

            if self.ws:
                self.ws.close()
                self.ws = None

            cfg = load_config()
            token = cfg.get("tokens", {}).get(tv_ip, "")

            # Probe device info to update MAC / name if possible
            info = probe_samsung_tv(tv_ip, timeout=1.0)
            if info:
                cfg["tv_ip"] = tv_ip
                cfg["tv_name"] = info.get("name") or cfg.get("tv_name", "")
                if info.get("mac") and info["mac"] != "none":
                    cfg["tv_mac"] = info["mac"]
                save_config(cfg)

            # Try secure port 8002 first (standard for 2016+ Tizen TVs), fallback to 8001
            for port, use_ssl in [(8002, True), (8001, False)]:
                path = f"/api/v2/channels/samsung.remote.control?name={APP_NAME_B64}"
                if token and use_ssl:
                    path += f"&token={token}"
                try:
                    self.status = "pairing"
                    ws = MinimalWebSocket(tv_ip, port, path, use_ssl=use_ssl, timeout=25.0)
                    ws.connect()
                    msg = ws.recv_json()
                    event = msg.get("event", "")
                    if event == "ms.channel.connect":
                        new_token = msg.get("data", {}).get("token")
                        if new_token:
                            cfg = load_config()
                            cfg.setdefault("tokens", {})[tv_ip] = new_token
                            cfg["tv_ip"] = tv_ip
                            save_config(cfg)
                        self.ws = ws
                        self.connected_ip = tv_ip
                        self.status = "connected"
                        self.last_error = ""
                        # Start background reader to handle pings/disconnects
                        threading.Thread(target=self._reader_loop, args=(ws,), daemon=True).start()
                        return True, "Connected"
                    elif event in ("ms.channel.timeOut", "ms.channel.unauthorized"):
                        ws.close()
                        self.status = "error"
                        self.last_error = "电视端未点击允许或已拒绝，请重试并在电视右上角点击【允许】"
                        return False, self.last_error
                except Exception as e:
                    self.last_error = str(e)
                    continue

            self.status = "error"
            return False, f"无法连接电视 ({tv_ip})，请确认电视已开机且在同一 Wi-Fi 下。({self.last_error})"

    def _reader_loop(self, ws: MinimalWebSocket) -> None:
        try:
            while self.ws is ws:
                msg = ws.recv_json()
                if msg.get("event") == "ms.channel.connect":
                    new_token = msg.get("data", {}).get("token")
                    if new_token and self.connected_ip:
                        cfg = load_config()
                        cfg.setdefault("tokens", {})[self.connected_ip] = new_token
                        save_config(cfg)
        except Exception:
            if self.ws is ws:
                self.ws = None
                self.status = "disconnected"

    def send_key(self, key: str, cmd: str = "Click") -> tuple[bool, str]:
        cfg = load_config()
        tv_ip = cfg.get("tv_ip", "").strip()
        if not tv_ip:
            return False, "请先选择或输入三星电视 IP 地址"

        # If pressing power and TV is unreachable, also send Wake-on-LAN packet
        if key in ("KEY_POWER", "KEY_POWEROFF") and cfg.get("tv_mac"):
            send_wol(cfg["tv_mac"])

        ok, msg = self.ensure_connected(tv_ip)
        if not ok:
            if key in ("KEY_POWER", "KEY_POWEROFF") and cfg.get("tv_mac"):
                return True, "已发送开机唤醒信号 (Wake-on-LAN)"
            return False, msg

        payload = {
            "method": "ms.remote.control",
            "params": {
                "Cmd": cmd,
                "DataOfCmd": key,
                "Option": "false",
                "TypeOfRemote": "SendRemoteKey",
            },
        }
        try:
            self.ws.send_json(payload)
            return True, f"Sent {key}"
        except Exception:
            # Reconnect once if socket was stale
            self.ws = None
            self.status = "disconnected"
            ok, msg = self.ensure_connected(tv_ip)
            if not ok:
                return False, msg
            self.ws.send_json(payload)
            return True, f"Sent {key}"

    def send_text(self, text: str) -> tuple[bool, str]:
        cfg = load_config()
        tv_ip = cfg.get("tv_ip", "").strip()
        if not tv_ip:
            return False, "请先选择或输入三星电视 IP 地址"
        ok, msg = self.ensure_connected(tv_ip)
        if not ok:
            return False, msg

        b64_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        payload = {
            "method": "ms.remote.control",
            "params": {
                "Cmd": b64_text,
                "DataOfCmd": "base64",
                "TypeOfRemote": "SendInputString",
            },
        }
        try:
            self.ws.send_json(payload)
            return True, "已发送文字到电视"
        except Exception as e:
            self.ws = None
            self.status = "disconnected"
            return False, str(e)


controller = SamsungTVController()


class RemoteHTTPHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Keep console clean

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            html_file = BASE_DIR / "index.html"
            body = html_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/manifest.json":
            body = (BASE_DIR / "manifest.json").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/sw.js":
            body = (BASE_DIR / "sw.js").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/api/status":
            cfg = load_config()
            self._send_json({
                "ok": True,
                "tv_ip": cfg.get("tv_ip", ""),
                "tv_name": cfg.get("tv_name", ""),
                "tv_mac": cfg.get("tv_mac", ""),
                "has_token": bool(cfg.get("tokens", {}).get(cfg.get("tv_ip", ""))),
                "connection_status": controller.status,
                "local_ip": get_local_ip(),
            })
        elif parsed.path == "/api/discover":
            tvs = discover_samsung_tvs()
            cfg = load_config()
            # Auto-select if none configured yet and 1 found
            if tvs and not cfg.get("tv_ip"):
                cfg["tv_ip"] = tvs[0]["ip"]
                cfg["tv_name"] = tvs[0]["name"]
                if tvs[0].get("mac"):
                    cfg["tv_mac"] = tvs[0]["mac"]
                save_config(cfg)
            self._send_json({"ok": True, "tvs": tvs, "selected_ip": cfg.get("tv_ip", "")})
        else:
            self._send_json({"ok": False, "error": "Not found"}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}

        if parsed.path == "/api/connect":
            tv_ip = body.get("tv_ip", "").strip()
            if not tv_ip:
                self._send_json({"ok": False, "error": "テレビ/电视 IP 不能为空"}, 400)
                return
            cfg = load_config()
            cfg["tv_ip"] = tv_ip
            save_config(cfg)
            ok, msg = controller.ensure_connected(tv_ip)
            cfg = load_config()
            self._send_json({
                "ok": ok,
                "message": msg,
                "tv_ip": cfg.get("tv_ip", ""),
                "tv_name": cfg.get("tv_name", ""),
                "has_token": bool(cfg.get("tokens", {}).get(tv_ip)),
            })

        elif parsed.path == "/api/key":
            key = body.get("key", "").strip()
            cmd = body.get("cmd", "Click").strip()
            if not key:
                self._send_json({"ok": False, "error": "Missing key"}, 400)
                return
            ok, msg = controller.send_key(key, cmd=cmd)
            self._send_json({"ok": ok, "message": msg})

        elif parsed.path == "/api/text":
            text = body.get("text", "")
            ok, msg = controller.send_text(text)
            self._send_json({"ok": ok, "message": msg})

        elif parsed.path == "/api/wol":
            cfg = load_config()
            sent = send_wol(cfg.get("tv_mac", ""))
            self._send_json({
                "ok": sent,
                "message": "已发送 Wake-on-LAN 唤醒包" if sent else "尚未记录电视 MAC 地址，请先在电视开机状态下连接一次",
            })
        else:
            self._send_json({"ok": False, "error": "Not found"}, 404)


def main():
    port = int(os.environ.get("PORT", "8765"))
    local_ip = get_local_ip()
    print("=" * 56)
    print("📺 三星电视网页遥控器 (Samsung Smart TV Web Remote)")
    print("=" * 56)
    print(f"💻 电脑访问: http://127.0.0.1:{port}")
    print(f"📱 手机访问: http://{local_ip}:{port}  (请确保手机连在同一 Wi-Fi)")
    print("=" * 56)

    server = http.server.ThreadingHTTPServer(("0.0.0.0", port), RemoteHTTPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止服务。")


if __name__ == "__main__":
    main()
