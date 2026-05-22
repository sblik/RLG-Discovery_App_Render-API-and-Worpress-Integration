# create_plugin_zip.py — packages the WordPress plugin folder into an installable .zip.
# NOTE: The output .zip file is listed in .gitignore and should NOT be committed.
#       Upload it manually via WP Admin → Plugins → Add New → Upload Plugin.

import zipfile
from pathlib import Path

REPO_ROOT  = Path(__file__).parent
PLUGIN_DIR = REPO_ROOT / "wordpress-plugin" / "rlg-discovery-integration"
OUTPUT_ZIP = REPO_ROOT / "rlg-discovery-integration-1.9.0.zip"

def create_zip():
    print(f"Zipping plugin from : {PLUGIN_DIR}")
    print(f"Output              : {OUTPUT_ZIP}")
    print()

    with zipfile.ZipFile(str(OUTPUT_ZIP), "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path in sorted(PLUGIN_DIR.rglob("*")):
            if abs_path.is_dir():
                continue
            arcname = abs_path.relative_to(REPO_ROOT / "wordpress-plugin")
            print(f"  + {arcname}")
            zf.write(str(abs_path), arcname=str(arcname))

    size_kb = OUTPUT_ZIP.stat().st_size / 1024
    print(f"\nDone — {OUTPUT_ZIP.name}  ({size_kb:.1f} KB)")
    print()
    print("To install:")
    print("  WP Admin → Plugins → Add New → Upload Plugin → choose this .zip")
    print("  If already installed: Deactivate → Delete → re-upload")
    print()
    print("After install, set API URL:")
    print("  WP Admin → Settings → RLG Discovery Integration")
    print("  Production : https://<your-render-app>.onrender.com")
    print("  Local test : http://localhost:8000")

if __name__ == "__main__":
    create_zip()
