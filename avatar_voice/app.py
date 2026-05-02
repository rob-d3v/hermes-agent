"""
avatar_voice — Desktop App
Setup, controle e chat numa janela compacta.

Uso: python app.py
"""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import filedialog

try:
    import winreg as _winreg
    _WIN = True
except ImportError:
    _WIN = False

import customtkinter as ctk
import requests
import yaml

# ── Tema ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BASE    = "#1e1e2e"
SURFACE = "#181825"
OVERLAY = "#313244"
MUTED   = "#45475a"
TEXT    = "#cdd6f4"
SUBTEXT = "#a6adc8"
BLUE    = "#89b4fa"
GREEN   = "#a6e3a1"
RED     = "#f38ba8"
YELLOW  = "#f9e2af"
MAUVE   = "#cba6f7"
TEAL    = "#94e2d5"

STATE_COLOR = {
    "SLEEPING":   "#585b70",
    "GREETING":   MAUVE,
    "LISTENING":  GREEN,
    "WAITING":    YELLOW,
    "PROCESSING": BLUE,
    "RESPONDING": TEAL,
    "FOLLOWUP":   GREEN,
    "STARTING":   YELLOW,
    "STOPPED":    "#585b70",
}

PROVIDER_PRESETS = {
    "ollama":     ("mascote",           "ollama",                           "http://localhost:11434/v1"),
    "openai":     ("gpt-4o-mini",       "",                                 "https://api.openai.com/v1"),
    "hermes":     ("hermes-agent",      "aa6531e6c0db6b2fba53bb133fac2e0a", "http://localhost:8642/v1"),
    "openrouter": ("openai/gpt-4o-mini","",                                 "https://openrouter.ai/api/v1"),
}

