"""Grid-first extraction of scanned/digital timetables using Gemini Vision.

Each day is cropped independently after a layout pass. This prevents the model
from silently mixing Friday, Saturday, the subject legend, and adjacent rows.
No school-specific timetable data or fixed pixel coordinates are hardcoded.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")

LAYOUT_PROMPT = """Analyze the page as an image, using VISUAL boundaries rather than OCR order.
Return ONLY JSON, in normalized coordinates 0..1000 relative to image width/height:
{"class_label":"exact section printed above timetable", "grid_bbox":[left,top,right,bottom],
 "header_bbox":[left,top,right,bottom],
 "day_bboxes":{"Monday":[left,top,right,bottom],"Tuesday":...,"Wednesday":...,
 "Thursday":...,"Friday":...,"Saturday":...},
 "legend_bbox":[left,top,right,bottom] or null, "warnings":[]}
Grid is the DAY×PERIOD table, NOT the nearby important-dates box or subject legend.
Each day_bbox MUST contain only the actual timetable cells of THAT day, including
its DAY LABEL at the left and the entire row to the far right. Do not cross into
neighboring days. header_bbox is ONLY the time-header row. legend_bbox is the
code/name reference table below the timetable (if present). Every bbox uses
[left,top,right,bottom]. Missing or uncertain day: OMIT it and add warning.
Avoid guesswork; accurately locate table borders before answering."""

DAY_PROMPT = """You are reading ONLY the {day} row from a real college timetable.
Images supplied: 1) TIME HEADERS, 2) ONLY THIS DAY'S GRID ROW,
3) OPTIONAL subject legend for names ONLY.
Critical: Align cell contents to the visible horizontal time-column grid.
Merged cells span exactly their visible columns, INCLUDING short break columns
when the merged cell actually crosses them. Do not create a BREAK in such a cell.
LUNCH is not a subject and should occur only in the column marked LUNCH; never
move LUNCH to an adjacent time column or multiply it into extra columns.
Read the subject code INSIDE the grid row; legend may expand that code into a
name, but NEVER replace or infer a code. Read LA/PD literally. Blank cells
produce NO rows. Keep a merged multi-period activity as separate occupied time
slots ONLY when the grid shows they are covered. Do not use other days' cells.
Never guess. Use warnings with specific time/column when uncertain.
Use 24-hour time and return ONLY JSON:
{{"rows":[{{"class":"{section}","day_of_week":"{day}",
"time_slot":"09:00-09:55","subject_code":null,"activity":"Library",
"is_lab":false,"lab_id":null}}],"warnings":[]}}
IMPORTANT: The example is format only, NOT content. Verify EVERY emitted row
visually against the day image and header. There is no requirement to fill all slots."""


def parse_json(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", (text or "").strip(), flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    result = json.loads(cleaned)
    if not isinstance(result, dict):
        raise ValueError("Provider response must be a JSON object")
    return result


def bbox(value: Any, size: tuple[int, int], *, min_w: int = 10, min_h: int = 7) -> tuple[int, int, int, int]:
    """Convert normalized 0..1000 coordinates into a checked pixel rectangle."""
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("Missing or malformed visual bounding box")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise ValueError("Bounding box values must be numbers")
    x0, y0, x1, y1 = map(float, value)
    if not (0 <= x0 < x1 <= 1000 and 0 <= y0 < y1 <= 1000):
        raise ValueError("Bounding box outside image")
    w, h = size
    result = (round(x0 * w / 1000), round(y0 * h / 1000),
              round(x1 * w / 1000), round(y1 * h / 1000))
    if result[2] - result[0] < min_w or result[3] - result[1] < min_h:
        raise ValueError("Bounding box too small")
    return result


def render_pages(data: bytes, mime_type: str, max_pages: int = 3):
    """Images in memory only. For scanned PDFs, render each page for visual reading."""
    from PIL import Image, ImageOps
    if mime_type == "application/pdf":
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            if len(doc) > max_pages:
                raise ValueError(f"PDF has {len(doc)} pages; maximum is {max_pages} per upload")
            pages = []
            for p in doc:
                pix = p.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                pages.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
            return pages
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if image.width * image.height > 18_000_000:
        image.thumbnail((4000, 4000))
    return [image]


def png_bytes(image) -> bytes:
    bio = io.BytesIO()
    image.save(bio, format="PNG")
    return bio.getvalue()


def provider_json(client, model: str, prompt: str, pictures: list) -> dict[str, Any]:
    from google.genai import types
    contents = [prompt] + [types.Part.from_bytes(data=png_bytes(im), mime_type="image/png") for im in pictures]
    response = client.models.generate_content(model=model, contents=contents)
    return parse_json(response.text)


def extract_grid_first(client, model: str, document: bytes, mime_type: str) -> dict[str, Any]:
    """One layout pass and at most six narrow day passes per page.

    No database operations. If layout is uncertain, return warnings and reviewable
    partial results; never fabricate rows to fill a timetable.
    """
    pages = render_pages(document, mime_type)
    all_rows: list[dict] = []
    warnings: list[str] = []
    for page_no, image in enumerate(pages, 1):
        layout = provider_json(client, model, LAYOUT_PROMPT, [image])
        warnings.extend(f"Page {page_no} layout: {w}" for w in layout.get("warnings", []) if isinstance(w, str))
        section = str(layout.get("class_label") or "").strip()
        day_boxes = layout.get("day_bboxes")
        if not isinstance(day_boxes, dict) or len(day_boxes) < 1:
            warnings.append(f"Page {page_no}: no timetable day rows confidently located; manual review needed.")
            continue
        try:
            grid = bbox(layout.get("grid_bbox"), image.size)
            header = bbox(layout.get("header_bbox"), image.size)
        except ValueError as exc:
            warnings.append(f"Page {page_no}: invalid timetable layout: {exc}")
            continue
        header_image = image.crop(header)
        legend_image = None
        if layout.get("legend_bbox") is not None:
            try:
                legend_image = image.crop(bbox(layout["legend_bbox"], image.size))
            except ValueError:
                warnings.append(f"Page {page_no}: subject legend region unclear")
        for day in DAYS:
            if day not in day_boxes:
                warnings.append(f"Page {page_no}: {day} row not confidently located")
                continue
            try:
                rect = bbox(day_boxes[day], image.size)
                # Crop must stay inside the timetable grid's horizontal extent.
                if rect[0] < grid[0] - image.width * 0.03 or rect[2] > grid[2] + image.width * 0.03:
                    raise ValueError("day row is outside timetable grid")
                # Do not trust day boxes that span multiple days.
                if rect[3] - rect[1] > (grid[3] - grid[1]) * 0.35:
                    raise ValueError("day row extends across multiple days")
                pictures = [header_image, image.crop(rect)]
                if legend_image is not None:
                    pictures.append(legend_image)
                result = provider_json(client, model, DAY_PROMPT.format(day=day, section=section), pictures)
                rows = result.get("rows", [])
                if not isinstance(rows, list):
                    raise ValueError("day response has no rows array")
                for row in rows:
                    if not isinstance(row, dict):
                        warnings.append(f"Page {page_no} {day}: non-object row ignored")
                        continue
                    if row.get("day_of_week") != day:
                        warnings.append(f"Page {page_no} {day}: provider returned a row assigned to a different day; rejected")
                        continue
                    row["class"] = section or row.get("class")
                    all_rows.append(row)
                warnings.extend(f"Page {page_no} {day}: {w}" for w in result.get("warnings", []) if isinstance(w, str))
            except (ValueError, KeyError, TypeError) as exc:
                warnings.append(f"Page {page_no} {day}: could not read day row: {exc}")
    return {"rows": all_rows, "warnings": warnings}
