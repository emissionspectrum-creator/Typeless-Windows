#!/usr/bin/env python3
# coding=utf-8
"""Typeless —— 本機中文語音聽寫記事本（Windows 版）

按錄音鈕或 Ctrl+9 開始／停止錄音，辨識結果插在游標處。
自己不注入其他 App，用 Ctrl+X 剪下再貼到目標視窗。

由 Ubuntu / GTK4 版移植。差異：GTK4 → Tkinter、parecord → sounddevice、
模型與推論引擎不放在本專案，改指向 ASR_HOME。見 README.md。
"""
import contextlib
import ctypes
import io
import os
import sys
import tempfile
import threading
import tkinter as tk
import wave
from tkinter import ttk

import numpy as np
import sounddevice as sd

# 模型與推論引擎在別的專案底下，這裡只借過來用，不複製 1.5 GB 檔案。
# 換機器只要改這一行。
ASR_HOME = r"C:\dev\qwen3-asr"

sys.path.insert(0, ASR_HOME)
from qwen_asr_gguf.inference import ASREngineConfig, QwenASREngine  # noqa: E402

# Windows 用系統預設輸入裝置就好，不必像 Linux 那樣指名裝置 ——
# 那邊的預設來源是喇叭的 monitor（錄出來全是零），這邊沒有這個陷阱。
SAMPLE_RATE = 16000
BLOCK = 320           # 320 frames = 20 ms。放任 PortAudio 自己決定的話，
                      # 每次回呼會吐一大塊，起止邊界會差到 ±1 秒。

SILENCE_RMS = 300.0   # 靜音門檻。本機實測（Jabra SPEAK 510）：環境噪音 RMS 約 1，
                      # 正常講話整段 RMS 約 1670。門檻夾在中間，兩邊餘裕都很大。
                      # 換麥克風要重新量。
MIN_SECONDS = 0.3

# s2twp 之後仍需修正的（實測清單）
FIXES = [("還沒幹", "還沒乾"), ("臺南", "台南"), ("陽臺", "陽台")]

# 深色配色。Tk 沒有主題引擎，每個元件的顏色都要自己指定。
# 兩個狀態色沿用 Ubuntu 版的值 —— 它們本來就是為深色底調的。
# 文字區字體大小：改 FONT 那個數字就好。
BG = "#1E1E1E"          # 視窗底
TEXT_BG = "#252526"     # 文字區底
FG = "#E0E0E0"          # 一般文字
BTN_BG = "#333337"
BTN_ACTIVE = "#3F3F46"  # 按鈕被按下／滑鼠移過去
SEL_BG = "#264F78"      # 選取範圍
IDLE_FG = "#6FBF9F"     # 綠：待機
REC_FG = "#D9776F"      # 紅：錄音中
DIM_FG = "#9A9A9A"      # 灰：其他訊息
FONT = ("Microsoft JhengHei UI", 14)


# --- 錄音 -------------------------------------------------------------

class Recorder:
    """以 16kHz/16-bit/單聲道 擷取，不做取樣率轉換。

    全程常駐、閒置時把資料丟掉。每次現開串流要等裝置喚醒，實測會吃掉開頭
    約 1 秒，講話會被切頭。代價是麥克風指示燈一直亮著。
    """

    def __init__(self):
        self.chunks = None        # None = 未在錄音
        self.lock = threading.Lock()
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16",
            blocksize=BLOCK, callback=self._pump)
        self.stream.start()

    def _pump(self, indata, _frames, _time, _status):
        # PortAudio 的執行緒，回呼一結束緩衝區就被重用，一定要複製一份出來。
        with self.lock:
            if self.chunks is not None:
                self.chunks.append(indata.tobytes())

    def start(self):
        with self.lock:
            self.chunks = []

    def stop(self):
        with self.lock:
            pcm = b"".join(self.chunks or [])
            self.chunks = None
        return pcm

    def shutdown(self):
        self.stream.stop()
        self.stream.close()


def pcm_stats(pcm):
    a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if a.size == 0:
        return 0.0, 0.0
    return a.size / SAMPLE_RATE, float(np.sqrt((a * a).mean()))


def to_wav(pcm):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


# --- 辨識 -------------------------------------------------------------

