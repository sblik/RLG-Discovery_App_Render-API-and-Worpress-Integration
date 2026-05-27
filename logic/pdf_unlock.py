"""
PDF password removal/unlock functionality.

Contains: Functions to decrypt password-protected PDFs.
"""
from __future__ import annotations

import io
import logging
import os
import zipfile
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

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
) -> tuple:
    """
    Unlock password-protected PDFs.

    Args:
        files: List of (filename, file_bytes) tuples
        password_mode: "Single password for all", "Per-file password list (CSV)", or "Try no password"
        password_for_all: Password to use for all files (if mode is single)
        password_map: Dict mapping filenames to passwords (if mode is per-file)

    Returns:
        Tuple of (zip_bytes, failures) where failures is a dict mapping
        filename -> reason string for every file that could not be unlocked.
        Successfully unlocked files are in the ZIP; failed files are omitted
        so the batch never aborts for one bad file.
    """
    if not PIKEPDF_AVAILABLE:
        raise RuntimeError("pikepdf is not installed")

    pdf_count = sum(1 for f, _ in files if f.lower().endswith(".pdf") and not _is_mac_resource_junk(f))
    logger.info("unlock_pdfs: %d PDF(s), mode=%r", pdf_count, password_mode)

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

    # failures maps filename → human-readable reason for every file skipped.
    # Populated below so the caller can surface it in X-Failed-Files header.
    failures: Dict[str, str] = {}

    zip_buffer = io.BytesIO()
    succeeded = 0
    failures = []
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fname, data in files:
            if _is_mac_resource_junk(fname):
                continue
            if fname.lower().endswith(".pdf"):
                status, unlocked_data = _process_pdf(data, _resolve_password(fname))
                out_name = os.path.splitext(fname)[0] + ".pdf"
                if unlocked_data is not None:
                    zf.writestr(out_name, unlocked_data)
                else:
                    # _process_pdf returns (reason_str, None) on failure
                    failures[fname] = status
                    logger.warning("Unlock skipped %s: %s", fname, status)
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
                            else:
                                failures[member] = status
                                logger.warning("Unlock skipped %s: %s", member, status)
                except zipfile.BadZipFile:
                    failures[fname] = "Not a valid ZIP file"
                    logger.warning("Unlock skipped nested ZIP %s: bad ZIP", fname)

    zip_buffer.seek(0)
    n_ok = pdf_count - len(failures)
    if failures:
        logger.warning("unlock_pdfs: %d succeeded, %d failed: %s", n_ok, len(failures),
                       list(failures.keys()))
    else:
        logger.info("unlock_pdfs: all %d PDF(s) unlocked successfully", n_ok)
    return zip_buffer.read(), failures


def check_passwords(
    files: List[Tuple[str, bytes]],
    password_map: Dict[str, str],
) -> List[str]:
    """
    Pre-validate per-file passwords without doing any processing.

    Tries to open each file whose name appears in *password_map* using the
    provided password.  Returns a list of filenames for which the password
    was **incorrect**.  Files not in *password_map* are skipped (no check).
    Files that are not PDFs are also skipped.

    Used by /pipeline/run to catch wrong passwords before OCR starts so the
    attorney can correct them without wasting processing time.
    """
    if not PIKEPDF_AVAILABLE:
        return []

    checked = [f for f, _ in files if f.lower().endswith(".pdf")]
    logger.info("check_passwords: pre-validating passwords for %d PDF(s)", len(checked))
    bad: List[str] = []
    for fname, data in files:
        if not fname.lower().endswith(".pdf"):
            continue
        base = os.path.basename(fname)
        stem = os.path.splitext(base)[0]
        pw = password_map.get(fname) or password_map.get(base) or password_map.get(stem)
        if not pw:
            continue  # No password provided for this file — skip check
        try:
            with io.BytesIO(data) as buf:
                pikepdf.open(buf, password=pw).close()
        except PasswordError:
            bad.append(fname)
            logger.warning("check_passwords: wrong password for '%s'", fname)
        except Exception:
            pass  # Non-password errors are handled during actual processing

    if bad:
        logger.warning("check_passwords: %d file(s) have incorrect passwords: %s",
                       len(bad), bad)
    else:
        logger.info("check_passwords: all passwords validated successfully")
    return bad
