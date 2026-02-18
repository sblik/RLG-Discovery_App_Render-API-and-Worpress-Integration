"""
PDF password removal/unlock functionality.

Contains: Functions to decrypt password-protected PDFs.
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import Dict, List, Optional, Tuple

from .utils import _is_mac_resource_junk

# Optional: pikepdf for unlocking & repair
try:
    import pikepdf
    from pikepdf import PasswordError, PdfError
    PIKEPDF_AVAILABLE = True
except Exception:
    pikepdf = None
    PasswordError = PdfError = Exception
    PIKEPDF_AVAILABLE = False


def unlock_pdfs(
    files: List[Tuple[str, bytes]],
    password_mode: str,
    password_for_all: Optional[str],
    password_map: Dict[str, str]
) -> bytes:
    """
    Unlock password-protected PDFs.

    Args:
        files: List of (filename, file_bytes) tuples
        password_mode: "Single password for all", "Per-file password list (CSV)", or "Try no password"
        password_for_all: Password to use for all files (if mode is single)
        password_map: Dict mapping filenames to passwords (if mode is per-file)

    Returns:
        ZIP file bytes containing unlocked PDFs
    """
    if not PIKEPDF_AVAILABLE:
        raise RuntimeError("pikepdf is not installed")

    def _resolve_password(path: str) -> Optional[str]:
        if password_mode == "Single password for all":
            return (password_for_all or "").strip() or None
        elif password_mode == "Per-file password list (CSV)":
            base = os.path.basename(path)
            stem = os.path.splitext(base)[0]
            return password_map.get(path) or password_map.get(base) or password_map.get(stem)
        else:
            return None

    def _process_pdf(src_bytes: bytes, password: Optional[str]) -> Tuple[str, Optional[bytes]]:
        try:
            with io.BytesIO(src_bytes) as src_buf:
                try:
                    pdf = pikepdf.open(src_buf) if password is None else pikepdf.open(src_buf, password=password)
                except PasswordError:
                    return "Password required or incorrect", None
                except PdfError as e:
                    return f"PDF error: {e.__class__.__name__}", None
                out_mem = io.BytesIO()
                pdf.save(out_mem)  # saved without encryption
                pdf.close()
                return "Unlocked", out_mem.getvalue()
        except Exception as e:
            return f"Unexpected error: {e}", None

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, data in files:
            if _is_mac_resource_junk(fname):
                continue
            if fname.lower().endswith(".pdf"):
                status, unlocked_data = _process_pdf(data, _resolve_password(fname))
                out_name = os.path.splitext(fname)[0] + ".pdf"
                if unlocked_data is not None:
                    zf.writestr(out_name, unlocked_data)
            elif fname.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data), 'r') as inzip:
                        for member in inzip.namelist():
                            if member.endswith('/'):
                                continue
                            if _is_mac_resource_junk(member):
                                continue
                            if not member.lower().endswith('.pdf'):
                                continue
                            pw = _resolve_password(member)
                            status, unlocked_data = _process_pdf(inzip.read(member), pw)
                            out_name = f"{os.path.splitext(member)[0]}.pdf"
                            if unlocked_data is not None:
                                zf.writestr(out_name, unlocked_data)
                except zipfile.BadZipFile:
                    pass

    zip_buffer.seek(0)
    return zip_buffer.read()
