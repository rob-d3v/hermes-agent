"""
morph_voice — Desktop App
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

CONFIG_PATH = Path(__file__).parent / "config.yaml"


# ── App ───────────────────────────────────────────────────────────────────────
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("morph_voice")
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
        ctk.CTkLabel(hdr, text="morph_voice",
                     font=("Courier New", 14, "bold"), text_color=BLUE
                     ).pack(side="left", padx=18, pady=10)
        self._badge = ctk.CTkLabel(hdr, text="○  STOPPED",
                                   font=("Courier New", 11), text_color=MUTED)
        self._badge.pack(side="right", padx=18)

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

        # Whisper STT
        s2 = self._card(scroll, "WHISPER  (STT)")
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
        devs = self._audio_devices()
        self._mic_cb = self._combo(self._hrow(s5, label="Mic"),    ["Default"] + devs)
        self._out_cb = self._combo(self._hrow(s5, label="Output"), ["Default"] + devs)

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
        self._chat.tag_config("morph",   foreground=BLUE)
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

    def _save_from_ui(self):
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

        self._write_config(cfg)
        self._cfg = cfg
        self._log_line("Config salvo.", color=GREEN)

    def _on_provider(self, value: str):
        model, key, url = PROVIDER_PRESETS.get(value, ("","",""))
        self._set_entry(self._model_e, model)
        self._set_entry(self._url_e,   url)
        if key:
            self._set_entry(self._apikey_e, key)
        else:
            self._apikey_e.delete(0, "end")

    @staticmethod
    def _set_entry(e: ctk.CTkEntry, val: str):
        e.delete(0, "end")
        e.insert(0, val)

    # ── Pipeline ──────────────────────────────────────────────────────────────
    def _toggle(self):
        if self._running:
            self._stop()
        else:
            self._save_from_ui()
            self._start()

    def _start(self):
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
                text=True, bufsize=1,
                cwd=str(Path(__file__).parent),
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
        elif t == "response":   self._chat_append("morph",   ev.get("text",""), "morph")
        elif t == "inject":     self._chat_append("enviado", ev.get("text",""), "inject")
        elif t == "tts":        self._log_line(f"[TTS] {ev.get('text','')[:70]}")

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

    def _on_close(self):
        if self._running:
            self._stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
