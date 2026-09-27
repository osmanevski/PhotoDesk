<p align="center"><img src="static/icon.png" width="104" alt="PhotoDesk icon"></p>
<h1 align="center">PhotoDesk</h1>
<p align="center">One scan. Many photographs. Every story kept together.<br>Bir taramada çok fotoğraf. Her fotoğrafın hikâyesi bir arada.</p>
<p align="center"><strong>English</strong> · <a href="README.tr.md">Türkçe</a></p>

## English

PhotoDesk is a local macOS app for turning sheets of scanned photographs into individual archives. Separate multiple prints, straighten skewed edges, match handwritten backs, and export each photo as a high-quality JPEG. Start without AI, or choose a Codex model or OpenRouter API model when you want visual interpretation and natural-language revisions.

## Türkçe

**PhotoDesk**, tek taramadaki birden fazla fotoğrafı ayıran, eğik kenarlarını düzelten ve yazılı arka yüzlerini fotoğraflarla birleştiren bir **macOS uygulamasıdır**. Boş arkaları çıktıya eklemez; her fotoğrafı yüksek kaliteli JPEG olarak kaydeder. Köşeleri, yönü, eşleşmeleri ve dosya adlarını kaydetmeden önce düzenleyebilirsin.

**Yapay zekâsız ve çevrimdışı** kullanılabilir. Görsel yorumlama ve doğal dille düzeltme için isteğe bağlı **Codex** veya **OpenRouter API** desteği bulunur. Arayüz İngilizce açılır; üst çubuktan **Türkçe** seçebilirsin. Orijinal taramalar korunur, yalnız onayladığın sonuçlar yeni klasöre kaydedilir.

Başlamak için depoyu indirip `python3 install_macos.py` çalıştır, ardından **PhotoDesk** uygulamasını aç ve taramalarını sürükleyip bırak. macOS ve Python 3.11+ gerekir.

**[Türkçe kurulum, kullanım ve veri saklama rehberi →](README.tr.md)**

![PhotoDesk reviewing a synthetic sample archive](docs/screenshot.png)
*Illustrated test prints, not personal photographs.*

## What it does

- **Multiple scans at once.** Drag and drop JPEG, PNG, TIFF, PDF or HEIC files.
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

## Archive a batch

1. Create a batch and drop in the front and back scans.
2. For automatic grouping, name scans `1a.jpeg` / `1b.jpeg`, `2a.jpeg` / `2b.jpeg`, and so on: **a = front**, **b = back**. Keep each print in the same position when turning it over. Other filenames can be uploaded, but local automatic pairing requires a numeric group; use the editable pairing controls for special names.
3. Choose **Local · No AI**, **AI · Codex**, or **API · OpenRouter**. If prints touch, choose a layout such as **2 × 2**.
4. Review the detected boundaries, orientation and matches. Faint writing and white paper on a white scanner lid need particular care. Set missing-back photos to **No back — save front only** when appropriate, then approve the results.
5. Select **Save JPEGs**. Only approved photos are exported, into a new timestamped folder. Open it in Finder or download a ZIP. `arsiv-kaydi.json` records the plan, source hashes and processing settings.

The writing on a back follows the portrait/landscape orientation of its photo and may remain sideways. Physical borders and notes on the front belong to the print and should be retained.

## Processing modes

| Mode | What runs | What to expect |
| --- | --- | --- |
| Local | OpenCV and Pillow on your Mac | No model or network requests. Geometry and position-based pairing, sequential names, manual orientation review. Every suggestion needs approval. |
| Codex | Your installed, signed-in Codex CLI | Visual analysis, descriptive names and natural-language revisions. Model and supported effort levels come from the local Codex catalog. Images are sent to the chosen model. |
| OpenRouter | Your chosen image + structured-output API model | Separate model/effort preferences, catalog refresh and paid API usage billed to your OpenRouter account. |

**Codex:** install and sign in to Codex CLI separately. The model calls use an isolated, tool-disabled, read-only session. The chosen model and effort are never silently replaced. CLI integration was exercised with version 0.157.1; future CLI changes may require updates.

**OpenRouter:** select the API mode, add your key, test the connection, refresh models, and select a model. The key is stored in a dedicated macOS Keychain item, never returned to the browser or written to the app state. The connection test validates the key without sending photos or invoking a model. Models without advertised effort levels use their default. Cancelling stops local waiting/result application; it may not cancel or refund an already submitted remote request.

## Storage and limits

Original files are unchanged. Imported copies, working images and batch state stay under:

```text
~/Library/Application Support/FotografMasasi/
```

The legacy data directory and `com.osmanevski.fotografmasasi` bundle identifier are intentionally retained for upgrades. Default exports go to `~/Downloads/Fotograf-Masasi/`; choose another folder in the export dialog.

A batch supports up to **100 scan pages / 200 print sides**; each upload request is limited to **512 MB**. One analysis job runs at a time. PDF pages containing an equivalent single image use that embedded image; other pages are rasterized at up to 600 DPI / 60 MP. AI uses previews up to 2100 pixels; final exports use the full-resolution working images.

There is no scanner-control button or background folder watcher: import completed scans with drag and drop. Local detection cannot reliably infer the subject, upright orientation or every faint inscription; inspect the results. Closing a browser tab does not stop the server or an active analysis. Use **Cancel** to stop an analysis. To stop the server, quit its `app.py` process in Activity Monitor.

## Develop and test

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -v
python app.py --data /tmp/photodesk-dev --port 8875
```

Tests use synthetic images and mocked model calls; they do not require a paid API key. The app and test suite target macOS because credentials use the system Keychain. Live paid OpenRouter photo analysis is not part of the test suite.

UI logic and Turkish copy are maintained in `locales/tr/`; `locales/en.json` contains the English catalog. The build translates source literals, never user data in the live DOM. Rebuild generated assets after changing either source:

```sh
python scripts/build_icon.py
python scripts/build_locales.py
python scripts/build_locales.py --check
```

`static/icon.svg` is the vector mark; `build_icon.py` renders matching PNG and ICNS assets. `locales/server.en.json` covers application status/errors. AI output follows the language selected when the job starts; older notes are not retroactively translated.

The behavioral prompt is in `skills/fotograf-arsivi/SKILL.md`. It guides analysis; pixel transformations stay in local code. No sample personal scans, API credentials or runtime state are included in this repository.
