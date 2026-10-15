"""Benchmark testleri. Sadece Python standart kütüphanesi kullanılır.

Her zaman-sınırlı test bir "iş birimi" fonksiyonunu verilen süre boyunca
tekrar tekrar çalıştırır ve saniyedeki iş miktarını döndürür (yüksek = iyi).
"""

import array
import hashlib
import json
import multiprocessing
import os
import random
import re
import sqlite3
import sys
import time
import zlib


def timed(unit, budget):
    """unit() çağrısını budget saniye boyunca tekrarlar, saniyedeki iş miktarını döndürür."""
    unit()  # ısınma turu
    work = 0.0
    start = time.perf_counter()
    deadline = start + budget
    while True:
        work += unit()
        now = time.perf_counter()
        if now >= deadline:
            return work / (now - start)


# ====================================================================== CPU
def _collatz_unit():
    steps = 0
    for n in range(1, 1501):
        x = n
        while x != 1:
            x = (x >> 1) if not (x & 1) else 3 * x + 1
            steps += 1
    return steps / 1e6


def _mandel_unit(size=40, max_iter=64):
    iters = 0
    for py in range(size):
        ci = py * 2.4 / size - 1.2
        for px in range(size):
            cr = px * 3.0 / size - 2.1
            zr = zi = 0.0
            i = 0
            while i < max_iter and zr * zr + zi * zi <= 4.0:
                zr, zi = zr * zr - zi * zi + cr, 2.0 * zr * zi + ci
                i += 1
            iters += i
    return iters / 1e6


_WORDS = ("islemci bellek disk performans test skor cekirdek grafik veri hiz "
          "bilgisayar sistem dosya ag kullanici program surum guncelleme").split()
_cache = {}


def _sample_text():
    if "text" not in _cache:
        rnd = random.Random(42)
        _cache["text"] = " ".join(rnd.choice(_WORDS) for _ in range(150_000)).encode()
    return _cache["text"]


def cpu_integer(budget):
    return timed(_collatz_unit, budget)


def cpu_float(budget):
    return timed(_mandel_unit, budget)


def cpu_compress(budget):
    data = _sample_text()
    mb = len(data) / 1e6

    def unit():
        zlib.decompress(zlib.compress(data, 6))
        return mb
    return timed(unit, budget)


def cpu_hash(budget):
    data = random.Random(1).randbytes(8 << 20)
    mb = len(data) / 1e6

    def unit():
        hashlib.sha256(data).digest()
        return mb
    return timed(unit, budget)


def _mixed_unit():
    _collatz_unit()
    _mandel_unit()
    return 1.0


def _mc_worker(args):
    start_at, budget = args
    while time.time() < start_at:
        time.sleep(0.001)
    return timed(_mixed_unit, budget)


def _noop(_):
    return os.getpid()


def cpu_multicore(budget):
    """Tüm mantıksal çekirdeklerde aynı anda çalışır; toplam iş/s ve ölçekleme oranı döner."""
    n = os.cpu_count() or 1
    single = timed(_mixed_unit, max(0.4, budget / 3))
    ctx = multiprocessing.get_context("spawn")  # her platformda aynı ve thread-güvenli
    with ctx.Pool(n) as pool:
        pool.map(_noop, range(n * 4))  # işçilerin hepsi ayağa kalksın
        start_at = time.time() + 0.3
        rates = pool.map(_mc_worker, [(start_at, budget)] * n, chunksize=1)
    total = sum(rates)
    return total, {"threads": n, "scaling": total / single if single else 0.0}


# =================================================================== BELLEK
def mem_bandwidth(budget):
    size = 64 << 20
    src = bytearray(b"\x5a") * size
    dst = bytearray(size)
    ms, md = memoryview(src), memoryview(dst)
    mb = size / 1e6

    def unit():
        md[:] = ms
        return mb
    try:
        return timed(unit, budget)
    finally:
        ms.release()
        md.release()


def mem_latency(budget):
    n = 1 << 22                     # 4M x 4 bayt = 16 MB, CPU önbelleklerinden büyük
    mask = n - 1
    a, c = 1103515245, 12345        # tam periyotlu LCG -> tüm hücreler tek bir döngüde gezilir
    table = array.array("I", ((a * i + c) & mask for i in range(n)))
    state = [0]
    hops = 200_000

    def unit():
        i = state[0]
        t = table
        for _ in range(hops):
            i = t[i]
        state[0] = i
        return hops / 1e6
    return timed(unit, budget)


def _alloc_unit():
    objs = [{"id": i, "ad": "oge", "deger": (i, i + 1)} for i in range(20_000)]
    objs.sort(key=lambda o: -o["id"])
    del objs
    return 0.02


def mem_alloc(budget):
    return timed(_alloc_unit, budget)


# ================================================================ DEPOLAMA
def _no_cache(fd):
    """Mümkün olan platformlarda işletim sistemi önbelleğini atla."""
    if sys.platform == "darwin":
        try:
            import fcntl
            fcntl.fcntl(fd, 48, 1)  # F_NOCACHE
        except Exception:
            pass


def _drop_cache(fd):
    if hasattr(os, "posix_fadvise"):
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


