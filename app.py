import base64
import io
import logging
import os
import shutil
import tempfile
import uuid
import zipfile

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dcc, html, no_update
from flask import jsonify, request, send_from_directory

from converter import convert_to_geotiff, extract_images

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED = {
    "pdf": "PDF Document",
    "docx": "Word Document",
    "png": "PNG Image",
    "jpg": "JPEG Image",
    "jpeg": "JPEG Image",
    "tiff": "TIFF Image",
    "tif": "TIFF Image",
    "bmp": "BMP Image",
    "gif": "GIF Image",
    "webp": "WebP Image",
}

UPLOAD_ROOT = os.path.join(tempfile.gettempdir(), "geotiff_converter")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# Server-side session storage: session_id -> [entry, ...]
SESSIONS: dict[str, list[dict]] = {}

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.SLATE, dbc.icons.FONT_AWESOME],
    title="GeoTIFF Converter",
    suppress_callback_exceptions=True,
)
app.server.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB


# ---------------------------------------------------------------------------
# Flask upload route — bypasses dcc.Upload entirely
# ---------------------------------------------------------------------------


@app.server.route("/api/upload", methods=["POST"])
def api_upload():
    session_id = request.form.get("session_id", "default")
    session_path = _session_dir(session_id)
    entries = SESSIONS.get(session_id, [])
    existing_names = {e["filename"] for e in entries}

    uploaded = []
    for f in request.files.getlist("files"):
        filename = f.filename
        if not filename or filename in existing_names:
            continue
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext not in SUPPORTED:
            continue

        file_path = os.path.join(session_path, filename)
        f.save(file_path)
        file_size = os.path.getsize(file_path)

        with open(file_path, "rb") as fp:
            file_bytes = fp.read()
        preview_src, page_info = _make_preview(file_bytes, filename)

        entries.append(
            {
                "filename": filename,
                "path": file_path,
                "file_type": SUPPORTED[ext],
                "size_str": _format_size(file_size),
                "page_info": page_info,
                "preview_src": preview_src,
            }
        )
        existing_names.add(filename)
        uploaded.append(filename)
        logger.info("Uploaded: %s (%s)", filename, _format_size(file_size))

    SESSIONS[session_id] = entries
    return jsonify({"uploaded": uploaded, "total": len(entries)})


