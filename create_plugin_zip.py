"""Build the installable WordPress plugin zip.

Path-independent: locations are derived from this file's location, so it runs
on any machine/OS without editing. Output is named for the plugin version read
from the plugin header, e.g. rlg-discovery-integration-1.7.7.zip
"""
import os
import re
import zipfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(REPO_ROOT, "wordpress-plugin")          # arcnames are relative to here
SRC_DIR = os.path.join(BASE_DIR, "rlg-discovery-integration")
PLUGIN_PHP = os.path.join(SRC_DIR, "rlg-discovery-integration.php")

SKIP_FILES = {".DS_Store", "Thumbs.db"}
SKIP_DIRS = {"__MACOSX", ".idea", "__pycache__", ".git"}


def read_version():
    with open(PLUGIN_PHP, encoding="utf-8") as f:
        m = re.search(r"^\s*\*\s*Version:\s*(.+?)\s*$", f.read(), re.MULTILINE)
    return m.group(1) if m else "0.0.0"


def create_zip():
    version = read_version()
    output_filename = os.path.join(REPO_ROOT, f"rlg-discovery-integration-{version}.zip")

    files = []
    for root, dirs, names in os.walk(SRC_DIR):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(names):
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            files.append(os.path.join(root, name))

    print(f"Zipping from: {SRC_DIR}")
    print(f"Output to:    {output_filename}")

    with zipfile.ZipFile(output_filename, "w", zipfile.ZIP_DEFLATED) as zf:
        # explicit directory entries (matches prior release layout)
        dir_arcs = set()
        for path in files:
            d = os.path.dirname(os.path.relpath(path, BASE_DIR))
            while d and d not in dir_arcs:
                dir_arcs.add(d)
                d = os.path.dirname(d)
        for d in sorted(dir_arcs):
            zf.writestr(d.replace(os.sep, "/") + "/", "")
        for path in files:
            arcname = os.path.relpath(path, BASE_DIR).replace(os.sep, "/")
            print(f"Adding: {arcname}")
            zf.write(path, arcname=arcname)

    print(f"Zip created successfully: {os.path.basename(output_filename)}")


if __name__ == "__main__":
    create_zip()
