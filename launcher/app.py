from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "warcontrol.config.json"
EXAMPLE_CONFIG_PATH = ROOT / "warcontrol.config.json.example"
START_SCRIPT = ROOT / "scripts" / "start-warcontrol-v2.ps1"
STOP_SCRIPT = ROOT / "scripts" / "stop-warcontrol.ps1"

COLORS = {
    "bg_base": "#060a0f",
    "bg_panel": "#0a1410",
    "bg_panel_alt": "#0b1721",
    "bg_button": "#102433",
    "bg_button_hover": "#173247",
    "border": "#1e3a2a",
    "text_primary": "#c8d0c0",
    "text_muted": "#3a5a40",
    "accent_live": "#44ff88",
    "accent_warn": "#ffaa00",
    "accent_danger": "#ff4444",
}

LAUNCHER_SCHEMES = [
    "minecraft://",
    "shell:AppsFolder\\Microsoft.4297127D64EC6_8wekyb3d8bbwe!Minecraft",
]

DEFAULT_CONFIG = {
    "server": "NationGlory",
    "source": "",
    "edition": "auto",
    "logPath": "",
    "mode": "live",
    "openBrowser": True,
    "dashboardUrl": "http://127.0.0.1:3000",
    "apiUrl": "http://127.0.0.1:8000",
    "minecraftLauncherPath": "",
}


def _load_config() -> dict[str, object]:
    if not CONFIG_PATH.exists() and EXAMPLE_CONFIG_PATH.exists():
        CONFIG_PATH.write_text(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    if not CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_CONFIG)
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def _save_config(config: dict[str, object]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _python_command() -> list[str]:
    venv_python = ROOT / "api" / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return [str(venv_python)]
    return [sys.executable]


def _powershell_command(script_path: Path, *extra_args: str) -> list[str]:
    return [
        "powershell.exe",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        *extra_args,
    ]


def _minecraft_path_candidates(config_path: str) -> list[str]:
    candidates: list[str] = []
    if config_path:
        candidates.append(config_path)
    local_appdata = os.getenv("LOCALAPPDATA", "")
    program_files = os.getenv("ProgramFiles", r"C:\Program Files")
    program_files_x86 = os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)")
    exe_candidates = [
        Path(local_appdata) / "Programs" / "Minecraft Launcher" / "MinecraftLauncher.exe",
        Path(program_files) / "Minecraft Launcher" / "MinecraftLauncher.exe",
        Path(program_files_x86) / "Minecraft Launcher" / "MinecraftLauncher.exe",
        Path(local_appdata) / "Microsoft" / "WindowsApps" / "MinecraftLauncher.exe",
    ]
    for candidate in exe_candidates:
        if candidate.exists():
            candidates.append(str(candidate))
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _detect_minecraft_launcher_path(config_path: str) -> str:
    candidates = _minecraft_path_candidates(config_path)
    return candidates[0] if candidates else ""


def _detect_log_path(config_path: str) -> str:
    candidates: list[str] = []
    if config_path:
        candidates.append(config_path)
    appdata = os.getenv("APPDATA", "")
    local_appdata = os.getenv("LOCALAPPDATA", "")
    if appdata:
        candidates.append(str(Path(appdata) / ".minecraft" / "logs" / "latest.log"))
        candidates.append(str(Path(appdata) / "Minecraft Bedrock" / "logs" / "latest.log"))
    if local_appdata:
        candidates.append(
            str(
                Path(local_appdata)
                / "Packages"
                / "Microsoft.MinecraftUWP_8wekyb3d8bbwe"
                / "LocalState"
                / "logs"
                / "latest.log"
            )
        )
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return candidates[0] if candidates else ""


def _launch_minecraft(config_path: str) -> tuple[bool, str]:
    for candidate in _minecraft_path_candidates(config_path):
        try:
            os.startfile(candidate)
            return True, f"Minecraft launcher started: {Path(candidate).name}"
        except OSError:
            continue
    for scheme in LAUNCHER_SCHEMES:
        try:
            os.startfile(scheme)
            return True, "Minecraft launcher requested."
        except OSError:
            continue
    return False, "Minecraft launcher not detected."


