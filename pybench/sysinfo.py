"""Sistem bilgilerini (işletim sistemi, CPU, RAM, GPU) platforma göre toplar."""

import os
import platform
import shutil
import subprocess
import sys

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # Windows'ta konsol penceresi açılmasın


_EXTRA_PATHS = ["/usr/sbin", "/sbin", "/usr/bin", "/bin", "/usr/local/bin"]


def _run(cmd, timeout=8):
    # Paketlenmiş uygulama Finder/masaüstünden açılınca PATH kısıtlı olabilir
    exe = shutil.which(cmd[0]) or shutil.which(
        cmd[0], path=os.pathsep.join([os.environ.get("PATH", "")] + _EXTRA_PATHS))
    if not exe:
        return ""
    cmd = [exe] + list(cmd[1:])
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def _fmt_gb(num_bytes):
    return f"{num_bytes / (1 << 30):.1f} GB" if num_bytes else "Bilinmiyor"


# ---------------------------------------------------------------- macOS
def _mac():
    info = {}
    ver = platform.mac_ver()[0]
    info["os"] = f"macOS {ver}" if ver else "macOS"
    info["cpu"] = _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor()
    info["physical_cores"] = _run(["sysctl", "-n", "hw.physicalcpu"])
    perf = _run(["sysctl", "-n", "hw.perflevel0.physicalcpu"])
    eff = _run(["sysctl", "-n", "hw.perflevel1.physicalcpu"])
    if perf and eff:
        info["core_layout"] = f"{perf} performans + {eff} verimlilik"
    mem = _run(["sysctl", "-n", "hw.memsize"])
    info["ram"] = _fmt_gb(int(mem)) if mem.isdigit() else "Bilinmiyor"
    gpus = [line.split(":", 1)[1].strip()
            for line in _run(["system_profiler", "SPDisplaysDataType"], timeout=15).splitlines()
            if "Chipset Model" in line]
    info["gpu"] = ", ".join(gpus)
    model = _run(["sysctl", "-n", "hw.model"])
    if model:
        info["model"] = model
    return info


# ---------------------------------------------------------------- Linux
def _linux():
    info = {}
    distro = ""
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            distro = line.split("=", 1)[1].strip().strip('"')
    info["os"] = f"{distro or 'Linux'} (çekirdek {platform.release()})"

    cpuinfo = _read("/proc/cpuinfo")
    cpu = ""
    for line in cpuinfo.splitlines():
        if line.lower().startswith(("model name", "hardware", "cpu model")):
            cpu = line.split(":", 1)[1].strip()
            break
    lscpu = _run(["lscpu"])
    if not cpu:
        for line in lscpu.splitlines():
            if line.startswith("Model name:"):
                cpu = line.split(":", 1)[1].strip()
    info["cpu"] = cpu or platform.processor() or platform.machine()

    cores = set()
    phys = core = None
    for line in cpuinfo.splitlines():
        if line.startswith("physical id"):
            phys = line.split(":")[1].strip()
        elif line.startswith("core id"):
            core = line.split(":")[1].strip()
            cores.add((phys, core))
    if cores:
        info["physical_cores"] = str(len(cores))
    else:
        parsed = _run(["lscpu", "-p=core,socket"])
        uniq = {l for l in parsed.splitlines() if l and not l.startswith("#")}
        if uniq:
            info["physical_cores"] = str(len(uniq))

    for line in _read("/proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            info["ram"] = _fmt_gb(int(line.split()[1]) * 1024)
    gpus = []
    for line in _run(["lspci"]).splitlines():
        if "VGA" in line or "3D controller" in line or "Display controller" in line:
            gpus.append(line.split(":", 2)[-1].strip())
    info["gpu"] = ", ".join(gpus)
    model = _read("/sys/devices/virtual/dmi/id/product_name").strip()
    if model:
        info["model"] = model
    return info


# ---------------------------------------------------------------- Windows
def _windows():
    import ctypes
    import winreg

    info = {}
    build = sys.getwindowsversion().build
    name = "11" if build >= 22000 and platform.release() == "10" else platform.release()
    info["os"] = f"Windows {name} (derleme {build})"

    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        info["cpu"] = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    except OSError:
        info["cpu"] = platform.processor()

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        info["ram"] = _fmt_gb(stat.ullTotalPhys)

    ps = _run(["powershell", "-NoProfile", "-Command",
               "(Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum;"
               "(Get-CimInstance Win32_VideoController).Name;"
               "(Get-CimInstance Win32_ComputerSystem).Model"], timeout=20)
    lines = [l.strip() for l in ps.splitlines() if l.strip()]
    if lines and lines[0].isdigit():
        info["physical_cores"] = lines.pop(0)
    if lines:
        info["model"] = lines.pop()
    info["gpu"] = ", ".join(lines)
    return info


def collect():
    """Sistem bilgilerini sözlük olarak döndürür; hata olsa bile çökmez."""
    base = {
        "os": platform.platform(),
        "cpu": platform.processor() or platform.machine(),
        "arch": platform.machine(),
        "logical_cores": str(os.cpu_count() or 1),
        "physical_cores": "",
        "ram": "Bilinmiyor",
        "gpu": "",
        "python": f"{platform.python_implementation()} {platform.python_version()}",
        "hostname": platform.node(),
    }
    try:
        if sys.platform == "darwin":
            base.update(_mac())
        elif sys.platform.startswith("linux"):
            base.update(_linux())
        elif sys.platform == "win32":
            base.update(_windows())
    except Exception:
        pass
    base = {k: (v or "Bilinmiyor") for k, v in base.items()}
    return base


LABELS = [
    ("model", "Cihaz modeli"),
    ("os", "İşletim sistemi"),
    ("cpu", "İşlemci"),
    ("arch", "Mimari"),
    ("physical_cores", "Fiziksel çekirdek"),
    ("core_layout", "Çekirdek düzeni"),
    ("logical_cores", "Mantıksal çekirdek"),
    ("ram", "Bellek (RAM)"),
    ("gpu", "Ekran kartı"),
    ("python", "Python"),
    ("hostname", "Bilgisayar adı"),
]
