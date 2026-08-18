# Typeless（Windows 版）

本機中文語音聽寫記事本。錄音、辨識、輸出繁體中文，全部在自己的機器上跑，不連任何雲端服務。

一個視窗、一個按鈕、一塊文字區。按 `Ctrl+9` 開始說話，再按一次停止，約一秒後文字出現在游標處。自己剪下、貼到你要用的地方。

```
┌─────────────────────────────────┐
│ 待機                             │  ← 狀態列（綠=待機 紅=錄音中 灰=其他）
├─────────────────────────────────┤
│ ▌         錄音 / 停止         ▐ │  ← 全寬按鈕，文字固定不變
├─────────────────────────────────┤
│                                 │
│  文字編輯區                       │
│                                 │
└─────────────────────────────────┘
```

由 [Ubuntu / GTK4 版](https://github.com/emissionspectrum-creator/Typeless) 移植。

## 它不做什麼

**不會把文字注入到其他 App。** 原版是被 GNOME Wayland 逼的（一般程式無法置頂、搶不回鍵盤焦點）；Windows 沒有這個限制，全域熱鍵和自動貼上都做得到，但移植時刻意維持記事本形態 —— 少一整條焦點時序與剪貼簿還原的坑，代價是多按一次 `Ctrl+X`。

也不做：自動儲存、開檔存檔、字幕輸出、錄音音量顯示、麥克風熱插拔偵測。**關掉視窗文字就沒了。**

## 執行環境

實測組合（其他版本未測）：

| | |
|---|---|
| OS | Windows 11 Pro 26200 |
| Python | 3.13.13 |
| GUI | Tkinter（Tk 8.6.15，Python 內建），深色介面 |
| 錄音 | sounddevice / PortAudio，系統預設輸入裝置 |
| GPU | Vulkan |

模型跑在兩個地方：**encoder 走 CPU（ONNX int4）**，**decoder 走 GPU（llama.cpp Vulkan）**。

實測效能（4.3 秒中文音檔）：

```
暖機   1.23 s
辨識   1.08 s
輸出   這件衣服洗完還沒乾，先晾在陽台。
```

## 安裝

**這個儲存庫不含模型與推論引擎。** 它們來自 `C:\dev\qwen3-asr`（[Qwen3-ASR-GGUF](https://github.com/HaujetZhao/Qwen3-ASR-GGUF) 的本機部署），Typeless 只是借過來用，不複製那 1.5 GB：

- `model\` —— 三個模型檔，共 1.4 GB
- `qwen_asr_gguf\` —— 第三方推論引擎與 llama.cpp 預編譯 DLL（**b8533**，Vulkan）

路徑寫在 `typeless.py` 開頭的 `ASR_HOME`，換機器改那一行。

```bat
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
run.bat
```

桌面捷徑：對 `run.bat` 按右鍵 → 傳送到 → 桌面（建立捷徑）。

## 設定

都在 `typeless.py` 開頭：

| 常數 | 作用 |
|---|---|
| `ASR_HOME` | 模型與推論引擎的位置。**換機器一定要改。** |
| `SILENCE_RMS` | 靜音門檻。本機 Jabra SPEAK 510 實測：環境噪音 RMS 約 1，正常講話整段 RMS 約 1670 |
| `BG` / `TEXT_BG` / `FG` / `BTN_BG` / `BTN_ACTIVE` / `SEL_BG` | 深色介面配色 |
| `IDLE_FG` / `REC_FG` / `DIM_FG` | 狀態列三色（綠＝待機、紅＝錄音中、灰＝其他） |
| `FONT` | 文字區字體與大小 |
| `FIXES` | OpenCC `s2twp` 之後仍需人工修正的詞 |

錄音裝置**不用設**，跟著 Windows 的預設輸入裝置走（控制台 → 音效 → 錄製）。Linux 版那個寫死的裝置名是為了避開「預設來源是喇叭 monitor」的陷阱，Windows 沒有這個問題。

## 快捷鍵

`Ctrl+9` 開始／停止錄音。主鍵盤和數字鍵盤都可以（`KP_9` 和 `KP_Prior` 都綁了，不必管 NumLock）。

**這是 App 內快捷鍵**，視窗要有焦點才有效，不註冊全域熱鍵。

文字區的編輯功能是 Tk 內建的：`Ctrl+X/C/V`、`Ctrl+A` 全選、`Ctrl+Z/Y` 復原重做、中文輸入法。右鍵選單是自己補的（Tk 的 Text 不像 GTK 的 TextView 自帶）。

## 已知限制

- **長錄音完全沒測過。** `n_ctx=2048` 在長音訊下的行為未知。設計上假設每次只講幾十個字。
- **麥克風執行中被拔掉不會偵測。** 啟動時會檢查有沒有可用的輸入裝置，不在就顯示錯誤並停用按鈕。
- **`SILENCE_RMS` 只在這支麥克風上量過。** 同一支 Jabra SPEAK 510，Windows 的環境噪音 RMS 是 1、Ubuntu 是 67，差兩個數量級（驅動的增益與降噪不同）。換麥克風要重新量。
- **`pythonw.exe` 沒有主控台，`sys.stdout` 是 `None`**，任何 `print` 都會炸。推論引擎裡有一行重試訊息沒被 `verbose` 關掉，所以 `typeless.py` 啟動時把 stdout 換成 `StringIO`。除錯時把 `run.bat` 裡的 `pythonw` 改成 `python` 就看得到訊息。
- **llama.cpp 釘在 b8533，換版本不只是換檔案。** `qwen_asr_gguf\inference\llama.py` 是手寫的 ctypes 綁定，5 個結構共 58 個欄位、39 個函式簽章全部照 b8533 的 `llama.h` 寫死。ctypes 靠偏移量存取欄位，上游在結構中間增刪欄位時 DLL 照樣載入、**不會報錯**，但欄位全部錯位。升級要重校 58 個欄位，而且沒有測試抓得到錯位。

## 授權

本儲存庫只包含自己寫的部分（`typeless.py`、文件、設定檔）。模型權重與 `qwen_asr_gguf\` 的推論程式碼授權條件**未確認**，要在別處使用請自行向上游確認。llama.cpp 二進位為 **MIT License**（Copyright (c) 2023-2026 The ggml authors）。
