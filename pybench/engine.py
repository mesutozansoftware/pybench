"""Testleri sırayla çalıştırır, puanlar ve sonuç geçmişini saklar.

Puanlama: her test için  puan = ölçülen / referans * taban_puan.
Referans makine (Apple M1 MacBook Air, Python 3.13) her kategoride taban puanların
toplamını, toplamda 100.000 puan alır.
GPU referansı: Apple M1 8 çekirdekli GPU, OpenGL 4.1.
"""

import datetime
import json
import os
import tempfile
import threading
import time

from . import __version__, gpu, tests

CATEGORIES = [
    ("cpu", "İşlemci (CPU)"),
    ("gpu", "Ekran Kartı (GPU)"),
    ("mem", "Bellek (RAM)"),
    ("disk", "Depolama"),
    ("ux", "Günlük Kullanım (UX)"),
]
CATEGORY_NAMES = dict(CATEGORIES)

# id, kategori, ad, birim, referans değer, taban puan
TEST_DEFS = [
    ("cpu_integer", "cpu", "Tamsayı aritmetiği", "M işlem/s", 17.0, 4500),
    ("cpu_float", "cpu", "Kayan nokta (Mandelbrot)", "M iter/s", 11.5, 4500),
    ("cpu_compress", "cpu", "Sıkıştırma (zlib)", "MB/s", 38.0, 3000),
    ("cpu_hash", "cpu", "Kriptografi (SHA-256)", "MB/s", 2400.0, 3000),
    ("cpu_multicore", "cpu", "Çok çekirdek", "iş/s", 620.0, 15000),
    ("gpu_alu", "gpu", "Shader işlem gücü", "G iter/s", 70.0, 8000),
    ("gpu_fill", "gpu", "Doldurma hızı", "G piksel/s", 61.0, 5000),
    ("gpu_texture", "gpu", "Doku örnekleme", "G texel/s", 22.0, 6000),
    ("gpu_geometry", "gpu", "Geometri", "M üçgen/s", 610.0, 6000),
    ("mem_bandwidth", "mem", "Bellek bant genişliği", "MB/s", 29000.0, 6000),
    ("mem_latency", "mem", "Rastgele erişim", "M erişim/s", 17.0, 4500),
    ("mem_alloc", "mem", "Nesne oluşturma", "M nesne/s", 4.3, 4500),
    ("disk_seq_write", "disk", "Sıralı yazma", "MB/s", 3000.0, 4500),
    ("disk_seq_read", "disk", "Sıralı okuma", "MB/s", 2600.0, 4500),
    ("disk_rand_write", "disk", "Rastgele 4K yazma", "IOPS", 12000.0, 3000),
    ("disk_rand_read", "disk", "Rastgele 4K okuma", "IOPS", 15000.0, 3000),
    ("ux_json", "ux", "JSON işleme", "işlem/s", 1450.0, 3000),
    ("ux_regex", "ux", "Metin arama (regex)", "MB/s", 14.0, 3000),
    ("ux_sqlite", "ux", "Veritabanı (SQLite)", "işlem/s", 210.0, 3000),
    ("ux_sort", "ux", "Sıralama", "M öğe/s", 7.8, 3000),
    ("ux_image", "ux", "Görüntü işleme", "M piksel/s", 3.0, 3000),
]
TESTS = {t[0]: dict(id=t[0], cat=t[1], name=t[2], unit=t[3], ref=t[4], base=t[5]) for t in TEST_DEFS}
CATEGORY_BASE = {c: sum(t["base"] for t in TESTS.values() if t["cat"] == c) for c, _ in CATEGORIES}
TOTAL_BASE = sum(CATEGORY_BASE.values())

# Okuma testleri normalde işletim sistemi önbelleğini atlar (Windows: FILE_FLAG_NO_BUFFERING,
# macOS: F_NOCACHE, Linux: fadvise). Atlanamazsa okumalar bellekten yapılır ve gerçek dışı
# hızlı ölçülür; o durumda okuma puanları bu oranda düşürülür ve taban puanla sınırlanır.
READ_CACHE_PENALTY = 0.30
READ_TESTS = ("disk_seq_read", "disk_rand_read")

GPU_TESTS = ["gpu_alu", "gpu_fill", "gpu_texture", "gpu_geometry"]
DISK_TESTS = ["disk_seq_write", "disk_seq_read", "disk_rand_write", "disk_rand_read"]

# Çalıştırma adımları: (adım adı, test id'leri, fonksiyon)
STEPS = [
    ("Tamsayı aritmetiği", ["cpu_integer"], tests.cpu_integer),
    ("Kayan nokta", ["cpu_float"], tests.cpu_float),
    ("Sıkıştırma", ["cpu_compress"], tests.cpu_compress),
    ("Kriptografi", ["cpu_hash"], tests.cpu_hash),
    ("Çok çekirdek", ["cpu_multicore"], tests.cpu_multicore),
    ("Ekran kartı testleri", GPU_TESTS, "gpu"),
    ("Bellek bant genişliği", ["mem_bandwidth"], tests.mem_bandwidth),
    ("Rastgele bellek erişimi", ["mem_latency"], tests.mem_latency),
    ("Nesne oluşturma", ["mem_alloc"], tests.mem_alloc),
    ("Depolama testleri", DISK_TESTS, "disk"),
    ("JSON işleme", ["ux_json"], tests.ux_json),
    ("Metin arama", ["ux_regex"], tests.ux_regex),
    ("Veritabanı", ["ux_sqlite"], tests.ux_sqlite),
    ("Sıralama", ["ux_sort"], tests.ux_sort),
    ("Görüntü işleme", ["ux_image"], tests.ux_image),
]

