"""tkinter tabanlı grafik arayüz (macOS / Linux / Windows)."""

import json
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, engine, sysinfo

C = {
    "bg": "#0e1120", "panel": "#161a2e", "panel2": "#222846", "line": "#2c3358",
    "text": "#eef0fb", "muted": "#8a90b4", "accent": "#ff4d5e", "accent2": "#ff7a85",
}
CAT_COLOR = {"cpu": "#38bdf8", "gpu": "#f472b6", "mem": "#a78bfa", "disk": "#34d399", "ux": "#fbbf24"}

if sys.platform == "darwin":
    FAMILY = "Helvetica Neue"
elif sys.platform == "win32":
    FAMILY = "Segoe UI"
else:
    FAMILY = "DejaVu Sans"


def F(size, weight="normal"):
    return (FAMILY, size, weight)


class Gauge(tk.Canvas):
    """AnTuTu tarzı halka skor göstergesi."""

    def __init__(self, master, size=270, ring=18):
        super().__init__(master, width=size, height=size, bg=C["bg"], highlightthickness=0)
        self.size, self.ring = size, ring
        p = ring / 2 + 4
        self.box = (p, p, size - p, size - p)
        self.create_oval(*self.box, outline=C["panel2"], width=ring)
        self.arcs = []
        mid = size / 2
        self.big = self.create_text(mid, mid - 8, text="0", fill=C["text"], font=F(40, "bold"))
        self.small = self.create_text(mid, mid + 34, text="HAZIR", fill=C["muted"], font=F(11, "bold"))

    def _clear(self):
        for a in self.arcs:
            self.delete(a)
        self.arcs = []

    def progress(self, frac, color, label):
        self._clear()
        if frac > 0:
            self.arcs.append(self.create_arc(*self.box, start=90, extent=-359.9 * frac,
                                             style="arc", outline=color, width=self.ring))
        self.itemconfig(self.big, text=f"%{int(frac * 100)}")
        self.itemconfig(self.small, text=label.upper())

    def segments(self, parts, frac=1.0):
        """parts: [(değer, renk)] - halkayı kategori paylarına göre renklendirir."""
        self._clear()
        total = sum(v for v, _ in parts) or 1
        start = 90.0
        for value, color in parts:
            ext = 360.0 * value / total * frac
            if ext > 2:
                self.arcs.append(self.create_arc(*self.box, start=start, extent=-(ext - 1.5),
                                                 style="arc", outline=color, width=self.ring))
            start -= ext

    def set_text(self, big, small):
        self.itemconfig(self.big, text=big)
        self.itemconfig(self.small, text=small)


