"""Generate build inputs from the source of truth in qpop.py.

Writes to build/:
  icon.ico          - multi-size app icon (same bell as the tray)
  version_info.txt  - Windows file properties for QPop.exe (Details tab)
  version.txt       - plain version string, read by build.bat for the installer
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import qpop  # noqa: E402

BUILD = os.path.join(ROOT, "build")
os.makedirs(BUILD, exist_ok=True)

version = qpop.__version__
parts = (list(qpop.parse_version(version)) + [0, 0, 0, 0])[:4]

qpop.draw_logo(qpop.COLORS["normal"], 256).save(
    os.path.join(BUILD, "icon.ico"),
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)

with open(os.path.join(BUILD, "version_info.txt"), "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(parts)}, prodvers={tuple(parts)}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'QPop'),
      StringStruct('FileDescription', 'QPop - queue pop notifications'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'QPop'),
      StringStruct('OriginalFilename', 'QPop.exe'),
      StringStruct('ProductName', 'QPop'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")

with open(os.path.join(BUILD, "version.txt"), "w", encoding="utf-8") as f:
    f.write(version)

print(f"Build assets for QPop {version} written to {BUILD}")