def _url_is_alive(url: str) -> bool:
    try:
        with urlopen(url, timeout=2) as response:
            return 200 <= response.status < 400
    except (OSError, URLError, ValueError):
        return False


class LauncherApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("WarControl Launcher")
        self.root.geometry("980x720")
        self.root.minsize(920, 680)
        self.root.configure(bg=COLORS["bg_base"])

        self.config = _load_config()
        self.status_var = tk.StringVar(value="Ready")
        self.api_var = tk.StringVar(value="API: offline")
        self.web_var = tk.StringVar(value="Dashboard: offline")
        self.collect_var = tk.StringVar(value="Collector: standby")
        self.minecraft_var = tk.StringVar(value="Minecraft: not detected")

        self._build_ui()
        self._refresh_minecraft_detection()
        self._refresh_status()

    def _build_ui(self) -> None:
        container = tk.Frame(self.root, bg=COLORS["bg_base"], padx=22, pady=22)
        container.pack(fill="both", expand=True)

        header = tk.Frame(container, bg=COLORS["bg_base"])
        header.pack(fill="x", pady=(0, 16))

        left_header = tk.Frame(header, bg=COLORS["bg_base"])
        left_header.pack(side="left", anchor="w")
        tk.Label(
            left_header,
            text="▶ WARCONTROL",
            fg=COLORS["accent_live"],
            bg=COLORS["bg_base"],
            font=("Consolas", 26, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left_header,
            text="Launcher desktop commission - controle local, surveillance et dashboard",
            fg=COLORS["text_muted"],
            bg=COLORS["bg_base"],
            font=("Consolas", 10),
        ).pack(anchor="w", pady=(4, 0))

        right_header = tk.Frame(header, bg=COLORS["bg_base"])
        right_header.pack(side="right", anchor="e")
        tk.Label(
            right_header,
            text="NATIONSGLORY",
            fg=COLORS["text_primary"],
            bg=COLORS["bg_base"],
            font=("Consolas", 12, "bold"),
        ).pack(anchor="e")
        tk.Label(
            right_header,
            text="one-click local control",
            fg=COLORS["text_muted"],
            bg=COLORS["bg_base"],
            font=("Consolas", 9),
        ).pack(anchor="e", pady=(4, 0))

        status_grid = tk.Frame(container, bg=COLORS["bg_base"])
        status_grid.pack(fill="x", pady=(0, 18))
        self.status_cards: list[tuple[tk.Label, tk.StringVar]] = []
        for idx, (title, variable) in enumerate(
            [
                ("SYSTEM", self.status_var),
                ("API", self.api_var),
                ("DASHBOARD", self.web_var),
                ("COLLECTOR", self.collect_var),
                ("MINECRAFT", self.minecraft_var),
            ]
        ):
            card = tk.Frame(
                status_grid,
                bg=COLORS["bg_panel"],
                bd=1,
                relief="solid",
                highlightbackground=COLORS["border"],
                highlightcolor=COLORS["border"],
                highlightthickness=1,
                padx=14,
                pady=12,
            )
            card.grid(row=0, column=idx, sticky="nsew", padx=(0 if idx == 0 else 8, 0))
            status_grid.grid_columnconfigure(idx, weight=1)
            tk.Label(
                card,
                text=title,
                fg=COLORS["text_muted"],
                bg=COLORS["bg_panel"],
                font=("Consolas", 9, "bold"),
            ).pack(anchor="w")
            value = tk.Label(
                card,
                textvariable=variable,
                fg=COLORS["text_primary"],
                bg=COLORS["bg_panel"],
                font=("Consolas", 12, "bold"),
                pady=6,
            )
            value.pack(anchor="w")
            self.status_cards.append((value, variable))

        content = tk.Frame(container, bg=COLORS["bg_base"])
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        left_panel = tk.Frame(
            content,
            bg=COLORS["bg_panel"],
            bd=1,
            relief="solid",
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border"],
            highlightthickness=1,
            padx=18,
            pady=18,
        )
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        tk.Label(
            left_panel,
            text="CONFIGURATION",
            fg=COLORS["accent_live"],
            bg=COLORS["bg_panel"],
            font=("Consolas", 14, "bold"),
        ).pack(anchor="w", pady=(0, 14))

        form = tk.Frame(left_panel, bg=COLORS["bg_panel"])
        form.pack(fill="x")

        self.server_var = tk.StringVar(value=str(self.config.get("server", "")))
        self.source_var = tk.StringVar(value=str(self.config.get("source", "")))
        self.log_path_var = tk.StringVar(value=str(self.config.get("logPath", "")))
        self.minecraft_path_var = tk.StringVar(value=str(self.config.get("minecraftLauncherPath", "")))
        self.mode_var = tk.StringVar(value=str(self.config.get("mode", "live")))
        self.open_browser_var = tk.BooleanVar(value=bool(self.config.get("openBrowser", True)))

        self._add_field(form, "Server", self.server_var, 0)
        self._add_field(form, "Source", self.source_var, 1)
        self._add_field(form, "Log Path", self.log_path_var, 2)
        self._add_field(form, "Minecraft Path", self.minecraft_path_var, 3)

        self.minecraft_hint_var = tk.StringVar(value="Launcher status: checking...")
        tk.Label(
            form,
            textvariable=self.minecraft_hint_var,
            fg=COLORS["text_muted"],
            bg=COLORS["bg_panel"],
            font=("Consolas", 9),
        ).grid(row=4, column=1, sticky="w", pady=(2, 8))

        options = tk.Frame(form, bg=COLORS["bg_panel"])
        options.grid(row=5, column=0, columnspan=2, sticky="we", pady=(12, 0))

        tk.Label(options, text="Mode", fg=COLORS["text_primary"], bg=COLORS["bg_panel"], font=("Consolas", 10, "bold")).pack(side="left")
        tk.Radiobutton(
            options,
            text="Live",
            value="live",
            variable=self.mode_var,
            bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_panel_alt"],
            activebackground=COLORS["bg_panel"],
            activeforeground=COLORS["text_primary"],
        ).pack(side="left", padx=(12, 4))
        tk.Radiobutton(
            options,
            text="Demo",
            value="demo",
            variable=self.mode_var,
            bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_panel_alt"],
            activebackground=COLORS["bg_panel"],
            activeforeground=COLORS["text_primary"],
        ).pack(side="left", padx=4)
        tk.Checkbutton(
            options,
            text="Open dashboard automatically",
            variable=self.open_browser_var,
            bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"],
            selectcolor=COLORS["bg_panel_alt"],
            activebackground=COLORS["bg_panel"],
            activeforeground=COLORS["text_primary"],
        ).pack(side="left", padx=(18, 0))

        button_bar = tk.Frame(left_panel, bg=COLORS["bg_panel"])
        button_bar.pack(fill="x", pady=(18, 0))

        self._add_button(button_bar, "Save Config", self.save_config)
        self._add_button(button_bar, "Detect Automatically", self.detect_automatically)
        self._add_button(button_bar, "Start All", self.start_warcontrol)
        self._add_button(button_bar, "Stop WarControl", self.stop_warcontrol)
        self._add_button(button_bar, "Open Dashboard", self.open_dashboard)
        self._add_button(button_bar, "Launch Minecraft", self.launch_minecraft)

        right_panel = tk.Frame(
            content,
            bg=COLORS["bg_panel_alt"],
            bd=1,
            relief="solid",
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["border"],
            highlightthickness=1,
            padx=18,
            pady=18,
        )
        right_panel.grid(row=0, column=1, sticky="nsew")

        tk.Label(
            right_panel,
            text="OPERATIONS",
            fg=COLORS["accent_warn"],
            bg=COLORS["bg_panel_alt"],
            font=("Consolas", 14, "bold"),
        ).pack(anchor="w", pady=(0, 14))

        tip = tk.Label(
            right_panel,
            text="Flow recommande\n\n1. Save Config\n2. Start WarControl\n3. Launch Minecraft\n4. Rejoindre NationGlory\n5. Observer le dashboard",
            justify="left",
            fg=COLORS["text_primary"],
            bg=COLORS["bg_panel_alt"],
            font=("Consolas", 10),
        )
        tip.pack(anchor="w", fill="x")

        help_box = tk.Text(
            right_panel,
            height=16,
            bg=COLORS["bg_panel"],
            fg=COLORS["text_primary"],
            insertbackground=COLORS["text_primary"],
            relief="solid",
            bd=1,
            font=("Consolas", 10),
            wrap="word",
        )
        help_box.pack(fill="both", expand=True, pady=(16, 0))
        help_box.insert(
            "1.0",
            "Flow client recommande :\n"
            "1. Verifie ou ajuste la configuration.\n"
            "2. Clique sur 'Start WarControl'.\n"
            "3. Clique sur 'Launch Minecraft'.\n"
            "4. Rejoins NationGlory.\n"
            "5. Le dashboard se met a jour automatiquement.\n\n"
            "Mode demo sert a presenter le produit sans dependre des logs Minecraft.\n"
            "Le champ 'Minecraft Path' est optionnel et permet de forcer un launcher custom.\n",
        )
        help_box.configure(state="disabled")

    def _add_field(self, parent: tk.Widget, label: str, variable: tk.StringVar, row: int) -> None:
        tk.Label(
            parent,
            text=label,
            fg=COLORS["text_primary"],
            bg=COLORS["bg_panel"],
            font=("Consolas", 10, "bold"),
        ).grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        tk.Entry(
            parent,
            textvariable=variable,
            bg=COLORS["bg_panel_alt"],
            fg=COLORS["text_primary"],
            insertbackground=COLORS["text_primary"],
            relief="solid",
            bd=1,
            font=("Consolas", 10),
            width=72,
        ).grid(row=row, column=1, sticky="we", pady=6)
        parent.grid_columnconfigure(1, weight=1)

    def _add_button(self, parent: tk.Widget, text: str, command) -> None:
        tk.Button(
            parent,
            text=text,
            command=command,
            bg=COLORS["bg_button"],
            fg=COLORS["text_primary"],
            activebackground=COLORS["bg_button_hover"],
            activeforeground="#ffffff",
            relief="flat",
            padx=14,
            pady=10,
            font=("Consolas", 10, "bold"),
        ).pack(side="left", padx=(0, 10))

    def _collect_config(self) -> dict[str, object]:
        return {
            "server": self.server_var.get().strip() or "NationGlory",
            "source": self.source_var.get().strip(),
            "edition": str(self.config.get("edition", "auto")),
            "logPath": self.log_path_var.get().strip(),
            "mode": self.mode_var.get(),
            "openBrowser": bool(self.open_browser_var.get()),
            "dashboardUrl": str(self.config.get("dashboardUrl", "http://127.0.0.1:3000")),
            "apiUrl": str(self.config.get("apiUrl", "http://127.0.0.1:8000")),
            "minecraftLauncherPath": self.minecraft_path_var.get().strip(),
        }

    def save_config(self) -> None:
        self.config = self._collect_config()
        _save_config(self.config)
        self.status_var.set("Config saved.")
        self._refresh_minecraft_detection()

    def detect_automatically(self) -> None:
        minecraft_path = _detect_minecraft_launcher_path(self.minecraft_path_var.get().strip())
        log_path = _detect_log_path(self.log_path_var.get().strip())
        if minecraft_path:
            self.minecraft_path_var.set(minecraft_path)
        if log_path:
            self.log_path_var.set(log_path)
        self.save_config()
        detected = []
        if minecraft_path:
            detected.append("launcher")
        if log_path:
            detected.append("log path")
        self.status_var.set(
            f"Auto-detect done: {', '.join(detected)}." if detected else "Auto-detect found no local path."
        )
        self._refresh_minecraft_detection()

    def start_warcontrol(self) -> None:
        self.save_config()
        args = [
            "-Mode",
            str(self.config["mode"]),
        ]
        if bool(self.config["openBrowser"]):
            args.append("-OpenBrowser")
        if self.config["logPath"]:
            args.extend(["-LogPath", str(self.config["logPath"])])
        if self.config["server"]:
            args.extend(["-Server", str(self.config["server"])])
        if self.config["source"]:
            args.extend(["-Source", str(self.config["source"])])
        subprocess.Popen(_powershell_command(START_SCRIPT, *args), cwd=ROOT)
        launch_ok, launch_message = _launch_minecraft(str(self.config.get("minecraftLauncherPath", "")))
        self.status_var.set("WarControl starting... " + launch_message)
        if not launch_ok:
            self.status_var.set("WarControl starting... Minecraft launcher not found.")
        self._refresh_minecraft_detection()
        self.root.after(2500, self._refresh_status)

    def stop_warcontrol(self) -> None:
        subprocess.Popen(_powershell_command(STOP_SCRIPT), cwd=ROOT)
        self.status_var.set("Stop signal sent.")
        self.root.after(1500, self._refresh_status)

    def open_dashboard(self) -> None:
        webbrowser.open(str(self.config.get("dashboardUrl", "http://127.0.0.1:3000")))

    def launch_minecraft(self) -> None:
        self.save_config()
        ok, message = _launch_minecraft(str(self.config.get("minecraftLauncherPath", "")))
        self.status_var.set(message)
        if not ok:
            messagebox.showerror("WarControl", message)
        self._refresh_minecraft_detection()

    def _refresh_minecraft_detection(self) -> None:
        detected_path = _detect_minecraft_launcher_path(self.minecraft_path_var.get().strip())
        if detected_path:
            self.minecraft_var.set("Minecraft: detected")
            self.minecraft_hint_var.set(f"Launcher status: detected - {detected_path}")
        else:
            self.minecraft_var.set("Minecraft: not detected")
            self.minecraft_hint_var.set("Launcher status: not detected - use Detect Automatically or set a path.")

    def _refresh_status(self) -> None:
        def worker() -> None:
            api_ok = _url_is_alive(str(self.config.get("apiUrl", "http://127.0.0.1:8000")) + "/health")
            web_ok = _url_is_alive(str(self.config.get("dashboardUrl", "http://127.0.0.1:3000")))
            self.root.after(0, lambda: self._apply_status(api_ok, web_ok))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(5000, self._refresh_status)

    def _apply_status(self, api_ok: bool, web_ok: bool) -> None:
        collector_text = "Collector: live" if api_ok else "Collector: standby"
        self.collect_var.set(collector_text)
        self.api_var.set(f"API: {'online' if api_ok else 'offline'}")
        self.web_var.set(f"Dashboard: {'online' if web_ok else 'offline'}")
        if api_ok and web_ok:
            self.status_var.set("WarControl ready.")
        elif api_ok or web_ok:
            self.status_var.set("WarControl partially online.")
        else:
            self.status_var.set("WarControl idle.")

        palette = {
            True: COLORS["accent_live"],
            False: COLORS["accent_danger"],
        }
        states = [
            (self.status_cards[0][0], api_ok and web_ok),
            (self.status_cards[1][0], api_ok),
            (self.status_cards[2][0], web_ok),
            (self.status_cards[3][0], api_ok),
            (self.status_cards[4][0], self.minecraft_var.get().endswith("detected")),
        ]
        for label, ok in states:
            label.configure(fg=palette[ok])

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    app = LauncherApp()
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