class Engine:
    def __init__(self):
        cfg = ASREngineConfig(
            model_dir=os.path.join(ASR_HOME, "model"),
            encoder_frontend_fn="qwen3_asr_encoder_frontend.int4.onnx",
            encoder_backend_fn="qwen3_asr_encoder_backend.int4.onnx",
            llm_fn="qwen3_asr_llm.q5_k.gguf",
            onnx_provider="CPU", llm_use_gpu=True,
            n_ctx=2048, enable_aligner=False, verbose=False)
        self.engine = QwenASREngine(config=cfg)
        import opencc
        self.cc = opencc.OpenCC("s2twp")

    def transcribe(self, wav_bytes):
        fd, path = tempfile.mkstemp(suffix=".wav")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(wav_bytes)
            # 引擎會邊解碼邊把簡體原文印到 stdout，擋掉。
            # （Windows 主控台是 cp950，簡體字直接印會 UnicodeEncodeError。）
            with contextlib.redirect_stdout(io.StringIO()):
                # duration 必須明確傳 None，否則預設 0.0 會讀取 0 個音框
                res = self.engine.transcribe(
                    audio_file=path, language=None, context="",
                    start_second=0.0, duration=None, temperature=0)
        finally:
            os.unlink(path)
        text = self.cc.convert(res.text)
        for bad, good in FIXES:
            text = text.replace(bad, good)
        return text.strip()

    def shutdown(self):
        self.engine.shutdown()


# --- 視窗 -------------------------------------------------------------

def dark_titlebar(root):
    """標題列不歸 Tk 管，要跟 Windows 講一聲，否則深色視窗頂著一條白邊。

    設定後已經畫好的標題列不會自己重畫，收合再展開一次逼它重來。
    失敗就算了 —— 只是難看，不影響功能。
    """
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # 20 = 用深色標題列
            hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
        root.withdraw()
        root.deiconify()
    except Exception:
        pass


