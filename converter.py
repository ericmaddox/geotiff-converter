import io
import logging
import os
import tempfile
import zipfile

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def _get_native_render_dpi(page):
    """Determine the DPI at which the page should be rendered so the largest
    embedded image appears at its native pixel resolution (no resampling)."""
    best_dpi = 0
    try:
        for img_info in page.get_images(full=True):
            w, h = img_info[2], img_info[3]
            if w * h < 100_000:
                continue
            for rect in page.get_image_rects(img_info):
                if rect.width > 0 and rect.height > 0:
                    dpi_x = w * 72 / rect.width
                    dpi_y = h * 72 / rect.height
                    best_dpi = max(best_dpi, dpi_x, dpi_y)
    except Exception:
        pass
    return best_dpi if best_dpi > 0 else 0


def extract_images_from_pdf(file_bytes, dpi=300, auto_dpi=False):
    import fitz

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    images = []
    for page in doc:
        render_dpi = dpi

        if auto_dpi:
            native_dpi = _get_native_render_dpi(page)
            if native_dpi > 0:
                render_dpi = native_dpi
                logger.info(
                    "  native DPI=%.0f, rendering at %.0f DPI", native_dpi, render_dpi
                )

        mat = fitz.Matrix(render_dpi / 72, render_dpi / 72)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        logger.info("  rendered page: %dx%d", img.width, img.height)
        images.append(img)

    doc.close()
    return images


def extract_images_from_docx(file_bytes):
    from docx import Document

    doc = Document(io.BytesIO(file_bytes))
    images = []
    for rel in doc.part.rels.values():
        if "image" in rel.reltype:
            img_bytes = rel.target_part.blob
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)
    return images


def load_image(file_bytes):
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode != "RGB":
        img = img.convert("RGB")
    return [img]


def extract_images(file_bytes, filename, dpi=300, auto_dpi=False):
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext == "pdf":
        return extract_images_from_pdf(file_bytes, dpi, auto_dpi=auto_dpi)
    elif ext == "docx":
        return extract_images_from_docx(file_bytes)
    elif ext in ("png", "jpg", "jpeg", "tiff", "tif", "bmp", "gif", "webp"):
        return load_image(file_bytes)
    else:
        raise ValueError(f"Unsupported file format: .{ext}")


def image_to_geotiff(image, crs_epsg=4326, bounds=None):
    import rasterio
    from rasterio.crs import CRS
    from rasterio.transform import from_bounds

    img_array = np.array(image)
    height, width = img_array.shape[:2]

    if bounds is None:
        bounds = (-180, -90, 180, 90)

    west, south, east, north = bounds
    transform = from_bounds(west, south, east, north, width, height)

    if len(img_array.shape) == 2:
        count = 1
        data = img_array[np.newaxis, :, :]
    else:
        count = img_array.shape[2]
        data = np.moveaxis(img_array, -1, 0)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".tif")
    os.close(tmp_fd)

    try:
        with rasterio.open(
            tmp_path,
            "w",
            driver="GTiff",
            height=height,
            width=width,
            count=count,
            dtype=str(data.dtype),
            crs=CRS.from_epsg(crs_epsg),
            transform=transform,
            compress="lzw",
        ) as dst:
            dst.write(data)

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def convert_to_geotiff(file_bytes, filename, crs_epsg=4326, bounds=None, dpi=300):
    images = extract_images(file_bytes, filename, dpi, auto_dpi=True)

    if not images:
        raise ValueError("No images found in the uploaded file.")

    results = []
    base_name = filename.rsplit(".", 1)[0] if "." in filename else filename

    for i, img in enumerate(images):
        geotiff_bytes = image_to_geotiff(img, crs_epsg, bounds)
        if len(images) == 1:
            name = f"{base_name}.tif"
        else:
            name = f"{base_name}_page_{i + 1}.tif"
        results.append((name, geotiff_bytes))

    if len(results) == 1:
        return results[0]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in results:
            zf.writestr(name, data)
    zip_buffer.seek(0)
    return (f"{base_name}_geotiffs.zip", zip_buffer.read())
