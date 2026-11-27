# Govee H6630 Pixel Hub 🎮✨

A high-performance, modular desktop companion and live streaming engine for the **Govee Gaming Pixel Light H6630** (32×32 RGB LED Matrix).

Directly interfaces with the device over Bluetooth Low Energy (BLE) + local Govee LAN API (for zero-BLE brightness control) to transform the matrix into an ambient Spotify visualizer, 2D-gradient digital & split-flap clock, Pomodoro focus timer, 32×32 Pixel-Art Studio, Twitch Live-Alert display, and World of Warcraft Character HUD.

---

## ✨ Features

### 🎵 Spotify & Windows Media Visualizer
* **Rounded-Corner Album Art:** 20×20 centered album cover with Lanczos filtering and soft anti-aliased LED corner fade (plus retro vinyl disc fallback).
* **Atmospheric Ambient Glow:** Dynamic aura bleeding out from the cover edges with color normalization.
* **70% Translucent Top Bar:** Sleek horizontal weather icon + crisp white temperature (`2px` minus) across the top edge.
* **Calm & Seamless Marquee:** Infinite horizontal scroll separated by a clean white dot (`Title · Artist`) with vertical font shading.
* **Instant Pause Transition:** Immediately switches to your clock upon pause or playback stop.

### 🕒 2D Gradient Digital Clock & Split-Flap Flip Clock
* **2D Gradient Digital Clock:** Smooth multi-stop color gradients across 5×7 numerals with time-of-day palettes (`Auto`, `Aurora`, `Sunset`, `Ocean`, `Cyberpunk`, `Fire`, or any `Custom` hex color from the dashboard), ambient edge glow, pulsing colon, day/date header, and integrated mini weather.
* **3D Split-Flap Flip Clock:** Optional horizontal & vertical retro flip cards with metallic hinges and split seam.

### 🌙 Automatic Night Mode & LAN Brightness (0 % BLE)
* **Zero-BLE Brightness Control:** Adjusts display brightness via Govee's local LAN API (UDP 4003).
* **Scheduled Night Mode:** Automatically dims brightness and switches to a warm eye-friendly night theme during your configured night hours.

### ⏱️ Pomodoro & Focus Timer
* **Gradient Perimeter Progress Ring:** Animated 32×32 border countdown ring with `MM` / `M:SS` display and a flashing `DONE!` alert when finished.
* **Quick Presets:** `25m Fokus`, `5m Pause`, `15m`, or custom duration & label from the dashboard or system tray.

### 🎨 32×32 Pixel-Art Studio & Image/GIF Upload
* **Interactive Paint Canvas:** Draw directly on a 32×32 canvas in the browser and push it to the H6630.
* **PNG / JPG / GIF Upload:** Upload any image or animated GIF; automatically resized and delta-encoded for the 32×32 matrix.

### ⚔️ World of Warcraft Character HUD (`GoveePixelStats` Addon)
* **Included WoW Addon (`wow-addon/GoveePixelStats`):** Supports Retail, Classic, and `_forever_` (`16001`).
* **Class-Colored Pixel HUD:** Displays character name & sword icon in official Blizzard class colors, level/iLvl, and scrolling stats (`Crit`, `Haste`, `Mastery`, `Versatility`, `Gold`, `Zone`).

### 🟣 Twitch Live-Alerts & 🎮 Auto-Game-Detection
* **Twitch Live-Alerts:** Auth-free background polling alerts you with a pulsing red `● LIVE` banner when favorite streamers go live.
* **Auto-Game-Detection:** Automatically recognizes running PC games and displays a compact game HUD with session timer & CPU bar.

### 🎙️ Discord & Webhook Alerts
* **Toast & Webhook Alerts:** Displays Discord notifications or external triggers via `POST /api/alert`.
* **Local IPC Voice HUD:** Optional Discord Voice activity indicator.

### 📌 Windows System Tray & 🌐 Dark-Mode Web Dashboard (`localhost:5000`)
* **System Tray Icon:** Quick-access tray icon next to the Windows clock (Open Dashboard, 25m Focus Timer, Display On/Off, Quit).
* **LED Matrix Preview:** Realistic 32×32 round-LED grid emulator in the browser.
* **REST API:** Full JSON API (`/api/status`, `/api/config`, `/api/timer`, `/api/custom_art`, `/api/brightness`, `/api/alert`, `/api/switch_plugin`).

---

## 🎧 Bluetooth & AirPods Coexistence Architecture

A common issue with single Bluetooth controllers (such as the Realtek RTL8761B USB adapter) is that streaming high-bitrate A2DP stereo audio to **Apple AirPods Pro** while concurrently doing BLE data transfers can cause audio stutter or link drops.

Pixel Hub solves this through a dedicated low-interference transport layer:
1. **Zero Active Scanning:** Bypasses `BleakScanner` and connects directly via WinRT device handles using the hardware address (`CC:B8:5E:BE:0F:99`).
2. **Paced Packet Intervals & Skip Debounce:** Uses 35 ms packet pacing, 750 ms track-skip debounce, and 800 ms inter-upload gap so rapid Spotify skips never congest the BLE link.
3. **Optimized GIF Payloads:** Delta-frame encoding keeps clock updates under ~880 bytes and Spotify marquees around ~3.8 KB (with fullscreen weather carousel disabled by default).
4. **Persistent Session Handling:** Eliminates repeated connect/disconnect renegotiations during song changes.