class App:
    def __init__(self):
        self.state = "warm"
        self.engine = None
        self.rec = None

        self.root = tk.Tk()
        self.root.title("Typeless")
        self.root.geometry("520x440")
        self.root.configure(bg=BG)
        dark_titlebar(self.root)

        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=8, pady=8)

        # 狀態列：靠左、單行。換行會讓下面整塊往下推。
        self.status = tk.Label(frame, anchor="w", text="", bg=BG, fg=DIM_FG)
        self.status.pack(fill="x")

        # 標籤固定不變，任何狀態都一樣 —— 它只是開關，狀態全在狀態列。
        # 不可聚焦：焦點停在按鈕上時空白鍵和 Enter 會再次觸發它，
        # 使用者以為在打字，其實在開關錄音。滑鼠點擊不需要焦點照樣有效。
        # relief=flat：Windows 的立體邊框在深色底上看起來像沒對齊。
        self.button = tk.Button(frame, text="錄音 / 停止", takefocus=0,
                                command=self.toggle,
                                bg=BTN_BG, fg=FG,
                                activebackground=BTN_ACTIVE, activeforeground=FG,
                                disabledforeground=DIM_FG,
                                relief="flat", highlightthickness=0)
        self.button.pack(fill="x", ipady=12, pady=(6, 6))

        text_box = tk.Frame(frame, bg=BG)
        text_box.pack(fill="both", expand=True)
        # Windows 的 tk.Scrollbar 走系統畫法，bg/troughcolor 全被忽略，
        # 深色底上就是一條白。只有 ttk 的 clam 主題吃得到顏色。
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Vertical.TScrollbar",
                        background=BTN_BG, troughcolor=TEXT_BG,
                        bordercolor=BG, arrowcolor=FG,
                        darkcolor=BTN_BG, lightcolor=BTN_BG)
        style.map("Dark.Vertical.TScrollbar",
                  background=[("active", BTN_ACTIVE)])
        scroll = ttk.Scrollbar(text_box, style="Dark.Vertical.TScrollbar")
        scroll.pack(side="right", fill="y")
        # undo=True 才有 Ctrl+Z / Ctrl+Y，Tk 預設是關的。
        # 其餘 Ctrl+X/C/V/A 是 Tk 內建，不用綁。
        # insertbackground 是游標顏色，不設的話深色底上會看不見。
        self.view = tk.Text(text_box, wrap="char", undo=True, font=FONT,
                            padx=6, pady=6, yscrollcommand=scroll.set,
                            bg=TEXT_BG, fg=FG, insertbackground=FG,
                            selectbackground=SEL_BG, selectforeground=FG,
                            relief="flat", highlightthickness=0)
        self.view.pack(side="left", fill="both", expand=True)
        scroll.config(command=self.view.yview)

        # GTK 的 TextView 自帶右鍵選單，Tk 沒有，補一個。
        self.menu = tk.Menu(self.root, tearoff=0, bg=TEXT_BG, fg=FG,
                            activebackground=SEL_BG, activeforeground=FG,
                            borderwidth=0)
        for label, event in (("剪下", "<<Cut>>"), ("複製", "<<Copy>>"),
                             ("貼上", "<<Paste>>")):
            self.menu.add_command(
                label=label,
                command=lambda e=event: self.view.event_generate(e))
        self.menu.add_separator()
        self.menu.add_command(
            label="全選", command=lambda: self.view.event_generate("<<SelectAll>>"))
        self.view.bind("<Button-3>", self.popup)

        # 數字鍵盤的 9 是不同的 keysym，而且隨 NumLock 改變：
        # 開 -> KP_9，關 -> KP_Prior。兩個都綁，使用者不必管 NumLock。
        for seq in ("<Control-Key-9>", "<Control-KP_9>", "<Control-KP_Prior>"):
            self.root.bind_all(seq, lambda _e: self.toggle())

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.view.focus_set()
        self.set_status("載入模型中…", DIM_FG)
        self.button.config(state="disabled")
        threading.Thread(target=self.warm_up, daemon=True).start()

    def popup(self, event):
        self.view.focus_set()
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # --- 狀態列 ---

    def set_status(self, text, fg=DIM_FG):
        self.status.config(text=text, fg=fg)

    def go_idle(self):
        self.state = "idle"
        self.button.config(state="normal")
        self.set_status("待機", IDLE_FG)

    # --- 暖機 ---

    def warm_up(self):
        # 沒有麥克風的話，不檢查只會一路錄到 rms=0 的空音訊。
        # GUI 版沒有人看得到 stderr，錯誤一定要進狀態列。
        try:
            sd.check_input_settings(
                samplerate=SAMPLE_RATE, channels=1, dtype="int16")
        except Exception:
            self.later(self.go_dead, "找不到麥克風，請接上後重開")
            return
        try:
            engine = Engine()
            rec = Recorder()
        except Exception as e:
            self.later(self.go_dead, f"載入失敗：{e}")
            return
        self.later(self.on_ready, engine, rec)

    def later(self, fn, *args):
        """從工作執行緒回到主執行緒 —— Tk 的元件只准主執行緒碰。"""
        self.root.after(0, fn, *args)

    def on_ready(self, engine, rec):
        self.engine = engine
        self.rec = rec
        self.go_idle()

    def go_dead(self, msg):
        self.state = "dead"
        self.button.config(state="disabled")
        self.set_status(msg)

    # --- 錄音／辨識 ---

    def toggle(self):
        # Ctrl+9 不受按鈕 disable 影響，狀態要自己擋
        if self.state == "idle":
            self.state = "rec"
            self.rec.start()
            self.set_status("錄音中", REC_FG)
        elif self.state == "rec":
            pcm = self.rec.stop()
            self.state = "busy"
            self.button.config(state="disabled")
            self.set_status("辨識中…", DIM_FG)
            threading.Thread(target=self.work, args=(pcm,), daemon=True).start()

    def work(self, pcm):
        secs, rms = pcm_stats(pcm)
        if secs < MIN_SECONDS or rms < SILENCE_RMS:
            # 不顯示的話，使用者體感就是「按了沒反應」。
            self.later(self.done, None, f"靜音跳過（{secs:.1f}s）")
            return
        try:
            text = self.engine.transcribe(to_wav(pcm))
        except Exception as e:
            self.later(self.done, None, f"辨識失敗：{e}")
            return
        if not text:
            self.later(self.done, None, f"辨識結果是空的（{secs:.1f}s）")
            return
        self.later(self.done, text, None)

    def done(self, text, msg):
        if text:
            # 原樣插在游標處，不自動加換行或空白 —— 要斷句由使用者自己按 Enter。
            # 插入後游標會停在文字末端。
            self.view.insert("insert", text)
        self.go_idle()
        if msg:
            # 灰色訊息一直留著，直到下次開始錄音才被蓋掉。不用計時器。
            self.set_status(msg)

    # --- 收尾 ---

    def on_close(self):
        if self.rec:
            self.rec.shutdown()
        if self.engine:
            self.engine.shutdown()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    # pythonw.exe 沒有主控台，sys.stdout 是 None，任何 print 都會炸。
    # 推論引擎裡有一行重試訊息沒被 verbose 關掉。
    if sys.stdout is None:
        sys.stdout = sys.stderr = io.StringIO()
    App().run()
