<p align="center"><img src="static/icon.png" width="104" alt="PhotoDesk icon"></p>
<h1 align="center">PhotoDesk</h1>
<p align="center">One scan. Many photographs. Every story kept together.<br>Bir taramada çok fotoğraf. Her fotoğrafın hikâyesi bir arada.</p>
<p align="center"><strong>English</strong> · <a href="README.tr.md">Türkçe</a></p>

## English

PhotoDesk is a local app for macOS, Windows and Linux for turning sheets of scanned photographs into individual archives. Separate multiple prints, straighten skewed edges, match handwritten backs, and export each photo as a high-quality JPEG. Start without AI, or choose a Codex model or OpenRouter API model when you want visual interpretation and natural-language revisions.

## Türkçe

**PhotoDesk**, tek taramadaki birden fazla fotoğrafı ayıran, eğik kenarlarını düzelten ve yazılı arka yüzlerini fotoğraflarla birleştiren **macOS, Windows ve Linux üzerinde çalışan yerel bir uygulamadır**. Boş arkaları çıktıya eklemez; her fotoğrafı yüksek kaliteli JPEG olarak kaydeder. Köşeleri, yönü, eşleşmeleri ve dosya adlarını kaydetmeden önce düzenleyebilirsin.

**Yapay zekâsız ve çevrimdışı** kullanılabilir. Görsel yorumlama ve doğal dille düzeltme için isteğe bağlı **Codex** veya **OpenRouter API** desteği bulunur. Arayüz İngilizce açılır; üst çubuktan **Türkçe** seçebilirsin. Orijinal taramalar korunur, yalnız onayladığın sonuçlar yeni klasöre kaydedilir.

Başlamak için depoyu indirip `python3 install_macos.py` çalıştır, ardından **PhotoDesk** uygulamasını aç ve taramalarını sürükleyip bırak. Windows/Linux kurulum komutları aşağıda; Python 3.11+ gerekir.

**[Türkçe kurulum, kullanım ve veri saklama rehberi →](README.tr.md)**

![PhotoDesk reviewing a synthetic sample archive](docs/screenshot.png)
*Illustrated test prints, not personal photographs.*

## What it does

- **Multiple scans at once.** Drag and drop JPEG, PNG, TIFF or PDF files. HEIC import remains macOS-only.
- **Front and back together.** Portrait photos use a side-by-side layout; landscape photos use a stacked layout. Blank backs are omitted. A missing back is never silently treated as blank.
- **Editable results.** Drag the four corners, rotate a print, change its pairing or filename, approve individual results, and undo the last 30 plan changes.
- **Full-resolution exports.** Perspective correction, aligned edges, a 24-pixel separator, JPEG quality 100 with 4:4:4 chroma sampling, and source DPI metadata. Geometric operations resample pixels; JPEG is not lossless.
- **English and Turkish.** English is the default. Change the language in the top bar; the choice is remembered in your browser. Existing batch names and notes are preserved.

## Install on macOS

Use Python **3.11 or newer** (3.12 recommended). Keep the checkout in a permanent location: the launcher runs the code from this folder.

```sh
git clone https://github.com/osmanevski/PhotoDesk.git
cd PhotoDesk
python3 install_macos.py
```

The installer creates `~/Applications/PhotoDesk.app`, a Desktop shortcut, and an isolated Python environment. Open **PhotoDesk** to launch the interface at **http://127.0.0.1:8874**. It listens on loopback only. The launcher is not a signed or notarized standalone distribution.

Existing Fotoğraf Masası installations retain their working data, Keychain entry and runtime. The installer renames the existing app bundle when it recognizes the bundle identifier. `--skip-deps` reuses an already installed runtime.

## Install on Windows / Linux

Use **Python 3.11+** (3.12 recommended). These are source installs, not standalone `.exe` or AppImage bundles. One codebase is shared by all systems; no extra pip dependencies are needed for OS integration.

Windows (native Python from python.org, not Microsoft Store Python):

```powershell
git clone https://github.com/osmanevski/PhotoDesk.git
cd PhotoDesk
py -3.12 install.py
py -3.12 start.py
```

Linux desktop:

```sh
git clone https://github.com/osmanevski/PhotoDesk.git
cd PhotoDesk
python3 install.py
python3 start.py
```

On Debian/Ubuntu, install `python3-venv` if Python reports that venv/ensurepip is missing. `xdg-utils` provides the Open folder action. **Only OpenRouter key storage** requires `libsecret-tools` (`secret-tool`) and an unlocked desktop Secret Service (such as GNOME Keyring). Without a credential store, Local and Codex modes still work. Keys are never silently saved in plaintext. A missing desktop browser/file manager does not prevent JPEG export; open the printed URL or export folder manually.

`install.py` also works on macOS by invoking the existing Mac installer. Keep the checkout in place. After updating the checkout, rerun the installer and restart the server. `start.py` uses the installed runtime without activating a venv; it accepts `--no-open`, `--data PATH`, and `--port PORT`.

## Archive a batch