class CategoryCard(tk.Frame):
    def __init__(self, master, cat, title):
        super().__init__(master, bg=C["panel"], padx=16, pady=12, highlightthickness=1,
                         highlightbackground=C["line"])
        self.cat = cat
        color = CAT_COLOR[cat]
        head = tk.Frame(self, bg=C["panel"])
        head.pack(fill="x")
        tk.Label(head, text="●", fg=color, bg=C["panel"], font=F(12)).pack(side="left")
        tk.Label(head, text=title, fg=C["muted"], bg=C["panel"], font=F(11, "bold")).pack(side="left", padx=6)
        self.score_lbl = tk.Label(self, text="—", fg=C["text"], bg=C["panel"], font=F(24, "bold"), anchor="w")
        self.score_lbl.pack(fill="x", pady=(4, 2))
        self.bar = tk.Canvas(self, height=6, bg=C["panel2"], highlightthickness=0)
        self.bar.pack(fill="x")
        self.bar_fill = self.bar.create_rectangle(0, 0, 0, 6, fill=color, width=0)
        self.ratio_lbl = tk.Label(self, text="Referans: " + engine.fmt_score(engine.CATEGORY_BASE[cat]),
                                  fg=C["muted"], bg=C["panel"], font=F(9), anchor="w")
        self.ratio_lbl.pack(fill="x", pady=(3, 6))
        self.rows = {}
        for tid, t in engine.TESTS.items():
            if t["cat"] != cat:
                continue
            row = tk.Frame(self, bg=C["panel"])
            row.pack(fill="x")
            tk.Label(row, text=t["name"], fg=C["muted"], bg=C["panel"], font=F(10), anchor="w").pack(side="left")
            val = tk.Label(row, text="—", fg=C["text"], bg=C["panel"], font=F(10, "bold"), anchor="e")
            val.pack(side="right")
            self.rows[tid] = val
        self.note = tk.Label(self, text="", fg=C["muted"], bg=C["panel"], font=F(9), anchor="w",
                             justify="left", wraplength=250)
        self.note.pack(fill="x", pady=(4, 0))
        self.bar.bind("<Configure>", lambda e: self._draw_bar())
        self.ratio = 0.0

    def reset(self):
        self.score_lbl.config(text="—")
        for v in self.rows.values():
            v.config(text="—", fg=C["text"])
        self.note.config(text="", fg=C["muted"])
        self.ratio_lbl.config(text="Referans: " + engine.fmt_score(engine.CATEGORY_BASE[self.cat]))
        self.ratio = 0.0
        self._draw_bar()

    def set_test(self, tid, points):
        self.rows[tid].config(text=engine.fmt_score(points), fg=CAT_COLOR[self.cat])

    def set_score(self, points):
        self.score_lbl.config(text=engine.fmt_score(points))
        self.ratio = points / engine.CATEGORY_BASE[self.cat]
        self.ratio_lbl.config(text=f"Referansın %{self.ratio * 100:.0f}'i")
        self._draw_bar()

    def _draw_bar(self):
        w = self.bar.winfo_width()
        self.bar.coords(self.bar_fill, 0, 0, w * min(1.0, self.ratio / 2), 6)


