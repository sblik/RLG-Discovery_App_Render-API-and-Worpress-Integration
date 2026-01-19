#!/usr/bin/env python3
"""
Test script to verify Bates label positioning fix.
Creates synthetic PDFs with different mediabox configurations and tests the labeling.
"""

import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

import logic

# PDF generation imports
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.colors import Color

try:
    import pikepdf
    PIKEPDF_AVAILABLE = True
except ImportError:
    PIKEPDF_AVAILABLE = False
    print("WARNING: pikepdf not available, some tests will be skipped")


def create_normal_pdf() -> bytes:
    """Create a standard PDF with mediabox at [0, 0, 612, 792] (letter size)."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 24)
    c.drawString(100, 700, "Normal PDF - MediaBox at origin")
    c.drawString(100, 650, "MediaBox: [0, 0, 612, 792]")
    c.setFont("Helvetica", 12)
    c.drawString(100, 600, "This is a standard letter-size PDF.")
    c.drawString(100, 580, "The Bates label should appear in the bottom-right corner.")
    # Draw a border to visualize page edges
    c.setStrokeColor(Color(0.8, 0.8, 0.8))
    c.rect(10, 10, 592, 772)
    c.save()
    return buf.getvalue()


def create_offset_origin_pdf() -> bytes:
    """Create a PDF with mediabox that has a non-zero origin."""
    if not PIKEPDF_AVAILABLE:
        raise RuntimeError("pikepdf required for this test")

    # First create a normal PDF
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.setFont("Helvetica", 24)
    c.drawString(100, 700, "Offset Origin PDF")
    c.drawString(100, 650, "MediaBox: [72, 72, 684, 864]")
    c.setFont("Helvetica", 12)
    c.drawString(100, 600, "This PDF has a mediabox with non-zero origin.")
    c.drawString(100, 580, "The Bates label should still appear correctly positioned.")
    c.setStrokeColor(Color(0.8, 0.8, 0.8))
    c.rect(10, 10, 592, 772)
    c.save()

    # Now modify the mediabox using pikepdf
    pdf = pikepdf.open(io.BytesIO(buf.getvalue()))
    page = pdf.pages[0]
    # Set mediabox with 1-inch (72pt) offset origin
    # This creates a page where the coordinate system starts at (72, 72)
    page.mediabox = [72, 72, 684, 864]  # Still 612x792 in size, but offset origin

    out_buf = io.BytesIO()
    pdf.save(out_buf)
    pdf.close()
    return out_buf.getvalue()


def create_different_size_pdf() -> bytes:
    """Create a PDF with A4 page size."""
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)  # A4 is 595.27 x 841.89 points
    c.setFont("Helvetica", 24)
    c.drawString(100, 750, "A4 Size PDF")
    c.drawString(100, 700, f"MediaBox: [0, 0, {A4[0]:.0f}, {A4[1]:.0f}]")
    c.setFont("Helvetica", 12)
    c.drawString(100, 650, "This is an A4-sized PDF (different from US Letter).")
    c.drawString(100, 630, "The Bates label should adapt to the page dimensions.")
    c.setStrokeColor(Color(0.8, 0.8, 0.8))
    c.rect(10, 10, A4[0] - 20, A4[1] - 20)
    c.save()
    return buf.getvalue()


def create_multi_page_pdf() -> bytes:
    """Create a multi-page PDF with mixed configurations."""
    if not PIKEPDF_AVAILABLE:
        raise RuntimeError("pikepdf required for this test")

    # Create a 3-page PDF
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)

    # Page 1 - normal
    c.setFont("Helvetica", 24)
    c.drawString(100, 700, "Page 1 - Normal Origin")
    c.setFont("Helvetica", 12)
    c.drawString(100, 650, "MediaBox at [0, 0, 612, 792]")
    c.showPage()

    # Page 2 - will be modified to have offset origin
    c.setFont("Helvetica", 24)
    c.drawString(100, 700, "Page 2 - Will Have Offset Origin")
    c.setFont("Helvetica", 12)
    c.drawString(100, 650, "MediaBox will be [72, 72, 684, 864]")
    c.showPage()

    # Page 3 - normal again
    c.setFont("Helvetica", 24)
    c.drawString(100, 700, "Page 3 - Normal Origin Again")
    c.setFont("Helvetica", 12)
    c.drawString(100, 650, "MediaBox at [0, 0, 612, 792]")
    c.save()

    # Modify page 2's mediabox
    pdf = pikepdf.open(io.BytesIO(buf.getvalue()))
    pdf.pages[1].mediabox = [72, 72, 684, 864]

    out_buf = io.BytesIO()
    pdf.save(out_buf)
    pdf.close()
    return out_buf.getvalue()


def run_bates_labeling(pdf_bytes: bytes, filename: str, diagnostics: bool = True) -> bytes:
    """Run Bates labeling on a PDF and return the labeled PDF bytes."""
    file_pairs = [(filename, pdf_bytes)]

    records, last_used, labeled_pairs = logic.walk_and_label(
        file_pairs,
        prefix="TEST",
        start_num=1,
        digits=6,
        font_name="Helvetica",
        font_size=12,
        zone="Bottom Right (Z3)",
        zone_padding=18.0,
        color_rgb=(0, 0, 255),  # Blue
        diagnostics=diagnostics
    )

    print(f"\n  Labeled {len(records)} file(s), last Bates number: {last_used}")
    for rec in records:
        print(f"    - {rec.filename}: {rec.first_label} to {rec.last_label} ({rec.pages_or_files} pages)")

    if labeled_pairs:
        return labeled_pairs[0][1]
    return b""


def inspect_pdf_mediabox(pdf_bytes: bytes, label: str):
    """Inspect and print the mediabox of each page in a PDF."""
    if not PIKEPDF_AVAILABLE:
        print(f"  Cannot inspect {label} - pikepdf not available")
        return

    pdf = pikepdf.open(io.BytesIO(pdf_bytes))
    print(f"\n  {label}:")
    for i, page in enumerate(pdf.pages):
        mbox = page.mediabox
        print(f"    Page {i+1} MediaBox: [{float(mbox[0]):.1f}, {float(mbox[1]):.1f}, {float(mbox[2]):.1f}, {float(mbox[3]):.1f}]")
        cropbox = getattr(page, 'cropbox', None)
        if cropbox:
            print(f"    Page {i+1} CropBox: [{float(cropbox[0]):.1f}, {float(cropbox[1]):.1f}, {float(cropbox[2]):.1f}, {float(cropbox[3]):.1f}]")
    pdf.close()


def main():
    print("=" * 60)
    print("BATES LABEL POSITIONING TEST")
    print("=" * 60)

    # Create output directory
    output_dir = Path(__file__).parent / "test_output"
    output_dir.mkdir(exist_ok=True)

    # Test 1: Normal PDF
    print("\n[TEST 1] Normal PDF (MediaBox at origin)")
    print("-" * 40)
    normal_pdf = create_normal_pdf()
    inspect_pdf_mediabox(normal_pdf, "Before labeling")
    labeled_normal = run_bates_labeling(normal_pdf, "normal.pdf")
    if labeled_normal:
        inspect_pdf_mediabox(labeled_normal, "After labeling")
        (output_dir / "labeled_normal.pdf").write_bytes(labeled_normal)
        print(f"  Saved to: {output_dir / 'labeled_normal.pdf'}")

    # Test 2: Offset Origin PDF
    if PIKEPDF_AVAILABLE:
        print("\n[TEST 2] Offset Origin PDF (MediaBox at [72, 72, ...])")
        print("-" * 40)
        offset_pdf = create_offset_origin_pdf()
        inspect_pdf_mediabox(offset_pdf, "Before labeling")
        labeled_offset = run_bates_labeling(offset_pdf, "offset_origin.pdf")
        if labeled_offset:
            inspect_pdf_mediabox(labeled_offset, "After labeling")
            (output_dir / "labeled_offset_origin.pdf").write_bytes(labeled_offset)
            print(f"  Saved to: {output_dir / 'labeled_offset_origin.pdf'}")
    else:
        print("\n[TEST 2] SKIPPED - pikepdf not available")

    # Test 3: Different Size (A4)
    print("\n[TEST 3] A4 Size PDF")
    print("-" * 40)
    a4_pdf = create_different_size_pdf()
    inspect_pdf_mediabox(a4_pdf, "Before labeling")
    labeled_a4 = run_bates_labeling(a4_pdf, "a4_size.pdf")
    if labeled_a4:
        inspect_pdf_mediabox(labeled_a4, "After labeling")
        (output_dir / "labeled_a4.pdf").write_bytes(labeled_a4)
        print(f"  Saved to: {output_dir / 'labeled_a4.pdf'}")

    # Test 4: Multi-page with mixed origins
    if PIKEPDF_AVAILABLE:
        print("\n[TEST 4] Multi-page PDF with Mixed MediaBox Origins")
        print("-" * 40)
        multi_pdf = create_multi_page_pdf()
        inspect_pdf_mediabox(multi_pdf, "Before labeling")
        labeled_multi = run_bates_labeling(multi_pdf, "multi_page.pdf")
        if labeled_multi:
            inspect_pdf_mediabox(labeled_multi, "After labeling")
            (output_dir / "labeled_multi_page.pdf").write_bytes(labeled_multi)
            print(f"  Saved to: {output_dir / 'labeled_multi_page.pdf'}")
    else:
        print("\n[TEST 4] SKIPPED - pikepdf not available")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print(f"Output files saved to: {output_dir}")
    print("=" * 60)
    print("\nPlease visually inspect the labeled PDFs to verify:")
    print("  1. Labels appear in the correct position (bottom-right)")
    print("  2. Labels are consistently positioned across all pages")
    print("  3. Labels adapt correctly to different page sizes")


if __name__ == "__main__":
    main()