HISTORY_DIR = os.path.join(os.path.expanduser("~"), ".pybench")
HISTORY_FILE = os.path.join(HISTORY_DIR, "history.json")


class Cancelled(Exception):
    pass


def score(test_id, value, cached_read=False):
    t = TESTS[test_id]
    if not t["ref"]:
        return 0
    pts = value / t["ref"] * t["base"]
    if cached_read and test_id in READ_TESTS:
        pts = min(pts * (1 - READ_CACHE_PENALTY), t["base"])
    return int(round(pts))


def run(sysinfo=None, quick=False, disk_dir=None, progress=None, on_result=None, stop_event=None):
    """Tüm testleri çalıştırır.

    progress(adim_no, adim_sayisi, adim_adi) her adımdan önce,
    on_result(test_id, deger, puan, ek) her ölçüm bittiğinde çağrılır.
    """
    budget = 0.6 if quick else 1.5
    disk_mb = 128 if quick else 256
    disk_dir = disk_dir or tempfile.gettempdir()
    stop_event = stop_event or threading.Event()
    results = {}
    started = time.time()

    for idx, (title, ids, fn) in enumerate(STEPS):
        if stop_event.is_set():
            raise Cancelled()
        if progress:
            progress(idx, len(STEPS), title)
        cached = False
        if fn == "disk":
            out = tests.disk_all(budget, disk_dir, disk_mb)
            cached = not out.pop("read_uncached", True)
            note = {"penalty": READ_CACHE_PENALTY} if cached else {}
            values = {k: (v, note if k in READ_TESTS else {}) for k, v in out.items()}
        elif fn == "gpu":
            out = gpu.gpu_all(budget)
            info = {k: out[k] for k in ("renderer", "gl_version", "software", "fps_1080p", "error") if k in out}
            values = {tid: (out.get(tid, 0.0), info) for tid in ids}
        else:
            out = fn(budget)
            value, extra = out if isinstance(out, tuple) else (out, {})
            values = {ids[0]: (value, extra)}
        for tid, (value, extra) in values.items():
            pts = score(tid, value, cached)
            results[tid] = {"value": value, "score": pts, "extra": extra}
            if on_result:
                on_result(tid, value, pts, extra)
    if progress:
        progress(len(STEPS), len(STEPS), "Tamamlandı")

    cats = {c: sum(r["score"] for tid, r in results.items() if TESTS[tid]["cat"] == c)
            for c, _ in CATEGORIES}
    return {
        "version": __version__,
        "date": datetime.datetime.now().isoformat(timespec="seconds"),
        "duration": round(time.time() - started, 1),
        "quick": quick,
        "total": sum(cats.values()),
        "categories": cats,
        "tests": results,
        "system": sysinfo or {},
    }


def load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_history(result):
    history = load_history()
    history.append(result)
    os.makedirs(HISTORY_DIR, exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(history[-100:], f, ensure_ascii=False, indent=1)
    os.replace(tmp, HISTORY_FILE)
    return history


def clear_history():
    try:
        os.remove(HISTORY_FILE)
    except OSError:
        pass


def fmt_value(value):
    if value >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def fmt_score(points):
    return f"{points:,}".replace(",", ".")


def report_text(result):
    """Sonucu okunabilir düz metin rapora çevirir (CLI ve dışa aktarma için)."""
    s = result.get("system", {})
    lines = [
        f"PyBench {result.get('version', '')} sonuç raporu - {result.get('date', '')}",
        "=" * 64,
        f"Cihaz     : {s.get('model', '-')}",
        f"Sistem    : {s.get('os', '-')}",
        f"İşlemci   : {s.get('cpu', '-')} ({s.get('logical_cores', '?')} iş parçacığı)",
        f"Bellek    : {s.get('ram', '-')}",
        f"Mod       : {'Hızlı' if result.get('quick') else 'Tam'} · süre {result.get('duration', 0)} sn",
        "",
        f"TOPLAM PUAN: {fmt_score(result['total'])}   (referans: {fmt_score(TOTAL_BASE)})",
        "",
    ]
    for cat, cat_name in CATEGORIES:
        lines.append(f"{cat_name:<28}{fmt_score(result['categories'].get(cat, 0)):>12}")
        for tid, t in TESTS.items():
            r = result["tests"].get(tid)
            if t["cat"] != cat or not r:
                continue
            val = f"{fmt_value(r['value'])} {t['unit']}"
            lines.append(f"   {t['name']:<26}{val:>18}{fmt_score(r['score']):>10}")
            extra = r.get("extra", {})
            if extra.get("scaling"):
                lines.append(f"      {extra['threads']} iş parçacığı, {extra['scaling']:.1f}x ölçekleme")
            if extra.get("penalty"):
                lines.append(f"      Önbellek atlanamadı: puan -%{extra['penalty'] * 100:.0f}, en fazla taban puan")
        if cat == "gpu":
            g = next((result["tests"][t].get("extra", {}) for t in GPU_TESTS if t in result["tests"]), {})
            if g.get("error"):
                lines.append(f"   ! {g['error']}")
            elif g.get("renderer"):
                soft = " (yazılımsal - gerçek GPU değil)" if g.get("software") else ""
                lines.append(f"   GPU: {g['renderer']}{soft} · OpenGL {g.get('gl_version', '?')}")
        lines.append("")
    return "\n".join(lines)