def disk_all(budget, directory, size_mb=256):
    """Sıralı yazma/okuma ve rastgele 4K yazma/okuma. Geçici dosyayı sonunda siler."""
    path = os.path.join(directory, f"pybench_{os.getpid()}.tmp")
    block = random.Random(3).randbytes(4 << 20)  # sıkıştırılamaz veri
    count = max(1, (size_mb << 20) // len(block))
    total_mb = count * len(block) / 1e6
    flags = os.O_RDWR | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    res = {}
    try:
        fd = os.open(path, flags)
        try:
            _no_cache(fd)
            t0 = time.perf_counter()
            for _ in range(count):
                os.write(fd, block)
            os.fsync(fd)
            res["disk_seq_write"] = total_mb / (time.perf_counter() - t0)
            _drop_cache(fd)
        finally:
            os.close(fd)

        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        try:
            _no_cache(fd)
            _drop_cache(fd)
            t0 = time.perf_counter()
            while os.read(fd, len(block)):
                pass
            res["disk_seq_read"] = total_mb / (time.perf_counter() - t0)
        finally:
            os.close(fd)

        blocks = count * len(block) // 4096
        rnd = random.Random(9)
        page = block[:4096]
        fd = os.open(path, os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            _no_cache(fd)
            ops = 0
            t0 = time.perf_counter()
            deadline = t0 + budget
            while time.perf_counter() < deadline:
                for _ in range(32):
                    os.lseek(fd, rnd.randrange(blocks) * 4096, os.SEEK_SET)
                    os.write(fd, page)
                os.fsync(fd)
                ops += 32
            res["disk_rand_write"] = ops / (time.perf_counter() - t0)
            _drop_cache(fd)

            ops = 0
            t0 = time.perf_counter()
            deadline = t0 + budget
            while time.perf_counter() < deadline:
                for _ in range(32):
                    os.lseek(fd, rnd.randrange(blocks) * 4096, os.SEEK_SET)
                    os.read(fd, 4096)
                ops += 32
            res["disk_rand_read"] = ops / (time.perf_counter() - t0)
        finally:
            os.close(fd)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return res


# ======================================================= UX (günlük işler)
def ux_json(budget):
    doc = {"kullanicilar": [
        {"id": i, "ad": f"kullanici{i}", "etiketler": ["a", "b", "c"],
         "puan": i * 1.5, "aktif": i % 2 == 0, "adres": {"sehir": "Istanbul", "kod": 34000 + i}}
        for i in range(400)]}

    def unit():
        json.loads(json.dumps(doc))
        return 1.0
    return timed(unit, budget)


def ux_regex(budget):
    rnd = random.Random(5)
    lines = []
    for i in range(4000):
        lines.append(f"2026-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d} "
                     f"kullanici{i}@ornek.com.tr Odeme {rnd.randint(10, 99999)}.{rnd.randint(0, 99):02d} TL "
                     f"IP 10.{rnd.randint(0, 255)}.{rnd.randint(0, 255)}.{rnd.randint(0, 255)} "
                     + " ".join(rnd.choice(_WORDS) for _ in range(8)))
    text = "\n".join(lines)
    mb = len(text.encode()) / 1e6
    patterns = [re.compile(p) for p in (
        r"[\w.]+@[\w.]+\.\w+", r"\d{4}-\d{2}-\d{2}", r"\b\d+\.\d{2} TL\b",
        r"(?:\d{1,3}\.){3}\d{1,3}", r"\b(?:disk|grafik|veri)\w*")]

    def unit():
        for p in patterns:
            p.findall(text)
        text.upper().split()
        return mb
    return timed(unit, budget)


def ux_sqlite(budget):
    rnd = random.Random(11)
    rows = [(i, f"urun{i}", rnd.choice(_WORDS), rnd.random() * 1000, rnd.randint(1, 50))
            for i in range(4000)]

    def unit():
        con = sqlite3.connect(":memory:")
        cur = con.cursor()
        cur.execute("CREATE TABLE urun (id INTEGER PRIMARY KEY, ad TEXT, kat TEXT, fiyat REAL, stok INT)")
        cur.executemany("INSERT INTO urun VALUES (?,?,?,?,?)", rows)
        cur.execute("CREATE INDEX ix_kat ON urun(kat)")
        for w in _WORDS:
            cur.execute("SELECT COUNT(*), AVG(fiyat) FROM urun WHERE kat=?", (w,)).fetchone()
        cur.execute("SELECT kat, SUM(fiyat*stok) FROM urun GROUP BY kat ORDER BY 2 DESC").fetchall()
        cur.execute("UPDATE urun SET fiyat = fiyat * 1.1 WHERE stok < 10")
        con.commit()
        con.close()
        return 1.0
    return timed(unit, budget)


def ux_sort(budget):
    rnd = random.Random(13)
    nums = [rnd.random() for _ in range(100_000)]
    words = [rnd.choice(_WORDS) + str(rnd.randint(0, 9999)) for _ in range(50_000)]

    def unit():
        sorted(nums)
        sorted(words)
        return 0.15
    return timed(unit, budget)


def ux_image(budget):
    w = h = 96
    rnd = random.Random(17)
    img = bytes(rnd.randrange(256) for _ in range(w * h))
    out = bytearray(w * h)
    mpx = (w - 2) * (h - 2) / 1e6

    def unit():
        src = img
        for y in range(1, h - 1):
            r0, r1, r2 = (y - 1) * w, y * w, (y + 1) * w
            for x in range(1, w - 1):
                s = (src[r0 + x - 1] + src[r0 + x] + src[r0 + x + 1]
                     + src[r1 + x - 1] + src[r1 + x] + src[r1 + x + 1]
                     + src[r2 + x - 1] + src[r2 + x] + src[r2 + x + 1])
                out[r1 + x] = s // 9
        return mpx
    return timed(unit, budget)
