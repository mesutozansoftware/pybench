"""PyBench giriş noktası.

    python main.py                 -> grafik arayüz
    python main.py --cli           -> terminalde çalıştır
    python main.py --cli --quick   -> hızlı mod
    python main.py --cli --json sonuc.json
"""

import argparse
import json
import multiprocessing
import os
import sys


def _setup_console():
    """Windows'ta pencereli exe'nin konsolu yoktur; çağrıldığı terminale bağlan ve UTF-8 yaz."""
    if sys.stdout is None and sys.platform == "win32":
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
    if sys.stdout is None:
        sys.stdout = sys.stderr = open(os.devnull, "w")
    elif hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def run_cli(args):
    from pybench import engine, sysinfo

    _setup_console()

    print("PyBench - sistem bilgisi toplanıyor...", flush=True)
    info = sysinfo.collect()
    print(f"  {info['cpu']} · {info['ram']} · {info['os']}\n", flush=True)

    def progress(i, n, title):
        if i < n:
            print(f"[{i + 1:>2}/{n}] {title}...", flush=True)

    def on_result(tid, value, points, extra):
        t = engine.TESTS[tid]
        print(f"        {t['name']:<26}{engine.fmt_value(value):>12} {t['unit']:<11}{engine.fmt_score(points):>8} puan",
              flush=True)

    try:
        res = engine.run(info, quick=args.quick, disk_dir=args.disk_dir, progress=progress, on_result=on_result)
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        return 1
    print()
    engine.save_history(res)
    print(engine.report_text(res))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=2)
        print(f"JSON kaydedildi: {args.json}")
    return 0


def main():
    p = argparse.ArgumentParser(description="PyBench - AnTuTu benzeri bilgisayar performans testi")
    p.add_argument("--cli", action="store_true", help="arayüz olmadan terminalde çalıştır")
    p.add_argument("--quick", action="store_true", help="hızlı mod (daha kısa, daha az kesin)")
    p.add_argument("--json", metavar="DOSYA", help="sonucu JSON olarak kaydet (CLI)")
    p.add_argument("--disk-dir", metavar="KLASÖR", help="depolama testinin yapılacağı klasör")
    args = p.parse_args()

    if args.cli:
        return run_cli(args)
    try:
        from pybench import gui
    except ImportError as e:  # Linux'ta python3-tk kurulu olmayabilir
        print(f"Grafik arayüz açılamadı ({e}).\n"
              "Linux'ta: sudo apt install python3-tk  (veya --cli ile çalıştır)")
        return 1
    gui.main()
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # PyInstaller ile paketlenmiş exe için gerekli
    sys.exit(main())
