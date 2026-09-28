<p align="center"><img src="static/icon.png" width="104" alt="PhotoDesk ikonu"></p>
<h1 align="center">PhotoDesk</h1>
<p align="center">Bir taramada çok fotoğraf. Her fotoğrafın hikâyesi bir arada.</p>
<p align="center"><a href="README.md">English</a> · <strong>Türkçe</strong></p>

PhotoDesk, aynı taramadaki fotoğrafları ayıran, eğik kenarları düzleştiren ve yazılı arkalarını önleriyle birleştiren macOS, Windows ve Linux için yerel bir uygulamadır. Yapay zekâ kullanmadan başlayabilir; görsel yorumlama ve doğal dille düzeltme için Codex veya OpenRouter seçebilirsin. İngilizce varsayılandır; üst çubuktan Türkçe seçilir ve tercih tarayıcıda korunur.

![Örnek çizimlerle PhotoDesk arayüzü](docs/screenshot.png)

## Kurulum

macOS ve Python 3.11+ gerekir; 3.12 önerilir. Uygulama kodu bu klasörden çalıştığı için depoyu kalıcı bir yerde tut.

```sh
git clone https://github.com/osmanevski/PhotoDesk.git
cd PhotoDesk
python3 install_macos.py
```

`~/Applications/PhotoDesk.app`, Masaüstü kısayolu ve bağımsız Python ortamı oluşturulur. Uygulamayı açınca tarayıcıda `http://127.0.0.1:8874` açılır; sunucu yalnız yerel bağlantıları kabul eder. Paket imzalı/noter onaylı bağımsız dağıtım değildir. Önceki Fotoğraf Masası kurulumunun çalışma kayıtları ve Anahtar Zinciri kaydı korunur.

## Windows ve Linux kurulumu

Python 3.11+ gerekir; 3.12 önerilir. Bunlar aynı kaynak koddan kurulumdur; bağımsız EXE/AppImage paketleri değildir. İşletim sistemi desteği için ek pip bağımlılığı yoktur.

Windows (python.org Python kurulumu; Microsoft Store sürümü desteklenmez):

```powershell
git clone https://github.com/osmanevski/PhotoDesk.git
cd PhotoDesk
py -3.12 install.py
py -3.12 start.py
```

Linux masaüstü:

```sh
git clone https://github.com/osmanevski/PhotoDesk.git
cd PhotoDesk
python3 install.py
python3 start.py
```

Debian/Ubuntu'da venv eksikse `python3-venv`, klasör açma için `xdg-utils` gerekir. **Yalnız OpenRouter anahtarını saklamak için** `libsecret-tools` (`secret-tool`) ve açık bir masaüstü Secret Service kasası gerekir. Kasa yokken Yerel ve Codex modları çalışır; anahtar düz metin dosyaya yazılmaz. Windows'ta Codex yerel kurulmalıdır; WSL içindeki kurulum ayrı ortamdır. Standart npm kurulumu ve `codex.exe` desteklenir. Gerekirse `PHOTODESK_CODEX` ile yolu belirt; model kataloğu `CODEX_HOME` değişkenine uyar.

`install.py` macOS'ta mevcut Mac kurucusuna yönlendirir. Kod güncellenince kurucuyu tekrar çalıştırıp sunucuyu yeniden başlat. `start.py`, ortamı etkinleştirmeden kurulu Python'u kullanır; `--no-open`, `--data YOL`, `--port PORT` seçenekleri vardır.

## Kullanım

1. **Yeni iş** oluştur ve taramaları topluca sürükle.
2. Ön/arka grupları için `1a.jpeg / 1b.jpeg`, `2a / 2b` adlarını kullan: **a ön**, **b arka**. Çevirirken baskıları aynı yerde tut. Özel adlı dosyalar da yüklenebilir; yerel otomatik eşleştirme sayısal grup ister, diğerlerini elle eşleştir.
3. **Yerel · Yapay zekâsız**, **Yapay zekâ · Codex** veya **API · OpenRouter** seç. Fotoğraflar birbirine değiyorsa 2 × 2 gibi bir yerleşim kullan.
4. Köşeleri, yönleri, eşleşmeleri ve adları kontrol et; gerekli alanları değiştir ve sonuçları onayla. Eksik arka, boş arka kabul edilmez. Tek yüz kaydetmek için uygun arka durumunu seç.
5. **JPEG’leri kaydet** ile yalnız onaylı fotoğrafları yeni klasöre kaydet. Dosya yöneticisinde açabilir veya ZIP indirebilirsin.

