# GeoTIFF Converter

A web-based tool for converting PDF, DOCX, and image files into georeferenced GeoTIFF format. Built with [Dash](https://dash.plotly.com/) and [Rasterio](https://rasterio.readthedocs.io/).

## Features

- **Drag-and-drop multi-file upload** — drop multiple files at once; they upload in parallel via a dedicated Flask endpoint
- **Supported formats** — PDF (including GeoPDF), DOCX, PNG, JPG, JPEG, TIFF, BMP, GIF, WebP
- **Smart PDF handling** — auto-detects embedded image resolution and renders at native DPI to preserve full quality without upscaling
- **Configurable geospatial metadata** — set CRS (EPSG code) and bounding box coordinates
- **Batch conversion** — converts all uploaded files and bundles multi-file output into a single ZIP download
- **Server-side processing** — files are stored and converted on the server, keeping the browser lightweight even for large files

## Prerequisites

- Python 3.10+

## Getting Started

```bash
# Clone the repository
git clone https://github.com/<your-username>/geo-tif-converter.git
cd geo-tif-converter

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # macOS / Linux
# .venv\Scripts\activate    # Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

The app will be available at **http://127.0.0.1:8050/**.

## Usage

1. **Upload** — drag and drop files onto the upload zone, or click to browse. Multiple files are supported.
2. **Configure** — adjust geospatial settings (CRS, bounding box, minimum DPI) as needed.
3. **Convert** — click "Convert to GeoTIFF". A download button appears when conversion is complete.

## Project Structure

```
geo-tif-converter/
├── app.py              # Dash application, Flask routes, and callbacks
├── converter.py        # File-to-GeoTIFF conversion logic
├── requirements.txt    # Python dependencies
└── assets/
    ├── upload.js       # Client-side drag-and-drop upload handler
    └── styles.css      # Drop zone styling
```

## How It Works

### PDF Conversion

The converter detects the native resolution of embedded images in PDF files and renders pages at that exact DPI. This avoids upscaling artifacts that occur when rendering at a fixed DPI higher than the source imagery. For standard PDFs with vector content, the user-specified DPI is used as a floor.

### GeoTIFF Output

Output files are written with:
- **Driver**: GTiff
- **Compression**: LZW (lossless)
- **CRS**: Configurable (default EPSG:4326 / WGS 84)
- **Transform**: Computed from user-supplied bounding box coordinates

## Tech Stack

| Component | Library |
|-----------|---------|
| Web framework | Dash 4.0 / Flask |
| UI components | Dash Bootstrap Components |
| PDF rendering | PyMuPDF |
| GeoTIFF writing | Rasterio |
| Image processing | Pillow, NumPy |
| DOCX parsing | python-docx |

## License

This project is provided as-is. See [LICENSE](LICENSE) for details.
