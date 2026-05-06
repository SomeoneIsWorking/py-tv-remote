import asyncio
import json
import os

from edifice import component, App, Window, HBoxView, VBoxView, Label, Button, TextInput, ProgressBar, use_state, use_async_call

from androidtvremote2 import AndroidTVRemote

from .discovery import discover_tvs


def _config_dir():
    d = os.path.expanduser("~/.config/tv_remote")
    os.makedirs(d, exist_ok=True)
    return d


def _paired_path():
    return os.path.join(_config_dir(), "paired.json")


def _load_paired():
    try:
        with open(_paired_path()) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_paired(tvs):
    with open(_paired_path(), "w") as f:
        json.dump(tvs, f, indent=2)


def _add_paired(ip, name, mac):
    tvs = _load_paired()
    tvs = [t for t in tvs if t.get("ip") != ip]
    tvs.insert(0, {"ip": ip, "name": name, "mac": mac})
    _save_paired(tvs)
    return tvs

BTN = {"min-width": 64, "min-height": 40, "font-size": "14px", "border": "1px solid #555", "border-radius": "6px", "padding": "4px 12px"}
BTN_PRIMARY = {**BTN, "background-color": "#1a73e8", "color": "white", "border": "1px solid #1a73e8", "font-weight": "bold"}
BTN_DANGER = {**BTN, "background-color": "#d32f2f", "color": "white", "border": "1px solid #d32f2f"}
BTN_SM = {**BTN, "min-width": 48, "min-height": 36, "font-size": "13px", "padding": "2px 8px"}
BTN_DPAD = {"min-width": 52, "min-height": 44, "font-size": "18px", "border": "1px solid #555", "border-radius": "8px", "background-color": "#333", "color": "#eee", "padding": "2px"}
BTN_OK = {**BTN_DPAD, "min-width": 56, "min-height": 44, "background-color": "#1a73e8", "color": "white", "border": "1px solid #1a73e8", "font-weight": "bold"}
BTN_DISABLED = {**BTN, "background-color": "#2a2a2a", "color": "#666", "border": "1px solid #333"}
SECTION = {"font-size": "11px", "color": "#888", "margin-top": "12px", "margin-bottom": "2px", "font-weight": "bold", "letter-spacing": "1px"}
INPUT = {"border": "1px solid #555", "border-radius": "6px", "padding": "6px 10px", "font-size": "14px", "min-height": 32, "background-color": "#222", "color": "#eee"}
CARD = {"border": "1px solid #333", "border-radius": "10px", "padding": "14px", "background-color": "#1e1e1e"}


def _get_cert_dir():
    d = os.path.expanduser("~/.config/tv_remote/certs")
    os.makedirs(d, exist_ok=True)
    return d


def _paths_for(ip):
    safe = ip.replace(".", "_").replace(":", "_")
    d = _get_cert_dir()
    return os.path.join(d, f"{safe}.pem"), os.path.join(d, f"{safe}.key")


