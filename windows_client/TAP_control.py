#!/usr/bin/env python3
"""
DooverWorx TAP Session Utility (Windows) Static-key by Default PoC

Default behavior:
- Creates a named TAP adapter
- Starts an OpenVPN TAP tunnel using ./static.key (located next to this script) if present
- Uses cipher/auth defaults: AES-256-CBC / SHA256
- Keeps TAP alive while running
- On exit: stops tunnel and deletes (or disables) TAP

Overrides:
- --static-key <path> to use a different static key
- --no-static-key to disable static key usage (e.g. switching to TLS later)
- --cipher / --auth to override crypto knobs
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple


# ---------- helpers ----------

def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def parse_endpoint(endpoint: str) -> Tuple[str, int]:
    ep = endpoint.replace("tcp://", "").replace("tls://", "").strip()
    if "/" in ep:
        ep = ep.split("/", 1)[0]
    host, port_s = ep.rsplit(":", 1)
    return host.strip(), int(port_s)


def find_exe(candidates: list[str], name: str) -> str:
    for c in candidates:
        if not c:
            continue
        if os.path.isabs(c) and os.path.exists(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    raise FileNotFoundError(f"Could not find {name}")


def interface_exists(name: str) -> bool:
    p = subprocess.run(
        ["netsh", "interface", "show", "interface", f"name={name}"],
        text=True,
        capture_output=True,
    )
    return p.returncode == 0


def set_interface_enabled(name: str, enabled: bool):
    desired = "Enabled" if enabled else "Disabled"
    result = run(["netsh", "interface", "show", "interface", f"name={name}"], check=False)
    if desired in (result.stdout or ""):
        return
    state = "ENABLED" if enabled else "DISABLED"
    run(["netsh", "interface", "set", "interface", f"name={name}", f"admin={state}"])

def ovpn_path(p: Path) -> str:
    """
    Return a path string safe to embed in an .ovpn file on Windows.
    Use forward slashes to avoid OpenVPN backslash-escape warnings.
    """
    return str(p.resolve()).replace("\\", "/")

def read_text_if_exists(p: Path) -> str:
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

# ---------- OpenVPN config ----------

def slurp(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore").strip() + "\n"


def build_ovpn(
    host: str,
    port: int,
    tap_name: str,
    mtu: int,
    cipher: str,
    auth: str,
    static_key: Optional[Path],
    pkcs12: Optional[Path],
    ca: Optional[Path],
    cert: Optional[Path],
    key: Optional[Path],
    auth_user_pass: Optional[Path],
    extra: Optional[str],
) -> str:
    
    is_static = static_key is not None

    if is_static:
        # Pure static-key / p2p config (no TLS directives)
        cfg = f"""
dev tap
dev-node "{tap_name}"

mode p2p
proto tcp-client
remote {host} {port}

nobind
persist-key
persist-tun

verb 4
mute 10

# MTU safety
tun-mtu {mtu}
mssfix {max(900, mtu - 100)}

keepalive 10 60
explicit-exit-notify 0

# Static key mode
secret "{ovpn_path(static_key)}"

# Crypto (static-key mode uses these)
cipher {cipher}
auth {auth}
"""
        # NOTE: no 'client' directive, no remote-cert-tls, no ca/cert/key/pkcs12

    else:
        # TLS-capable client config (future)
        cfg = f"""
client
dev tap
dev-node "{tap_name}"

proto tcp-client
remote {host} {port}

resolv-retry infinite
nobind
persist-key
persist-tun

remote-cert-tls server

verb 4
mute 10

tun-mtu {mtu}
mssfix {max(900, mtu - 100)}

keepalive 10 60
explicit-exit-notify 0

# Crypto defaults (TLS mode)
data-ciphers AES-256-GCM:AES-128-GCM:CHACHA20-POLY1305
data-ciphers-fallback {cipher}
auth {auth}
"""

    # Static key mode (your current server is using --secret)
    if static_key:
        cfg += f'\nsecret "{ovpn_path(static_key)}"\n'

    # Optional TLS/auth blocks (not used in static-key mode, but kept for future)
    if pkcs12:
        cfg += f'\npkcs12 "{pkcs12}"\n'
    elif ca and cert and key:
        cfg += f"""
