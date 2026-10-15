# PyBench

Bilgisayarlar için AnTuTu benzeri performans testi. **Windows, macOS ve Linux** üzerinde
çalışır. İşlemci, ekran kartı, bellek, depolama ve günlük kullanım performansını ölçer ve
tek bir puan verir.

## İndir (Python gerekmez)

[**Releases**](https://github.com/mesutozansoftware/pybench/releases/latest) sayfasından
sisteminize uygun dosyayı indirin:

| Sistem | Dosya |
|---|---|
| Windows 10/11 (64 bit) | `PyBench-windows-x64.exe` |
| macOS, Apple Silicon (M1/M2/M3/M4…) | `PyBench-macos-apple-silicon.zip` |
| macOS, Intel | `PyBench-macos-intel.zip` |
| Linux (x64) | `PyBench-linux-x64.tar.gz` |

- **Windows:** SmartScreen uyarısı çıkarsa *Ek bilgi → Yine de çalıştır* (uygulama imzalı değil).
- **macOS:** Zip'i açın, `PyBench.app`'e sağ tıklayıp *Aç*'ı seçin. "Hasarlı / açılamıyor"
  derse Terminal'de `xattr -cr ~/Downloads/PyBench.app` çalıştırın.
- **Linux:** `tar -xzf PyBench-linux-x64.tar.gz && ./PyBench`

## Testler

Her test belirli bir süre boyunca çalışır ve saniyedeki iş miktarını ölçer. Tam test yaklaşık
30–60 saniye sürer.

| Kategori | Testler | Taban puan |
|----------|---------|-----------:|
| **İşlemci (CPU)** | Tamsayı aritmetiği, kayan nokta (Mandelbrot), zlib sıkıştırma, SHA-256, çok çekirdek | 30.000 |
| **Ekran Kartı (GPU)** | Shader işlem gücü, doldurma hızı, doku örnekleme, geometri (1920×1080, OpenGL 3.3) | 25.000 |
| **Bellek (RAM)** | Bant genişliği (64 MB kopyalama), rastgele erişim (16 MB tablo), nesne oluşturma | 15.000 |
| **Depolama** | Sıralı yazma/okuma (256 MB), rastgele 4K yazma/okuma (IOPS) | 15.000 |
| **Günlük Kullanım (UX)** | JSON, regex metin arama, SQLite veritabanı, sıralama, görüntü işleme | 15.000 |

**Puanlama:** `puan = ölçüm / referans × taban puan`. Referans makine olan
**Apple M1 MacBook Air** toplam **100.000** puan alır. 200.000 puan, referans makinenin
iki katı hız demektir.

Sonuçlar `~/.pybench/history.json` dosyasına kaydedilir ve **Geçmiş** sekmesinde görünür.
Her sonucu `.txt` rapor veya `.json` olarak dışa aktarabilirsiniz.

### Ekran kartı testi

GPU testleri ekranda pencere açmadan, ekran dışı (offscreen) OpenGL 3.3 ile 1080p
çözünürlükte çizim yapar. Bir sürücü hatası programı çökertmesin diye ayrı bir süreçte
çalışır. OpenGL 3.3 desteklenmiyorsa (çok eski sürücü, sanal makine vb.) GPU testi 0 puan
alır ve nedeni kartta gösterilir. Bilgisayarda gerçek bir GPU yoksa ve sistem yazılımsal
çizime (llvmpipe vb.) düşerse kartta "yazılımsal" uyarısı çıkar.

### Depolama testinde önbellek

Okuma testleri işletim sisteminin dosya önbelleğini atlar, böylece RAM'den değil gerçekten
diskten okunur: Windows'ta `FILE_FLAG_NO_BUFFERING`, macOS'ta `F_NOCACHE`, Linux'ta
`posix_fadvise`. Önbellek herhangi bir nedenle atlanamazsa okumalar gerçek dışı hızlı
ölçülür (testte Windows'ta rastgele okuma yazmanın 600 katı çıktı). Bu durumda okuma
puanları **%30 düşürülür ve en fazla taban puan kadar** verilir; kartta bunun notu
görünür. Oran `pybench/engine.py` içindeki `READ_CACHE_PENALTY` ile ayarlanabilir.

## Kaynak koddan çalıştırma

Python 3.9+ gerekir.

```
pip install -r requirements.txt     # GPU testi için moderngl
python main.py                      # arayüz
python main.py --cli                # terminal modu
python main.py --cli --quick        # hızlı test
python main.py --cli --json sonuc.json
python main.py --cli --disk-dir /Volumes/USB   # başka bir diski test et
```

moderngl kurulu değilse program yine çalışır, sadece GPU testi atlanır. Linux'ta arayüz
açılmazsa tkinter'ı kurun (`sudo apt install python3-tk`).

## Kendin derle

```
pip install -r requirements-build.txt
python build.py
```

Çıktı `dist/` klasörüne yazılır. Her sistem için derleme o sistemin üzerinde yapılmalıdır.
GitHub Actions, `v*` etiketi gönderildiğinde dört platform için de otomatik derleyip
sürüm (release) oluşturur: [.github/workflows/build.yml](.github/workflows/build.yml).

## Bilinmesi gerekenler

- CPU, bellek ve UX testleri Python ile yazıldığı için puanlar Python sürümünden de etkilenir.
  Hazır indirilen uygulamaların hepsi aynı Python sürümüyle derlenir, bu yüzden aralarında
  karşılaştırma yapılabilir.
- Daha tutarlı sonuç için test sırasında başka uygulama kullanmayın. Dizüstü
  bilgisayarlarda şarj kablosunu takın.