def _app_dir() -> Path:
    """Diretório de dados do usuário: junto ao .exe quando frozen, junto ao app.py em dev."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

CONFIG_PATH = _app_dir() / "config.yaml"

DEFAULT_SYSTEM = (
    "Você é um mascote de stream e sem filtro.\n"
    "Você fala com sotaque de Goiás, usa expressões como 'uai', 'trem', 'anêim', "
    "'tá doido' e 'mô do céu'.\n"
    "Suas respostas devem ser curtas (máximo 2 frases) para o TTS não demorar.\n"
    "Seja engraçado, meio sarcástico e trate o pessoal da stream como se fosse "
    "todo mundo de casa."
)


# ── App ───────────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("avatar_voice")
        self.geometry("500x740")
        self.minsize(460, 600)
        self.configure(fg_color=SURFACE)

        self._cfg     = self._load_config()
        self._proc    = None
        self._running = False
        self._evq     = queue.Queue()

        self._build()
        self._apply_config()
        self.after(120, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if "--autostart" in sys.argv:
            self.after(2000, self._start)

    # ── Config I/O ────────────────────────────────────────────────────────────
    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _write_config(self, cfg: dict):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # ── UI Build ──────────────────────────────────────────────────────────────
    def _build(self):
        # ── Header
        hdr = ctk.CTkFrame(self, fg_color="#11111b", corner_radius=0, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="avatar_voice",
                     font=("Courier New", 14, "bold"), text_color=BLUE
                     ).pack(side="left", padx=18, pady=10)
        self._badge = ctk.CTkLabel(hdr, text="○  STOPPED",
                                   font=("Courier New", 11), text_color=MUTED)
        self._badge.pack(side="right", padx=18)
        self._prov_lbl = ctk.CTkLabel(hdr, text="",
                                      font=("Courier New", 10), text_color=SUBTEXT)
        self._prov_lbl.pack(side="right", padx=(0, 6))

        # ── Tabs
        self._tabs = ctk.CTkTabview(
            self, fg_color=BASE,
            segmented_button_fg_color=OVERLAY,
            segmented_button_selected_color=BLUE,
            segmented_button_selected_hover_color="#7ba4f5",
            segmented_button_unselected_hover_color=MUTED,
            border_width=0,
        )
        self._tabs.pack(fill="both", expand=True, padx=0, pady=0)
        for name in ("Setup", "Monitor", "Chat"):
            self._tabs.add(name)

        self._build_setup(self._tabs.tab("Setup"))
        self._build_monitor(self._tabs.tab("Monitor"))
        self._build_chat(self._tabs.tab("Chat"))

        # ── Bottom bar
        bar = ctk.CTkFrame(self, fg_color="#11111b", corner_radius=0, height=58)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self._save_btn = ctk.CTkButton(
            bar, text="Save", width=80, height=36, corner_radius=8,
            font=("Courier New", 11), fg_color=OVERLAY, hover_color=MUTED,
            text_color=TEXT, command=self._save_from_ui,
        )
        self._save_btn.pack(side="right", padx=(0, 12), pady=11)

        self._start_btn = ctk.CTkButton(
            bar, text="▶  Start", width=130, height=36, corner_radius=8,
            font=("Courier New", 12, "bold"), fg_color=GREEN,
            hover_color="#94d3a2", text_color="#1e1e2e",
            command=self._toggle,
        )
        self._start_btn.pack(side="right", padx=(12, 6), pady=11)

    # ── Setup tab ─────────────────────────────────────────────────────────────
    def _build_setup(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color=BASE, scrollbar_button_color=MUTED)
        scroll.pack(fill="both", expand=True)

        # Provider
        self._prov_var = ctk.StringVar(value="ollama")
        s = self._card(scroll, "PROVIDER")
        self._prov_seg = ctk.CTkSegmentedButton(
            s, values=["ollama", "openai", "hermes", "openrouter"],
            variable=self._prov_var, font=("Courier New", 11),
            selected_color=BLUE, selected_hover_color="#7ba4f5",
            unselected_color=OVERLAY, unselected_hover_color=MUTED,
            fg_color=OVERLAY, command=self._on_provider,
        )
        self._prov_seg.pack(fill="x", pady=(2, 6))
        self._model_e  = self._row(s, "Model")
        self._apikey_e = self._row(s, "API Key", show="*")
        self._url_e    = self._row(s, "URL")

        # Mascote (Ollama Modelfile) — only shown for ollama provider
        sm = self._card(scroll, "MASCOTE  (Ollama Modelfile)")
        self._mascote_card = sm.master
        r  = self._hrow(sm)
        self._mf_base_e = self._labeled(r, "Base", width=110)
        self._mf_base_e.insert(0, "gemma2:2b")
        self._mf_name_e = self._labeled(r, "Nome", width=85)
        self._mf_name_e.insert(0, "mascote")
        r2 = self._hrow(sm)
        self._mf_temp_lbl, self._mf_temp_sl = self._slider(
            r2, "Temp", 0.1, 2.0, 19, 0.9, fmt=lambda v: f"{v:.1f}")
        ctk.CTkLabel(sm, text="System prompt:", font=("Courier New", 9),
                     text_color=MUTED).pack(anchor="w", pady=(6, 1))
        self._mf_sys = ctk.CTkTextbox(
            sm, height=88, font=("Courier New", 10), fg_color=SURFACE,
            text_color=TEXT, wrap="word", border_color=MUTED,
            border_width=1, corner_radius=6)
        self._mf_sys.pack(fill="x", pady=(0, 6))
        self._mf_sys.insert("1.0", DEFAULT_SYSTEM)
        r3 = self._hrow(sm)
        ctk.CTkButton(r3, text="Salvar .mf", width=100, height=28,
                      corner_radius=6, font=("Courier New", 10),
                      fg_color=OVERLAY, hover_color=MUTED, text_color=TEXT,
                      command=self._save_modelfile).pack(side="left", padx=(0, 8))
        ctk.CTkButton(r3, text="Criar no Ollama", width=130, height=28,
                      corner_radius=6, font=("Courier New", 10, "bold"),
                      fg_color=MAUVE, hover_color="#b994e8", text_color="#1e1e2e",
                      command=self._create_mascote).pack(side="left")

        # Whisper STT
        s2 = self._card(scroll, "WHISPER  (STT)")
        self._whisper_card = s2.master
        r = self._hrow(s2)
        self._whisper_cb = self._combo(r, ["tiny","base","small","medium","large-v3"], w=130)
        self._lang_e     = self._labeled(r, "Lang", width=44)
        self._stt_dev_cb = self._combo(self._hrow(s2, label="Device"), ["auto","cpu","cuda"], w=90)

        # Piper TTS
        s3 = self._card(scroll, "PIPER  (TTS)")
        r = self._hrow(s3, label="Voice")
        self._tts_e = ctk.CTkEntry(r, font=("Courier New", 10), height=28, corner_radius=6,
                                    fg_color=OVERLAY, border_color=MUTED, text_color=TEXT)
        self._tts_e.pack(side="left", fill="x", expand=True, padx=(4, 4))
        ctk.CTkButton(r, text="…", width=28, height=28, corner_radius=6,
                      fg_color=SURFACE, hover_color=MUTED,
                      command=lambda: self._browse(self._tts_e, "*.onnx")).pack(side="left")

        r2 = self._hrow(s3)
        self._speed_lbl, self._speed_sl = self._slider(r2, "Speed", 0.5, 2.0, 30, 0.95,
                                                         fmt=lambda v: f"{v:.2f}")
        self._pitch_lbl, self._pitch_sl = self._slider(r2, "Pitch", -6, 6, 12, 0,
                                                         fmt=lambda v: f"{int(v):+d}", pad=12)

        r3 = self._hrow(s3, label="Test")
        self._tts_test_e = ctk.CTkEntry(
            r3, font=("Courier New", 10), height=28, corner_radius=6,
            fg_color=OVERLAY, border_color=MUTED, text_color=TEXT,
            placeholder_text="Frase para testar o Piper…",
        )
        self._tts_test_e.pack(side="left", fill="x", expand=True, padx=(4, 4))
        self._tts_test_e.insert(0, "Uai, ocê tá me ouvindo bem, sô?")
        self._tts_btn = ctk.CTkButton(
            r3, text="▶", width=32, height=28, corner_radius=6,
            font=("Courier New", 11, "bold"),
            fg_color=TEAL, hover_color="#7ecfc3", text_color="#1e1e2e",
            command=self._tts_test,
        )
        self._tts_btn.pack(side="left")

        # Wake Word
        s4 = self._card(scroll, "WAKE WORD")
        r = self._hrow(s4, label="Model")
        self._ww_e = ctk.CTkEntry(r, font=("Courier New", 10), height=28, corner_radius=6,
                                   fg_color=OVERLAY, border_color=MUTED, text_color=TEXT)
        self._ww_e.pack(side="left", fill="x", expand=True, padx=(4, 4))
        ctk.CTkButton(r, text="…", width=28, height=28, corner_radius=6,
                      fg_color=SURFACE, hover_color=MUTED,
                      command=lambda: self._browse(self._ww_e, "*.onnx")).pack(side="left")

        r2 = self._hrow(s4)
        self._thresh_lbl, self._thresh_sl = self._slider(r2, "Threshold", 0.1, 0.99, 18, 0.5,
                                                          fmt=lambda v: f"{v:.2f}")
        self._kb_var = ctk.BooleanVar()
        ctk.CTkCheckBox(r2, text="Keyboard fallback", variable=self._kb_var,
                        font=("Courier New", 10), text_color=SUBTEXT,
                        checkbox_width=16, checkbox_height=16,
                        fg_color=BLUE, border_color=MUTED,
                        checkmark_color="#1e1e2e"
                        ).pack(side="left", padx=(14, 0))

        # Audio Devices
        s5 = self._card(scroll, "AUDIO")
        self._audio_devs = self._audio_devices()
        self._mic_cb = self._combo(self._hrow(s5, label="Mic"),    ["Default"] + self._audio_devs)
        self._out_cb = self._combo(self._hrow(s5, label="Output"), ["Default"] + self._audio_devs)

        # Sistema
        s6 = self._card(scroll, "SISTEMA")
        self._startup_var = ctk.BooleanVar(value=self._startup_enabled())
        ctk.CTkCheckBox(
            s6, text="Iniciar com o Windows", variable=self._startup_var,
            font=("Courier New", 10), text_color=SUBTEXT,
            checkbox_width=16, checkbox_height=16,
            fg_color=BLUE, border_color=MUTED, checkmark_color="#1e1e2e",
            command=self._apply_startup,
            state="normal" if _WIN else "disabled",
        ).pack(anchor="w", pady=(2, 4))

    # ── Monitor tab ───────────────────────────────────────────────────────────
    def _build_monitor(self, parent):
        self._log = ctk.CTkTextbox(
            parent, font=("Courier New", 10), fg_color=BASE,
            text_color=SUBTEXT, wrap="word", activate_scrollbars=True,
        )
        self._log.pack(fill="both", expand=True, padx=8, pady=8)
        self._log.configure(state="disabled")

    # ── Chat tab ──────────────────────────────────────────────────────────────
    def _build_chat(self, parent):
        self._chat = ctk.CTkTextbox(
            parent, font=("Courier New", 11), fg_color=BASE,
            text_color=TEXT, wrap="word", activate_scrollbars=True,
        )
        self._chat.pack(fill="both", expand=True, padx=8, pady=(8, 4))
        self._chat.configure(state="disabled")
        self._chat.tag_config("user",    foreground=GREEN)
        self._chat.tag_config("avatar",   foreground=BLUE)
        self._chat.tag_config("inject",  foreground=YELLOW)
        self._chat.tag_config("dim",     foreground=MUTED)

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=8, pady=(0, 8))
        self._msg_e = ctk.CTkEntry(row, font=("Courier New", 11), height=34,
                                    corner_radius=8, fg_color=OVERLAY,
                                    border_color=MUTED, text_color=TEXT,
                                    placeholder_text="Injetar mensagem (bypassa wake word)…")
        self._msg_e.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._msg_e.bind("<Return>", lambda _: self._send())
        ctk.CTkButton(row, text="Send", width=70, height=34, corner_radius=8,
                      font=("Courier New", 11, "bold"),
                      fg_color=BLUE, hover_color="#7ba4f5", text_color="#1e1e2e",
                      command=self._send).pack(side="left")

    # ── UI helpers ────────────────────────────────────────────────────────────
    def _card(self, parent, title: str) -> ctk.CTkFrame:
        wrap = ctk.CTkFrame(parent, fg_color=OVERLAY, corner_radius=10)
        wrap.pack(fill="x", padx=10, pady=(6, 0))
        ctk.CTkLabel(wrap, text=title, font=("Courier New", 9, "bold"),
                     text_color=MUTED).pack(anchor="w", padx=10, pady=(6, 0))
        inner = ctk.CTkFrame(wrap, fg_color="transparent")
        inner.pack(fill="x", padx=8, pady=(2, 8))
        return inner

    def _row(self, parent, label: str, show: str = "") -> ctk.CTkEntry:
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", pady=(3, 0))
        ctk.CTkLabel(r, text=label, font=("Courier New", 10),
                     text_color=SUBTEXT, width=52, anchor="w").pack(side="left")
        e = ctk.CTkEntry(r, font=("Courier New", 11), height=28, corner_radius=6,
                         fg_color=SURFACE, border_color=MUTED, text_color=TEXT,
                         show=show)
        e.pack(side="left", fill="x", expand=True, padx=(4, 0))
        return e

    def _hrow(self, parent, label: str = "") -> ctk.CTkFrame:
        r = ctk.CTkFrame(parent, fg_color="transparent")
        r.pack(fill="x", pady=(3, 0))
        if label:
            ctk.CTkLabel(r, text=label, font=("Courier New", 10),
                         text_color=SUBTEXT, width=52, anchor="w").pack(side="left")
        return r

    def _labeled(self, parent, label: str, width: int = 60) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, font=("Courier New", 10),
                     text_color=SUBTEXT).pack(side="left", padx=(8, 2))
        e = ctk.CTkEntry(parent, font=("Courier New", 11), height=28,
                          corner_radius=6, fg_color=SURFACE, border_color=MUTED,
                          text_color=TEXT, width=width)
        e.pack(side="left")
        return e

    def _combo(self, parent, values: list, w: int = 0) -> ctk.CTkComboBox:
        kw = {"width": w} if w else {}
        c = ctk.CTkComboBox(parent, values=values, font=("Courier New", 10),
                             height=28, corner_radius=6, fg_color=SURFACE,
                             border_color=MUTED, button_color=MUTED,
                             dropdown_fg_color=OVERLAY, text_color=TEXT, **kw)
        c.pack(side="left", padx=(4, 0))
        return c

    def _slider(self, parent, label: str, lo, hi, steps, default,
                fmt, pad: int = 0):
        if pad:
            ctk.CTkFrame(parent, fg_color="transparent", width=pad
                         ).pack(side="left")
        ctk.CTkLabel(parent, text=label, font=("Courier New", 10),
                     text_color=SUBTEXT).pack(side="left", padx=(4, 2))
        lbl = ctk.CTkLabel(parent, text=fmt(default), font=("Courier New", 10),
                            text_color=TEXT, width=32)
        sl  = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps,
                             width=100, height=16, button_color=BLUE,
                             button_hover_color="#7ba4f5", progress_color=BLUE,
                             fg_color=MUTED,
                             command=lambda v, l=lbl, f=fmt: l.configure(text=f(v)))
        sl.set(default)
        sl.pack(side="left", padx=(0, 4))
        lbl.pack(side="left")
        return lbl, sl

    def _browse(self, entry: ctk.CTkEntry, pattern: str):
        path = filedialog.askopenfilename(
            filetypes=[(pattern.replace("*","Model"), pattern), ("All","*.*")])
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _audio_devices(self) -> list:
        try:
            import sounddevice as sd
            return [f"{i}: {d['name']}" for i, d in enumerate(sd.query_devices())]
        except Exception:
            return []

    # ── Config sync ───────────────────────────────────────────────────────────
    def _apply_config(self):
        cfg   = self._cfg
        agent = cfg.get("agent", {})
        stt   = cfg.get("stt", {})
        tts   = cfg.get("tts", {})
        ww    = cfg.get("wake_word", {})

        url = agent.get("base_url", "http://localhost:11434/v1")
        prov = ("openai" if "openai.com" in url else
                "hermes" if "8642" in url else
                "openrouter" if "openrouter" in url else "ollama")
        self._prov_var.set(prov)

        self._set_entry(self._model_e,  agent.get("model",   "mascote"))
        self._set_entry(self._apikey_e, agent.get("api_key", ""))
        self._set_entry(self._url_e,    url)

        self._whisper_cb.set(stt.get("model", "small"))
        self._set_entry(self._lang_e, stt.get("language", "pt"))
        self._stt_dev_cb.set(stt.get("device", "auto"))

        self._set_entry(self._tts_e, tts.get("model_path","../piper_models/nanda_ptbr.onnx"))
        spd = tts.get("length_scale", 0.95)
        self._speed_sl.set(spd); self._speed_lbl.configure(text=f"{spd:.2f}")
        pit = tts.get("pitch_semitones", 0)
        self._pitch_sl.set(pit); self._pitch_lbl.configure(text=f"{int(pit):+d}")

        self._set_entry(self._ww_e, ww.get("model_path","../wake_word_models/central.onnx"))
        thr = ww.get("threshold", 0.5)
        self._thresh_sl.set(thr); self._thresh_lbl.configure(text=f"{thr:.2f}")
        self._kb_var.set(ww.get("fallback_mode") == "keyboard")

        audio = cfg.get("audio", {})
        self._restore_device(self._mic_cb, audio.get("input_device"))
        self._restore_device(self._out_cb, audio.get("output_device"))
        self._update_prov_label()
        self._toggle_mascote_card(prov == "ollama")

    def _do_save(self):
        cfg = self._cfg
        for sec in ("agent","stt","tts","wake_word","audio"):
            cfg.setdefault(sec, {})

        cfg["agent"].update({
            "base_url":    self._url_e.get().strip(),
            "model":       self._model_e.get().strip(),
        })
        key = self._apikey_e.get().strip()
        if key:
            cfg["agent"]["api_key"] = key

        cfg["stt"].update({
            "model":    self._whisper_cb.get(),
            "language": self._lang_e.get().strip(),
            "device":   self._stt_dev_cb.get(),
        })
        cfg["tts"].update({
            "model_path":    self._tts_e.get().strip(),
            "length_scale":  round(self._speed_sl.get(), 2),
            "pitch_semitones": int(self._pitch_sl.get()),
        })
        cfg["wake_word"].update({
            "model_path":  self._ww_e.get().strip(),
            "threshold":   round(self._thresh_sl.get(), 2),
            "fallback_mode": "keyboard" if self._kb_var.get() else None,
        })

        def _dev_index(val: str):
            if val == "Default":
                return None
            try:
                return int(val.split(":")[0])
            except (ValueError, IndexError):
                return None

        cfg["audio"].update({
            "input_device":  _dev_index(self._mic_cb.get()),
            "output_device": _dev_index(self._out_cb.get()),
        })

        self._write_config(cfg)
        self._cfg = cfg
        self._update_prov_label()

    def _save_from_ui(self):
        """Salva e dá feedback visual (botão Save manual)."""
        self._do_save()
        self._log_line("Config salvo.")
        self._save_btn.configure(text="Salvo ✓", fg_color="#2d5a27", text_color=GREEN)
        self.after(1500, lambda: self._save_btn.configure(text="Save", fg_color=OVERLAY, text_color=TEXT))

    def _on_provider(self, value: str):
        model, key, url = PROVIDER_PRESETS.get(value, ("","",""))
        self._set_entry(self._model_e, model)
        self._set_entry(self._url_e,   url)
        if key:
            self._set_entry(self._apikey_e, key)
        else:
            self._apikey_e.delete(0, "end")
        self._update_prov_label(value, model)
        self._toggle_mascote_card(value == "ollama")

    def _toggle_mascote_card(self, show: bool):
        if show:
            if not self._mascote_card.winfo_ismapped():
                self._mascote_card.pack(fill="x", padx=10, pady=(6, 0),
                                        before=self._whisper_card)
        else:
            self._mascote_card.pack_forget()

    def _update_prov_label(self, provider: str = "", model: str = ""):
        provider = provider or self._prov_var.get()
        model    = model    or self._model_e.get().strip()
        self._prov_lbl.configure(text=f"[{provider}  {model}]")

    @staticmethod
    def _set_entry(e: ctk.CTkEntry, val: str):
        e.delete(0, "end")
        e.insert(0, val)

    # ── Pipeline ──────────────────────────────────────────────────────────────
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._do_save()
            self._start()

    def _start(self):
        if getattr(sys, "frozen", False):
            # Running as PyInstaller .exe — re-invoke self with _pipeline flag
            cmd = [sys.executable, "_pipeline",
                   "--provider", self._prov_var.get(),
                   "--port", "3005"]
        else:
            cmd = [sys.executable,
                   str(Path(__file__).parent / "main.py"),
                   "--provider", self._prov_var.get(),
                   "--port", "3005"]
        model = self._model_e.get().strip()
        if model:
            cmd += ["--model", model]

        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=str(_app_dir()),
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except Exception as exc:
            self._log_line(f"Erro ao iniciar: {exc}", color=RED)
            return

        self._running = True
        self._start_btn.configure(text="■  Stop", fg_color=RED, hover_color="#e07070")
        self._set_state("STARTING")
        threading.Thread(target=self._read_proc, daemon=True).start()
        threading.Thread(target=self._sse_loop,  daemon=True).start()

    def _stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self._running = False
        self._start_btn.configure(text="▶  Start", fg_color=GREEN, hover_color="#94d3a2")
        self._set_state("STOPPED")

    def _read_proc(self):
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            self._evq.put(("log", line.rstrip()))
        if self._running:
            self._evq.put(("dead", None))

    def _sse_loop(self):
        time.sleep(3)
        while self._running:
            try:
                with requests.get("http://localhost:3005/events",
                                   stream=True, timeout=(5, None),
                                   headers={"Accept": "text/event-stream"}) as r:
                    for raw in r.iter_lines():
                        if not self._running:
                            return
                        if raw and raw.startswith(b"data:"):
                            try:
                                self._evq.put(("sse", json.loads(raw[5:])))
                            except Exception:
                                pass
            except Exception:
                if self._running:
                    time.sleep(2)

    def _send(self):
        txt = self._msg_e.get().strip()
        if not txt:
            return
        self._msg_e.delete(0, "end")
        threading.Thread(
            target=lambda: requests.post(
                "http://localhost:3005/send",
                json={"text": txt}, timeout=3),
            daemon=True,
        ).start()

    # ── Event loop ────────────────────────────────────────────────────────────
    def _poll(self):
        try:
            while True:
                kind, data = self._evq.get_nowait()
                if   kind == "log":  self._log_line(data)
                elif kind == "sse":  self._on_sse(data)
                elif kind == "dead": self._stop()
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _on_sse(self, ev: dict):
        t = ev.get("type")
        if   t == "state":      self._set_state(ev.get("state",""))
        elif t == "transcript": self._chat_append("você",    ev.get("text",""), "user")
        elif t == "response":   self._chat_append("avatar",   ev.get("text",""), "avatar")
        elif t == "inject":     self._chat_append("enviado", ev.get("text",""), "inject")
        elif t == "tts":        self._chat_append("avatar", ev.get("text",""), "avatar")

    def _set_state(self, state: str):
        color = STATE_COLOR.get(state, MUTED)
        sym   = "●" if state not in ("STOPPED","STARTING") else "○"
        self._badge.configure(text=f"{sym}  {state}", text_color=color)

    def _log_line(self, msg: str, color: str = ""):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _chat_append(self, who: str, text: str, tag: str):
        self._chat.configure(state="normal")
        self._chat.insert("end", f"{who}:  ", tag)
        self._chat.insert("end", text + "\n\n")
        self._chat.see("end")
        self._chat.configure(state="disabled")

    def _build_modelfile(self) -> str:
        base  = self._mf_base_e.get().strip() or "gemma2:2b"
        temp  = round(self._mf_temp_sl.get(), 1)
        sys_p = self._mf_sys.get("1.0", "end").strip()
        return (
            f"FROM {base}\n"
            f"PARAMETER temperature {temp}\n"
            'PARAMETER stop "User:"\n'
            'SYSTEM """\n'
            f"{sys_p}\n"
            '"""\n'
        )

    def _save_modelfile(self):
        content = self._build_modelfile()
        name    = self._mf_name_e.get().strip() or "mascote"
        path    = filedialog.asksaveasfilename(
            defaultextension=".mf",
            filetypes=[("Modelfile", "*.mf"), ("All", "*.*")],
            initialfile=f"{name}.mf",
        )
        if not path:
            return
        Path(path).write_text(content, encoding="utf-8")
        self._log_line(f"Modelfile salvo: {path}")

    def _create_mascote(self):
        import tempfile
        name    = self._mf_name_e.get().strip() or "mascote"
        content = self._build_modelfile()
        tmp     = Path(tempfile.mktemp(suffix=".mf"))
        tmp.write_text(content, encoding="utf-8")
        self._log_line(f"Criando modelo '{name}'… veja no Monitor.")
        self._tabs.set("Monitor")
        threading.Thread(
            target=self._run_ollama_create, args=(name, tmp), daemon=True
        ).start()

    def _run_ollama_create(self, name: str, mf_path: Path):
        try:
            proc = subprocess.Popen(
                ["ollama", "create", name, "-f", str(mf_path)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            for line in proc.stdout:
                self._evq.put(("log", line.rstrip()))
            proc.wait()
            self._evq.put(("log", f"[ollama] '{name}' pronto (código {proc.returncode})"))
        except FileNotFoundError:
            self._evq.put(("log", "[ollama] comando não encontrado — Ollama instalado?"))
        except Exception as e:
            self._evq.put(("log", f"[ollama] erro: {e}"))
        finally:
            try:
                mf_path.unlink()
            except Exception:
                pass

    def _tts_test(self):
        text = self._tts_test_e.get().strip()
        if not text:
            return
        self._tts_btn.configure(state="disabled", text="…")
        self._tabs.set("Monitor")

        cfg = self._cfg.get("tts", {})
        model_path   = self._tts_e.get().strip() or cfg.get("model_path", "../piper_models/nanda_ptbr.onnx")
        length_scale = round(self._speed_sl.get(), 2)
        pitch        = int(self._pitch_sl.get())
        noise_scale  = cfg.get("noise_scale", 0.667)
        noise_w      = cfg.get("noise_w", 0.8)
        piper_bin    = cfg.get("piper_binary", "piper")

        audio_cfg  = self._cfg.get("audio", {})
        out_device = audio_cfg.get("output_device")

        def run():
            try:
                import shutil
                sys.path.insert(0, str(Path(__file__).parent))
                from tts_piper import PiperTTS

                # Resolve piper binary path
                resolved_bin = shutil.which(piper_bin) or piper_bin
                sox_found = shutil.which("sox")
                self._evq.put(("log", f"[TTS test] piper={resolved_bin}"))
                self._evq.put(("log", f"[TTS test] model={model_path}"))
                self._evq.put(("log", f"[TTS test] speed(length_scale)={length_scale}  pitch={pitch:+d}st"))
                self._evq.put(("log", f"[TTS test] sox={'sim → ' + sox_found if sox_found else 'NÃO encontrado (pitch usa numpy)'}"))
                self._evq.put(("log", f"[TTS test] texto → {text[:70]}"))

                tts = PiperTTS(
                    piper_binary=piper_bin,
                    model_path=model_path,
                    length_scale=length_scale,
                    noise_scale=noise_scale,
                    noise_w=noise_w,
                    pitch_semitones=pitch,
                    output_device=out_device,
                )
                tts.speak(text)
                self._evq.put(("log", "[TTS test] concluído."))
            except Exception as exc:
                self._evq.put(("log", f"[TTS test] erro: {exc}"))
            finally:
                self.after(0, lambda: self._tts_btn.configure(state="normal", text="▶"))

        threading.Thread(target=run, daemon=True).start()

    def _restore_device(self, combo: ctk.CTkComboBox, saved):
        if saved is None:
            combo.set("Default")
            return
        # saved é índice inteiro — acha a string correspondente "N: Nome"
        prefix = f"{saved}:"
        match = next((d for d in self._audio_devs if d.startswith(prefix)), None)
        combo.set(match if match else "Default")

    @staticmethod
    def _startup_enabled() -> bool:
        if not _WIN:
            return False
        try:
            with _winreg.OpenKey(_winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run") as k:
                _winreg.QueryValueEx(k, "avatar_voice")
                return True
        except OSError:
            return False

    def _apply_startup(self):
        if not _WIN:
            return
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        pythonw  = Path(sys.executable).parent / "pythonw.exe"
        app_path = Path(__file__).resolve()
        try:
            with _winreg.OpenKey(_winreg.HKEY_CURRENT_USER, key_path, 0,
                                 _winreg.KEY_SET_VALUE) as k:
                if self._startup_var.get():
                    _winreg.SetValueEx(k, "avatar_voice", 0, _winreg.REG_SZ,
                                       f'"{pythonw}" "{app_path}" --autostart')
                else:
                    try:
                        _winreg.DeleteValue(k, "avatar_voice")
                    except OSError:
                        pass
        except OSError as e:
            self._log_line(f"[startup] erro no registro: {e}")

    def _on_close(self):
        if self._running:
            self._stop()
        self.destroy()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_pipeline":
        sys.argv.pop(1)
        if not getattr(sys, "frozen", False):
            # Dev mode: add avatar_voice/ to path (frozen: PyInstaller already did it)
            _pkg = str(Path(__file__).parent)
            if _pkg not in sys.path:
                sys.path.insert(0, _pkg)
        import main as _m
        _m.main()
    else:
        App().mainloop()
