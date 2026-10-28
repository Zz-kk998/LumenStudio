"""Build TWO native executables for the current OS using PyInstaller.

The second binary is an actual external MCP stdio server. Keep both binaries
together in the release folder.
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

def build():
    if shutil.which("pyinstaller") is None:
        print("请先安装：python -m pip install -r requirements-build.txt")
        return 1
    sep = os.pathsep
    common = [sys.executable, "-m", "PyInstaller",
              "--noconfirm", "--clean", "--onefile"]
    subprocess.run(common + ["--windowed", "--name", "DesktopAgent",
        "--add-data", f"mcp.json{sep}.",
        "--add-data", f"examples{sep}examples",
        "main.py"], cwd=ROOT, check=True)
    subprocess.run(common + ["--name", "demo_mcp_server",
        "server/demo_mcp_server.py"], cwd=ROOT, check=True)
    print("Build complete: DesktopAgent.exe and demo_mcp_server.exe are in dist/")
    return 0

if __name__ == "__main__":
    raise SystemExit(build())
