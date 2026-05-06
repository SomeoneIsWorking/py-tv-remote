import socket
import threading
from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange

ANDROIDTV_REMOTE = "_androidtvremote2._tcp.local."
ANDROIDTV_REMOTE_OLD = "_androidtvremote._tcp.local."
GOOGLECAST = "_googlecast._tcp.local."
REMOTE_PORT = 6466


def _check_port(ip, port, timeout=1):
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        s.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def discover_tvs(timeout=3):
    found = []
    seen_ips = set()

    zeroconf = Zeroconf()

    def add_tv(name, ips, server, port, service_type):
        for ip in ips:
            if ip not in seen_ips:
                seen_ips.add(ip)
                found.append({
                    "name": name,
                    "host": server or "",
                    "ips": [ip],
                    "port": port,
                    "service_type": service_type,
                })

    def on_service_state_change(zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            info = zeroconf.get_service_info(service_type, name)
            if info:
                ips = [socket.inet_ntoa(addr) for addr in info.addresses] if info.addresses else []
                display_name = name.replace(f".{service_type}", "").replace("\\", "")
                server = str(info.server).rstrip(".") if info.server else ""
                add_tv(display_name, ips, server, info.port, service_type)

    browsers = [
        ServiceBrowser(zeroconf, ANDROIDTV_REMOTE, handlers=[on_service_state_change]),
        ServiceBrowser(zeroconf, ANDROIDTV_REMOTE_OLD, handlers=[on_service_state_change]),
        ServiceBrowser(zeroconf, GOOGLECAST, handlers=[on_service_state_change]),
    ]

    threading.Event().wait(timeout)
    zeroconf.close()

    result = []
    for tv in found:
        if tv["service_type"] in (ANDROIDTV_REMOTE, ANDROIDTV_REMOTE_OLD):
            result.append({k: v for k, v in tv.items() if k != "service_type"})
        elif tv["service_type"] == GOOGLECAST:
            ip = tv["ips"][0]
            if _check_port(ip, REMOTE_PORT):
                name = tv["name"].split("-", 1)[-1][:20] if "-" in tv["name"] else tv["name"]
                result.append({
                    "name": f"{name} (Android TV)",
                    "host": tv["host"],
                    "ips": [ip],
                })

    return result