<ca>
{slurp(ca)}</ca>
<cert>
{slurp(cert)}</cert>
<key>
{slurp(key)}</key>
"""

    if auth_user_pass:
        cfg += f'\nauth-user-pass "{auth_user_pass}"\n'

    if extra:
        cfg += "\n" + extra.strip() + "\n"

    return "\n".join(line.rstrip() for line in cfg.strip().splitlines()) + "\n"


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser("DooverWorx TAP Session (static-key default)")

    ap.add_argument("--tap-name", required=True)
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--cleanup-mode", choices=["delete", "disable"], default="delete")
    ap.add_argument("--mtu", type=int, default=1300)
    ap.add_argument("--extra", help="Extra OpenVPN directives")

    ap.add_argument("--openvpn-path")
    ap.add_argument("--tapctl-path")

    # Crypto defaults (your chosen knobs)
    ap.add_argument("--cipher", default="AES-256-CBC")
    ap.add_argument("--auth", default="SHA256")

    # Static key behavior
    ap.add_argument("--static-key", type=Path, default=None,
                    help="Path to static.key to use for OpenVPN --secret mode. "
                         "If omitted, defaults to ./static.key next to this script if present.")
    ap.add_argument("--no-static-key", action="store_true",
                    help="Disable static-key mode even if ./static.key exists. Useful when switching to TLS later.")

    # OPTIONAL auth (TLS path later)
    ap.add_argument("--pkcs12", type=Path)
    ap.add_argument("--ca", type=Path)
    ap.add_argument("--cert", type=Path)
    ap.add_argument("--key", type=Path)
    ap.add_argument("--auth-user-pass", type=Path)

    args = ap.parse_args()

    if not sys.platform.startswith("win"):
        print("Windows only", file=sys.stderr)
        return 2

    if args.ca and not (args.cert and args.key):
        ap.error("--ca requires --cert and --key")

    openvpn = find_exe([
        args.openvpn_path or "",
        r"C:\Program Files\OpenVPN\bin\openvpn.exe",
        "openvpn.exe",
    ], "openvpn.exe")

    tapctl = find_exe([
        args.tapctl_path or "",
        r"C:\Program Files\OpenVPN\bin\tapctl.exe",
        "tapctl.exe",
    ], "tapctl.exe")

    # Resolve static key default: static.key next to this script
    script_dir = Path(__file__).resolve().parent
    default_key = script_dir / "static.key"

    static_key: Optional[Path] = None
    if not args.no_static_key:
        static_key = args.static_key if args.static_key else (default_key if default_key.exists() else None)

    # If user explicitly provided --static-key, require it exists
    if args.static_key and not args.static_key.exists():
        ap.error(f"--static-key not found: {args.static_key}")

    # If we're in static-key mode, require we have a key
    if not args.no_static_key and static_key is None:
        print("[warn] No static.key found next to script and no --static-key provided.", file=sys.stderr)
        print("[warn] Client will start WITHOUT --secret. If your server is static-key mode, it will NOT connect.", file=sys.stderr)

    host, port = parse_endpoint(args.endpoint)
    proc = None
    created = False

    tap_name = args.tap_name
    if interface_exists(tap_name):
        print(f"TAP '{tap_name}' already exists")
    else:
        print(f"[tap] Creating TAP '{tap_name}'")
        run([tapctl, "create", "--name", tap_name])
        created = True

    def cleanup():
        nonlocal proc, created
        if proc and proc.poll() is None:
            proc.terminate()
        if created:
            try:
                if args.cleanup_mode == "delete":
                    run([tapctl, "delete", "--name", tap_name])
                else:
                    set_interface_enabled(tap_name, False)
            except Exception as e:
                print(f"[cleanup] {e}", file=sys.stderr)

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    for _ in range(20):
        if interface_exists(tap_name):
            break
        time.sleep(0.25)

    set_interface_enabled(tap_name, True)

    with tempfile.TemporaryDirectory(prefix="dooverworx-") as td:
        cfg = build_ovpn(
            host=host,
            port=port,
            tap_name=tap_name,
            mtu=args.mtu,
            cipher=args.cipher,
            auth=args.auth,
            static_key=static_key,
            pkcs12=args.pkcs12,
            ca=args.ca,
            cert=args.cert,
            key=args.key,
            auth_user_pass=args.auth_user_pass,
            extra=args.extra,
        )
        cfg_path = Path(td) / "client.ovpn"
        log_path = Path(td) / "openvpn.log"
        cfg_path.write_text(cfg, encoding="utf-8")

        print("[tunnel] Starting OpenVPN")
        if static_key:
            print(f"[tunnel] Using static-key: {static_key}")
        print(f"[tunnel] Cipher/Auth: {args.cipher} / {args.auth}")

        # proc = subprocess.Popen(
        #     [openvpn, "--config", str(cfg_path), "--log", str(log_path)],
        #     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        # )
        proc = subprocess.Popen(
            [openvpn, "--config", str(cfg_path), "--log", str(log_path)],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        print("[tunnel] Running. Ctrl+C to stop.")
        try:
            while True:
                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    print(line.rstrip())
                if proc.poll() is not None:
                    print(f"[tunnel] OpenVPN exited with code {proc.returncode}")
                    print(f"[tunnel] Log file: {log_path}")
                    # try:
                    #     print(log_path.read_text(encoding="utf-8", errors="ignore"))
                    # except Exception:
                    #     pass
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[tunnel] Shutdown requested by user")

    return 0


if __name__ == "__main__":
    import shlex
    import ctypes

    args_str = " ".join(shlex.quote(a) for a in sys.argv[1:])

    def is_admin():
        try:
            return ctypes.windll.shell32.IsUserAnAdmin()
        except Exception:
            return False

    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            "cmd.exe",
            f'/k "{sys.executable} "{os.path.abspath(__file__)}" {args_str}"',
            None,
            1
        )
        sys.exit(0)

    print("Running as administrator")
    main()
    print("\n\nDone.\n")