Dikey fotoğrafta ön solda, arka sağda; yatay fotoğrafta ön üstte, arka alttadır. Yazı fotoğrafın yönünü izler ve yan kalabilir. Boş arkalar çıktıya eklenmez. Dört köşe düzleştirilir, ortak kenara hizalanır ve 24 piksel ara bırakılır. JPEG kalite 100 / 4:4:4 ve kaynak DPI bilgisi korunur; geometrik işlemler yeniden örnekleme içerir, JPEG kayıpsız değildir. Orijinal dosyalar değişmez.

## İşleme seçenekleri

- **Yerel:** OpenCV/Pillow; model veya ağ çağrısı yapmaz. Konum/boyut eşleştirmesi ve sıralı adlar önerir. Konuyu ve doğru yönü anlayamaz; bütün sonuçlar onay bekler. Soluk yazıyı ve beyaz zemindeki kâğıt kenarlarını kontrol et.
- **Codex:** Ayrı kurulmuş, giriş yapılmış Codex CLI gerekir. Model ve effort yerel katalogdan seçilir; görüntüler seçilen modele gönderilir. Başka modele sessiz geçiş yapılmaz.
- **OpenRouter:** Ayrı API anahtarı, model ve effort seçimi. Anahtar macOS Anahtar Zinciri, Windows Credential Manager veya Linux Secret Service kasasında tutulur. Bağlantı testi fotoğraf göndermez veya model çağırmaz. Analiz ücretlidir; iptal, başlamış uzak işlemin ücretini geri almayabilir.

## Veriler ve sınırlar

Çalışmalar macOS’ta `~/Library/Application Support/FotografMasasi/`, Windows’ta `%LOCALAPPDATA%\PhotoDesk`, Linux’ta `$XDG_DATA_HOME/photodesk` (varsayılan `~/.local/share/photodesk`) içinde tutulur. Varsayılan çıktı `~/Downloads/Fotograf-Masasi/`; kayıt ekranında değiştirilebilir. Eski yollar yükseltmede veri kaybetmemek için korunmuştur. Kaynak hashleri, eşleşmeler ve işleme ayarları `arsiv-kaydi.json` içinde bulunur.

İş başına 100 tarama sayfası / 200 yüz, yükleme isteği başına 512 MB sınırı vardır. Tek analiz aynı anda çalışır. JPEG, PNG, TIFF ve PDF kabul edilir. HEIC içe aktarma yalnız macOS üzerinde desteklenir. Model önizlemeyi görür; çıktı tam çözünürlükten üretilir. Doğrudan yazıcı kontrolü ve klasör izleyicisi yoktur; tamamlanan taramaları sürükleyerek ekle. Sekmeyi kapatmak analizi veya sunucuyu durdurmaz; analiz için **İptal**, sunucu için işletim sisteminin süreç yöneticisi kullanılır (Activity Monitor / Görev Yöneticisi vb.). Aktif iş sırasında sunucuyu durdurma.

Geliştirme, test ve çeviri dosyalarının ayrıntıları [İngilizce README](README.md#develop-and-test) içinde. Depoda kişisel tarama, API anahtarı veya çalışma kaydı bulunmaz. Testler sentetik görüntüler ve taklit model yanıtları kullanır; gerçek ücretli OpenRouter analizi test kapsamında değildir.

CI macOS, Ubuntu ve Windows / Python 3.12 ile Windows / Python 3.11 üzerinde çalışır. Süreç testleri sahte Codex kullanır; gerçek model çağrısı yapmaz. Linux kasa kilidi açma ve macOS izin pencereleri otomatik test kapsamında değildir. Windows kasa testi yalnız kendine ait geçici bir deneme kaydı oluşturup siler.