@app.server.route("/api/download/<session_id>/<filename>")
def api_download(session_id, filename):
    output_dir = os.path.join(_session_dir(session_id), "output")
    return send_from_directory(output_dir, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def serve_layout():
    session_id = str(uuid.uuid4())

    geo_settings = dbc.Card(
        [
            dbc.CardHeader(
                html.H5(
                    [
                        html.I(className="fas fa-map-marked-alt me-2"),
                        "Geospatial Settings",
                    ],
                    className="mb-0",
                )
            ),
            dbc.CardBody(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("CRS (EPSG Code)"),
                                    dbc.Input(
                                        id="epsg",
                                        type="number",
                                        value=4326,
                                        min=1,
                                        placeholder="e.g. 4326",
                                    ),
                                    dbc.FormText("Default: WGS 84 (EPSG:4326)"),
                                ],
                                md=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Minimum DPI (for PDF / DOCX)"),
                                    dbc.Input(
                                        id="dpi",
                                        type="number",
                                        value=300,
                                        min=72,
                                        max=1200,
                                        step=1,
                                    ),
                                    dbc.FormText(
                                        "Auto-detects native resolution; this sets the floor"
                                    ),
                                ],
                                md=6,
                            ),
                        ],
                        className="mb-3",
                    ),
                    html.Hr(),
                    dbc.Label("Bounding Box Coordinates"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("West", className="small text-muted"),
                                    dbc.Input(
                                        id="west",
                                        type="number",
                                        value=-180,
                                        step="any",
                                    ),
                                ],
                                xs=6,
                                md=3,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("South", className="small text-muted"),
                                    dbc.Input(
                                        id="south",
                                        type="number",
                                        value=-90,
                                        step="any",
                                    ),
                                ],
                                xs=6,
                                md=3,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("East", className="small text-muted"),
                                    dbc.Input(
                                        id="east",
                                        type="number",
                                        value=180,
                                        step="any",
                                    ),
                                ],
                                xs=6,
                                md=3,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("North", className="small text-muted"),
                                    dbc.Input(
                                        id="north",
                                        type="number",
                                        value=90,
                                        step="any",
                                    ),
                                ],
                                xs=6,
                                md=3,
                            ),
                        ]
                    ),
                ]
            ),
        ],
        className="mb-4",
    )

    return dbc.Container(
        [
            dcc.Store(id="session-id", data=session_id),
            dcc.Store(id="file-count", data=0),
            dcc.Interval(id="poll-interval", interval=1500, n_intervals=0),
            # Header
            html.H1(
                [
                    html.I(className="fas fa-globe-americas me-3"),
                    "GeoTIFF Converter",
                ],
                className="text-center mt-4 mb-2",
            ),
            html.P(
                "Convert PDF, DOCX, and image files to georeferenced GeoTIFF format",
                className="text-center text-muted mb-4",
            ),
            html.Hr(className="mb-4"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            # Custom drop zone (replaces dcc.Upload)
                            dbc.Card(
                                dbc.CardBody(
                                    html.Div(
                                        [
                                            html.I(
                                                className="fas fa-cloud-upload-alt",
                                                style={
                                                    "fontSize": "3rem",
                                                    "color": "#5dade2",
                                                },
                                            ),
                                            html.P(
                                                "Drag & Drop Files or Click to Browse",
                                                className="mt-3 mb-1 fw-bold",
                                            ),
                                            html.P(
                                                "Supports: "
                                                + ", ".join(
                                                    f".{ext}"
                                                    for ext in sorted(
                                                        set(SUPPORTED.keys())
                                                    )
                                                ),
                                                className="text-muted small mb-0",
                                            ),
                                        ],
                                        id="drop-zone",
                                        **{"data-session": session_id},
                                    )
                                ),
                                className="mb-4",
                            ),
                            # File list (populated by polling callback)
                            html.Div(id="file-info"),
                            # Clear button
                            html.Div(
                                dbc.Button(
                                    [
                                        html.I(className="fas fa-trash-alt me-2"),
                                        "Clear All Files",
                                    ],
                                    id="clear-btn",
                                    color="danger",
                                    outline=True,
                                    size="sm",
                                    className="w-100 mb-4",
                                ),
                                id="clear-btn-wrapper",
                                style={"display": "none"},
                            ),
                            # Geo settings
                            geo_settings,
                            # Convert button
                            dbc.Button(
                                [
                                    html.I(className="fas fa-cogs me-2"),
                                    "Convert to GeoTIFF",
                                ],
                                id="convert-btn",
                                color="primary",
                                size="lg",
                                className="w-100 mb-4",
                                disabled=True,
                            ),
                            # Status
                            dcc.Loading(
                                html.Div(id="status"),
                                type="circle",
                                color="#5dade2",
                            ),
                        ],
                        lg=8,
                        className="mx-auto",
                    ),
                ],
                justify="center",
            ),
            html.Hr(className="mt-4"),
            html.P(
                "Built with Dash & Rasterio",
                className="text-center text-muted small pb-3",
            ),
        ],
        fluid=False,
        style={"maxWidth": "820px"},
        className="py-2",
    )


app.layout = serve_layout


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _session_dir(session_id: str) -> str:
    d = os.path.join(UPLOAD_ROOT, session_id)
    os.makedirs(d, exist_ok=True)
    return d


def _format_size(nbytes: int) -> str:
    if nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    return f"{nbytes / (1024 * 1024):.1f} MB"


def _make_preview(file_bytes: bytes, filename: str):
    try:
        images = extract_images(file_bytes, filename, dpi=72)
        if not images:
            return None, ""
        thumb = images[0].copy()
        thumb.thumbnail((120, 120))
        buf = io.BytesIO()
        thumb.save(buf, format="PNG")
        buf.seek(0)
        src = "data:image/png;base64," + base64.b64encode(buf.read()).decode()
        page_info = f" \u2022 {len(images)} pages" if len(images) > 1 else ""
        return src, page_info
    except Exception:
        return None, ""


