"""3SG Group — Dashboard de pilotage.

Five sections (Media, Social, Influence, ATL, BTL). Each section accepts PDF
event-report uploads (with event date, name, brand) and displays a 12-month
calendar grid for the selected year. Clicking a month reveals every report
filed in that month.
"""

from __future__ import annotations

import base64
import io
import json
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Config & paths
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
REPORTS_DIR = STATIC_DIR / "reports"
INDEX_PATH = REPORTS_DIR / "index.json"
MEDIA_DIR = STATIC_DIR / "media"
MEDIA_MANIFEST = MEDIA_DIR / "active.json"
PAID_DIR = STATIC_DIR / "paid"
PAID_MANIFEST = PAID_DIR / "active.json"

SECTIONS = ["Media", "Social", "Influence", "Paid", "ATL", "BTL"]
SECTION_ICONS = {
    "Media": "📺",
    "Social": "💬",
    "Influence": "✨",
    "Paid": "💸",
    "ATL": "📡",
    "BTL": "🎪",
}
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

LOGO_PATH = Path(__file__).parent / "3sg_logo.png"

st.set_page_config(
    page_title="3SG Group — Dashboard de pilotage",
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else "📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Supabase Storage (persistent backend)
# ---------------------------------------------------------------------------
def _sb_cfg() -> tuple[str | None, str | None, str]:
    """Return (url, key, bucket) from Streamlit secrets, or (None, None, ...)."""
    try:
        cfg = st.secrets["supabase"]
        return cfg["url"].rstrip("/"), cfg["service_key"], cfg.get("bucket", "3sg-reports")
    except Exception:
        return None, None, "3sg-reports"


SB_URL, SB_KEY, SB_BUCKET = _sb_cfg()
SB_ENABLED = bool(SB_URL and SB_KEY)


def _sb_headers(extra: dict | None = None) -> dict:
    h = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}
    if extra:
        h.update(extra)
    return h