@component
def RemoteApp(self):
    state, set_state = use_state({
        "screen": "tv_list",
        "tvs": [],
        "paired_tvs": _load_paired(),
        "selected_tv": None,
        "error_msg": "",
        "remote": None,
        "manual_ip": "",
        "scanning": False,
        "pairing_code_input": "",
    })

    async def do_discover_async():
        set_state(lambda s: {**s, "scanning": True, "error_msg": ""})
        loop = asyncio.get_running_loop()
        try:
            tvs = await loop.run_in_executor(None, lambda: discover_tvs(timeout=5))
            found = len(tvs)
            err = f"Found {found} TV(s)" if found else "No TVs found"
            set_state(lambda s: {**s, "tvs": tvs, "scanning": False, "error_msg": err})
        except Exception as e:
            set_state(lambda s: {**s, "scanning": False, "error_msg": f"Discovery failed: {e}"})

    async def do_connect_async(tv):
        ips = tv.get("ips", [])
        host = tv.get("host", "").rstrip(".")
        ip = ips[0] if ips else host
        cert, key = _paths_for(ip)

        remote = AndroidTVRemote("TV Remote", cert, key, ip)
        needs = await remote.async_generate_cert_if_missing()

        if needs:
            try:
                name, mac = await remote.async_get_name_and_mac()
            except Exception:
                name, mac = ip, ""
            set_state(lambda s: {**s, "screen": "pairing", "selected_tv": {**tv, "name": name}})
            try:
                await remote.async_start_pairing()
                set_state(lambda s: {**s, "remote": remote, "screen": "pairing_code"})
                return
            except Exception as e:
                set_state(lambda s: {**s, "screen": "error", "error_msg": f"Pairing failed: {e}"})
                return

        try:
            await remote.async_connect()
            ips = tv.get("ips", [])
            ip = ips[0] if ips else tv.get("host", "").rstrip(".") or tv.get("name", "")
            paired = _add_paired(ip, tv.get("name", ip), "")
            set_state(lambda s: {**s, "screen": "remote", "remote": remote, "selected_tv": tv, "paired_tvs": paired})
        except Exception:
            try:
                name, mac = await remote.async_get_name_and_mac()
            except Exception:
                name, mac = ip, ""
            set_state(lambda s: {**s, "screen": "pairing", "selected_tv": {**tv, "name": name}})
            try:
                await remote.async_start_pairing()
                set_state(lambda s: {**s, "remote": remote, "screen": "pairing_code"})
            except Exception as e:
                set_state(lambda s: {**s, "screen": "error", "error_msg": f"Pairing failed: {e}"})

    async def do_finish_pairing_async(code_str):
        remote = state.get("remote")
        if remote is None:
            return
        try:
            await remote.async_finish_pairing(code_str.strip())
            await remote.async_connect()
            sv = state.get("selected_tv") or {}
            ip = (sv.get("ips") or [None])[0] or sv.get("host", "").rstrip(".") or sv.get("name", "")
            name = sv.get("name", ip)
            paired = _add_paired(ip, name, "")
            set_state(lambda s: {**s, "screen": "remote", "remote": remote, "paired_tvs": paired})
        except Exception as e:
            set_state(lambda s: {**s, "screen": "error", "error_msg": f"Pairing: {e}"})

    async def send_key_async(key_name):
        r = state.get("remote")
        if r is None:
            return
        try:
            r.send_key_command(key_name)
        except Exception:
            set_state(lambda s: {**s, "screen": "error", "error_msg": "Connection lost", "remote": None})

    discover, _ = use_async_call(do_discover_async)
    connect, _ = use_async_call(do_connect_async)
    finish_pairing, _ = use_async_call(do_finish_pairing_async)
    send_key, _ = use_async_call(send_key_async)

    def on_scan(event=None):
        discover()

    def on_tv_select(tv, event=None):
        connect(tv)

    def on_connect_ip(event=None):
        ip = state.get("manual_ip", "").strip()
        if ip:
            connect({"name": ip, "ips": [ip], "host": ip})

    def on_send_key(key_name, event=None):
        send_key(key_name)

    def on_finish_pairing(event=None):
        code = state.get("pairing_code_input", "")
        if code:
            finish_pairing(code)

    def on_pairing_code_change(text):
        set_state(lambda s: {**s, "pairing_code_input": text})

    def disconnect(event=None):
        r = state.get("remote")
        if r:
            r.disconnect()
        set_state(lambda s: {**s, "screen": "tv_list", "remote": None, "selected_tv": None})

    with Window(title="TV Remote", style={"background-color": "#121212", "color": "#eee"}):
        if state["screen"] == "tv_list":
            with VBoxView(style={"margin": 16, "spacing": 10}):
                Label(text="TV Remote", style={"font-size": "24px", "font-weight": "bold", "color": "#eee", "margin-bottom": 4})

                scanning = state.get("scanning", False)
                if scanning:
                    with VBoxView(style={"spacing": 8}):
                        ProgressBar(value=0, min_value=0, max_value=0, style={"min-width": 280, "max-height": 4})
                        Label(text="Scanning for TVs...", style={"color": "#888", "font-size": "13px"})
                    Button(title="Scan for TVs", enabled=False, style=BTN_DISABLED)
                else:
                    Button(title="Scan for TVs", on_click=on_scan, style=BTN_PRIMARY)

                err = state.get("error_msg", "")
                if err:
                    Label(text=err, style={"color": "#aaa", "font-size": "13px"})

                paired_tvs = state.get("paired_tvs", [])
                if paired_tvs:
                    Label(text="Paired TVs", style=SECTION)
                    for ptv in paired_tvs:
                        with VBoxView(style=CARD):
                            Button(
                                title=f"{ptv.get('name', ptv['ip'])}  {ptv['ip']}",
                                on_click=lambda e, p=ptv: on_tv_select({"name": p.get("name", p['ip']), "ips": [p['ip']], "host": p['ip']}),
                                style={**BTN, "text-align": "left", "border": "none", "padding": "8px 0", "min-width": 260},
                            )

                tvs = state.get("tvs", [])
                if tvs:
                    Label(text="Found on network", style=SECTION)
                    for tv in tvs:
                        ips = tv.get("ips", [])
                        ip = ips[0] if ips else tv.get("host", "")
                        with VBoxView(style=CARD):
                            Button(
                                title=f"{tv['name']}  {ip}",
                                on_click=lambda e, t=tv: on_tv_select(t),
                                style={**BTN, "text-align": "left", "border": "none", "padding": "8px 0", "min-width": 260},
                            )

                Label(text="Manual connect", style=SECTION)
                with HBoxView(style={"spacing": 8}):
                    TextInput(
                        text=state.get("manual_ip", ""),
                        placeholder_text="Enter IP address",
                        on_change=lambda t: set_state(lambda s: {**s, "manual_ip": t}),
                        style=INPUT,
                    )
                    Button(title="Connect", on_click=on_connect_ip, style=BTN_PRIMARY)

        elif state["screen"] == "pairing":
            tv_name = (state.get("selected_tv") or {}).get("name", "")
            with VBoxView(style={"margin": 16, "spacing": 12, "align": "center"}):
                Label(text="Pairing", style={"font-size": "20px", "font-weight": "bold"})
                ProgressBar(value=0, min_value=0, max_value=0, style={"min-width": 280, "max-height": 4})
                Label(text=f"Connecting to {tv_name}...", style={"color": "#aaa", "font-size": "13px"})
                Button(title="Cancel", on_click=disconnect, style=BTN)

        elif state["screen"] == "pairing_code":
            tv_name = (state.get("selected_tv") or {}).get("name", "")
            with VBoxView(style={"margin": 16, "spacing": 12}):
                Label(text="Pairing code", style={"font-size": "20px", "font-weight": "bold"})
                Label(text=f"TV: {tv_name}", style={"color": "#aaa", "font-size": "13px"})
                Label(text="Enter the 6-character code shown on your TV:", style={"font-size": "13px", "margin-top": 8})
                TextInput(
                    text=state.get("pairing_code_input", ""),
                    placeholder_text="e.g. A3B7C9",
                    on_change=on_pairing_code_change,
                    style={**INPUT, "font-size": "18px", "letter-spacing": "4px", "text-align": "center", "min-width": 200, "max-width": 200},
                )
                with HBoxView(style={"spacing": 8}):
                    Button(title="Pair", on_click=on_finish_pairing, style=BTN_PRIMARY)
                    Button(title="Cancel", on_click=disconnect, style=BTN)

        elif state["screen"] == "remote":
            tv_name = (state.get("selected_tv") or {}).get("name", "")
            if state.get("remote") is None:
                Label(text="Not connected.")
                Button(title="Back", on_click=disconnect, style=BTN)
            else:
                with VBoxView(style={"margin": 12, "spacing": 2}):
                    with HBoxView(style={"spacing": 8}):
                        Label(text=tv_name, style={"font-size": "16px", "font-weight": "bold"})
                        Label(text="\u25cf Connected", style={"color": "#4caf50", "font-size": "12px"})
                        Button(title="\u2715", on_click=disconnect, style={**BTN_SM, "min-width": 32, "border": "none", "color": "#888"})

                    Label(text="Volume", style=SECTION)
                    with HBoxView(style={"spacing": 6}):
                        Button(title="\u2212", on_click=lambda e: on_send_key("VOLUME_DOWN"), style=BTN_SM)
                        Button(title="\u23FB Mute", on_click=lambda e: on_send_key("VOLUME_MUTE"), style=BTN_SM)
                        Button(title="+", on_click=lambda e: on_send_key("VOLUME_UP"), style=BTN_SM)

                    Label(text="Navigation", style=SECTION)
                    with VBoxView(style={"align": "center", "spacing": 4}):
                        Button(title="\u25B2", on_click=lambda e: on_send_key("DPAD_UP"), style=BTN_DPAD)
                        with HBoxView(style={"spacing": 4}):
                            Button(title="\u25C0", on_click=lambda e: on_send_key("DPAD_LEFT"), style=BTN_DPAD)
                            Button(title="OK", on_click=lambda e: on_send_key("DPAD_CENTER"), style=BTN_OK)
                            Button(title="\u25B6", on_click=lambda e: on_send_key("DPAD_RIGHT"), style=BTN_DPAD)
                        Button(title="\u25BC", on_click=lambda e: on_send_key("DPAD_DOWN"), style=BTN_DPAD)

                    Label(text="Media", style=SECTION)
                    with HBoxView(style={"spacing": 6}):
                        Button(title="\u23EE Prev", on_click=lambda e: on_send_key("MEDIA_PREVIOUS"), style=BTN_SM)
                        Button(title="\u23EF Play/Pause", on_click=lambda e: on_send_key("MEDIA_PLAY_PAUSE"), style=BTN_SM)
                        Button(title="\u23ED Next", on_click=lambda e: on_send_key("MEDIA_NEXT"), style=BTN_SM)

                    Label(text="Actions", style=SECTION)
                    with VBoxView(style={"spacing": 4}):
                        with HBoxView(style={"spacing": 6}):
                            Button(title="\u2190 Back", on_click=lambda e: on_send_key("BACK"), style=BTN_SM)
                            Button(title="\u2302 Home", on_click=lambda e: on_send_key("HOME"), style=BTN_SM)
                            Button(title="\u2630 Menu", on_click=lambda e: on_send_key("MENU"), style=BTN_SM)
                        Button(title="\u23FB Power", on_click=lambda e: on_send_key("POWER"), style={**BTN_DANGER, "min-width": 200})

        elif state["screen"] == "error":
            with VBoxView(style={"margin": 16, "spacing": 12}):
                Label(text="Error", style={"font-size": "20px", "font-weight": "bold", "color": "#d32f2f"})
                Label(text=state.get("error_msg", "Unknown error"), style={"color": "#aaa"})
                Button(title="Back", on_click=disconnect, style=BTN)


def main():
    App(RemoteApp()).start()


if __name__ == "__main__":
    main()
