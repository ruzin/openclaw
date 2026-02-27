#!/usr/bin/env python3
"""noVNC login session manager for Tesco.

Starts a headless Chrome inside a virtual display (Xvfb), exposes it via
x11vnc + websockify (noVNC), and lets the user log into Tesco through a
real browser. Akamai sees a genuine human interaction.

Usage:
  python3 tesco-vnc-login.py start <profile> [--cdp-port PORT]
  python3 tesco-vnc-login.py status <profile>
  python3 tesco-vnc-login.py stop <profile>
  python3 tesco-vnc-login.py cleanup

Requires: Xvfb, x11vnc, websockify, fluxbox, google-chrome (or chromium).
"""

import argparse
import glob
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SESSION_DIR = Path("/tmp")
SESSION_PREFIX = "tesco-vnc-"
SESSION_SUFFIX = ".json"
DISPLAY_BASE = 100
WEBSOCKIFY_PORT_BASE = 6080
MAX_SESSIONS = 10
SESSION_TTL_SECONDS = 1800  # 30 minutes

# VM public IP – used to build the noVNC URL
VM_IP = os.environ.get("TESCO_VNC_HOST", "16.60.83.110")

# noVNC HTML path (Debian/Ubuntu default)
NOVNC_PATH = "/usr/share/novnc"


def session_file(profile: str) -> Path:
    return SESSION_DIR / f"{SESSION_PREFIX}{profile}{SESSION_SUFFIX}"


def find_chrome() -> str:
    """Find the Chrome/Chromium binary."""
    for name in ("google-chrome", "google-chrome-stable", "chromium-browser", "chromium"):
        path = subprocess.run(
            ["which", name], capture_output=True, text=True
        ).stdout.strip()
        if path:
            return path
    raise RuntimeError("Chrome or Chromium not found in PATH")


def is_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def is_display_free(display_num: int) -> bool:
    lock = Path(f"/tmp/.X{display_num}-lock")
    return not lock.exists()


def allocate_display() -> int:
    """Find the next free X display number."""
    for n in range(DISPLAY_BASE, DISPLAY_BASE + MAX_SESSIONS):
        if is_display_free(n):
            return n
    raise RuntimeError("No free display numbers available")


def allocate_port() -> int:
    """Find the next free websockify port."""
    for p in range(WEBSOCKIFY_PORT_BASE, WEBSOCKIFY_PORT_BASE + MAX_SESSIONS):
        if is_port_free(p):
            return p
    raise RuntimeError("No free websockify ports available")


def wait_for_port(port: int, timeout: float = 10) -> bool:
    """Wait until a TCP port is accepting connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


def kill_pid(pid: int) -> None:
    """Send SIGTERM then SIGKILL if the process doesn't exit."""
    try:
        os.kill(pid, signal.SIGTERM)
        # Give it a moment to exit gracefully
        for _ in range(10):
            os.kill(pid, 0)  # check if alive
            time.sleep(0.1)
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # already dead


# ── Commands ────────────────────────────────────────────────────────────