class DeviceCard(tk.Frame):
    """Izgaradaki altıncı kutu: cihaz özeti."""

    FIELDS = (("cpu", "İşlemci"), ("gpu", "Ekran kartı"), ("ram", "Bellek"), ("os", "Sistem"))

    def __init__(self, master):
        super().__init__(master, bg=C["panel"], padx=16, pady=12, highlightthickness=1,
                         highlightbackground=C["line"])
        tk.Label(self, text="Cihaz", fg=C["muted"], bg=C["panel"], font=F(11, "bold"), anchor="w").pack(fill="x")
        self.values = {}
        for key, label in self.FIELDS:
            tk.Label(self, text=label, fg=C["muted"], bg=C["panel"], font=F(9), anchor="w").pack(fill="x", pady=(8, 0))
            v = tk.Label(self, text="…", fg=C["text"], bg=C["panel"], font=F(10, "bold"), anchor="w",
                         justify="left", wraplength=250)
            v.pack(fill="x")
            self.values[key] = v

    def set(self, key, text):
        self.values[key].config(text=text or "Bilinmiyor")


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.sys = None
        self.thread = None
        self.stop_event = threading.Event()
        self.last_result = None
        self.history = engine.load_history()

        root.title(f"PyBench {__version__} — Performans Testi")
        root.configure(bg=C["bg"])
        root.geometry("1220x800")
        root.minsize(1100, 740)
        self._style()
        self._build()
        self._fill_history()
        threading.Thread(target=self._load_sysinfo, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(50, self._poll)

    # ------------------------------------------------------------ görünüm
    def _style(self):
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", background=C["bg"], foreground=C["text"], font=F(10),
                    bordercolor=C["line"], fieldbackground=C["panel"], troughcolor=C["panel2"])
        s.configure("TNotebook", background=C["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0),
                    bordercolor=C["line"], lightcolor=C["bg"], darkcolor=C["bg"])
        s.configure("TNotebook.Tab", background=C["bg"], foreground=C["muted"], padding=(18, 8),
                    borderwidth=0, font=F(11, "bold"), bordercolor=C["bg"], lightcolor=C["bg"])
        s.map("TNotebook.Tab", background=[("selected", C["panel"])], foreground=[("selected", C["text"])],
              lightcolor=[("selected", C["accent"])], bordercolor=[("selected", C["line"])])
        s.configure("TFrame", background=C["bg"])
        for name, bg, active in (("Accent", C["accent"], C["accent2"]), ("Ghost", C["panel2"], C["line"])):
            s.configure(f"{name}.TButton", background=bg, foreground="#ffffff", borderwidth=0,
                        focusthickness=0, padding=(18, 11), font=F(12, "bold"))
            s.map(f"{name}.TButton", background=[("disabled", C["panel2"]), ("active", active)],
                  foreground=[("disabled", C["muted"])])
        s.configure("Small.TButton", background=C["panel2"], foreground=C["text"], borderwidth=0,
                    padding=(12, 7), font=F(10))
        s.map("Small.TButton", background=[("active", C["line"])])
        s.configure("Horizontal.TProgressbar", troughcolor=C["panel2"], background=C["accent"],
                    bordercolor=C["panel2"], lightcolor=C["accent"], darkcolor=C["accent"], thickness=6)
        s.configure("TCheckbutton", background=C["bg"], foreground=C["muted"], font=F(10))
        s.map("TCheckbutton", background=[("active", C["bg"])], indicatorcolor=[("selected", C["accent"])])
        s.configure("Treeview", background=C["panel"], fieldbackground=C["panel"], foreground=C["text"],
                    rowheight=28, borderwidth=0, font=F(10))
        s.map("Treeview", background=[("selected", C["panel2"])], foreground=[("selected", C["text"])])
        s.configure("Treeview.Heading", background=C["panel2"], foreground=C["muted"], relief="flat",
                    font=F(10, "bold"), padding=(8, 6))
        s.map("Treeview.Heading", background=[("active", C["line"])])
        s.configure("Vertical.TScrollbar", background=C["panel2"], troughcolor=C["panel"], borderwidth=0,
                    arrowcolor=C["muted"])

    def _build(self):
        head = tk.Frame(self.root, bg=C["bg"], padx=22, pady=14)
        head.pack(fill="x")
        tk.Label(head, text="Py", fg=C["accent"], bg=C["bg"], font=F(24, "bold")).pack(side="left")
        tk.Label(head, text="Bench", fg=C["text"], bg=C["bg"], font=F(24, "bold")).pack(side="left")
        tk.Label(head, text="  macOS · Linux · Windows performans testi", fg=C["muted"], bg=C["bg"],
                 font=F(11)).pack(side="left", pady=(8, 0))
        self.head_cpu = tk.Label(head, text="Sistem bilgisi alınıyor…", fg=C["muted"], bg=C["bg"], font=F(10))
        self.head_cpu.pack(side="right", pady=(8, 0))

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.nb = nb
        self._build_test_tab(nb)
        self._build_detail_tab(nb)
        self._build_system_tab(nb)
        self._build_history_tab(nb)

    def _build_test_tab(self, nb):
        tab = tk.Frame(nb, bg=C["bg"], padx=12, pady=16)
        nb.add(tab, text="  Test  ")
        left = tk.Frame(tab, bg=C["bg"])
        left.pack(side="left", fill="y", padx=(4, 20))
        self.gauge = Gauge(left)
        self.gauge.pack(pady=(6, 10))
        self.status = tk.Label(left, text="Başlamak için butona bas", fg=C["muted"], bg=C["bg"], font=F(10))
        self.status.pack()
        self.pbar = ttk.Progressbar(left, maximum=len(engine.STEPS), length=260)
        self.pbar.pack(pady=(8, 14))
        self.start_btn = ttk.Button(left, text="TESTİ BAŞLAT", style="Accent.TButton", command=self.start)
        self.start_btn.pack(fill="x")
        self.stop_btn = ttk.Button(left, text="Durdur", style="Ghost.TButton", command=self.stop)
        self.quick = tk.BooleanVar(value=False)
        self.quick_chk = ttk.Checkbutton(left, text="Hızlı mod (~2x daha kısa, daha az kesin)", variable=self.quick)
        self.quick_chk.pack(pady=(10, 4), anchor="w")
        self.export_btn = ttk.Button(left, text="Sonucu dışa aktar…", style="Small.TButton",
                                     command=lambda: self.export(self.last_result), state="disabled")
        self.export_btn.pack(fill="x", pady=(6, 0))
        self.compare = tk.Label(left, text="Referans: Apple M1 MacBook Air = 100.000 puan", fg=C["muted"],
                                bg=C["bg"], font=F(9), wraplength=260, justify="center")
        self.compare.pack(side="bottom", pady=6)

        grid = tk.Frame(tab, bg=C["bg"])
        grid.pack(side="left", fill="both", expand=True)
        self.cards = {}
        for i, (cat, title) in enumerate(engine.CATEGORIES):
            card = CategoryCard(grid, cat, title)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=6, pady=6)
            self.cards[cat] = card
        self.device = DeviceCard(grid)
        self.device.grid(row=1, column=2, sticky="nsew", padx=6, pady=6)
        for i in range(3):
            grid.columnconfigure(i, weight=1, uniform="c")
        for i in range(2):
            grid.rowconfigure(i, weight=1, uniform="r")

    def _build_detail_tab(self, nb):
        tab = tk.Frame(nb, bg=C["bg"], padx=12, pady=12)
        nb.add(tab, text="  Detaylar  ")
        cols = ("value", "unit", "ref", "score")
        tv = ttk.Treeview(tab, columns=cols, show="tree headings")
        tv.heading("#0", text="Test", anchor="w")
        tv.column("#0", width=300)
        for c, t, w in (("value", "Ölçüm", 140), ("unit", "Birim", 110), ("ref", "Referans", 120),
                        ("score", "Puan", 110)):
            tv.heading(c, text=t, anchor="e")
            tv.column(c, width=w, anchor="e")
        tv.tag_configure("cat", font=F(11, "bold"))
        for cat, title in engine.CATEGORIES:
            tv.tag_configure(cat, foreground=CAT_COLOR[cat])
            tv.insert("", "end", iid=cat, text=title, values=("", "", "", "—"), open=True, tags=("cat", cat))
            for tid, t in engine.TESTS.items():
                if t["cat"] == cat:
                    tv.insert(cat, "end", iid=tid, text=t["name"],
                              values=("—", t["unit"], engine.fmt_value(t["ref"]), "—"))
        tv.pack(fill="both", expand=True)
        self.detail = tv
        tk.Label(tab, text="Puan = ölçüm / referans × taban puan. Tüm değerlerde yüksek olan daha iyidir.",
                 fg=C["muted"], bg=C["bg"], font=F(9)).pack(anchor="w", pady=(8, 0))

    def _build_system_tab(self, nb):
        tab = tk.Frame(nb, bg=C["bg"], padx=12, pady=12)
        nb.add(tab, text="  Sistem  ")
        tv = ttk.Treeview(tab, columns=("v",), show="tree", selectmode="browse")
        tv.column("#0", width=220)
        tv.column("v", width=600)
        tv.pack(fill="both", expand=True)
        tv.insert("", "end", text="Yükleniyor…", values=("",))
        self.systv = tv

    def _build_history_tab(self, nb):
        tab = tk.Frame(nb, bg=C["bg"], padx=12, pady=12)
        nb.add(tab, text="  Geçmiş  ")
        cols = ("date", "total", "cpu", "gpu", "mem", "disk", "ux", "mode", "device")
        tv = ttk.Treeview(tab, columns=cols, show="headings", selectmode="browse")
        for c, t, w, a in (("date", "Tarih", 150, "w"), ("total", "Toplam", 100, "e"), ("cpu", "CPU", 80, "e"), ("gpu", "GPU", 80, "e"),
                           ("mem", "Bellek", 80, "e"), ("disk", "Depolama", 85, "e"), ("ux", "UX", 80, "e"),
                           ("mode", "Mod", 60, "center"), ("device", "İşlemci", 240, "w")):
            tv.heading(c, text=t, anchor=a)
            tv.column(c, width=w, anchor=a)
        tv.tag_configure("best", foreground=C["accent2"])
        tv.pack(fill="both", expand=True)
        self.histtv = tv
        bar = tk.Frame(tab, bg=C["bg"])
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Seçileni dışa aktar…", style="Small.TButton",
                   command=self._export_selected).pack(side="left")
        ttk.Button(bar, text="Geçmişi temizle", style="Small.TButton",
                   command=self._clear_history).pack(side="left", padx=8)
        tk.Label(bar, text=f"Kayıt yeri: {engine.HISTORY_FILE}", fg=C["muted"], bg=C["bg"],
                 font=F(9)).pack(side="right")

    # ------------------------------------------------------------ veri
    def _load_sysinfo(self):
        self.q.put(("sysinfo", sysinfo.collect()))

    def _show_sysinfo(self, info):
        self.sys = info
        self.systv.delete(*self.systv.get_children())
        for key, label in sysinfo.LABELS:
            if key in info:
                self.systv.insert("", "end", text=label, values=(info[key],))
        self.head_cpu.config(text=f"{info.get('cpu')}  ·  {info.get('ram')}  ·  {info.get('os')}")
        for key, _ in DeviceCard.FIELDS:
            self.device.set(key, info.get(key))

    def _fill_history(self):
        tv = self.histtv
        tv.delete(*tv.get_children())
        best = max((h.get("total", 0) for h in self.history), default=0)
        for i in range(len(self.history) - 1, -1, -1):
            h = self.history[i]
            cats = h.get("categories", {})
            tv.insert("", "end", iid=str(i), tags=("best",) if h.get("total") == best else (), values=(
                h.get("date", "").replace("T", " "), engine.fmt_score(h.get("total", 0)),
                *(engine.fmt_score(cats[c]) if c in cats else "—" for c, _ in engine.CATEGORIES),
                "Hızlı" if h.get("quick") else "Tam", h.get("system", {}).get("cpu", "")))

    # ------------------------------------------------------------ test akışı
    def start(self):
        if self.thread and self.thread.is_alive():
            return
        for card in self.cards.values():
            card.reset()
        for cat, _ in engine.CATEGORIES:
            self.detail.set(cat, "score", "—")
        for tid in engine.TESTS:
            self.detail.set(tid, "value", "—")
            self.detail.set(tid, "score", "—")
        self.cat_scores = {c: 0 for c, _ in engine.CATEGORIES}
        self.stop_event = threading.Event()
        self.start_btn.pack_forget()
        self.stop_btn.pack(fill="x", before=self.quick_chk)
        self.quick_chk.state(["disabled"])
        self.export_btn.state(["disabled"])
        self.pbar["value"] = 0
        self.gauge.progress(0, C["accent"], "Hazırlanıyor")
        self.status.config(text="Test başlıyor… Bu sırada bilgisayarı kullanmamak sonucu iyileştirir.")
        self.thread = threading.Thread(target=self._worker, args=(self.quick.get(),), daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.stop_btn.state(["disabled"])
        self.status.config(text="Mevcut adım bitince durdurulacak…")

    def _worker(self, quick):
        try:
            info = self.sys or sysinfo.collect()
            res = engine.run(
                info, quick=quick, stop_event=self.stop_event,
                progress=lambda i, n, t: self.q.put(("progress", i, n, t)),
                on_result=lambda tid, v, p, e: self.q.put(("result", tid, v, p, e)))
            self.history = engine.save_history(res)
            self.q.put(("done", res))
        except engine.Cancelled:
            self.q.put(("cancelled",))
        except Exception:
            self.q.put(("error", traceback.format_exc()))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                getattr(self, "_on_" + msg[0])(*msg[1:])
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _on_sysinfo(self, info):
        self._show_sysinfo(info)

    def _on_progress(self, i, n, title):
        self.pbar["value"] = i
        tid = engine.STEPS[min(i, n - 1)][1][0]
        color = CAT_COLOR[engine.TESTS[tid]["cat"]]
        self.gauge.progress(i / n, color, title)
        if i < n:
            self.status.config(text=f"Adım {i + 1}/{n}: {title}")

    def _on_result(self, tid, value, points, extra):
        t = engine.TESTS[tid]
        self.cat_scores[t["cat"]] += points
        card = self.cards[t["cat"]]
        card.set_test(tid, points)
        card.set_score(self.cat_scores[t["cat"]])
        if extra.get("scaling"):
            card.note.config(text=f"{extra['threads']} iş parçacığı · {extra['scaling']:.1f}x çok çekirdek ölçekleme")
        if extra.get("penalty"):
            card.note.config(text=f"Önbellek atlanamadı: okuma puanları -%{extra['penalty'] * 100:.0f} "
                                  "ve en fazla taban puan")
        if extra.get("error"):
            card.note.config(text=f"GPU testi yapılamadı: {extra['error']}", fg=C["accent2"])
        elif extra.get("renderer"):
            soft = " · yazılımsal, gerçek GPU değil" if extra.get("software") else ""
            card.note.config(text=f"{extra['renderer']} · 1080p'de {extra.get('fps_1080p', 0):.0f} FPS{soft}",
                             fg=C["muted"])
            self.device.set("gpu", extra["renderer"])
        self.detail.set(tid, "value", engine.fmt_value(value))
        self.detail.set(tid, "score", engine.fmt_score(points))
        self.detail.set(t["cat"], "score", engine.fmt_score(self.cat_scores[t["cat"]]))

    def _finish_ui(self):
        self.stop_btn.pack_forget()
        self.stop_btn.state(["!disabled"])
        self.start_btn.pack(fill="x", before=self.quick_chk)
        self.start_btn.config(text="TEKRAR TEST ET")
        self.quick_chk.state(["!disabled"])

    def _on_done(self, res):
        self._finish_ui()
        self.last_result = res
        self.export_btn.state(["!disabled"])
        self.pbar["value"] = len(engine.STEPS)
        self._fill_history()
        pct = res["total"] / engine.TOTAL_BASE * 100
        self.status.config(text=f"Tamamlandı · {res['duration']} saniye sürdü")
        self.compare.config(text=f"Referans makinenin (Apple M1, 100.000) %{pct:.0f}'i kadar performans")
        self._animate(res, 0)

    def _animate(self, res, step, steps=45):
        frac = 1 - (1 - step / steps) ** 3  # ease-out
        parts = [(res["categories"][c], CAT_COLOR[c]) for c, _ in engine.CATEGORIES]
        self.gauge.segments(parts, frac)
        self.gauge.set_text(engine.fmt_score(int(res["total"] * frac)), "TOPLAM PUAN")
        if step < steps:
            self.root.after(22, self._animate, res, step + 1)

    def _on_cancelled(self):
        self._finish_ui()
        self.start_btn.config(text="TESTİ BAŞLAT")
        self.gauge.set_text("—", "DURDURULDU")
        self.status.config(text="Test durduruldu.")

    def _on_error(self, tb):
        self._on_cancelled()
        self.gauge.set_text("!", "HATA")
        self.status.config(text="Test sırasında hata oluştu.")
        messagebox.showerror("PyBench", "Test sırasında hata oluştu:\n\n" + tb[-1500:])

    # ------------------------------------------------------------ dışa aktarma / geçmiş
    def export(self, result):
        if not result:
            return
        stamp = result["date"].replace(":", "").replace("-", "").replace("T", "_")
        path = filedialog.asksaveasfilename(
            title="Sonucu kaydet", initialfile=f"pybench_{stamp}.txt", defaultextension=".txt",
            filetypes=[("Metin raporu", "*.txt"), ("JSON", "*.json")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            if path.lower().endswith(".json"):
                json.dump(result, f, ensure_ascii=False, indent=2)
            else:
                f.write(engine.report_text(result))
        self.status.config(text=f"Kaydedildi: {path}")

    def _export_selected(self):
        sel = self.histtv.selection()
        if sel:
            self.export(self.history[int(sel[0])])

    def _clear_history(self):
        if self.history and messagebox.askyesno("PyBench", "Tüm test geçmişi silinsin mi?"):
            engine.clear_history()
            self.history = []
            self._fill_history()

    def _on_close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # yüksek DPI ekranlarda net görüntü
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()
