#!/usr/bin/env python3
"""
Verify the /bates encrypted-PDF preflight (hybrid soft-fail model):

  • all_clear         — plain PDFs only, 200 OK, no X-Failed-Files header
  • single_encrypted  — one encrypted PDF, 200 OK, X-Failed-Files lists it,
                        clean PDFs still labeled
  • multiple_encrypted — several encrypted PDFs, 200 OK, every encrypted file
                         listed in X-Failed-Files

Runs the endpoint in-process via FastAPI's TestClient so no live Render
deploy or running uvicorn is required.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pikepdf
from fastapi.testclient import TestClient
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as rl_canvas

from main import app

client = TestClient(app)


def _make_pdf(text: str = "hello") -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return buf.getvalue()


def _encrypt_pdf(pdf_bytes: bytes, password: str = "secret") -> bytes:
    """Return an AES-256 encrypted copy of pdf_bytes."""
    src = pikepdf.open(io.BytesIO(pdf_bytes))
    out = io.BytesIO()
    src.save(
        out,
        encryption=pikepdf.Encryption(owner=password, user=password, R=6),
    )
    src.close()
    return out.getvalue()


def _make_zip(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return buf.getvalue()


def _post_bates(zip_bytes: bytes):
    return client.post(
        "/bates",
        files={"files": ("upload.zip", zip_bytes, "application/zip")},
        data={"prefix": "TEST", "start_num": "1", "digits": "6"},
    )


def _output_pdf_names(resp) -> list[str]:
    """Names of PDFs in the response.

    /bates returns a ZIP for multi-file batches but unwraps single-file
    results to a bare PDF (see `_maybe_unwrap_single_file_path`). We
    handle both: the bare-PDF case is reported via Content-Disposition.
    """
    ctype = resp.headers.get("content-type", "")
    if "application/zip" in ctype:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            return [i.filename for i in zf.infolist()
                    if not i.is_dir()
                    and "__bates_records" not in i.filename]

    # Bare PDF — derive name from Content-Disposition for visibility.
    dispo = resp.headers.get("content-disposition", "")
    out_name = dispo.split('filename="', 1)[-1].rstrip('"') if 'filename="' in dispo else "<single>"
    return [out_name]


def test_all_clear():
    zip_bytes = _make_zip([
        ("a.pdf", _make_pdf("alpha")),
        ("b.pdf", _make_pdf("bravo")),
    ])
    resp = _post_bates(zip_bytes)
    assert resp.status_code == 200, resp.text
    assert "X-Failed-Files" not in resp.headers, \
        f"expected no failures, got {resp.headers.get('X-Failed-Files')!r}"
    names = _output_pdf_names(resp)
    assert sorted(names) == ["a.pdf", "b.pdf"], names
    print(f"  all_clear:           200 OK, no failures, labeled {names}")


def test_single_encrypted():
    # Two clean files keep the output a ZIP (single-file results unwrap to a
    # bare PDF named after the upload, which would hide the source names).
    zip_bytes = _make_zip([
        ("clean1.pdf", _make_pdf("one")),
        ("clean2.pdf", _make_pdf("two")),
        ("locked.pdf", _encrypt_pdf(_make_pdf("locked"))),
    ])
    resp = _post_bates(zip_bytes)
    assert resp.status_code == 200, resp.text

    raw = resp.headers.get("X-Failed-Files")
    assert raw, "expected X-Failed-Files header"
    failures = json.loads(raw)
    assert "locked.pdf" in failures, failures
    assert "Unlock" in failures["locked.pdf"], failures["locked.pdf"]

    names = _output_pdf_names(resp)
    assert sorted(names) == ["clean1.pdf", "clean2.pdf"], \
        f"expected both clean files, locked absent; got {names}"
    print(f"  single_encrypted:    200 OK, failures={failures}, labeled={sorted(names)}")


def test_multiple_encrypted():
    # Two clean files keep the output a ZIP (see test_single_encrypted note).
    zip_bytes = _make_zip([
        ("clean1.pdf", _make_pdf("clean1")),
        ("clean2.pdf", _make_pdf("clean2")),
        ("locked1.pdf", _encrypt_pdf(_make_pdf("a"))),
        ("locked2.pdf", _encrypt_pdf(_make_pdf("b"))),
        ("sub/locked3.pdf", _encrypt_pdf(_make_pdf("c"))),
    ])
    resp = _post_bates(zip_bytes)
    assert resp.status_code == 200, resp.text

    raw = resp.headers.get("X-Failed-Files")
    assert raw, "expected X-Failed-Files header"
    failures = json.loads(raw)
    for name in ("locked1.pdf", "locked2.pdf", "sub/locked3.pdf"):
        assert name in failures, f"missing {name!r} in {failures}"
        assert "Unlock" in failures[name]

    names = _output_pdf_names(resp)
    assert sorted(names) == ["clean1.pdf", "clean2.pdf"], \
        f"expected both clean files, all locked absent; got {names}"
    print(f"  multiple_encrypted:  200 OK, {len(failures)} failures flagged, labeled={sorted(names)}")


def main():
    print("Running /bates encrypted-PDF preflight tests:")
    test_all_clear()
    test_single_encrypted()
    test_multiple_encrypted()
    print("\nAll preflight tests passed.")


if __name__ == "__main__":
    main()