def _build_file_list_card(entries: list[dict]):
    count = len(entries)
    header_text = f"{count} file{'s' if count != 1 else ''} ready"

    body: list = [
        html.H6(
            [html.I(className="fas fa-layer-group me-2"), header_text],
            className="mb-3",
        )
    ]

    for i, entry in enumerate(entries):
        if i > 0:
            body.append(html.Hr(className="my-2"))

        preview_col: list = []
        if entry.get("preview_src"):
            preview_col = [
                html.Img(
                    src=entry["preview_src"],
                    className="img-fluid rounded",
                    style={"maxHeight": "100px"},
                )
            ]

        body.append(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Div(
                                [
                                    html.I(
                                        className="fas fa-file-alt me-2 text-primary"
                                    ),
                                    html.Strong(entry["filename"]),
                                ]
                            ),
                            html.Small(
                                f"{entry['file_type']} \u2022 {entry['size_str']}"
                                f"{entry.get('page_info', '')}",
                                className="text-muted",
                            ),
                        ],
                        md=8,
                        className="d-flex flex-column justify-content-center",
                    ),
                    dbc.Col(preview_col, md=4, className="text-end"),
                ],
                align="center",
                className="py-2",
            )
        )

    return dbc.Card(dbc.CardBody(body), className="mb-4")


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@app.callback(
    [
        Output("file-info", "children"),
        Output("file-count", "data"),
        Output("convert-btn", "disabled"),
        Output("clear-btn-wrapper", "style"),
    ],
    [
        Input("poll-interval", "n_intervals"),
        Input("clear-btn", "n_clicks"),
    ],
    [
        State("session-id", "data"),
        State("file-count", "data"),
    ],
    prevent_initial_call=True,
)
def update_file_list(_n_intervals, _clear_clicks, session_id, prev_count):
    triggered = dash.ctx.triggered_id

    if triggered == "clear-btn":
        SESSIONS.pop(session_id, None)
        shutil.rmtree(_session_dir(session_id), ignore_errors=True)
        return None, 0, True, {"display": "none"}

    entries = SESSIONS.get(session_id, [])
    current_count = len(entries)

    if current_count == (prev_count or 0):
        return no_update, no_update, no_update, no_update

    if current_count == 0:
        return None, 0, True, {"display": "none"}

    return (
        _build_file_list_card(entries),
        current_count,
        False,
        {"display": "block"},
    )


@app.callback(
    Output("status", "children"),
    Input("convert-btn", "n_clicks"),
    [
        State("session-id", "data"),
        State("epsg", "value"),
        State("west", "value"),
        State("south", "value"),
        State("east", "value"),
        State("north", "value"),
        State("dpi", "value"),
    ],
    prevent_initial_call=True,
)
def handle_convert(n_clicks, session_id, epsg, west, south, east, north, dpi):
    if not n_clicks:
        return no_update

    entries = SESSIONS.get(session_id, [])
    if not entries:
        return dbc.Alert("No files to convert.", color="warning")

    try:
        epsg = int(epsg) if epsg else 4326
        dpi = int(dpi) if dpi else 300
        bounds = (
            float(west) if west is not None else -180,
            float(south) if south is not None else -90,
            float(east) if east is not None else 180,
            float(north) if north is not None else 90,
        )

        all_results: list[tuple[str, bytes]] = []
        for entry in entries:
            logger.info("Converting %s ...", entry["filename"])
            with open(entry["path"], "rb") as fp:
                file_bytes = fp.read()
            result = convert_to_geotiff(
                file_bytes, entry["filename"], epsg, bounds, dpi
            )
            all_results.append(result)
            logger.info("  done: %s", result[0])

        # Save output to disk and serve via Flask route
        output_dir = os.path.join(_session_dir(session_id), "output")
        os.makedirs(output_dir, exist_ok=True)

        if len(all_results) == 1:
            out_name, out_bytes = all_results[0]
        else:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(
                zip_buffer, "w", zipfile.ZIP_DEFLATED
            ) as zf:
                for name, data in all_results:
                    zf.writestr(name, data)
            zip_buffer.seek(0)
            out_name = "geotiff_converted.zip"
            out_bytes = zip_buffer.read()

        output_path = os.path.join(output_dir, out_name)
        with open(output_path, "wb") as fp:
            fp.write(out_bytes)

        out_size = _format_size(len(out_bytes))
        download_url = f"/api/download/{session_id}/{out_name}"
        file_count = len(entries)
        label = f"{file_count} file{'s' if file_count != 1 else ''}"

        return html.Div(
            [
                dbc.Alert(
                    [
                        html.I(className="fas fa-check-circle me-2"),
                        f"Converted {label} successfully ({out_size})",
                    ],
                    color="success",
                    className="mb-3",
                ),
                html.A(
                    dbc.Button(
                        [
                            html.I(className="fas fa-download me-2"),
                            f"Download {out_name}",
                        ],
                        color="success",
                        size="lg",
                        className="w-100",
                    ),
                    href=download_url,
                    download=out_name,
                ),
            ]
        )

    except Exception as e:
        logger.exception("Conversion failed")
        return dbc.Alert(
            [
                html.I(className="fas fa-exclamation-triangle me-2"),
                f"Conversion failed: {e}",
            ],
            color="danger",
        )


if __name__ == "__main__":
    app.run(debug=True, port=8050, threaded=True)
