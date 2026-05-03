"""
avatar_voice — Desktop App
Setup, controle e chat numa janela moderna.

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

# -- Tema (Catppuccin Mocha) ---------------------------------------------------
ctk.deactivate_automatic_dpi_awareness()
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BASE      = "#1e1e2e"
SURFACE   = "#181825"
OVERLAY   = "#313244"
OVERLAY2  = "#393b54"
MUTED     = "#45475a"
TEXT      = "#cdd6f4"
SUBTEXT   = "#a6adc8"
BLUE      = "#89b4fa"
GREEN     = "#a6e3a1"
RED       = "#f38ba8"
YELLOW    = "#f9e2af"
MAUVE     = "#cba6f7"
TEAL      = "#94e2d5"
HEADER_BG = "#11111b"
CARD_BG   = "#262637"

FONT_TITLE = ("Segoe UI", 16, "bold")
FONT_H2    = ("Segoe UI", 11, "bold")
FONT_BODY  = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 10)
FONT_MONO  = ("Consolas", 11)
FONT_MONO_SM = ("Consolas", 10)
FONT_BADGE = ("Consolas", 11, "bold")

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

BUILTIN_PROVIDERS = {
    "ollama":     {"model": "mascote",            "api_key": "ollama",                           "base_url": "http://localhost:11434/v1",      "timeout": 240},
    "openai":     {"model": "gpt-4o-mini",        "api_key": "",                                 "base_url": "https://api.openai.com/v1",     "timeout": 30},
    "hermes":     {"model": "hermes-agent",       "api_key": "aa6531e6c0db6b2fba53bb133fac2e0a", "base_url": "http://localhost:8642/v1",       "timeout": 60},
    "openrouter": {"model": "openai/gpt-4o-mini", "api_key": "",                                 "base_url": "https://openrouter.ai/api/v1",  "timeout": 30},
    "openclaw":   {"model": "openclaw/default",   "api_key": "",                                 "base_url": "http://localhost:18789/v1",      "timeout": 60},
    "n8n":        {"model": "default",            "api_key": "",                                 "base_url": "http://localhost:5678/webhook/v1", "timeout": 30},
}

def _app_dir() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

CONFIG_PATH = _app_dir() / "config.yaml"
ASSETS_DIR  = _app_dir() / "assets"

DEFAULT_SYSTEM = (
    "Voce e um mascote de stream sem filtro. "
    "Fala com sotaque de Goias, usando expressoes como 'uai', 'trem', 'aneim', 'ta doido' e 'mo do ceu'. "
    "Seja engracado, meio sarcastico e trate o pessoal como se fosse todo mundo de casa. "
    "Responda de forma breve e natural, em portugues brasileiro, como em uma conversa falada. "
    "NUNCA use emojis, asteriscos, underlines, cerquilhas, til, travessoes, "
    "bullets, markdown ou qualquer simbolo especial. "
    "Escreva apenas texto simples, sem formatacao. "
    "Maximo de 2 frases curtas por resposta."
)


# -- App -----------------------------------------------------------------------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Avatar Voice")
        self.geometry("780x700")
        self.minsize(680, 560)
        self.configure(fg_color=SURFACE)

        # Window icon
        ico = ASSETS_DIR / "icon.ico"
        if ico.exists():
            self.iconbitmap(str(ico))

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

    # -- Config I/O ------------------------------------------------------------
    def _load_config(self) -> dict:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def _write_config(self, cfg: dict):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # -- UI Build --------------------------------------------------------------
    def _build(self):
        # -- Header ------------------------------------------------------------
        hdr = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=64)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        hdr_left = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_left.pack(side="left", padx=20, pady=8)

        # Logo image
        self._logo_img = None
        logo_path = ASSETS_DIR / "logo_64.png"
        if logo_path.exists():
            try:
                from PIL import Image
                pil = Image.open(logo_path).resize((40, 40), Image.LANCZOS)
                self._logo_img = ctk.CTkImage(pil, size=(40, 40))
                ctk.CTkLabel(hdr_left, image=self._logo_img, text=""
                             ).pack(side="left", padx=(0, 12))
            except Exception:
                pass

        title_col = ctk.CTkFrame(hdr_left, fg_color="transparent")
        title_col.pack(side="left")
        ctk.CTkLabel(title_col, text="Avatar Voice",
                     font=FONT_TITLE, text_color=TEXT
                     ).pack(anchor="w")
        ctk.CTkLabel(title_col, text="Voice assistant pipeline",
                     font=("Segoe UI", 9), text_color=MUTED
                     ).pack(anchor="w")

        # Status badge (right side of header)
        hdr_right = ctk.CTkFrame(hdr, fg_color="transparent")
        hdr_right.pack(side="right", padx=20, pady=8)

        self._prov_lbl = ctk.CTkLabel(hdr_right, text="",
                                       font=FONT_SMALL, text_color=SUBTEXT)
        self._prov_lbl.pack(anchor="e")

        self._badge = ctk.CTkLabel(hdr_right, text="STOPPED",
                                    font=FONT_BADGE, text_color=MUTED)
        self._badge.pack(anchor="e")

        # Accent line under header
        ctk.CTkFrame(self, fg_color=BLUE, height=2, corner_radius=0).pack(fill="x")

        # -- Tabs --------------------------------------------------------------
        self._tabs = ctk.CTkTabview(
            self, fg_color=BASE, corner_radius=0,
            segmented_button_fg_color=OVERLAY,
            segmented_button_selected_color=BLUE,
            segmented_button_selected_hover_color="#7ba4f5",
            segmented_button_unselected_hover_color=MUTED,
            border_width=0,
        )
        self._tabs.pack(fill="both", expand=True, padx=0, pady=0)
        for name in ("Setup", "Phrases", "Monitor", "Chat"):
            self._tabs.add(name)
        # Style the tab buttons
        self._tabs._segmented_button.configure(font=FONT_H2)

        self._build_setup(self._tabs.tab("Setup"))
        self._build_phrases(self._tabs.tab("Phrases"))
        self._build_monitor(self._tabs.tab("Monitor"))
        self._build_chat(self._tabs.tab("Chat"))

        # -- Bottom bar --------------------------------------------------------
        bar = ctk.CTkFrame(self, fg_color=HEADER_BG, corner_radius=0, height=64)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self._save_btn = ctk.CTkButton(
            bar, text="Save", width=100, height=40, corner_radius=10,
            font=FONT_BODY, fg_color=OVERLAY, hover_color=MUTED,
            text_color=TEXT, command=self._save_from_ui,
        )
        self._save_btn.pack(side="right", padx=(0, 16), pady=12)

        self._start_btn = ctk.CTkButton(
            bar, text="Start", width=150, height=40, corner_radius=10,
            font=("Segoe UI", 13, "bold"), fg_color=GREEN,
            hover_color="#94d3a2", text_color="#1e1e2e",
            command=self._toggle,
        )
        self._start_btn.pack(side="right", padx=(16, 8), pady=12)

        # Version label (left side of bottom bar)
        ctk.CTkLabel(bar, text="v1.0", font=("Segoe UI", 9),
                     text_color=MUTED).pack(side="left", padx=20)

    # -- Setup tab -------------------------------------------------------------
    def _build_setup(self, parent):
        scroll = ctk.CTkScrollableFrame(parent, fg_color=BASE,
                                         scrollbar_button_color=MUTED)
        scroll.pack(fill="both", expand=True, padx=4, pady=4)

        # -- Provider ----------------------------------------------------------
        self._prov_var = ctk.StringVar(value="ollama")
        s = self._card(scroll, "Provider", "LLM backend")
        prov_row = ctk.CTkFrame(s, fg_color="transparent")
        prov_row.pack(fill="x", pady=(4, 10))
        self._prov_menu = ctk.CTkOptionMenu(
            prov_row, variable=self._prov_var,
            values=self._provider_names(),
            font=FONT_BODY, dropdown_font=FONT_BODY,
            fg_color=OVERLAY, button_color=MUTED,
            button_hover_color="#7ba4f5",
            dropdown_fg_color=OVERLAY,
            dropdown_hover_color=BLUE,
            text_color=TEXT,
            command=self._on_provider,
            width=200,
        )
        self._prov_menu.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            prov_row, text="+", width=36, height=32, corner_radius=8,
            font=FONT_BODY, fg_color=OVERLAY, hover_color=GREEN,
            text_color=TEXT, command=self._add_provider,
        ).pack(side="left", padx=(0, 4))
        self._del_btn = ctk.CTkButton(
            prov_row, text="-", width=36, height=32, corner_radius=8,
            font=FONT_BODY, fg_color=OVERLAY, hover_color=RED,
            text_color=TEXT, command=self._remove_provider,
        )
        self._del_btn.pack(side="left")

        # Two-column row for model + api key
        cols = ctk.CTkFrame(s, fg_color="transparent")
        cols.pack(fill="x", pady=(0, 4))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._model_e = self._labeled_entry(left, "Model")

        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self._apikey_e = self._labeled_entry(right, "API Key", show="*")

        self._url_e = self._labeled_entry(s, "Base URL")

        ctk.CTkLabel(s, text="System prompt", font=FONT_SMALL,
                     text_color=SUBTEXT).pack(anchor="w", pady=(10, 3))
        self._sys_prompt = ctk.CTkTextbox(
            s, height=80, font=FONT_MONO_SM, fg_color=SURFACE,
            text_color=TEXT, wrap="word", border_color=MUTED,
            border_width=1, corner_radius=8)
        self._sys_prompt.pack(fill="x", pady=(0, 4))
        self._sys_prompt.insert("1.0", DEFAULT_SYSTEM)

        # -- Mascote (Ollama) --------------------------------------------------
        sm = self._card(scroll, "Mascote", "Ollama Modelfile builder")
        self._mascote_card = sm.master

        cols2 = ctk.CTkFrame(sm, fg_color="transparent")
        cols2.pack(fill="x", pady=(4, 4))
        cols2.columnconfigure(0, weight=1)
        cols2.columnconfigure(1, weight=1)
        cols2.columnconfigure(2, weight=1)

        f1 = ctk.CTkFrame(cols2, fg_color="transparent")
        f1.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self._mf_base_e = self._labeled_entry(f1, "Base model")
        self._mf_base_e.insert(0, "gemma2:2b")

        f2 = ctk.CTkFrame(cols2, fg_color="transparent")
        f2.grid(row=0, column=1, sticky="ew", padx=(6, 6))
        self._mf_name_e = self._labeled_entry(f2, "Name")
        self._mf_name_e.insert(0, "mascote")

        f3 = ctk.CTkFrame(cols2, fg_color="transparent")
        f3.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self._mf_temp_lbl, self._mf_temp_sl = self._labeled_slider(
            f3, "Temperature", 0.1, 2.0, 19, 0.9, fmt=lambda v: f"{v:.1f}")

        ctk.CTkLabel(sm, text="System prompt", font=FONT_SMALL,
                     text_color=SUBTEXT).pack(anchor="w", pady=(8, 3))
        self._mf_sys = ctk.CTkTextbox(
            sm, height=80, font=FONT_MONO_SM, fg_color=SURFACE,
            text_color=TEXT, wrap="word", border_color=MUTED,
            border_width=1, corner_radius=8)
        self._mf_sys.pack(fill="x", pady=(0, 8))
        self._mf_sys.insert("1.0", DEFAULT_SYSTEM)

        btn_row = ctk.CTkFrame(sm, fg_color="transparent")
        btn_row.pack(fill="x")
        ctk.CTkButton(btn_row, text="Save .mf", width=110, height=32,
                      corner_radius=8, font=FONT_SMALL,
                      fg_color=OVERLAY, hover_color=MUTED, text_color=TEXT,
                      command=self._save_modelfile).pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_row, text="Create in Ollama", width=150, height=32,
                      corner_radius=8, font=("Segoe UI", 10, "bold"),
                      fg_color=MAUVE, hover_color="#b994e8", text_color="#1e1e2e",
                      command=self._create_mascote).pack(side="left")

        # -- Two-column: STT + TTS ---------------------------------------------
        two_col = ctk.CTkFrame(scroll, fg_color="transparent")
        two_col.pack(fill="x", padx=0, pady=0)
        two_col.columnconfigure(0, weight=1)
        two_col.columnconfigure(1, weight=1)

        # STT card (left)
        stt_wrap = ctk.CTkFrame(two_col, fg_color="transparent")
        stt_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        s2 = self._card(stt_wrap, "Speech-to-Text", "Whisper STT")
        self._whisper_card = s2.master

        self._whisper_cb = self._labeled_combo(s2, "Model",
            ["tiny", "base", "small", "medium", "large-v3"], w=140)
        self._lang_e = self._labeled_entry(s2, "Language")
        self._stt_dev_cb = self._labeled_combo(s2, "Device",
            ["auto", "cpu", "cuda"], w=100)

        # TTS card (right)
        tts_wrap = ctk.CTkFrame(two_col, fg_color="transparent")
        tts_wrap.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        s3 = self._card(tts_wrap, "Text-to-Speech", "Piper TTS")

        voice_row = ctk.CTkFrame(s3, fg_color="transparent")
        voice_row.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(voice_row, text="Voice", font=FONT_SMALL,
                     text_color=SUBTEXT).pack(anchor="w")
        file_row = ctk.CTkFrame(voice_row, fg_color="transparent")
        file_row.pack(fill="x", pady=(2, 0))
        self._tts_e = ctk.CTkEntry(file_row, font=FONT_MONO_SM, height=30,
                                    corner_radius=8, fg_color=OVERLAY,
                                    border_color=MUTED, text_color=TEXT)
        self._tts_e.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(file_row, text="...", width=32, height=30, corner_radius=8,
                      fg_color=SURFACE, hover_color=MUTED, text_color=SUBTEXT,
                      command=lambda: self._browse(self._tts_e, "*.onnx")).pack(side="left")

        sl_row = ctk.CTkFrame(s3, fg_color="transparent")
        sl_row.pack(fill="x", pady=(4, 4))
        self._speed_lbl, self._speed_sl = self._labeled_slider(
            sl_row, "Speed", 0.5, 2.0, 30, 0.95, fmt=lambda v: f"{v:.2f}")
        self._pitch_lbl, self._pitch_sl = self._labeled_slider(
            sl_row, "Pitch", -6, 6, 12, 0, fmt=lambda v: f"{int(v):+d}")

        # TTS test
        ctk.CTkLabel(s3, text="Test", font=FONT_SMALL,
                     text_color=SUBTEXT).pack(anchor="w", pady=(6, 2))
        test_row = ctk.CTkFrame(s3, fg_color="transparent")
        test_row.pack(fill="x")
        self._tts_test_e = ctk.CTkEntry(
            test_row, font=FONT_MONO_SM, height=30, corner_radius=8,
            fg_color=OVERLAY, border_color=MUTED, text_color=TEXT,
            placeholder_text="Frase para testar...",
        )
        self._tts_test_e.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._tts_test_e.insert(0, "Uai, oce ta me ouvindo bem, so?")
        self._tts_btn = ctk.CTkButton(
            test_row, text="Play", width=60, height=30, corner_radius=8,
            font=("Segoe UI", 10, "bold"),
            fg_color=TEAL, hover_color="#7ecfc3", text_color="#1e1e2e",
            command=self._tts_test,
        )
        self._tts_btn.pack(side="left")

        # -- Two-column: Wake Word + Audio -------------------------------------
        two_col2 = ctk.CTkFrame(scroll, fg_color="transparent")
        two_col2.pack(fill="x", padx=0, pady=0)
        two_col2.columnconfigure(0, weight=1)
        two_col2.columnconfigure(1, weight=1)

        # Wake Word (left)
        ww_wrap = ctk.CTkFrame(two_col2, fg_color="transparent")
        ww_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        s4 = self._card(ww_wrap, "Wake Word", "OpenWakeWord trigger")

        ww_file_row = ctk.CTkFrame(s4, fg_color="transparent")
        ww_file_row.pack(fill="x", pady=(4, 4))
        ctk.CTkLabel(ww_file_row, text="Model", font=FONT_SMALL,
                     text_color=SUBTEXT).pack(anchor="w")
        ww_fr = ctk.CTkFrame(ww_file_row, fg_color="transparent")
        ww_fr.pack(fill="x", pady=(2, 0))
        self._ww_e = ctk.CTkEntry(ww_fr, font=FONT_MONO_SM, height=30,
                                   corner_radius=8, fg_color=OVERLAY,
                                   border_color=MUTED, text_color=TEXT)
        self._ww_e.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(ww_fr, text="...", width=32, height=30, corner_radius=8,
                      fg_color=SURFACE, hover_color=MUTED, text_color=SUBTEXT,
                      command=lambda: self._browse(self._ww_e, "*.onnx")).pack(side="left")

        self._thresh_lbl, self._thresh_sl = self._labeled_slider(
            s4, "Threshold", 0.1, 0.99, 18, 0.5, fmt=lambda v: f"{v:.2f}")

        self._kb_var = ctk.BooleanVar()
        ctk.CTkCheckBox(s4, text="Keyboard fallback", variable=self._kb_var,
                        font=FONT_SMALL, text_color=SUBTEXT,
                        checkbox_width=18, checkbox_height=18,
                        fg_color=BLUE, border_color=MUTED,
                        checkmark_color="#1e1e2e"
                        ).pack(anchor="w", pady=(8, 4))

        # Audio (right)
        audio_wrap = ctk.CTkFrame(two_col2, fg_color="transparent")
        audio_wrap.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        s5 = self._card(audio_wrap, "Audio", "Input/output devices")
        self._audio_devs = self._audio_devices()
        self._mic_cb = self._labeled_combo(s5, "Microphone",
                                            ["Default"] + self._audio_devs)
        self._out_cb = self._labeled_combo(s5, "Output",
                                            ["Default"] + self._audio_devs)

        # -- System ------------------------------------------------------------
        s6 = self._card(scroll, "System", "Startup options")
        self._startup_var = ctk.BooleanVar(value=self._startup_enabled())
        ctk.CTkCheckBox(
            s6, text="Start with Windows", variable=self._startup_var,
            font=FONT_BODY, text_color=SUBTEXT,
            checkbox_width=18, checkbox_height=18,
            fg_color=BLUE, border_color=MUTED, checkmark_color="#1e1e2e",
            command=self._apply_startup,
            state="normal" if _WIN else "disabled",
        ).pack(anchor="w", pady=(4, 4))

    # -- Phrases tab -----------------------------------------------------------
    def _build_phrases(self, parent):
        self._phrases_data = self._load_phrases_json()

        top = ctk.CTkFrame(parent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(top, text="Personalize as frases faladas pelo avatar",
                     font=FONT_SMALL, text_color=SUBTEXT).pack(side="left")

        self._phrases_save_btn = ctk.CTkButton(
            top, text="Save Phrases", width=120, height=32, corner_radius=8,
            font=("Segoe UI", 10, "bold"), fg_color=GREEN,
            hover_color="#94d3a2", text_color="#1e1e2e",
            command=self._save_phrases,
        )
        self._phrases_save_btn.pack(side="right")

        cols = ctk.CTkFrame(parent, fg_color="transparent")
        cols.pack(fill="both", expand=True, padx=8, pady=(4, 8))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        # Greetings column
        left = ctk.CTkFrame(cols, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        left.rowconfigure(1, weight=1)

        g_hdr = ctk.CTkFrame(left, fg_color="transparent")
        g_hdr.grid(row=0, column=0, sticky="ew", pady=(4, 2))
        ctk.CTkLabel(g_hdr, text="Greetings", font=FONT_H2,
                     text_color=MAUVE).pack(side="left")
        self._g_count = ctk.CTkLabel(g_hdr, text="0", font=FONT_SMALL,
                                      text_color=MUTED)
        self._g_count.pack(side="left", padx=(6, 0))

        g_list_frame = ctk.CTkFrame(left, fg_color=CARD_BG, corner_radius=10,
                                     border_width=1, border_color=OVERLAY)
        g_list_frame.grid(row=1, column=0, sticky="nsew")
        g_list_frame.rowconfigure(0, weight=1)
        g_list_frame.columnconfigure(0, weight=1)

        self._g_list = ctk.CTkTextbox(
            g_list_frame, font=FONT_MONO_SM, fg_color=CARD_BG,
            text_color=TEXT, wrap="none", corner_radius=10)
        self._g_list.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        g_btns = ctk.CTkFrame(left, fg_color="transparent")
        g_btns.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self._g_entry = ctk.CTkEntry(
            g_btns, font=FONT_MONO_SM, height=30, corner_radius=8,
            fg_color=OVERLAY, border_color=MUTED, text_color=TEXT,
            placeholder_text="Nova frase de saudação...")
        self._g_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._g_entry.bind("<Return>", lambda _: self._add_phrase("greetings"))
        ctk.CTkButton(g_btns, text="+", width=32, height=30, corner_radius=8,
                      font=FONT_BODY, fg_color=OVERLAY, hover_color=GREEN,
                      text_color=TEXT,
                      command=lambda: self._add_phrase("greetings")).pack(side="left", padx=(0, 2))
        ctk.CTkButton(g_btns, text="-", width=32, height=30, corner_radius=8,
                      font=FONT_BODY, fg_color=OVERLAY, hover_color=RED,
                      text_color=TEXT,
                      command=lambda: self._remove_phrase("greetings")).pack(side="left")

        # Waitings column
        right = ctk.CTkFrame(cols, fg_color="transparent")
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right.rowconfigure(1, weight=1)

        w_hdr = ctk.CTkFrame(right, fg_color="transparent")
        w_hdr.grid(row=0, column=0, sticky="ew", pady=(4, 2))
        ctk.CTkLabel(w_hdr, text="Waitings", font=FONT_H2,
                     text_color=YELLOW).pack(side="left")
        self._w_count = ctk.CTkLabel(w_hdr, text="0", font=FONT_SMALL,
                                      text_color=MUTED)
        self._w_count.pack(side="left", padx=(6, 0))

        w_list_frame = ctk.CTkFrame(right, fg_color=CARD_BG, corner_radius=10,
                                     border_width=1, border_color=OVERLAY)
        w_list_frame.grid(row=1, column=0, sticky="nsew")
        w_list_frame.rowconfigure(0, weight=1)
        w_list_frame.columnconfigure(0, weight=1)

        self._w_list = ctk.CTkTextbox(
            w_list_frame, font=FONT_MONO_SM, fg_color=CARD_BG,
            text_color=TEXT, wrap="none", corner_radius=10)
        self._w_list.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        w_btns = ctk.CTkFrame(right, fg_color="transparent")
        w_btns.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self._w_entry = ctk.CTkEntry(
            w_btns, font=FONT_MONO_SM, height=30, corner_radius=8,
            fg_color=OVERLAY, border_color=MUTED, text_color=TEXT,
            placeholder_text="Nova frase de espera...")
        self._w_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._w_entry.bind("<Return>", lambda _: self._add_phrase("waitings"))
        ctk.CTkButton(w_btns, text="+", width=32, height=30, corner_radius=8,
                      font=FONT_BODY, fg_color=OVERLAY, hover_color=GREEN,
                      text_color=TEXT,
                      command=lambda: self._add_phrase("waitings")).pack(side="left", padx=(0, 2))
        ctk.CTkButton(w_btns, text="-", width=32, height=30, corner_radius=8,
                      font=FONT_BODY, fg_color=OVERLAY, hover_color=RED,
                      text_color=TEXT,
                      command=lambda: self._remove_phrase("waitings")).pack(side="left")

        self._refresh_phrases_ui()

    def _load_phrases_json(self) -> dict:
        p = _app_dir() / "phrases.json"
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return {
                    "greetings": data.get("greetings", []),
                    "waitings": data.get("waitings", []),
                }
            except Exception:
                pass
        return {"greetings": [], "waitings": []}

    def _refresh_phrases_ui(self):
        greetings = self._phrases_data.get("greetings", [])
        waitings = self._phrases_data.get("waitings", [])

        self._g_list.delete("1.0", "end")
        for phrase in greetings:
            self._g_list.insert("end", phrase + "\n")
        self._g_count.configure(text=f"({len(greetings)})")

        self._w_list.delete("1.0", "end")
        for phrase in waitings:
            self._w_list.insert("end", phrase + "\n")
        self._w_count.configure(text=f"({len(waitings)})")

    def _parse_textbox(self, textbox) -> list:
        raw = textbox.get("1.0", "end").strip()
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def _add_phrase(self, category: str):
        entry = self._g_entry if category == "greetings" else self._w_entry
        textbox = self._g_list if category == "greetings" else self._w_list
        text = entry.get().strip()
        if not text:
            return
        # Sync edits from textbox before adding
        self._phrases_data[category] = self._parse_textbox(textbox)
        if text in self._phrases_data[category]:
            self._log_line(f"Frase já existe em {category}.", color=YELLOW)
            return
        self._phrases_data[category].append(text)
        entry.delete(0, "end")
        self._refresh_phrases_ui()

    def _remove_phrase(self, category: str):
        textbox = self._g_list if category == "greetings" else self._w_list
        # Sync edits from textbox
        self._phrases_data[category] = self._parse_textbox(textbox)
        lst = self._phrases_data[category]
        if not lst:
            return

        # Try to find selected line by cursor position
        try:
            cursor = textbox.index("insert")
            line_num = int(cursor.split(".")[0]) - 1
            if 0 <= line_num < len(lst):
                removed = lst.pop(line_num)
                self._log_line(f"Removida: {removed[:50]}")
                self._refresh_phrases_ui()
                return
        except Exception:
            pass

        removed = lst.pop()
        self._log_line(f"Removida (última): {removed[:50]}")
        self._refresh_phrases_ui()

    def _save_phrases(self):
        from phrases import save_phrases
        # Parse current textbox content (user may have edited inline)
        greetings = self._parse_textbox(self._g_list)
        waitings = self._parse_textbox(self._w_list)
        self._phrases_data = {"greetings": greetings, "waitings": waitings}
        save_phrases(greetings, waitings)
        self._refresh_phrases_ui()
        self._log_line(f"Phrases saved ({len(greetings)} greetings, {len(waitings)} waitings)")
        self._phrases_save_btn.configure(text="Saved!", fg_color="#2d5a27", text_color=GREEN)
        self.after(1500, lambda: self._phrases_save_btn.configure(
            text="Save Phrases", fg_color=GREEN, text_color="#1e1e2e"))

    # -- Monitor tab -----------------------------------------------------------
    def _build_monitor(self, parent):
        self._log = ctk.CTkTextbox(
            parent, font=FONT_MONO_SM, fg_color=BASE,
            text_color=SUBTEXT, wrap="word", activate_scrollbars=True,
            corner_radius=0,
        )
        self._log.pack(fill="both", expand=True, padx=12, pady=12)
        self._log.configure(state="disabled")

    # -- Chat tab --------------------------------------------------------------
    def _build_chat(self, parent):
        self._chat = ctk.CTkTextbox(
            parent, font=FONT_MONO, fg_color=BASE,
            text_color=TEXT, wrap="word", activate_scrollbars=True,
            corner_radius=0,
        )
        self._chat.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        self._chat.configure(state="disabled")
        self._chat.tag_config("user",   foreground=GREEN)
        self._chat.tag_config("avatar", foreground=BLUE)
        self._chat.tag_config("inject", foreground=YELLOW)
        self._chat.tag_config("dim",    foreground=MUTED)

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 12))
        self._msg_e = ctk.CTkEntry(row, font=FONT_MONO, height=38,
                                    corner_radius=10, fg_color=OVERLAY,
                                    border_color=MUTED, text_color=TEXT,
                                    placeholder_text="Inject message (bypasses wake word)...")
        self._msg_e.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._msg_e.bind("<Return>", lambda _: self._send())
        ctk.CTkButton(row, text="Send", width=80, height=38, corner_radius=10,
                      font=("Segoe UI", 11, "bold"),
                      fg_color=BLUE, hover_color="#7ba4f5", text_color="#1e1e2e",
                      command=self._send).pack(side="left")

    # -- UI Helpers ------------------------------------------------------------
    def _card(self, parent, title: str, subtitle: str = "") -> ctk.CTkFrame:
        wrap = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=12,
                             border_width=1, border_color=OVERLAY)
        wrap.pack(fill="x", padx=8, pady=(8, 0))

        hdr = ctk.CTkFrame(wrap, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(10, 0))
        ctk.CTkLabel(hdr, text=title, font=FONT_H2,
                     text_color=TEXT).pack(side="left")
        if subtitle:
            ctk.CTkLabel(hdr, text=subtitle, font=("Segoe UI", 9),
                         text_color=MUTED).pack(side="left", padx=(8, 0))

        inner = ctk.CTkFrame(wrap, fg_color="transparent")
        inner.pack(fill="x", padx=14, pady=(4, 12))
        return inner

    def _labeled_entry(self, parent, label: str, show: str = "") -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label, font=FONT_SMALL,
                     text_color=SUBTEXT).pack(anchor="w", pady=(4, 2))
        e = ctk.CTkEntry(parent, font=FONT_MONO, height=32, corner_radius=8,
                          fg_color=OVERLAY, border_color=MUTED, text_color=TEXT,
                          show=show)
        e.pack(fill="x")
        return e

    def _labeled_combo(self, parent, label: str, values: list, w: int = 0) -> ctk.CTkComboBox:
        ctk.CTkLabel(parent, text=label, font=FONT_SMALL,
                     text_color=SUBTEXT).pack(anchor="w", pady=(4, 2))
        kw = {"width": w} if w else {}
        c = ctk.CTkComboBox(parent, values=values, font=FONT_MONO_SM,
                             height=30, corner_radius=8, fg_color=OVERLAY,
                             border_color=MUTED, button_color=MUTED,
                             dropdown_fg_color=OVERLAY, text_color=TEXT, **kw)
        c.pack(fill="x")
        return c

    def _labeled_slider(self, parent, label: str, lo, hi, steps, default,
                        fmt):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(4, 2))

        ctk.CTkLabel(row, text=label, font=FONT_SMALL,
                     text_color=SUBTEXT).pack(side="left")
        lbl = ctk.CTkLabel(row, text=fmt(default), font=FONT_MONO_SM,
                            text_color=BLUE, width=40)
        lbl.pack(side="right")

        sl = ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=steps,
                            height=16, button_color=BLUE,
                            button_hover_color="#7ba4f5", progress_color=BLUE,
                            fg_color=MUTED,
                            command=lambda v, l=lbl, f=fmt: l.configure(text=f(v)))
        sl.set(default)
        sl.pack(fill="x", pady=(0, 2))
        return lbl, sl

    def _browse(self, entry: ctk.CTkEntry, pattern: str):
        path = filedialog.askopenfilename(
            filetypes=[(pattern.replace("*", "Model"), pattern), ("All", "*.*")])
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _audio_devices(self) -> list:
        try:
            import sounddevice as sd
            return [f"{i}: {d['name']}" for i, d in enumerate(sd.query_devices())]
        except Exception:
            return []

    # -- Config sync -----------------------------------------------------------
    def _apply_config(self):
        cfg   = self._cfg
        agent = cfg.get("agent", {})
        stt   = cfg.get("stt", {})
        tts   = cfg.get("tts", {})
        ww    = cfg.get("wake_word", {})

        url = agent.get("base_url", "http://localhost:11434/v1")
        # Find which provider matches the saved url+model
        prov = "ollama"
        for name, p in self._get_providers().items():
            if p.get("base_url") == url:
                prov = name
                break
        self._prov_var.set(prov)
        self._refresh_provider_menu()

        self._set_entry(self._model_e,  agent.get("model",   "mascote"))
        self._set_entry(self._apikey_e, agent.get("api_key", ""))
        self._set_entry(self._url_e,    url)
        saved_prompt = agent.get("system_prompt", "").strip()
        self._sys_prompt.delete("1.0", "end")
        self._sys_prompt.insert("1.0", saved_prompt or DEFAULT_SYSTEM)

        self._whisper_cb.set(stt.get("model", "small"))
        self._set_entry(self._lang_e, stt.get("language", "pt"))
        self._stt_dev_cb.set(stt.get("device", "auto"))

        self._set_entry(self._tts_e, tts.get("model_path", "../piper_models/nanda_ptbr.onnx"))
        spd = tts.get("length_scale", 0.95)
        self._speed_sl.set(spd); self._speed_lbl.configure(text=f"{spd:.2f}")
        pit = tts.get("pitch_semitones", 0)
        self._pitch_sl.set(pit); self._pitch_lbl.configure(text=f"{int(pit):+d}")

        self._set_entry(self._ww_e, ww.get("model_path", "../wake_word_models/central.onnx"))
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
        for sec in ("agent", "stt", "tts", "wake_word", "audio"):
            cfg.setdefault(sec, {})

        url = self._url_e.get().strip()
        model = self._model_e.get().strip()
        key = self._apikey_e.get().strip()

        cfg["agent"].update({
            "base_url":      url,
            "model":         model,
            "system_prompt": self._sys_prompt.get("1.0", "end").strip(),
        })
        if key:
            cfg["agent"]["api_key"] = key

        # Persist current provider fields into providers dict
        prov_name = self._prov_var.get()
        cfg.setdefault("providers", {})
        cfg["providers"][prov_name] = {
            "model": model, "api_key": key, "base_url": url,
            "timeout": self._get_providers().get(prov_name, {}).get("timeout", 30),
        }

        cfg["stt"].update({
            "model":    self._whisper_cb.get(),
            "language": self._lang_e.get().strip(),
            "device":   self._stt_dev_cb.get(),
        })
        cfg["tts"].update({
            "model_path":      self._tts_e.get().strip(),
            "length_scale":    round(self._speed_sl.get(), 2),
            "pitch_semitones": int(self._pitch_sl.get()),
        })
        cfg["wake_word"].update({
            "model_path":    self._ww_e.get().strip(),
            "threshold":     round(self._thresh_sl.get(), 2),
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
        self._do_save()
        self._log_line("Config saved.")
        self._save_btn.configure(text="Saved", fg_color="#2d5a27", text_color=GREEN)
        self.after(1500, lambda: self._save_btn.configure(
            text="Save", fg_color=OVERLAY, text_color=TEXT))

    def _get_providers(self) -> dict:
        """Merge built-in presets with user-saved providers (user wins)."""
        saved = self._cfg.get("providers", {}) or {}
        merged = {**BUILTIN_PROVIDERS, **saved}
        return merged

    def _provider_names(self) -> list:
        return list(self._get_providers().keys())

    def _refresh_provider_menu(self):
        names = self._provider_names()
        self._prov_menu.configure(values=names)
        if self._prov_var.get() not in names and names:
            self._prov_var.set(names[0])

    def _on_provider(self, value: str):
        p = self._get_providers().get(value, {})
        self._set_entry(self._model_e, p.get("model", ""))
        self._set_entry(self._url_e, p.get("base_url", ""))
        key = p.get("api_key", "")
        if key:
            self._set_entry(self._apikey_e, key)
        else:
            self._apikey_e.delete(0, "end")
        self._update_prov_label(value, p.get("model", ""))
        self._toggle_mascote_card(value == "ollama")

    def _add_provider(self):
        dialog = ctk.CTkInputDialog(
            text="Nome do novo provider:", title="Add Provider",
        )
        name = (dialog.get_input() or "").strip().lower()
        if not name:
            return
        if name in self._get_providers():
            self._log_line(f"Provider '{name}' already exists.", color=YELLOW)
            return
        self._cfg.setdefault("providers", {})[name] = {
            "model": "", "api_key": "", "base_url": "http://localhost:8080/v1", "timeout": 30,
        }
        self._refresh_provider_menu()
        self._prov_var.set(name)
        self._on_provider(name)
        self._log_line(f"Provider '{name}' added. Fill in the fields and Save.")

    def _remove_provider(self):
        name = self._prov_var.get()
        saved = self._cfg.get("providers", {})
        if name in saved:
            del saved[name]
            self._refresh_provider_menu()
            self._on_provider(self._prov_var.get())
            self._log_line(f"Provider '{name}' removed.")
        elif name in BUILTIN_PROVIDERS:
            self._log_line(f"Cannot remove built-in provider '{name}'.", color=YELLOW)
        else:
            self._log_line(f"Provider '{name}' not found.", color=RED)

    def _toggle_mascote_card(self, show: bool):
        if show:
            if not self._mascote_card.winfo_ismapped():
                self._mascote_card.pack(fill="x", padx=8, pady=(8, 0),
                                        before=self._whisper_card.master.master)
        else:
            self._mascote_card.pack_forget()

    def _update_prov_label(self, provider: str = "", model: str = ""):
        provider = provider or self._prov_var.get()
        model    = model    or self._model_e.get().strip()
        self._prov_lbl.configure(text=f"{provider} / {model}")

    @staticmethod
    def _set_entry(e: ctk.CTkEntry, val: str):
        e.delete(0, "end")
        e.insert(0, val)

    # -- Pipeline --------------------------------------------------------------
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._do_save()
            self._start()

    def _start(self):
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "_pipeline", "--port", "3005"]
        else:
            cmd = [sys.executable,
                   str(Path(__file__).parent / "main.py"),
                   "--port", "3005"]

        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                cwd=str(_app_dir()),
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except Exception as exc:
            self._log_line(f"Error starting: {exc}", color=RED)
            return

        self._running = True
        self._start_btn.configure(text="Stop", fg_color=RED, hover_color="#e07070")
        self._set_state("STARTING")
        threading.Thread(target=self._read_proc, daemon=True).start()
        threading.Thread(target=self._sse_loop, daemon=True).start()

    def _stop(self):
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self._running = False
        self._start_btn.configure(text="Start", fg_color=GREEN, hover_color="#94d3a2")
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

    # -- Event loop ------------------------------------------------------------
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
        if   t == "state":      self._set_state(ev.get("state", ""))
        elif t == "transcript": self._chat_append("you",    ev.get("text", ""), "user")
        elif t == "response":   self._chat_append("avatar", ev.get("text", ""), "avatar")
        elif t == "inject":     self._chat_append("sent",   ev.get("text", ""), "inject")
        elif t == "tts":        self._chat_append("avatar", ev.get("text", ""), "avatar")

    def _set_state(self, state: str):
        color = STATE_COLOR.get(state, MUTED)
        self._badge.configure(text=state, text_color=color)

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
        self._log_line(f"Modelfile saved: {path}")

    def _create_mascote(self):
        import tempfile
        name    = self._mf_name_e.get().strip() or "mascote"
        content = self._build_modelfile()
        tmp     = Path(tempfile.mktemp(suffix=".mf"))
        tmp.write_text(content, encoding="utf-8")
        self._log_line(f"Creating model '{name}'...")
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
            self._evq.put(("log", f"[ollama] '{name}' ready (code {proc.returncode})"))
        except FileNotFoundError:
            self._evq.put(("log", "[ollama] command not found - is Ollama installed?"))
        except Exception as e:
            self._evq.put(("log", f"[ollama] error: {e}"))
        finally:
            try:
                mf_path.unlink()
            except Exception:
                pass

    def _tts_test(self):
        text = self._tts_test_e.get().strip()
        if not text:
            return
        self._tts_btn.configure(state="disabled", text="...")
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

                resolved_bin = shutil.which(piper_bin) or piper_bin
                sox_found = shutil.which("sox")
                self._evq.put(("log", f"[TTS test] piper={resolved_bin}"))
                self._evq.put(("log", f"[TTS test] model={model_path}"))
                self._evq.put(("log", f"[TTS test] speed={length_scale}  pitch={pitch:+d}st"))
                self._evq.put(("log", f"[TTS test] sox={'yes: ' + sox_found if sox_found else 'not found (pitch uses numpy)'}"))
                self._evq.put(("log", f"[TTS test] text: {text[:70]}"))

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
                self._evq.put(("log", "[TTS test] done."))
            except Exception as exc:
                self._evq.put(("log", f"[TTS test] error: {exc}"))
            finally:
                self.after(0, lambda: self._tts_btn.configure(state="normal", text="Play"))

        threading.Thread(target=run, daemon=True).start()

    def _restore_device(self, combo: ctk.CTkComboBox, saved):
        if saved is None:
            combo.set("Default")
            return
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
            self._log_line(f"[startup] registry error: {e}")

    def _on_close(self):
        if self._running:
            self._stop()
        self.destroy()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "_pipeline":
        sys.argv.pop(1)
        if not getattr(sys, "frozen", False):
            _pkg = str(Path(__file__).parent)
            if _pkg not in sys.path:
                sys.path.insert(0, _pkg)
        import main as _m
        _m.main()
    else:
        App().mainloop()