1. Create a batch and drop in the front and back scans.
2. For automatic grouping, name scans `1a.jpeg` / `1b.jpeg`, `2a.jpeg` / `2b.jpeg`, and so on: **a = front**, **b = back**. Keep each print in the same position when turning it over. Other filenames can be uploaded, but local automatic pairing requires a numeric group; use the editable pairing controls for special names.
3. Choose **Local · No AI**, **AI · Codex**, or **API · OpenRouter**. If prints touch, choose a layout such as **2 × 2**.
4. Review the detected boundaries, orientation and matches. Faint writing and white paper on a white scanner lid need particular care. Set missing-back photos to **No back — save front only** when appropriate, then approve the results.
5. Select **Save JPEGs**. Only approved photos are exported, into a new timestamped folder. Open it in your file manager or download a ZIP. `arsiv-kaydi.json` records the plan, source hashes and processing settings.

The writing on a back follows the portrait/landscape orientation of its photo and may remain sideways. Physical borders and notes on the front belong to the print and should be retained.

## Processing modes

| Mode | What runs | What to expect |
| --- | --- | --- |
| Local | OpenCV and Pillow on your computer | No model or network requests. Geometry and position-based pairing, sequential names, manual orientation review. Every suggestion needs approval. |
| Codex | Your installed, signed-in Codex CLI | Visual analysis, descriptive names and natural-language revisions. Model and supported effort levels come from the local Codex catalog. Images are sent to the chosen model. |
| OpenRouter | Your chosen image + structured-output API model | Separate model/effort preferences, catalog refresh and paid API usage billed to your OpenRouter account. |

**Codex:** install and sign in to Codex CLI separately. The model calls use an isolated, tool-disabled, read-only session. The chosen model and effort are never silently replaced. CLI integration on macOS was exercised with version 0.157.1; future CLI changes may require updates. Windows needs a native Codex installation (an installation inside WSL is separate). Native `codex.exe` and the standard npm `codex.cmd` layout are supported; the npm entry point is run through Node directly, without a command shell. `PHOTODESK_CODEX` can select an explicit executable, and `CODEX_HOME` selects the model catalog. CI tests process handling with synthetic commands; it does not run paid model calls or certify every CLI version’s sandbox setup.

**OpenRouter:** select the API mode, add your key, test the connection, refresh models, and select a model. The key is stored in macOS Keychain, Windows Credential Manager, or Linux Secret Service, never returned to the browser or written to the app state. The connection test validates the key without sending photos or invoking a model. Models without advertised effort levels use their default. Cancelling stops local waiting/result application; it may not cancel or refund an already submitted remote request.

## Storage and limits

Original files are unchanged. Imported copies, working images and batch state stay under:

```text
macOS:   ~/Library/Application Support/FotografMasasi/
Windows: %LOCALAPPDATA%\PhotoDesk\
Linux:   $XDG_DATA_HOME/photodesk/ (default: ~/.local/share/photodesk/)
```

The legacy data directory and `com.osmanevski.fotografmasasi` bundle identifier are intentionally retained for upgrades. Default exports go to `~/Downloads/Fotograf-Masasi/`; choose another folder in the export dialog.

A batch supports up to **100 scan pages / 200 print sides**; each upload request is limited to **512 MB**. One analysis job runs at a time. PDF pages containing an equivalent single image use that embedded image; other pages are rasterized at up to 600 DPI / 60 MP. AI uses previews up to 2100 pixels; final exports use the full-resolution working images.

There is no scanner-control button or background folder watcher: import completed scans with drag and drop. Local detection cannot reliably infer the subject, upright orientation or every faint inscription; inspect the results. Closing a browser tab does not stop the server or an active analysis. Use **Cancel** to stop an analysis. To stop the server, end its `app.py` process in your system process manager (Activity Monitor, Task Manager, or your Linux desktop equivalent). Avoid stopping it while a job is running. A per-data-folder process lock prevents duplicate writers.

## Develop and test

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -v
python app.py --data /tmp/photodesk-dev --port 8875
```

Tests use synthetic images and mocked model calls; they do not require a paid API key. CI runs on macOS, Ubuntu and Windows with Python 3.12, plus Windows/Python 3.11. Tests cover JPEG processing/export, UTF-8, credential-unavailable startup, upload cleanup, server locks, and process-tree termination. A Windows-only credential test creates and removes an isolated synthetic entry; it never accesses a personal key. Linux Secret Service and macOS keychain operations are mocked, so desktop unlock dialogs still need manual validation. Live paid OpenRouter photo analysis is not part of the test suite.

The interface is plain JavaScript with no build step: `static/app.js`, `static/style.css` and `static/index.html`. Every interface string lives once in `static/strings.json` under `en` and `tr`; the server embeds the selected language into the page, and user data is never translated. The test suite fails if a key is missing from either language. After changing the icon:

```sh
python scripts/build_icon.py
```

`static/icon.svg` is the vector mark; `build_icon.py` renders matching PNG and ICNS assets. `locales/server.en.json` covers application status/errors. AI output follows the language selected when the job starts; older notes are not retroactively translated.

The behavioral prompt is in `skills/fotograf-arsivi/SKILL.md`. It guides analysis; pixel transformations stay in local code. No sample personal scans, API credentials or runtime state are included in this repository.
