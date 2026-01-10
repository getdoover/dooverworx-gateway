#!/bin/sh
set -eu

# ------------------------------------
# Defaults from environment (compose)
# ------------------------------------
TARGET_IFACE="${TARGET_IFACE:-}"
BRIDGE_NAME="${BRIDGE_NAME:-dv_vpn_bridge}"
TAP_NAME="${TAP_NAME:-tap0}"
OPENVPN_PORT="${OPENVPN_PORT:-1194}"

usage() {
  cat <<EOF
Usage: $0 [--target-iface <iface_or_bridge>] [--bridge-name <name>] [--tap-name <name>]

Environment defaults (preferred via docker-compose):
  TARGET_IFACE  (required): interface or bridge to attach to
  BRIDGE_NAME   (optional): default dv_vpn_bridge
  TAP_NAME      (optional): default dv_tap0

Behavior:
- If TARGET_IFACE is a bridge (e.g. br0): attach TAP to that existing bridge.
- If TARGET_IFACE is a normal interface (e.g. eth1): create BRIDGE_NAME and attach iface + TAP to it.
- On exit: remove TAP and remove created bridge (only if this script created it).
EOF
}

# ------------------------------------
# Optional CLI overrides (take priority)
# ------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --target-iface)
      TARGET_IFACE="${2:-}"; shift 2;;
    --bridge-name)
      BRIDGE_NAME="${2:-}"; shift 2;;
    --tap-name)
      TAP_NAME="${2:-}"; shift 2;;
    -h|--help)
      usage; exit 0;;
    *)
      echo "[bridge] ERROR: unknown arg: $1" >&2
      usage
      exit 2;;
  esac
done

if [ -z "${TARGET_IFACE}" ]; then
  echo "[bridge] ERROR: TARGET_IFACE is required (set env TARGET_IFACE or pass --target-iface)" >&2
  usage
  exit 2
fi

echo "[bridge] target iface: ${TARGET_IFACE}"
echo "[bridge] bridge name:  ${BRIDGE_NAME}"
echo "[bridge] tap name:     ${TAP_NAME}"

# ------------------------------------
# Helpers
# ------------------------------------
iface_exists() {
  ip link show "$1" >/dev/null 2>&1
}

is_bridge() {
  [ -d "/sys/class/net/$1/bridge" ]
}

set_master() {
  ip link set dev "$1" master "$2" 2>/dev/null || true
}

unset_master() {
  ip link set dev "$1" nomaster 2>/dev/null || true
}

safe_link_del() {
  if iface_exists "$1"; then
    ip link set dev "$1" down 2>/dev/null || true
    ip link del "$1" 2>/dev/null || true
  fi
}

# ------------------------------------
# Preconditions
# ------------------------------------
iface_exists "${TARGET_IFACE}" || {
  echo "[bridge] ERROR: target '${TARGET_IFACE}' not found"
  ip link || true
  exit 1
}

# Enable forwarding (often not strictly required for pure L2)
sysctl -w net.ipv4.ip_forward=1 >/dev/null 2>&1 || true

# ------------------------------------
# Decide mode
# ------------------------------------
ATTACH_BRIDGE=""
CREATED_BRIDGE=0
OVPN_PID=""

if is_bridge "${TARGET_IFACE}"; then
  # Attach TAP to existing bridge
  ATTACH_BRIDGE="${TARGET_IFACE}"
  echo "[bridge] target is an existing bridge: ${ATTACH_BRIDGE}"

  # Ensure bridge is up
  ip link set dev "${ATTACH_BRIDGE}" up 2>/dev/null || true
else
  # Create a new bridge and attach target iface + TAP
  ATTACH_BRIDGE="${BRIDGE_NAME}"
  echo "[bridge] target is a normal interface; will create bridge: ${ATTACH_BRIDGE}"

  if iface_exists "${ATTACH_BRIDGE}"; then
    echo "[bridge] ERROR: bridge '${ATTACH_BRIDGE}' already exists; refusing to modify it automatically." >&2
    echo "[bridge]        (Choose a different BRIDGE_NAME or point TARGET_IFACE at an existing bridge.)" >&2
    exit 1
  fi

  ip link add name "${ATTACH_BRIDGE}" type bridge
  CREATED_BRIDGE=1

  ip link set dev "${ATTACH_BRIDGE}" up

  ip link set dev "${TARGET_IFACE}" up
  ip link set dev "${TARGET_IFACE}" promisc on 2>/dev/null || true
  set_master "${TARGET_IFACE}" "${ATTACH_BRIDGE}"
fi

cleanup() {
  echo "[bridge] cleanup: stopping..."

  # Stop OpenVPN first
  if [ -n "${OVPN_PID}" ] && kill -0 "${OVPN_PID}" >/dev/null 2>&1; then
    kill "${OVPN_PID}" >/dev/null 2>&1 || true
    sleep 0.3
    kill -9 "${OVPN_PID}" >/dev/null 2>&1 || true
  fi

  # Detach and remove TAP
  if iface_exists "${TAP_NAME}"; then
    unset_master "${TAP_NAME}"
  fi
  safe_link_del "${TAP_NAME}"

  # If we created a bridge, detach iface and remove bridge
  if [ "${CREATED_BRIDGE}" -eq 1 ]; then
    unset_master "${TARGET_IFACE}"
    ip link set dev "${TARGET_IFACE}" promisc off 2>/dev/null || true
    safe_link_del "${ATTACH_BRIDGE}"
  fi

  echo "[bridge] cleanup: done."
}

trap cleanup INT TERM EXIT

# ------------------------------------
# Start OpenVPN (it must create TAP_NAME)
# ------------------------------------
echo "[openvpn] starting on port ${OPENVPN_PORT}..."
openvpn --config /etc/openvpn/server.conf --port "${OPENVPN_PORT}" &
OVPN_PID="$!"

# Wait for TAP to appear
for i in $(seq 1 80); do
  if iface_exists "${TAP_NAME}"; then
    break
  fi
  sleep 0.1
done

iface_exists "${TAP_NAME}" || {
  echo "[bridge] ERROR: TAP '${TAP_NAME}' never appeared"
  exit 1
}

# Attach TAP to chosen bridge
ip link set dev "${TAP_NAME}" up
ip link set dev "${TAP_NAME}" promisc on 2>/dev/null || true
set_master "${TAP_NAME}" "${ATTACH_BRIDGE}"

echo "[bridge] bridge ports:"
bridge link || true

echo "[bridge] running. Ctrl+C / stop container to exit."
wait "${OVPN_PID}"