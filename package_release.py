"""Create downloadable native ZIP with BOTH binaries.

Usage: python package_release.py [windows|macos|linux]
"""
from pathlib import Path
import os
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
def package(target):
    dist = ROOT / "dist"
    if not dist.is_dir():
        raise SystemExit("dist/ 不存在；先运行 python build.py")
    desired = {
        "windows": ["DesktopAgent.exe", "demo_mcp_server.exe"],
        "linux": ["DesktopAgent", "demo_mcp_server"],
        "macos": ["DesktopAgent.app", "demo_mcp_server"],
    }[target]
    for name in desired:
        if not (dist / name).exists():
            raise SystemExit(f"缺少 {name}；检查当前平台的 build.py 结果")
    release = ROOT / "release"
    release.mkdir(exist_ok=True)
    dest = release / f"DesktopAgent-v1.0.0-{target}.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in desired:
            entry = dist / name
            children = [entry] if entry.is_file() else sorted(entry.rglob("*"))
            for p in children:
                if p.is_file():
                    z.write(p, arcname=f"DesktopAgent-{target}/" +
                            str(p.relative_to(dist)).replace(os.sep, "/"))
        z.write(ROOT / "README.md", f"DesktopAgent-{target}/README.md")
        z.write(ROOT / "report.md", f"DesktopAgent-{target}/report.md")
    print(dest)
    return dest

if __name__ == "__main__":
    default = "windows" if sys.platform == "win32" else ("macos" if sys.platform == "darwin" else "linux")
    package(sys.argv[1] if len(sys.argv) > 1 else default)