> [!TIP]
> **Windows AirPods Optimization:**
> If you experience audio dropouts with AirPods on Windows when any Bluetooth device connects, open **Control Panel** $\rightarrow$ **Devices and Printers** $\rightarrow$ right-click **AirPods Pro** $\rightarrow$ **Properties** $\rightarrow$ **Services** tab, and uncheck **"Hands-Free Telephony"**. This locks Windows into dedicated high-quality A2DP stereo without dropping connections.

---

## 🚀 Quick Start (Windows 10 / 11)

### Prerequisites
* **Windows 10 (Build 19041+) or Windows 11**
* **Python 3.10+** (ensure *"Add Python to PATH"* is checked during installation)
* **Bluetooth Adapter** (BLE 4.2+)

### 1. Installation
Clone the repository and run the 1-click installer:
```cmd
git clone https://github.com/syqdur/govee-pixel-hub.git
cd govee-pixel-hub
Install-PixelHub.bat
```
The installer automatically creates an isolated virtual environment (`.venv-pixel`), upgrades `pip`, and installs all necessary dependencies.

### 2. Starting the Hub
Double-click:
```cmd
Start-PixelHub.bat
```
* The daemon connects to your Govee H6630 and starts the background worker.
* Your default web browser will automatically open to the dashboard at **http://127.0.0.1:5000/**.

To stop the service cleanly and turn off the display LEDs, run `Stop-PixelHub.bat`.

---

## ⚙️ Configuration Reference (`display_hub.json`)

Settings can be edited live via the Web Dashboard or in `display_hub.json`:

| Key | Default | Description |
| :--- | :--- | :--- |
| `text_speed_ms` | `150` | Marquee step interval in milliseconds (higher = slower, calmer scroll) |
| `text_hold_ms` | `1200` | Duration (ms) the track title stays still before scrolling begins |
| `spotify_font_mini` | `true` | Use compact 3×5 font for titles and artist names |
| `spotify_text_mode` | `"marquee"` | `"marquee"` (smooth gliding marquee) or `"pages"` (flip pages every 3s) |
| `spotify_ambient_breath` | `false` | Enable breathing animation on ambient aura (`false` saves BLE bandwidth) |
| `spotify_mini_clock` | `false` | Display mini digital clock on the left edge of Spotify screen |
| `spotify_show_weather` | `true` | Display outdoor weather badge on the right edge of Spotify screen |
| `spotify_eq` | `false` | Overlay dynamic spectrum equalizer bars on album art |
| `show_paused_spotify` | `false` | If `false`, immediately yields display to the Flip-Clock when music pauses |
| `idle_clock` | `true` | Enable idle clock when no media is playing |
| `clock_style` | `"flip"` | `"flip"` (split-flap) or `"digital"` (classic 5×7 digital) |
| `flip_style` | `"horizontal"` | `"horizontal"` (side-by-side) or `"vertical"` (stacked retro cards) |
| `clock_color` | `"#ffffff"` | Color hex code for digital clock numerals |
| `weather_enabled` | `true` | Enable live weather updates via Open-Meteo |
| `weather_city` | `"Berlin"` | City name for weather geolocation |
| `hardware_enabled` | `false` | Enable CPU/RAM hardware monitor in the idle carousel |
| `discord_enabled` | `false` | Enable Discord toast notification popups |
| `discord_voice_enabled`| `false` | Enable Discord voice channel HUD and speaking indicator |
| `carousel_seconds` | `15` | Time (seconds) each widget stays visible during idle rotation |
| `web_port` | `5000` | Port for the local Web Dashboard and REST API |

---

## 🧩 Architecture

```text
govee-pixel-hub/
├── core/
│   ├── ble_driver.py          # BLE connection & GIF streaming driver
│   ├── plugin_base.py         # Plugin abstract base class & status lifecycle
│   ├── priority_manager.py    # Alert interrupts, media priority & idle carousel
│   └── web_server.py          # Local HTTP daemon & REST API
├── plugins/
│   ├── spotify_plugin.py      # WinRT SystemMediaTransportControls session polling
│   ├── clock_plugin.py        # Split-flap flip clock & digital clock renderer
│   ├── weather_plugin.py      # Open-Meteo weather client & 14x14 weather glyphs
│   ├── discord_voice_plugin.py# Discord local IPC client & voice activity tracker
│   ├── discord_plugin.py      # Windows notification listener
│   └── hardware_plugin.py     # psutil CPU/RAM metrics
├── web/
│   └── index.html             # Responsive dark-mode dashboard & matrix emulator
├── hub.py                     # Main orchestrator loop
├── pixel_ble.py               # Direct Bleak / WinRT transport client
├── pixel_font.py              # Proportional pixel fonts (3x5, 5x7, Flip-Clock)
├── pixel_frame.py             # Binary protocol packer (0xA4 0x58 MTU framing)
├── scenes.py                  # PIL 32x32 rendering engine & GIF89a LZW encoder
├── display_hub.example.json   # Default template configuration
└── requirements.txt           # Unified Python dependency specification
```

---

## 🧪 Unit Tests

All rendering routines, font glyph tables, packet serializers, and plugin priority rules are backed by automated tests:

```cmd
.venv-pixel\Scripts\python.exe -m unittest discover tests
```

---

## 📄 License

MIT License. Designed with ❤️ for the Govee maker community.
