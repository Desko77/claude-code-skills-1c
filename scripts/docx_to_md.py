#!/usr/bin/env python3
"""Convert .docx to .md with embedded images (base64 or extracted files)."""

import sys
import os
import re
import base64
import hashlib
from pathlib import Path

try:
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
except ImportError:
    print("ERROR|python-docx not installed. Run: pip install python-docx", file=sys.stderr)
    sys.exit(1)


def get_image_ext(content_type: str) -> str:
    mapping = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
        "image/bmp": "bmp",
        "image/tiff": "tiff",
        "image/x-emf": "emf",
        "image/x-wmf": "wmf",
    }
    return mapping.get(content_type, "png")


def extract_images(doc, output_dir: Path) -> dict:
    """Extract images from docx, save to output_dir/images/, return rId->relative_path mapping."""
    images_dir = output_dir / "images"
    images_dir.mkdir(exist_ok=True)
    rid_to_path = {}
    idx = 0

    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            try:
                image_part = rel.target_part
            except ValueError:
                # External image link — skip
                continue
            idx += 1
            ext = get_image_ext(image_part.content_type)
            blob = image_part.blob
            # Use hash for dedup
            h = hashlib.md5(blob).hexdigest()[:8]
            fname = f"image_{idx:03d}_{h}.{ext}"
            fpath = images_dir / fname
            fpath.write_bytes(blob)
            rid_to_path[rel.rId] = f"images/{fname}"

    return rid_to_path


def para_to_md(para, rid_to_path: dict, doc) -> str:
    """Convert a paragraph to markdown."""
    style_name = para.style.name if para.style else ""

    # Heading detection
    heading_match = re.match(r"Heading\s*(\d+)", style_name, re.IGNORECASE)
    if not heading_match:
        # Try Russian heading styles
        heading_match = re.match(r"Заголовок\s*(\d+)", style_name, re.IGNORECASE)

    # Collect inline content (text + images)
    parts = []
    for run in para.runs:
        # Check for inline images in run
        for drawing in run._element.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}drawing'):
            # Try to find blip (image reference)
            blips = drawing.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
            for blip in blips:
                embed = blip.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if embed and embed in rid_to_path:
                    parts.append(f"\n\n![image]({rid_to_path[embed]})\n\n")

        # Check for inline pictures (VML / pict)
        for pict in run._element.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pict'):
            for imagedata in pict.findall('.//{urn:schemas-microsoft-com:vml}imagedata'):
                rid = imagedata.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                if rid and rid in rid_to_path:
                    parts.append(f"\n\n![image]({rid_to_path[rid]})\n\n")

        text = run.text or ""
        if text:
            # Bold / Italic
            if run.bold and run.italic:
                text = f"***{text}***"
            elif run.bold:
                text = f"**{text}**"
            elif run.italic:
                text = f"*{text}*"
            parts.append(text)

    line = "".join(parts).strip()

    if not line:
        return ""

    # Apply heading prefix
    if heading_match:
        level = int(heading_match.group(1))
        level = min(level, 6)
        return f"{'#' * level} {line}"

    # List detection
    numPr = para._element.find('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr')
    if numPr is not None:
        ilvl_el = numPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl')
        indent_level = int(ilvl_el.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '0')) if ilvl_el is not None else 0
        prefix = "  " * indent_level + "- "
        return f"{prefix}{line}"

    # Title / Subtitle
    if style_name in ("Title", "Subtitle", "Название", "Подзаголовок"):
        return f"# {line}"

    return line


def table_to_md(table) -> str:
    """Convert a docx table to markdown table."""
    rows_data = []
    for row in table.rows:
        cells = []
        for cell in row.cells:
            cell_text = cell.text.strip().replace("\n", " ").replace("|", "\\|")
            cells.append(cell_text)
        rows_data.append(cells)

    if not rows_data:
        return ""

    # Normalize column count
    max_cols = max(len(r) for r in rows_data)
    for r in rows_data:
        while len(r) < max_cols:
            r.append("")

    lines = []
    # Header
    lines.append("| " + " | ".join(rows_data[0]) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    # Body
    for row in rows_data[1:]:
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def convert_docx_to_md(docx_path: str) -> str:
    docx_path = Path(docx_path)
    if not docx_path.exists():
        print(f"ERROR|File not found: {docx_path}", file=sys.stderr)
        sys.exit(1)

    if docx_path.suffix.lower() != ".docx":
        print(f"ERROR|Not a .docx file: {docx_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = docx_path.parent
    output_md = output_dir / (docx_path.stem + ".md")

    doc = Document(str(docx_path))

    # Extract images
    rid_to_path = extract_images(doc, output_dir)

    # Process body elements in order (paragraphs and tables)
    blocks = []
    for element in doc.element.body:
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        if tag == "p":
            # Find the paragraph object
            from docx.text.paragraph import Paragraph
            para = Paragraph(element, doc)
            md_line = para_to_md(para, rid_to_path, doc)
            if md_line:
                blocks.append(md_line)

        elif tag == "tbl":
            from docx.table import Table as DocxTable
            tbl = DocxTable(element, doc)
            md_table = table_to_md(tbl)
            if md_table:
                blocks.append(md_table)

    md_content = "\n\n".join(blocks)

    # Write output
    output_md.write_text(md_content, encoding="utf-8")

    size = output_md.stat().st_size
    print(f"OK|{output_md}|{len(blocks)}|{size}")
    return str(output_md)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: docx_to_md.py <path_to_docx>", file=sys.stderr)
        sys.exit(1)

    convert_docx_to_md(sys.argv[1])
