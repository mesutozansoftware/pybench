"""Python gerektirmeyen bağımsız uygulamayı derler (PyInstaller).

    pip install -r requirements-build.txt
    python build.py

Çıktı: dist/PyBench.exe (Windows), dist/PyBench.app (macOS), dist/PyBench (Linux)
"""

import subprocess
import sys

args = [
    sys.executable, "-m", "PyInstaller", "main.py",
    "--name", "PyBench",
    "--noconfirm", "--clean", "--windowed",
    "--collect-all", "glcontext",        # OpenGL bağlam arka uçları dinamik yükleniyor
    "--collect-submodules", "moderngl",
]
if sys.platform == "darwin":
    args += ["--osx-bundle-identifier", "io.github.mesutozansoftware.pybench"]
else:
    args += ["--onefile"]

sys.exit(subprocess.call(args))