def sb_upload(remote_path: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """Upload (or overwrite) data to a path inside the bucket."""
    if not SB_ENABLED:
        raise RuntimeError("Supabase is not configured (missing secrets).")
    url = f"{SB_URL}/storage/v1/object/{SB_BUCKET}/{quote(remote_path)}"
    r = requests.post(
        url,
        headers=_sb_headers({
            "Content-Type": content_type,
            "x-upsert": "true",
            "cache-control": "3600",
        }),
        data=data,
        timeout=120,
    )
    if not r.ok:
        raise RuntimeError(f"Upload failed ({r.status_code})")


def sb_download(remote_path: str) -> bytes | None:
    """Download bytes from the bucket. Returns None if not found or on error."""
    if not SB_ENABLED:
        return None
    try:
        url = f"{SB_URL}/storage/v1/object/{SB_BUCKET}/{quote(remote_path)}"
        r = requests.get(url, headers=_sb_headers(), timeout=120)
        if r.status_code == 404:
            return None
        if not r.ok:
            return None
        return r.content
    except Exception:
        return None


def sb_delete(remote_path: str) -> None:
    if not SB_ENABLED:
        return
    url = f"{SB_URL}/storage/v1/object/{SB_BUCKET}/{quote(remote_path)}"
    requests.delete(url, headers=_sb_headers(), timeout=30)


def sb_public_url(remote_path: str) -> str:
    return f"{SB_URL}/storage/v1/object/public/{SB_BUCKET}/{quote(remote_path)}"


def sb_get_json(remote_path: str, default):
    raw = sb_download(remote_path)
    if raw is None:
        return default
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return default


def sb_put_json(remote_path: str, obj) -> None:
    sb_upload(
        remote_path,
        json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
    )

# ---------------------------------------------------------------------------
# CSS — dark violet theme reused from the Batam dashboard
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .stApp {
        background:
            radial-gradient(circle at 12% 18%, rgba(139,92,246,0.18), transparent 45%),
            radial-gradient(circle at 88% 12%, rgba(167,139,250,0.14), transparent 50%),
            radial-gradient(circle at 50% 110%, rgba(99,102,241,0.18), transparent 55%),
            #0E0B1F;
    }

    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #15102B 0%, #0B0817 100%);
        border-right: 1px solid rgba(167,139,250,0.18);
    }

    h1 {
        font-weight: 800 !important;
        letter-spacing: -0.02em;
        background: linear-gradient(90deg, #FFFFFF 0%, #C4B5FD 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }

    /* Section tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: rgba(26,19,48,0.6);
        padding: 6px;
        border-radius: 14px;
        border: 1px solid rgba(167,139,250,0.18);
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        border-radius: 10px;
        padding: 10px 18px;
        color: #C4B5FD;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #8B5CF6 0%, #A78BFA 100%) !important;
        color: white !important;
        box-shadow: 0 6px 18px rgba(139,92,246,0.35);
    }

    /* Month calendar cards = styled st.button */
    div[data-testid="stButton"] > button[kind].month-btn,
    .month-grid div[data-testid="stButton"] > button {
        position: relative;
        width: 100%;
        min-height: 110px;
        padding: 18px 16px;
        border-radius: 16px !important;
        background: linear-gradient(160deg, rgba(26,19,48,0.95) 0%, rgba(15,11,31,0.95) 100%) !important;
        border: 1px solid rgba(167,139,250,0.18) !important;
        box-shadow: 0 6px 20px rgba(0,0,0,0.35) !important;
        color: #F5F3FF !important;
        font-weight: 700 !important;
        line-height: 1.35 !important;
        white-space: pre-line !important;
        text-align: left !important;
        transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease !important;
        overflow: hidden;
    }
    .month-grid div[data-testid="stButton"] > button > div { width: 100%; }
    .month-grid div[data-testid="stButton"] > button p {
        font-size: 0.95rem !important;
        margin: 0 !important;
        text-align: left !important;
    }
    .month-grid div[data-testid="stButton"] > button::before {
        content: "";
        position: absolute; top: 0; left: 0; right: 0; height: 3px;
        border-radius: 16px 16px 0 0;
        background: linear-gradient(90deg, #8B5CF6, #A78BFA, #6366F1);
    }
    .month-grid div[data-testid="stButton"] > button:hover {
        transform: translateY(-2px);
        border-color: #A78BFA !important;
        box-shadow: 0 12px 28px rgba(139,92,246,0.4) !important;
    }
    .month-grid.has-sel-1 > div:nth-child(1) div[data-testid="stButton"] > button,
    .month-grid.has-sel-2 > div:nth-child(2) div[data-testid="stButton"] > button,
    .month-grid.has-sel-3 > div:nth-child(3) div[data-testid="stButton"] > button,
    .month-grid.has-sel-4 > div:nth-child(4) div[data-testid="stButton"] > button {
        border-color: #A78BFA !important;
        box-shadow: 0 10px 30px rgba(139,92,246,0.55) !important;
    }

    /* Report row card */
    .report-card {
        padding: 14px 16px;
        border-radius: 12px;
        background: rgba(26,19,48,0.7);
        border: 1px solid rgba(167,139,250,0.18);
        margin-bottom: 10px;
        transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
    }
    a.report-link { text-decoration: none !important; display: block; }
    a.report-link:hover .report-card {
        transform: translateY(-2px);
        border-color: #A78BFA;
        box-shadow: 0 10px 24px rgba(139,92,246,0.35);
    }
    .report-card .r-title { font-weight: 700; color: #F5F3FF; font-size: 1.02rem; }
    .report-card .r-meta { color: #C4B5FD; font-size: 0.85rem; margin-top: 2px; }

    /* KPI strip */
    .kpi {
        padding: 14px 16px;
        border-radius: 14px;
        background: linear-gradient(160deg, rgba(26,19,48,0.95), rgba(15,11,31,0.95));
        border: 1px solid rgba(167,139,250,0.2);
    }
    .kpi .label { color: #C4B5FD; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.1em; }
    .kpi .value { color: #F5F3FF; font-size: 1.6rem; font-weight: 800; margin-top: 4px; }

    /* Chart container — soft shadow + rounded corners + lift on hover */
    div[data-testid="stPlotlyChart"] {
        background: linear-gradient(160deg, rgba(26,19,48,0.55), rgba(15,11,31,0.55));
        border: 1px solid rgba(167,139,250,0.16);
        border-radius: 18px;
        padding: 10px 6px 4px 6px;
        box-shadow: 0 14px 38px rgba(0,0,0,0.45),
                    0 0 0 1px rgba(167,139,250,0.08) inset;
        transition: transform 0.25s ease, box-shadow 0.25s ease, border-color 0.25s ease;
    }
    div[data-testid="stPlotlyChart"]:hover {
        transform: translateY(-3px);
        border-color: rgba(167,139,250,0.32);
        box-shadow: 0 20px 48px rgba(139,92,246,0.32),
                    0 0 0 1px rgba(167,139,250,0.12) inset;
    }
    div[data-testid="stPlotlyChart"] .js-plotly-plot,
    div[data-testid="stPlotlyChart"] .plot-container,
    div[data-testid="stPlotlyChart"] .svg-container,
    div[data-testid="stPlotlyChart"] .main-svg {
        background: transparent !important;
        border-radius: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Storage helpers (Supabase-backed with local fallback)
# ---------------------------------------------------------------------------
INDEX_REMOTE = "index.json"


def load_index() -> list[dict]:
    if SB_ENABLED:
        return sb_get_json(INDEX_REMOTE, default=[])
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_index(rows: list[dict]) -> None:
    if SB_ENABLED:
        sb_put_json(INDEX_REMOTE, rows)
        return
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:60] or "report"


def save_report(
    section: str,
    event_date: date,
    event_name: str,
    brand: str,
    file_bytes: bytes,
    original_name: str,
) -> dict:
    stem = f"{event_date.isoformat()}_{slugify(event_name)}"
    suffix = Path(original_name).suffix.lower() or ".pdf"
    base_name = f"{stem}{suffix}"

    rows = load_index()
    existing_paths = {r.get("path", "") for r in rows}

    # Avoid overwriting
    n = 1
    candidate = base_name
    while f"reports/{section}/{candidate}" in existing_paths:
        n += 1
        candidate = f"{stem}-{n}{suffix}"

    remote_path = f"reports/{section}/{candidate}"

    if SB_ENABLED:
        sb_upload(remote_path, file_bytes, content_type="application/pdf")
        public_url = sb_public_url(remote_path)
    else:
        section_dir = REPORTS_DIR / section
        section_dir.mkdir(parents=True, exist_ok=True)
        (section_dir / candidate).write_bytes(file_bytes)
        public_url = f"app/static/{remote_path}"  # legacy local mode

    row = {
        "section": section,
        "event_date": event_date.isoformat(),
        "event_name": event_name.strip(),
        "brand": brand.strip(),
        "filename": candidate,
        "path": remote_path,
        "url": public_url,
        "original_name": original_name,
        "size_kb": round(len(file_bytes) / 1024, 1),
        "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    rows.append(row)
    save_index(rows)
    return row


def delete_report(row: dict) -> None:
    if SB_ENABLED:
        try:
            sb_delete(row["path"])
        except Exception:
            pass
    else:
        legacy = APP_DIR / "static" / row["path"]
        try:
            if legacy.exists():
                legacy.unlink()
        except OSError:
            pass
    rows = [r for r in load_index() if not (
        r.get("path") == row.get("path") and r.get("uploaded_at") == row.get("uploaded_at")
    )]
    save_index(rows)


# ---------------------------------------------------------------------------
# UI building blocks
# ---------------------------------------------------------------------------
def pdf_preview(path: Path, height: int = 720) -> None:
    """Inline-render a PDF using a base64 data-URI iframe."""
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError as exc:
        st.error(f"Could not read file: {exc}")
        return
    st.markdown(
        f'<iframe src="data:application/pdf;base64,{b64}" '
        f'width="100%" height="{height}" style="border:1px solid rgba(167,139,250,0.25);'
        f'border-radius:12px;"></iframe>',
        unsafe_allow_html=True,
    )


def upload_panel(section: str) -> None:
    # Show any pending banner from a previous run (survives st.rerun)
    flash_key = f"flash_{section}"
    flash = st.session_state.pop(flash_key, None)
    if flash:
        kind, msg = flash
        if kind == "ok":
            st.markdown(
                f'<div style="padding:14px 18px;border-radius:12px;'
                f'background:linear-gradient(90deg,#10B981 0%,#059669 100%);'
                f'color:white;font-weight:700;border:1px solid #34D399;'
                f'box-shadow:0 6px 20px rgba(16,185,129,0.35);margin-bottom:12px;">'
                f'✅ {msg}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="padding:14px 18px;border-radius:12px;'
                f'background:linear-gradient(90deg,#DC2626 0%,#B91C1C 100%);'
                f'color:white;font-weight:700;border:1px solid #F87171;'
                f'box-shadow:0 6px 20px rgba(220,38,38,0.35);margin-bottom:12px;">'
                f'❌ {msg}</div>',
                unsafe_allow_html=True,
            )

    with st.expander(f"⬆️  Upload a new {section} report", expanded=False):
        with st.form(f"upload_form_{section}", clear_on_submit=True):
            up = st.file_uploader(
                "PDF report",
                type=["pdf"],
                accept_multiple_files=False,
                key=f"upl_{section}",
            )
            c1, c2 = st.columns(2)
            with c1:
                ev_date = st.date_input(
                    "Event date",
                    value=date.today(),
                    key=f"date_{section}",
                    format="YYYY-MM-DD",
                )
                ev_name = st.text_input(
                    "Event name",
                    placeholder="e.g. PYM x Fabrika",
                    key=f"name_{section}",
                )
            with c2:
                brand = st.text_input(
                    "Brand / Client",
                    placeholder="e.g. Play Your Music",
                    key=f"brand_{section}",
                )
                st.caption(
                    "The file will be filed under the **month of the event date**."
                )
            submitted = st.form_submit_button(
                "💾 Save report", type="primary", use_container_width=True
            )
            if submitted:
                if up is None:
                    st.session_state[flash_key] = ("err", "Please choose a PDF file first.")
                    st.rerun()
                elif not ev_name.strip():
                    st.session_state[flash_key] = ("err", "Please enter the event name.")
                    st.rerun()
                elif not brand.strip():
                    st.session_state[flash_key] = ("err", "Please enter the brand / client.")
                    st.rerun()
                else:
                    try:
                        row = save_report(
                            section=section,
                            event_date=ev_date,
                            event_name=ev_name,
                            brand=brand,
                            file_bytes=up.getvalue(),
                            original_name=up.name,
                        )
                        st.session_state[flash_key] = (
                            "ok",
                            f"Report successfully uploaded — "
                            f"{row['event_name']} ({row['event_date']}) → {section}",
                        )
                    except Exception as exc:  # pragma: no cover
                        st.session_state[flash_key] = (
                            "err",
                            f"Upload failed: {exc}",
                        )
                    st.rerun()


def render_calendar(section: str, rows: list[dict]) -> None:
    section_rows = [r for r in rows if r["section"] == section]

    # KPI strip
    years_avail = sorted({int(r["event_date"][:4]) for r in section_rows}, reverse=True)
    default_year = years_avail[0] if years_avail else date.today().year
    if not years_avail:
        years_avail = [date.today().year]

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f'<div class="kpi"><div class="label">Total reports</div>'
            f'<div class="value">{len(section_rows)}</div></div>',
            unsafe_allow_html=True,
        )
    with k2:
        brands = {r["brand"] for r in section_rows if r.get("brand")}
        st.markdown(
            f'<div class="kpi"><div class="label">Brands covered</div>'
            f'<div class="value">{len(brands)}</div></div>',
            unsafe_allow_html=True,
        )
    with k3:
        events_this_year = sum(
            1 for r in section_rows if r["event_date"][:4] == str(default_year)
        )
        st.markdown(
            f'<div class="kpi"><div class="label">Events in {default_year}</div>'
            f'<div class="value">{events_this_year}</div></div>',
            unsafe_allow_html=True,
        )
    with k4:
        last = max((r["event_date"] for r in section_rows), default="—")
        st.markdown(
            f'<div class="kpi"><div class="label">Latest event</div>'
            f'<div class="value">{last}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # Year selector
    yc1, _ = st.columns([1, 4])
    with yc1:
        year_key = f"year_{section}"
        if year_key not in st.session_state or st.session_state[year_key] not in years_avail:
            st.session_state[year_key] = default_year
        year = st.selectbox(
            "Year",
            years_avail,
            index=years_avail.index(st.session_state[year_key]),
            key=year_key,
        )

    # Count per month
    counts = {m: 0 for m in range(1, 13)}
    for r in section_rows:
        try:
            d = datetime.fromisoformat(r["event_date"]).date()
        except ValueError:
            continue
        if d.year == year:
            counts[d.month] += 1

    sel_key = f"selected_month_{section}"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = None

    st.markdown(f"### 📅 {year} — monthly view")

    # 4 columns × 3 rows = 12 months. Each card IS a button.
    for row_i in range(3):
        sel = st.session_state[sel_key]
        sel_in_row = None
        if sel is not None:
            row_of_sel = (sel - 1) // 4
            if row_of_sel == row_i:
                sel_in_row = ((sel - 1) % 4) + 1
        sel_class = f" has-sel-{sel_in_row}" if sel_in_row else ""
        st.markdown(f'<div class="month-grid{sel_class}">', unsafe_allow_html=True)
        cols = st.columns(4, gap="small")
        for col_i in range(4):
            month_num = row_i * 4 + col_i + 1
            month_name = MONTHS[month_num - 1]
            n = counts[month_num]
            sub = "report" if n == 1 else "reports"
            label = f"{month_name.upper()}\n\n{n}  •  {sub}"
            with cols[col_i]:
                if st.button(
                    label,
                    key=f"btn_{section}_{year}_{month_num}",
                    help=f"Open {month_name} {year}",
                    use_container_width=True,
                ):
                    st.session_state[sel_key] = (
                        None if st.session_state[sel_key] == month_num else month_num
                    )
                    st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # Reports for the selected month
    sel = st.session_state[sel_key]
    if sel is None:
        st.info("👆 Click a month to see its reports.")
        return

    month_rows = [
        r for r in section_rows
        if r["event_date"][:7] == f"{year}-{sel:02d}"
    ]
    month_rows.sort(key=lambda r: r["event_date"], reverse=True)

    st.markdown(f"### 📁 {MONTHS[sel - 1]} {year} — {len(month_rows)} report(s)")
    if not month_rows:
        st.caption("No reports filed in this month yet.")
        return

    for i, r in enumerate(month_rows):
        # Public URL (Supabase) or legacy app/static URL
        href = r.get("url") or (
            "app/static/" + r["path"] if r.get("path", "").startswith("reports/")
            else r.get("path", "")
        )
        file_exists = bool(href)
        with st.container():
            c1, c2, c3 = st.columns([6, 2, 1])
            with c1:
                if file_exists:
                    st.markdown(
                        f'<a class="report-link" href="{href}" target="_blank" '
                        f'rel="noopener noreferrer">'
                        f'<div class="report-card">'
                        f'<div class="r-title">📄 {r["event_name"]}</div>'
                        f'<div class="r-meta">📅 {r["event_date"]}  •  🏷️ {r["brand"]}'
                        f'  •  {r["filename"]}  •  {r["size_kb"]} KB</div>'
                        f"</div></a>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div class="report-card">'
                        f'<div class="r-title">⚠️ {r["event_name"]} (file missing)</div>'
                        f'<div class="r-meta">📅 {r["event_date"]}  •  🏷️ {r["brand"]}</div>'
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            with c2:
                if file_exists:
                    st.link_button(
                        "⬇️ Download", href,
                        use_container_width=True,
                    )
            with c3:
                if st.button("🗑️", key=f"del_{section}_{i}_{r['filename']}",
                             help="Delete this report", use_container_width=True):
                    delete_report(r)
                    st.rerun()


# ---------------------------------------------------------------------------
# Media section — Excel-driven dashboard
# ---------------------------------------------------------------------------
MEDIA_COLOR_SEQ = ["#A78BFA", "#8B5CF6", "#6366F1", "#EC4899", "#F59E0B",
                   "#10B981", "#06B6D4", "#F472B6"]

# Per-Media palette — softened to match the violet/indigo dashboard theme
MEDIA_COLORS = {
    "tv":         "#F0A6C9",  # soft pink
    "radio":      "#B6A0F2",  # soft violet
    "affichage":  "#FFCB90",  # soft amber
    "presse":     "#5B6478",  # muted slate grey
    "digital":    "#7DD3DC",  # soft cyan
    "cinema":     "#86E4C0",  # soft mint
}


def _media_color(name: str) -> str:
    if not isinstance(name, str):
        return "#A78BFA"
    return MEDIA_COLORS.get(name.strip().lower(), "#B6A0F2")


def _media_color_map(values) -> dict:
    return {v: _media_color(v) for v in values}


MEDIA_REMOTE_DIR = "media"
MEDIA_MANIFEST_REMOTE = f"{MEDIA_REMOTE_DIR}/active.json"


def _save_media_file(file_bytes: bytes, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower() or ".xlsx"
    remote_path = f"{MEDIA_REMOTE_DIR}/plurimedias{suffix}"
    meta = {
        "filename": Path(remote_path).name,
        "path": remote_path,
        "original_name": original_name,
        "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "size_kb": round(len(file_bytes) / 1024, 1),
    }
    if SB_ENABLED:
        sb_upload(remote_path, file_bytes,
                  content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        sb_put_json(MEDIA_MANIFEST_REMOTE, meta)
    else:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        (MEDIA_DIR / Path(remote_path).name).write_bytes(file_bytes)
        MEDIA_MANIFEST.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    load_media_df.clear()  # type: ignore[attr-defined]
    return remote_path


def _active_media_meta() -> dict | None:
    if SB_ENABLED:
        meta = sb_get_json(MEDIA_MANIFEST_REMOTE, default=None)
        return meta
    if not MEDIA_MANIFEST.exists():
        return None
    try:
        return json.loads(MEDIA_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@st.cache_data(show_spinner=False)
def load_media_df(remote_path: str, version: str) -> pd.DataFrame:
    if SB_ENABLED:
        raw = sb_download(remote_path)
        if raw is None:
            return pd.DataFrame()
        df = pd.read_excel(io.BytesIO(raw))
    else:
        df = pd.read_excel(MEDIA_DIR / Path(remote_path).name)
    for col in ("Tarif Final", "GRP"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("Annonceur", "Media", "Support_1"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()
    return df


def _fmt_money(v: float) -> str:
    if pd.isna(v):
        return "—"
    return f"{v:,.0f} TND".replace(",", " ")


def _fmt_int(v: float) -> str:
    if pd.isna(v):
        return "—"
    return f"{int(round(v)):,}".replace(",", " ")


def render_media() -> None:
    # Upload panel (single active file)
    flash_key = "flash_Media"
    flash = st.session_state.pop(flash_key, None)
    if flash:
        kind, msg = flash
        bg = ("linear-gradient(90deg,#10B981 0%,#059669 100%)" if kind == "ok"
              else "linear-gradient(90deg,#DC2626 0%,#B91C1C 100%)")
        icon = "✅" if kind == "ok" else "❌"
        st.markdown(
            f'<div style="padding:14px 18px;border-radius:12px;background:{bg};'
            f'color:white;font-weight:700;margin-bottom:12px;">{icon} {msg}</div>',
            unsafe_allow_html=True,
        )

    with st.expander("⬆️  Upload / replace the Plurimedia Excel", expanded=False):
        with st.form("upload_media", clear_on_submit=True):
            up = st.file_uploader(
                "Excel file (.xlsx) — must contain columns: Annonceur, Media, "
                "Support_1, Tarif Final, GRP",
                type=["xlsx", "xls"],
                key="upl_media",
            )
            submitted = st.form_submit_button(
                "💾 Save Excel", type="primary", use_container_width=True
            )
            if submitted:
                if up is None:
                    st.session_state[flash_key] = ("err", "Please choose an Excel file first.")
                else:
                    try:
                        target = _save_media_file(up.getvalue(), up.name)
                        st.session_state[flash_key] = (
                            "ok",
                            f"Plurimedia data successfully uploaded — {Path(target).name}",
                        )
                    except Exception as exc:  # pragma: no cover
                        st.session_state[flash_key] = ("err", f"Upload failed: {exc}")
                st.rerun()

    active = _active_media_meta()
    if active is None:
        st.info("No Plurimedia file uploaded yet. Use the panel above to add one.")
        return

    df = load_media_df(active["path"], active["uploaded_at"])

    required = {"Annonceur", "Media", "Support_1", "Tarif Final", "GRP"}
    missing = required.difference(df.columns)
    if missing:
        st.error(f"Missing columns in Excel: {', '.join(sorted(missing))}")
        return

    st.divider()

    # ── Filter: Annonceur dropdown (multi-select) ──────────────────────────
    annonceurs = sorted([a for a in df["Annonceur"].dropna().unique() if a])
    f1, f2 = st.columns([3, 1])
    with f1:
        sel = st.multiselect(
            "Annonceur",
            options=annonceurs,
            default=[],
            placeholder="All annonceurs (leave empty for total)",
            key="media_annonceur_filter",
        )
    with f2:
        st.caption(f"**{len(annonceurs)}** annonceurs available")

    fdf = df if not sel else df[df["Annonceur"].isin(sel)]

    if fdf.empty:
        st.warning("No rows match the current selection.")
        return

    # ── KPIs ──────────────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            f'<div class="kpi"><div class="label">Total invest. (Tarif Final)</div>'
            f'<div class="value">{_fmt_money(fdf["Tarif Final"].sum())}</div></div>',
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            f'<div class="kpi"><div class="label">Total GRP</div>'
            f'<div class="value">{_fmt_int(fdf["GRP"].sum())}</div></div>',
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            f'<div class="kpi"><div class="label">Insertions</div>'
            f'<div class="value">{_fmt_int(len(fdf))}</div></div>',
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            f'<div class="kpi"><div class="label">Annonceurs</div>'
            f'<div class="value">{fdf["Annonceur"].nunique()}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")

    # ── Mix Media pie (Media × Tarif Final) ───────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🥧 Mix Media — Tarif Final")
        mix = (fdf.groupby("Media", dropna=True)["Tarif Final"]
               .sum().reset_index().sort_values("Tarif Final", ascending=False))
        if mix.empty or mix["Tarif Final"].sum() == 0:
            st.caption("No Tarif Final to display.")
        else:
            fig = px.pie(
                mix, names="Media", values="Tarif Final", hole=0.62,
                color="Media",
                color_discrete_map=_media_color_map(mix["Media"]),
            )
            fig.update_traces(
                textposition="outside",
                textinfo="label+percent",
                textfont=dict(size=13, color="#F5F3FF"),
                marker=dict(line=dict(color="#0E0B1F", width=3)),
                pull=[0.02] * len(mix),
                hovertemplate=(
                    "<b>%{label}</b><br>"
                    "Tarif Final : %{value:,.0f} TND<br>"
                    "Share : %{percent}<extra></extra>"
                ),
            )
            total = mix["Tarif Final"].sum()
            fig.update_layout(
                height=440,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                showlegend=True,
                legend=dict(
                    orientation="h", y=-0.08, x=0.5, xanchor="center",
                    font=dict(size=12),
                ),
                margin=dict(t=10, b=20, l=10, r=10),
                annotations=[dict(
                    text=f"<b>{total/1e6:,.1f}M</b><br><span style='font-size:11px;color:#C4B5FD'>TND</span>",
                    x=0.5, y=0.5, font=dict(size=22, color="#F5F3FF"),
                    showarrow=False,
                )],
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── TV / Radio support bar chart (Support_1 within TV+Radio) ──────────
    with c2:
        st.markdown("#### 📡 TV & Radio supports")
        tv_radio = fdf[fdf["Media"].str.lower().isin(["tv", "radio"])]
        sup = (tv_radio.groupby(["Support_1", "Media"], dropna=True)
               .agg(**{"Tarif Final": ("Tarif Final", "sum"),
                       "GRP": ("GRP", "sum")})
               .reset_index().sort_values("Tarif Final", ascending=True))
        sup = sup[sup["Tarif Final"] > 0]
        if sup.empty:
            st.caption("No TV/Radio supports for the current selection.")
        else:
            fig = px.bar(
                sup, x="Tarif Final", y="Support_1", orientation="h",
                color="Media",
                color_discrete_map=_media_color_map(sup["Media"].unique()),
                custom_data=["GRP", "Media"],
            )
            fig.update_traces(
                marker=dict(
                    line=dict(width=0),
                    cornerradius=10,
                ),
                hovertemplate=(
                    "<b>%{y}</b>  —  %{customdata[1]}<br>"
                    "Tarif Final : %{x:,.0f} TND<br>"
                    "GRP : %{customdata[0]:,.2f}"
                    "<extra></extra>"
                ),
            )
            fig.update_layout(
                height=max(440, 26 * len(sup)),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                xaxis=dict(
                    gridcolor="rgba(167,139,250,0.12)",
                    zerolinecolor="rgba(167,139,250,0.25)",
                    title="", tickformat=",.0f",
                ),
                yaxis=dict(title="", tickfont=dict(size=11)),
                bargap=0.25,
                margin=dict(t=10, b=10, l=10, r=20),
                legend=dict(orientation="h", y=1.08, x=0,
                            title_text="", font=dict(size=12)),
                hoverlabel=dict(bgcolor="#1A1330", bordercolor="#A78BFA",
                                font=dict(color="#F5F3FF")),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── Saisonnalité — spend by month (Mois × Tarif Final) — line chart ───
    st.markdown("#### 📆 Saisonnalité — spend by month")
    if "Mois" not in fdf.columns:
        st.caption("Column `Mois` is missing in the Excel.")
    else:
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        saison = (fdf.dropna(subset=["Mois"])
                  .assign(_m=lambda d: pd.to_numeric(d["Mois"], errors="coerce"))
                  .dropna(subset=["_m"])
                  .assign(_m=lambda d: d["_m"].astype(int))
                  .groupby("_m", as_index=False)["Tarif Final"].sum()
                  .sort_values("_m"))
        # Reindex to all 12 months so the line covers the whole year
        full = pd.DataFrame({"_m": range(1, 13)})
        saison = full.merge(saison, on="_m", how="left").fillna({"Tarif Final": 0})
        saison["Mois"] = saison["_m"].apply(lambda m: month_names[m - 1])

        if saison["Tarif Final"].sum() == 0:
            st.caption("No spend recorded by month.")
        else:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=saison["Mois"], y=saison["Tarif Final"],
                mode="lines+markers",
                line=dict(color="#A78BFA", width=3, shape="spline", smoothing=0.7),
                marker=dict(size=11, color="#EC4899",
                            line=dict(width=2, color="#0E0B1F")),
                fill="tozeroy",
                fillcolor="rgba(167,139,250,0.18)",
                hovertemplate="<b>%{x}</b><br>Tarif Final : %{y:,.0f} TND<extra></extra>",
                name="Tarif Final",
            ))
            fig.update_layout(
                height=420,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                xaxis=dict(
                    title="", showgrid=False,
                    categoryorder="array", categoryarray=saison["Mois"].tolist(),
                    tickfont=dict(size=12),
                ),
                yaxis=dict(
                    title="",
                    gridcolor="rgba(167,139,250,0.12)",
                    zerolinecolor="rgba(167,139,250,0.25)",
                    tickformat=",.0f",
                ),
                margin=dict(t=20, b=20, l=10, r=10),
                hoverlabel=dict(bgcolor="#1A1330", bordercolor="#A78BFA",
                                font=dict(color="#F5F3FF")),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"Source: `{Path(active['path']).name}` — "
        f"{len(df):,} rows • last upload {active['uploaded_at']}"
    )


# ---------------------------------------------------------------------------
# Paid section — Meta Ads-style global overview (inspired by Batam dashboard)
# ---------------------------------------------------------------------------
PAID_PLATFORM_COLORS = {
    "FB": "#7AA8F2",     # soft Meta blue
    "IG": "#F0A6C9",     # soft Insta pink
    "AN": "#B6A0F2",     # soft violet (Audience Network)
    "MSGR": "#86E4C0",   # soft mint (Messenger)
}
PAID_GENDER_COLORS = {
    "female": "#F0A6C9",
    "male":   "#7AA8F2",
    "all":    "#B6A0F2",
    "unknown": "#5B6478",
}


PAID_REMOTE_DIR = "paid"
PAID_MANIFEST_REMOTE = f"{PAID_REMOTE_DIR}/active.json"


def _save_paid_file(file_bytes: bytes, original_name: str) -> str:
    suffix = Path(original_name).suffix.lower() or ".xlsx"
    remote_path = f"{PAID_REMOTE_DIR}/paid{suffix}"
    meta = {
        "filename": Path(remote_path).name,
        "path": remote_path,
        "original_name": original_name,
        "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "size_kb": round(len(file_bytes) / 1024, 1),
    }
    if SB_ENABLED:
        sb_upload(remote_path, file_bytes,
                  content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        sb_put_json(PAID_MANIFEST_REMOTE, meta)
    else:
        PAID_DIR.mkdir(parents=True, exist_ok=True)
        (PAID_DIR / Path(remote_path).name).write_bytes(file_bytes)
        PAID_MANIFEST.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    load_paid_df.clear()  # type: ignore[attr-defined]
    return remote_path


def _active_paid_meta() -> dict | None:
    if SB_ENABLED:
        return sb_get_json(PAID_MANIFEST_REMOTE, default=None)
    if not PAID_MANIFEST.exists():
        return None
    try:
        return json.loads(PAID_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


@st.cache_data(show_spinner=False)
def load_paid_df(remote_path: str, version: str) -> pd.DataFrame:
    if SB_ENABLED:
        raw = sb_download(remote_path)
        if raw is None:
            return pd.DataFrame()
        df = pd.read_excel(io.BytesIO(raw))
    else:
        df = pd.read_excel(PAID_DIR / Path(remote_path).name)
    numeric_cols = [
        "Montant dépensé (USD)", "Impressions", "Couverture", "Clics (tous)",
        "Clics sur un lien", "CTR (tous)", "CTR (taux de clics sur le lien)",
        "CPC (Tous) (USD)", "CPC (coût par clic sur un lien) (USD)",
        "CPM (Coût pour 1 000 impressions) (USD)", "Résultats", "Répétition",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("Genre", "plateforme", "campaign_type", "campaign_sub_type",
              "Nom de la campagne"):
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()
    if "Fin" in df.columns:
        df["Fin"] = pd.to_datetime(df["Fin"], errors="coerce")
    return df


def render_paid() -> None:
    flash_key = "flash_Paid"
    flash = st.session_state.pop(flash_key, None)
    if flash:
        kind, msg = flash
        bg = ("linear-gradient(90deg,#10B981 0%,#059669 100%)" if kind == "ok"
              else "linear-gradient(90deg,#DC2626 0%,#B91C1C 100%)")
        icon = "✅" if kind == "ok" else "❌"
        st.markdown(
            f'<div style="padding:14px 18px;border-radius:12px;background:{bg};'
            f'color:white;font-weight:700;margin-bottom:12px;">{icon} {msg}</div>',
            unsafe_allow_html=True,
        )

    with st.expander("⬆️  Upload / replace the Paid Media Excel", expanded=False):
        with st.form("upload_paid", clear_on_submit=True):
            up = st.file_uploader(
                "Excel file (.xlsx) — Meta / paid-media export",
                type=["xlsx", "xls"],
                key="upl_paid",
            )
            submitted = st.form_submit_button(
                "💾 Save Excel", type="primary", use_container_width=True
            )
            if submitted:
                if up is None:
                    st.session_state[flash_key] = ("err", "Please choose an Excel file first.")
                else:
                    try:
                        target = _save_paid_file(up.getvalue(), up.name)
                        st.session_state[flash_key] = (
                            "ok",
                            f"Paid data successfully uploaded — {Path(target).name}",
                        )
                    except Exception as exc:  # pragma: no cover
                        st.session_state[flash_key] = ("err", f"Upload failed: {exc}")
                st.rerun()

    active = _active_paid_meta()
    if active is None:
        st.info("No Paid Media file uploaded yet. Use the panel above to add one.")
        return

    df = load_paid_df(active["path"], active["uploaded_at"])

    spend_col = "Montant dépensé (USD)"
    if spend_col not in df.columns:
        st.error(f"Missing required column: `{spend_col}`")
        return

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────
    f1, f2 = st.columns(2)
    with f1:
        genres = sorted([g for g in df["Genre"].dropna().unique() if g]) \
            if "Genre" in df.columns else []
        sel_g = st.multiselect(
            "Gender", genres, default=[],
            placeholder="All genders",
            key="paid_genre_filter",
        )
    with f2:
        plats = sorted([p for p in df["plateforme"].dropna().unique() if p]) \
            if "plateforme" in df.columns else []
        sel_p = st.multiselect(
            "Platform", plats, default=[],
            placeholder="All platforms",
            key="paid_plat_filter",
        )

    fdf = df.copy()
    if sel_g:
        fdf = fdf[fdf["Genre"].isin(sel_g)]
    if sel_p:
        fdf = fdf[fdf["plateforme"].isin(sel_p)]

    if fdf.empty:
        st.warning("No rows match the current selection.")
        return

    # ── KPIs ──────────────────────────────────────────────────────────────
    spend = fdf[spend_col].sum()
    impr = fdf["Impressions"].sum() if "Impressions" in fdf else 0
    reach = fdf["Couverture"].sum() if "Couverture" in fdf else 0
    clicks = fdf["Clics (tous)"].sum() if "Clics (tous)" in fdf else 0
    ctr = (clicks / impr * 100) if impr else 0
    cpc = (spend / clicks) if clicks else 0
    cpm = (spend / impr * 1000) if impr else 0

    def _kpi(label: str, value: str) -> str:
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value}</div></div>')

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi("Spend (USD)", f"${spend:,.0f}"), unsafe_allow_html=True)
    k2.markdown(_kpi("Impressions", _fmt_int(impr)), unsafe_allow_html=True)
    k3.markdown(_kpi("Reach", _fmt_int(reach)), unsafe_allow_html=True)
    k4.markdown(_kpi("Clicks", _fmt_int(clicks)), unsafe_allow_html=True)

    k5, k6, k7, k8 = st.columns(4)
    k5.markdown(_kpi("Avg CTR", f"{ctr:.2f}%"), unsafe_allow_html=True)
    k6.markdown(_kpi("Avg CPC (USD)", f"${cpc:.3f}"), unsafe_allow_html=True)
    k7.markdown(_kpi("Avg CPM (USD)", f"${cpm:.2f}"), unsafe_allow_html=True)
    k8.markdown(_kpi("Campaigns", f'{fdf["Nom de la campagne"].nunique() if "Nom de la campagne" in fdf else 0}'),
                unsafe_allow_html=True)

    st.write("")

    # ── Spend by platform donut + Spend by gender bar ─────────────────────
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 📱 Spend by platform")
        if "plateforme" not in fdf.columns:
            st.caption("Column `plateforme` is missing.")
        else:
            plat = (fdf.groupby("plateforme", dropna=True)[spend_col].sum()
                    .reset_index().sort_values(spend_col, ascending=False))
            plat = plat[plat[spend_col] > 0]
            if plat.empty:
                st.caption("No spend recorded.")
            else:
                fig = px.pie(
                    plat, names="plateforme", values=spend_col, hole=0.62,
                    color="plateforme",
                    color_discrete_map={p: PAID_PLATFORM_COLORS.get(p, "#B6A0F2")
                                        for p in plat["plateforme"]},
                )
                fig.update_traces(
                    textposition="outside", textinfo="label+percent",
                    textfont=dict(color="#F5F3FF", size=13),
                    marker=dict(line=dict(color="#0E0B1F", width=3)),
                    pull=[0.02] * len(plat),
                    hovertemplate="<b>%{label}</b><br>$%{value:,.0f}<br>%{percent}<extra></extra>",
                )
                fig.update_layout(
                    height=420,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                    showlegend=True,
                    legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center"),
                    margin=dict(t=10, b=20, l=10, r=10),
                    annotations=[dict(
                        text=f"<b>${spend/1000:,.1f}K</b><br>"
                             f"<span style='font-size:11px;color:#C4B5FD'>spend</span>",
                        x=0.5, y=0.5, font=dict(size=20, color="#F5F3FF"),
                        showarrow=False,
                    )],
                )
                st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("#### 👥 Spend by gender")
        if "Genre" not in fdf.columns:
            st.caption("Column `Genre` is missing.")
        else:
            gen = (fdf.groupby("Genre", dropna=True)[spend_col].sum()
                   .reset_index().sort_values(spend_col, ascending=True))
            gen = gen[gen[spend_col] > 0]
            if gen.empty:
                st.caption("No spend recorded.")
            else:
                fig = px.bar(
                    gen, x=spend_col, y="Genre", orientation="h",
                    color="Genre",
                    color_discrete_map={g: PAID_GENDER_COLORS.get(str(g).lower(),
                                        "#B6A0F2") for g in gen["Genre"]},
                    text=spend_col,
                )
                fig.update_traces(
                    texttemplate="$%{text:,.0f}", textposition="outside",
                    marker=dict(line=dict(width=0), cornerradius=10),
                    hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>",
                )
                fig.update_layout(
                    height=420,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                    xaxis=dict(gridcolor="rgba(167,139,250,0.12)", title="",
                               tickformat="$,.0f"),
                    yaxis=dict(title=""),
                    showlegend=False,
                    bargap=0.35,
                    margin=dict(t=20, b=10, l=10, r=30),
                )
                st.plotly_chart(fig, use_container_width=True)

    # ── Top 10 campaigns by spend ─────────────────────────────────────────
    st.markdown("#### 🏆 Top 10 campaigns by spend")
    if "Nom de la campagne" not in fdf.columns:
        st.caption("Column `Nom de la campagne` is missing.")
    else:
        agg = (fdf.groupby("Nom de la campagne", dropna=True)
               .agg(**{
                   "Spend": (spend_col, "sum"),
                   "Impressions": ("Impressions", "sum") if "Impressions" in fdf else (spend_col, "size"),
                   "Clicks": ("Clics (tous)", "sum") if "Clics (tous)" in fdf else (spend_col, "size"),
               })
               .reset_index()
               .sort_values("Spend", ascending=False)
               .head(10)
               .sort_values("Spend", ascending=True))
        if agg.empty:
            st.caption("No campaigns to display.")
        else:
            agg["short"] = agg["Nom de la campagne"].apply(
                lambda s: (s[:55] + "…") if len(str(s)) > 55 else s
            )
            fig = px.bar(
                agg, x="Spend", y="short", orientation="h",
                color="Spend",
                color_continuous_scale=["#6366F1", "#A78BFA", "#F0A6C9"],
                custom_data=["Impressions", "Clicks", "Nom de la campagne"],
            )
            fig.update_traces(
                marker=dict(line=dict(width=0), cornerradius=10),
                hovertemplate=(
                    "<b>%{customdata[2]}</b><br>"
                    "Spend : $%{x:,.0f}<br>"
                    "Impressions : %{customdata[0]:,.0f}<br>"
                    "Clicks : %{customdata[1]:,.0f}"
                    "<extra></extra>"
                ),
            )
            fig.update_layout(
                height=max(440, 38 * len(agg)),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                xaxis=dict(gridcolor="rgba(167,139,250,0.12)", title="",
                           tickformat="$,.0f"),
                yaxis=dict(title="", tickfont=dict(size=11)),
                coloraxis_showscale=False,
                bargap=0.25,
                margin=dict(t=10, b=10, l=10, r=20),
                hoverlabel=dict(bgcolor="#1A1330", bordercolor="#A78BFA",
                                font=dict(color="#F5F3FF")),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── Spend trend over time (Fin date) ──────────────────────────────────
    if "Fin" in fdf.columns and fdf["Fin"].notna().any():
        st.markdown("#### 📈 Spend over time")
        trend = (fdf.dropna(subset=["Fin"])
                 .assign(_d=fdf["Fin"].dt.to_period("W").dt.start_time)
                 .groupby("_d", as_index=False)[spend_col].sum()
                 .sort_values("_d"))
        if not trend.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=trend["_d"], y=trend[spend_col],
                mode="lines+markers",
                line=dict(color="#B6A0F2", width=3, shape="spline", smoothing=0.7),
                marker=dict(size=9, color="#F0A6C9",
                            line=dict(width=2, color="#0E0B1F")),
                fill="tozeroy",
                fillcolor="rgba(182,160,242,0.18)",
                hovertemplate="<b>Week of %{x|%b %d, %Y}</b><br>$%{y:,.0f}<extra></extra>",
            ))
            fig.update_layout(
                height=380,
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                xaxis=dict(title="", showgrid=False),
                yaxis=dict(title="", gridcolor="rgba(167,139,250,0.12)",
                           tickformat="$,.0f"),
                margin=dict(t=20, b=20, l=10, r=10),
                hoverlabel=dict(bgcolor="#1A1330", bordercolor="#A78BFA",
                                font=dict(color="#F5F3FF")),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"Source: `{Path(active['path']).name}` — "
        f"{len(df):,} rows • last upload {active['uploaded_at']}"
    )


def render_section(section: str) -> None:
    icon = SECTION_ICONS.get(section, "📁")
    st.markdown(f"## {icon} {section}")
    if section == "Media":
        render_media()
        return
    if section == "Paid":
        render_paid()
        return
    upload_panel(section)
    st.divider()
    render_calendar(section, load_index())


# ---------------------------------------------------------------------------
# Header & sidebar
# ---------------------------------------------------------------------------
_hcol1, _hcol2 = st.columns([1, 9], gap="small")
with _hcol1:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=90)
with _hcol2:
    st.title("Dashboard de pilotage — 3SG Group")
    st.caption(
        "Centralised event-report archive across **Media · Social · Influence · ATL · BTL**. "
        "Upload a PDF, attach the event date, and find it later in the monthly calendar."
    )

if not SB_ENABLED:
    st.error(
        "⚠️ **Supabase is NOT connected** — uploads will be lost on app restart.  \n"
        "Go to your Streamlit Cloud app → **⋮ → Settings → Secrets** and paste:\n"
        "```toml\n"
        "[supabase]\n"
        'url = "https://lqzlbjhhwtllmgyotwue.supabase.co"\n'
        'service_key = "YOUR_SERVICE_ROLE_KEY"\n'
        'bucket = "3sg-reports"\n'
        "```\n"
        "Then save — the app will reboot and connect automatically.",
        icon="🔴",
    )

with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
    st.markdown("### 🗂️ Library")
    rows = load_index()
    st.metric("Total reports", len(rows))
    by_section = {s: 0 for s in SECTIONS}
    for r in rows:
        if r["section"] in by_section:
            by_section[r["section"]] += 1
    for s in SECTIONS:
        st.write(f"{SECTION_ICONS[s]} **{s}** — {by_section[s]}")
    st.divider()
    if SB_ENABLED:
        st.success("🟢 Supabase connected — uploads persist.")
    else:
        st.error("🔴 Supabase NOT connected — add secrets!")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tabs = st.tabs([f"{SECTION_ICONS[s]}  {s}" for s in SECTIONS])
for tab, section in zip(tabs, SECTIONS):
    with tab:
        render_section(section)