def cmd_start(profile: str, cdp_port: int) -> int:
    sf = session_file(profile)
    if sf.exists():
        try:
            existing = json.loads(sf.read_text())
            # Check if the session is still alive
            xvfb_pid = existing.get("pids", {}).get("xvfb")
            if xvfb_pid:
                try:
                    os.kill(xvfb_pid, 0)
                    # Still running – return the existing URL
                    print(json.dumps({
                        "status": "already_running",
                        "url": existing.get("url", ""),
                        "expires_in": max(0, SESSION_TTL_SECONDS - int(
                            (datetime.now(timezone.utc) - datetime.fromisoformat(existing["started_at"])).total_seconds()
                        )),
                    }))
                    return 0
                except ProcessLookupError:
                    pass  # stale session file, clean up below
        except (json.JSONDecodeError, KeyError):
            pass
        # Stale session – clean up
        cmd_stop(profile, quiet=True)

    display_num = allocate_display()
    ws_port = allocate_port()
    display = f":{display_num}"
    vnc_port = 5900 + display_num
    password = secrets.token_urlsafe(9)[:12]  # 12-char random password

    browser_profile_dir = Path.home() / ".openclaw" / "browser" / profile / "user-data"
    browser_profile_dir.mkdir(parents=True, exist_ok=True)

    pids: dict[str, int] = {}

    try:
        # 1. Start Xvfb
        xvfb = subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1280x800x24", "-ac"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pids["xvfb"] = xvfb.pid
        time.sleep(0.5)

        env = {**os.environ, "DISPLAY": display}

        # 2. Start fluxbox (window manager)
        fluxbox = subprocess.Popen(
            ["fluxbox"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
        )
        pids["fluxbox"] = fluxbox.pid
        time.sleep(0.3)

        # 3. Launch Chrome
        chrome_bin = find_chrome()
        chrome = subprocess.Popen(
            [
                chrome_bin,
                f"--user-data-dir={browser_profile_dir}",
                f"--remote-debugging-port={cdp_port}",
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-translate",
                "--metrics-recording-only",
                "--window-size=1280,800",
                "--window-position=0,0",
                "https://www.tesco.com/groceries/en-GB/",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=env,
        )
        pids["chrome"] = chrome.pid
        time.sleep(1)

        # 4. Start x11vnc
        x11vnc = subprocess.Popen(
            [
                "x11vnc",
                "-display", display,
                "-passwd", password,
                "-rfbport", str(vnc_port),
                "-shared",
                "-forever",
                "-noxdamage",
                "-nopw",  # disable the warning about no password file
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pids["x11vnc"] = x11vnc.pid

        if not wait_for_port(vnc_port, timeout=5):
            raise RuntimeError(f"x11vnc did not start on port {vnc_port}")

        # 5. Start websockify
        websockify = subprocess.Popen(
            [
                "websockify",
                "--web", NOVNC_PATH,
                str(ws_port),
                f"localhost:{vnc_port}",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pids["websockify"] = websockify.pid

        if not wait_for_port(ws_port, timeout=5):
            raise RuntimeError(f"websockify did not start on port {ws_port}")

    except Exception:
        # Clean up any processes we started
        for pid in pids.values():
            kill_pid(pid)
        raise

    url = f"http://{VM_IP}:{ws_port}/vnc.html?autoconnect=true&password={password}"

    session = {
        "profile": profile,
        "display": display,
        "websockify_port": ws_port,
        "vnc_port": vnc_port,
        "cdp_port": cdp_port,
        "password": password,
        "url": url,
        "pids": pids,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    sf.write_text(json.dumps(session, indent=2))

    print(json.dumps({
        "status": "started",
        "url": url,
        "expires_in": SESSION_TTL_SECONDS,
    }))
    return 0


def cmd_status(profile: str) -> int:
    sf = session_file(profile)
    if not sf.exists():
        print(json.dumps({"logged_in": False, "session_active": False}))
        return 0

    try:
        session = json.loads(sf.read_text())
    except json.JSONDecodeError:
        print(json.dumps({"logged_in": False, "session_active": False}))
        return 0

    # Check if Xvfb is still alive
    xvfb_pid = session.get("pids", {}).get("xvfb")
    if not xvfb_pid:
        print(json.dumps({"logged_in": False, "session_active": False}))
        return 0

    try:
        os.kill(xvfb_pid, 0)
    except ProcessLookupError:
        print(json.dumps({"logged_in": False, "session_active": False}))
        return 0

    # Session is active – check login status via CDP
    cdp_port = session.get("cdp_port", 18810)
    logged_in = check_login_via_cdp(cdp_port)

    print(json.dumps({"logged_in": logged_in, "session_active": True}))
    return 0


def check_login_via_cdp(cdp_port: int) -> bool:
    """Check for the OAuth.AccessToken cookie on .tesco.com via CDP.

    Uses a minimal websocket implementation (stdlib only) to send a single
    CDP command and read the response. No third-party deps required.
    """
    import base64
    import http.client
    import struct

    try:
        conn = http.client.HTTPConnection("127.0.0.1", cdp_port, timeout=5)
        conn.request("GET", "/json")
        resp = conn.getresponse()
        targets = json.loads(resp.read())
        conn.close()

        page_ws = None
        for t in targets:
            if t.get("type") == "page":
                page_ws = t.get("webSocketDebuggerUrl")
                break
        if not page_ws:
            return False

        # Minimal websocket handshake + send/recv (RFC 6455, no masking needed
        # for local connections but we mask anyway for spec compliance)
        from urllib.parse import urlparse
        parsed = urlparse(page_ws)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or cdp_port
        path = parsed.path

        sock = socket.create_connection((host, port), timeout=5)
        ws_key = base64.b64encode(secrets.token_bytes(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        sock.sendall(handshake.encode())

        # Read HTTP response headers (until \r\n\r\n)
        header_buf = b""
        while b"\r\n\r\n" not in header_buf:
            chunk = sock.recv(4096)
            if not chunk:
                return False
            header_buf += chunk

        # Send CDP command (masked frame)
        payload = json.dumps({
            "id": 1,
            "method": "Network.getCookies",
            "params": {"urls": ["https://www.tesco.com"]},
        }).encode()

        mask_key = secrets.token_bytes(4)
        masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

        # Build frame: FIN + TEXT opcode, MASK bit + length, mask key, masked payload
        frame = bytearray()
        frame.append(0x81)  # FIN + TEXT
        plen = len(payload)
        if plen <= 125:
            frame.append(0x80 | plen)
        elif plen <= 65535:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", plen))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", plen))
        frame.extend(mask_key)
        frame.extend(masked)
        sock.sendall(bytes(frame))

        # Read response frame
        def recv_exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("socket closed")
                buf += chunk
            return buf

        hdr = recv_exact(2)
        resp_len = hdr[1] & 0x7F
        if resp_len == 126:
            resp_len = struct.unpack("!H", recv_exact(2))[0]
        elif resp_len == 127:
            resp_len = struct.unpack("!Q", recv_exact(8))[0]

        resp_data = recv_exact(resp_len)
        sock.close()

        result = json.loads(resp_data)
        cookies = result.get("result", {}).get("cookies", [])
        return any(c.get("name") == "OAuth.AccessToken" for c in cookies)

    except Exception:
        return False


def cmd_stop(profile: str, quiet: bool = False) -> int:
    sf = session_file(profile)
    if not sf.exists():
        if not quiet:
            print(json.dumps({"status": "not_running"}))
        return 0

    try:
        session = json.loads(sf.read_text())
    except json.JSONDecodeError:
        sf.unlink(missing_ok=True)
        if not quiet:
            print(json.dumps({"status": "stopped"}))
        return 0

    pids = session.get("pids", {})
    # Kill in reverse dependency order
    for name in ("websockify", "x11vnc", "fluxbox", "chrome", "xvfb"):
        pid = pids.get(name)
        if pid:
            kill_pid(pid)

    sf.unlink(missing_ok=True)
    if not quiet:
        print(json.dumps({"status": "stopped"}))
    return 0


def cmd_cleanup() -> int:
    now = datetime.now(timezone.utc)
    cleaned = 0

    for path in glob.glob(str(SESSION_DIR / f"{SESSION_PREFIX}*{SESSION_SUFFIX}")):
        sf = Path(path)
        try:
            session = json.loads(sf.read_text())
            started = datetime.fromisoformat(session["started_at"])
            age = (now - started).total_seconds()
            if age > SESSION_TTL_SECONDS:
                profile = session.get("profile", sf.stem.removeprefix(SESSION_PREFIX))
                cmd_stop(profile, quiet=True)
                cleaned += 1
        except (json.JSONDecodeError, KeyError):
            sf.unlink(missing_ok=True)
            cleaned += 1

    # Kill orphaned Xvfb processes that don't have a session file
    try:
        result = subprocess.run(
            ["pgrep", "-af", "Xvfb :(1[0-9][0-9])"],
            capture_output=True, text=True,
        )
        for line in result.stdout.strip().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                pid = int(parts[0])
                # Check if any session file references this PID
                has_session = False
                for spath in glob.glob(str(SESSION_DIR / f"{SESSION_PREFIX}*{SESSION_SUFFIX}")):
                    try:
                        s = json.loads(Path(spath).read_text())
                        if s.get("pids", {}).get("xvfb") == pid:
                            has_session = True
                            break
                    except (json.JSONDecodeError, KeyError):
                        pass
                if not has_session:
                    kill_pid(pid)
                    cleaned += 1
    except Exception:
        pass

    print(json.dumps({"status": "cleaned", "sessions_removed": cleaned}))
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(
        description="noVNC login session manager for Tesco."
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_start = sub.add_parser("start", help="Start a VNC login session")
    p_start.add_argument("profile", help="Browser profile name (e.g. tesco-ruzin)")
    p_start.add_argument(
        "--cdp-port", type=int, default=18810,
        help="Chrome DevTools Protocol port (default: 18810)",
    )

    p_status = sub.add_parser("status", help="Check login status")
    p_status.add_argument("profile", help="Browser profile name")

    p_stop = sub.add_parser("stop", help="Stop a VNC login session")
    p_stop.add_argument("profile", help="Browser profile name")

    sub.add_parser("cleanup", help="Remove expired sessions and orphaned processes")

    args = ap.parse_args()

    if args.command == "start":
        return cmd_start(args.profile, args.cdp_port)
    elif args.command == "status":
        return cmd_status(args.profile)
    elif args.command == "stop":
        return cmd_stop(args.profile)
    elif args.command == "cleanup":
        return cmd_cleanup()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
