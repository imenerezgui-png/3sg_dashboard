"""3SG Group — Dashboard de pilotage.

Five sections (Media, Social, Influence, ATL, BTL). Each section accepts PDF
event-report uploads (with event date, name, brand) and displays a 12-month
calendar grid for the selected year. Clicking a month reveals every report
filed in that month.
"""

from __future__ import annotations

import base64
import html as _html
import io
import json
import re
import tempfile
import uuid
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
        timeout=300,
    )
    if not r.ok:
        # Surface the real Supabase error so users see the cause (e.g. file too large)
        msg = ""
        try:
            j = r.json()
            msg = j.get("message") or j.get("error") or ""
        except Exception:
            msg = (r.text or "")[:300]
        size_mb = len(data) / (1024 * 1024)
        hint = ""
        if r.status_code == 400 and ("size" in msg.lower() or "exceed" in msg.lower()
                                      or "too large" in msg.lower() or size_mb > 50):
            hint = (f" — file is {size_mb:.1f} MB. "
                    "Raise the bucket file-size limit in Supabase "
                    "(Storage → bucket → Settings → File size limit).")
        raise RuntimeError(f"Upload failed ({r.status_code}): {msg}{hint}")


def sb_ensure_bucket_limits(max_mb: int = 200) -> None:
    """Best-effort: raise this bucket's file_size_limit so large PDFs are accepted.

    Uses the storage admin API (service-role key required). Silent on failure
    (e.g. RLS or insufficient privileges)."""
    if not SB_ENABLED:
        return
    try:
        url = f"{SB_URL}/storage/v1/bucket/{SB_BUCKET}"
        body = {"file_size_limit": max_mb * 1024 * 1024, "public": True}
        requests.put(url, headers=_sb_headers({"Content-Type": "application/json"}),
                     data=json.dumps(body), timeout=15)
    except Exception:
        pass


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


@st.cache_resource(show_spinner=False)
def _sb_bootstrap() -> bool:
    """Run once per app process: raise bucket limits so large PDFs are accepted."""
    sb_ensure_bucket_limits(max_mb=200)
    return True


if SB_ENABLED:
    _sb_bootstrap()

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


_MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun",
                "Jul","Aug","Sep","Oct","Nov","Dec"]


def _derive_year_month(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Return (year_series, month_series) of ints derived from the dataframe.

    Looks for explicit ``Année``/``Annee``/``Year`` and ``Mois``/``Month`` columns,
    otherwise tries to derive from any datetime column found
    (``Reporting starts``, ``Date``, ``Fin``…). Missing values come back as NaN.
    """
    year = pd.Series([pd.NA] * len(df), index=df.index, dtype="Float64")
    month = pd.Series([pd.NA] * len(df), index=df.index, dtype="Float64")

    for c in ("Année", "Annee", "Year", "year"):
        if c in df.columns:
            year = pd.to_numeric(df[c], errors="coerce")
            break
    for c in ("Mois", "Month", "month"):
        if c in df.columns:
            month = pd.to_numeric(df[c], errors="coerce")
            break

    if year.isna().all() or month.isna().all():
        for c in ("Reporting starts", "Reporting ends", "Date", "Fin", "Début", "Debut"):
            if c in df.columns:
                d = pd.to_datetime(df[c], errors="coerce")
                if year.isna().all():
                    year = d.dt.year.astype("Float64")
                if month.isna().all():
                    month = d.dt.month.astype("Float64")
                break
    return year, month


def _year_month_filters(df: pd.DataFrame, key_prefix: str) -> pd.DataFrame:
    """Render Year + Month multiselects in two columns and return filtered df."""
    year_s, month_s = _derive_year_month(df)
    fdf = df

    years = sorted({int(y) for y in year_s.dropna().tolist()})
    months = sorted({int(m) for m in month_s.dropna().tolist() if 1 <= int(m) <= 12})

    cy, cm = st.columns(2)
    with cy:
        if years:
            sel_y = st.multiselect(
                "Year", options=years, default=[],
                placeholder="All years",
                key=f"{key_prefix}_year_filter",
            )
            if sel_y:
                fdf = fdf[year_s.isin(sel_y)]
        else:
            st.caption("_No year column found_")
    with cm:
        if months:
            month_labels = {m: _MONTH_NAMES[m - 1] for m in months}
            sel_m = st.multiselect(
                "Month", options=months, default=[],
                format_func=lambda m: month_labels.get(m, str(m)),
                placeholder="All months",
                key=f"{key_prefix}_month_filter",
            )
            if sel_m:
                fdf = fdf[month_s.loc[fdf.index].isin(sel_m)]
        else:
            st.caption("_No month column found_")
    return fdf


def _render_insight_cards(title: str, items: list[dict]) -> None:
    """Render a row of styled insight cards.

    Each item: {"icon": "🏆", "label": "...", "value": "...", "sub": "..."}
    """
    if not items:
        return
    st.markdown(f"#### {title}")
    cards_css = """
    <style>
    .insight-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
                 gap:14px;margin-top:6px;margin-bottom:8px;}
    .insight-card{background:linear-gradient(135deg,rgba(167,139,250,0.12) 0%,
                  rgba(240,166,201,0.08) 100%);
                  border:1px solid rgba(167,139,250,0.25);
                  border-radius:16px;padding:16px 18px;
                  box-shadow:0 6px 24px rgba(0,0,0,0.25);
                  transition:transform .15s ease, box-shadow .15s ease;}
    .insight-card:hover{transform:translateY(-3px);
                  box-shadow:0 10px 30px rgba(167,139,250,0.25);}
    .insight-card .ic-head{display:flex;align-items:center;gap:8px;
                  font-size:12px;text-transform:uppercase;letter-spacing:.08em;
                  color:#C4B5FD;font-weight:600;}
    .insight-card .ic-icon{font-size:18px;}
    .insight-card .ic-value{font-size:22px;font-weight:800;color:#F5F3FF;
                  margin-top:6px;line-height:1.2;}
    .insight-card .ic-sub{font-size:12px;color:#A78BFA;margin-top:4px;}
    </style>
    """
    html = ['<div class="insight-row">']
    for it in items:
        icon = it.get("icon", "✨")
        label = it.get("label", "")
        value = it.get("value", "—")
        sub = it.get("sub", "")
        html.append(
            f'<div class="insight-card">'
            f'<div class="ic-head"><span class="ic-icon">{icon}</span>{label}</div>'
            f'<div class="ic-value">{value}</div>'
            + (f'<div class="ic-sub">{sub}</div>' if sub else "")
            + '</div>'
        )
    html.append('</div>')
    st.markdown(cards_css + "".join(html), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Per-section notes (campaigns annotations)
# ---------------------------------------------------------------------------
NOTES_REMOTE_DIR = "notes"
NOTES_LOCAL_DIR = APP_DIR / "static" / "notes"


def _notes_remote(section: str) -> str:
    return f"{NOTES_REMOTE_DIR}/{section.lower()}.json"


def _notes_local(section: str) -> Path:
    return NOTES_LOCAL_DIR / f"{section.lower()}.json"


def load_notes(section: str) -> list[dict]:
    if SB_ENABLED:
        data = sb_get_json(_notes_remote(section), default=[])
        return data if isinstance(data, list) else []
    p = _notes_local(section)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_notes(section: str, notes: list[dict]) -> None:
    if SB_ENABLED:
        sb_put_json(_notes_remote(section), notes)
    else:
        NOTES_LOCAL_DIR.mkdir(parents=True, exist_ok=True)
        _notes_local(section).write_text(
            json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8"
        )


_NOTES_CSS = """
<style>
.note-card{
    background:linear-gradient(135deg,rgba(167,139,250,0.10) 0%,
                                       rgba(240,166,201,0.06) 100%);
    border:1px solid rgba(167,139,250,0.22);
    border-radius:14px;padding:14px 16px;margin:8px 0;
    box-shadow:0 4px 18px rgba(0,0,0,0.22);
}
.note-card .note-head{font-size:13px;color:#C4B5FD;margin-bottom:6px;
                       text-transform:uppercase;letter-spacing:.05em;}
.note-card .note-camp{color:#F5F3FF;font-weight:700;font-size:15px;
                       text-transform:none;letter-spacing:0;}
.note-card .note-body{color:#F5F3FF;font-size:14px;line-height:1.55;
                       white-space:pre-wrap;}
</style>
"""


def render_notes_panel(section: str,
                       campaign_options: list[str] | None = None) -> None:
    """Notes block: Add note / See notes buttons + persisted storage.

    If ``campaign_options`` is provided (and non-empty), the campaign field in the
    Add-note form becomes a dropdown of those values instead of a free text input.
    """
    st.markdown("#### 📝 Campaign notes")
    st.markdown(_NOTES_CSS, unsafe_allow_html=True)

    add_key = f"notes_show_add_{section}"
    see_key = f"notes_show_see_{section}"
    flash_key = f"notes_flash_{section}"

    # Flash message (after add/delete)
    flash = st.session_state.pop(flash_key, None)
    if flash:
        kind, msg = flash
        if kind == "ok":
            st.success(msg)
        else:
            st.error(msg)

    b1, b2, _ = st.columns([1, 1, 4])
    with b1:
        if st.button("➕ Add note", key=f"notes_btn_add_{section}",
                     use_container_width=True):
            st.session_state[add_key] = not st.session_state.get(add_key, False)
            st.session_state[see_key] = False
            st.rerun()
    with b2:
        if st.button("👁️ See notes", key=f"notes_btn_see_{section}",
                     use_container_width=True):
            st.session_state[see_key] = not st.session_state.get(see_key, False)
            st.session_state[add_key] = False
            st.rerun()

    use_dropdown = bool(campaign_options)

    # ── Add note form ────────────────────────────────────────────────────
    if st.session_state.get(add_key):
        with st.form(f"notes_form_{section}", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                d = st.date_input("Date", value=date.today(),
                                  key=f"notes_date_{section}")
            with c2:
                if use_dropdown:
                    campaign = st.selectbox(
                        "Campaign",
                        options=campaign_options,
                        key=f"notes_camp_{section}",
                        help="Choose a campaign from the uploaded data.",
                    )
                else:
                    campaign = st.text_input(
                        "Campaign name",
                        placeholder="e.g. Summer launch 2026",
                        key=f"notes_camp_{section}",
                    )
            text = st.text_area(
                "Note (≈ 200 words max)",
                max_chars=1500, height=200,
                placeholder="Write your observations, learnings, next steps…",
                key=f"notes_text_{section}",
                help="Up to ~200 words (1500 characters).",
            )
            words = len(text.split()) if text else 0
            st.caption(f"{words} / 200 words")
            cs1, cs2 = st.columns([1, 1])
            with cs1:
                save = st.form_submit_button("💾 Save note", type="primary",
                                             use_container_width=True)
            with cs2:
                cancel = st.form_submit_button("✖ Cancel",
                                               use_container_width=True)
            if save:
                if not campaign.strip() or not text.strip():
                    st.warning("Campaign name and note text are both required.")
                else:
                    notes = load_notes(section)
                    notes.append({
                        "id": uuid.uuid4().hex[:10],
                        "date": d.isoformat(),
                        "campaign": campaign.strip(),
                        "text": text.strip(),
                        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    })
                    try:
                        save_notes(section, notes)
                        st.session_state[flash_key] = ("ok", "Note saved.")
                        st.session_state[add_key] = False
                    except Exception as exc:
                        st.session_state[flash_key] = ("err", f"Save failed: {exc}")
                    st.rerun()
            if cancel:
                st.session_state[add_key] = False
                st.rerun()

    # ── See notes view ───────────────────────────────────────────────────
    if st.session_state.get(see_key):
        notes = load_notes(section)
        if not notes:
            st.info("No notes yet. Click **Add note** to create the first one.")
            return
        campaigns = sorted({n.get("campaign", "") for n in notes if n.get("campaign")})
        sel = st.selectbox(
            "Filter by campaign",
            options=["— All campaigns —"] + campaigns,
            key=f"notes_filter_{section}",
        )
        shown = (notes if sel == "— All campaigns —"
                 else [n for n in notes if n.get("campaign") == sel])
        shown = sorted(shown, key=lambda n: n.get("date", ""), reverse=True)
        st.caption(f"{len(shown)} note(s)")
        for n in shown:
            safe_text = _html.escape(n.get("text", "")).replace("\n", "<br>")
            safe_camp = _html.escape(n.get("campaign", ""))
            safe_date = _html.escape(n.get("date", ""))
            st.markdown(
                f'<div class="note-card">'
                f'<div class="note-head"><span class="note-camp">{safe_camp}</span>'
                f'  ·  📅 {safe_date}</div>'
                f'<div class="note-body">{safe_text}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            with st.container():
                _, dc = st.columns([6, 1])
                with dc:
                    if st.button("🗑️ Delete", key=f"notes_del_{section}_{n['id']}",
                                 use_container_width=True):
                        kept = [x for x in load_notes(section) if x.get("id") != n["id"]]
                        try:
                            save_notes(section, kept)
                            st.session_state[flash_key] = ("ok", "Note deleted.")
                        except Exception as exc:
                            st.session_state[flash_key] = ("err", f"Delete failed: {exc}")
                        st.rerun()


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

    # ── Filters: Annonceur + Year + Month ─────────────────────────────────
    annonceurs = sorted([a for a in df["Annonceur"].dropna().unique() if a])
    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        sel = st.multiselect(
            "Annonceur",
            options=annonceurs,
            default=[],
            placeholder="All annonceurs (leave empty for total)",
            key="media_annonceur_filter",
        )
    year_s, month_s = _derive_year_month(df)
    years = sorted({int(y) for y in year_s.dropna().tolist()})
    months = sorted({int(m) for m in month_s.dropna().tolist() if 1 <= int(m) <= 12})
    with f2:
        sel_y = st.multiselect(
            "Year", options=years, default=[],
            placeholder=("All years" if years else "—"),
            key="media_year_filter",
            disabled=not years,
        )
    with f3:
        month_labels = {m: _MONTH_NAMES[m - 1] for m in months}
        sel_m = st.multiselect(
            "Month", options=months, default=[],
            format_func=lambda m: month_labels.get(m, str(m)),
            placeholder=("All months" if months else "—"),
            key="media_month_filter",
            disabled=not months,
        )

    fdf = df if not sel else df[df["Annonceur"].isin(sel)]
    if sel_y:
        fdf = fdf[year_s.loc[fdf.index].isin(sel_y)]
    if sel_m:
        fdf = fdf[month_s.loc[fdf.index].isin(sel_m)]

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

    # ── Key insights ─────────────────────────────────────────────────────
    insights: list[dict] = []
    try:
        if "Media" in fdf.columns and fdf["Tarif Final"].sum() > 0:
            mix = fdf.groupby("Media")["Tarif Final"].sum().sort_values(ascending=False)
            top_media = mix.index[0]
            share = mix.iloc[0] / mix.sum() * 100
            insights.append({
                "icon": "🏆", "label": "Top media",
                "value": str(top_media),
                "sub": f"{share:.1f}% of total invest. ({_fmt_money(mix.iloc[0])})",
            })
        if "Annonceur" in fdf.columns and fdf["Tarif Final"].sum() > 0:
            top_a = fdf.groupby("Annonceur")["Tarif Final"].sum().sort_values(ascending=False)
            insights.append({
                "icon": "👑", "label": "Top annonceur",
                "value": str(top_a.index[0]),
                "sub": f"{_fmt_money(top_a.iloc[0])} invested",
            })
        if "Mois" in fdf.columns and fdf["Tarif Final"].sum() > 0:
            _mois = pd.to_numeric(fdf["Mois"], errors="coerce")
            tmp = pd.DataFrame({"_m": _mois, "spend": fdf["Tarif Final"].values}).dropna()
            if not tmp.empty:
                by_month = tmp.groupby("_m")["spend"].sum().sort_values(ascending=False)
                month_names = ["Jan","Feb","Mar","Apr","May","Jun",
                               "Jul","Aug","Sep","Oct","Nov","Dec"]
                top_m = int(by_month.index[0])
                insights.append({
                    "icon": "📅", "label": "Peak month",
                    "value": month_names[top_m - 1] if 1 <= top_m <= 12 else str(top_m),
                    "sub": f"{_fmt_money(by_month.iloc[0])} that month",
                })
        if "GRP" in fdf.columns and fdf["GRP"].sum() > 0:
            cpp = fdf["Tarif Final"].sum() / fdf["GRP"].sum()
            insights.append({
                "icon": "📈", "label": "Avg cost per GRP",
                "value": _fmt_money(cpp),
                "sub": f"{_fmt_int(fdf['GRP'].sum())} total GRP",
            })
    except Exception:
        pass
    if insights:
        _render_insight_cards("✨ Key insights", insights)

    st.caption(
        f"Source: `{Path(active['path']).name}` — "
        f"{len(df):,} rows • last upload {active['uploaded_at']}"
    )


# ---------------------------------------------------------------------------
# Paid section — social-media global overview (Meta Ads export)
# ---------------------------------------------------------------------------
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

    # Normalize column names so old (English) and new (French OMD) schemas
    # both work without touching the rest of the code.
    # Collapse runs of whitespace and strip — handles "Budget  dt" double space.
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]

    rename_map = {
        # OMD MultiCampagnes (French) → canonical English names
        "Nom de la campagne":              "Campaign name",
        "Couverture":                      "Reach",
        "Clics (tous)":                    "Clicks (all)",
        "Interactions avec la publication": "Post engagements",
        "J'aime sur Facebook":             "Facebook likes",
        "J’aime sur Facebook":             "Facebook likes",  # curly apostrophe
        "Visites du profil Instagram":     "Instagram profile visits",
        "Budget dt":                       "Budget",
        "Budget DT":                       "Budget",
        "Indicateur de résultats":         "Objective",
        "Indicateur de resultats":         "Objective",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    numeric_cols = [
        "Reach", "Impressions", "Frequency", "Clicks (all)",
        "Post engagements", "ThruPlays", "CTR (all)",
        "Facebook likes", "Instagram profile visits",
        "Budget", "Résultats",
    ]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("Annonceur", "Campaign name", "Objective"):
        if c in df.columns:
            df[c] = df[c].astype("string").str.strip()
    # Normalize objective casing so "reach"/"Reach" don't split into two slices
    if "Objective" in df.columns:
        df["Objective"] = df["Objective"].str.title()
    for c in ("Reporting starts", "Reporting ends"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
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
                "Excel file (.xlsx) — must contain: Annonceur, Campaign name, "
                "Reach, Impressions, Clicks (all), Post engagements, ThruPlays, CTR (all)",
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
                    except Exception as exc:
                        st.session_state[flash_key] = ("err", f"Upload failed: {exc}")
                st.rerun()

    active = _active_paid_meta()
    if active is None:
        st.info("No Paid Media file uploaded yet. Use the panel above to add one.")
        return

    df = load_paid_df(active["path"], active["uploaded_at"])
    if df.empty:
        st.warning("File could not be loaded or is empty.")
        return

    st.divider()

    # ── Filters: Annonceur + Year + Month ─────────────────────────────────
    # Find the Annonceur column case-insensitively, ignoring extra spaces.
    ann_col = next(
        (c for c in df.columns if str(c).strip().lower() == "annonceur"),
        None,
    )
    if ann_col is None:
        annonceurs: list[str] = []
        st.info(
            "ℹ️ The uploaded Excel does not contain an `Annonceur` column. "
            "Showing all rows. Re-upload an Excel with an `Annonceur` column "
            "to enable that filter."
        )
    else:
        annonceurs = sorted({
            str(a).strip()
            for a in df[ann_col].dropna().tolist()
            if str(a).strip()
        })

    year_s, month_s = _derive_year_month(df)
    years = sorted({int(y) for y in year_s.dropna().tolist()})
    months = sorted({int(m) for m in month_s.dropna().tolist() if 1 <= int(m) <= 12})

    # Default Annonceur = top one by Impressions (so the dashboard always lands
    # on a meaningful single advertiser; user can switch).
    default_annonceur: str | None = None
    if annonceurs and ann_col is not None:
        try:
            if "Impressions" in df.columns:
                top_series = (df.assign(_a=df[ann_col].astype("string").str.strip())
                              .dropna(subset=["_a"])
                              .groupby("_a")["Impressions"].sum()
                              .sort_values(ascending=False))
                if not top_series.empty:
                    default_annonceur = str(top_series.index[0])
        except Exception:
            default_annonceur = None
        if default_annonceur is None:
            default_annonceur = annonceurs[0]

    fa, fy, fm = st.columns([2, 1, 1])
    with fa:
        if annonceurs:
            sel_idx = (annonceurs.index(default_annonceur)
                       if default_annonceur in annonceurs else 0)
            sel_a_value = st.selectbox(
                "Annonceur",
                options=annonceurs,
                index=sel_idx,
                key="paid_annonceur_filter",
            )
        else:
            st.selectbox(
                "Annonceur",
                options=["— column not in file —"],
                index=0,
                key="paid_annonceur_filter",
                disabled=True,
            )
            sel_a_value = None
    with fy:
        sel_y = st.multiselect(
            "Year", options=years, default=[],
            placeholder=("All years" if years else "—"),
            key="paid_year_filter",
            disabled=not years,
        )
    with fm:
        month_labels = {m: _MONTH_NAMES[m - 1] for m in months}
        sel_m = st.multiselect(
            "Month", options=months, default=[],
            format_func=lambda m: month_labels.get(m, str(m)),
            placeholder=("All months" if months else "—"),
            key="paid_month_filter",
            disabled=not months,
        )

    fdf = df.copy()
    # If the source column had a different case/spacing, expose it as "Annonceur"
    # so the downstream charts and insights keep working unchanged.
    if ann_col is not None and ann_col != "Annonceur":
        fdf["Annonceur"] = fdf[ann_col]
    if sel_a_value and ann_col is not None:
        fdf = fdf[fdf[ann_col].astype("string").str.strip() == sel_a_value]
    if sel_y:
        fdf = fdf[year_s.loc[fdf.index].isin(sel_y)]
    if sel_m:
        fdf = fdf[month_s.loc[fdf.index].isin(sel_m)]

    if fdf.empty:
        st.warning("No rows match the current selection.")
        return

    # ── KPIs ──────────────────────────────────────────────────────────────
    def _kpi(label: str, value: str) -> str:
        return (f'<div class="kpi"><div class="label">{label}</div>'
                f'<div class="value">{value}</div></div>')

    impr      = fdf["Impressions"].sum() if "Impressions" in fdf else 0
    reach     = fdf["Reach"].sum() if "Reach" in fdf else 0
    clicks    = fdf["Clicks (all)"].sum() if "Clicks (all)" in fdf else 0
    engage    = fdf["Post engagements"].sum() if "Post engagements" in fdf else 0
    thruplays = fdf["ThruPlays"].sum() if "ThruPlays" in fdf else 0
    avg_ctr   = fdf["CTR (all)"].mean() * 100 if "CTR (all)" in fdf and fdf["CTR (all)"].notna().any() else 0
    fb_likes  = fdf["Facebook likes"].sum() if "Facebook likes" in fdf else 0
    ig_visits = fdf["Instagram profile visits"].sum() if "Instagram profile visits" in fdf else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(_kpi("Impressions",      _fmt_int(impr)),      unsafe_allow_html=True)
    k2.markdown(_kpi("Reach",            _fmt_int(reach)),     unsafe_allow_html=True)
    k3.markdown(_kpi("Clicks",           _fmt_int(clicks)),    unsafe_allow_html=True)
    k4.markdown(_kpi("Post Engagements", _fmt_int(engage)),    unsafe_allow_html=True)

    k5, k6, k7, k8 = st.columns(4)
    k5.markdown(_kpi("ThruPlays",     _fmt_int(thruplays)),        unsafe_allow_html=True)
    k6.markdown(_kpi("Avg CTR",       f"{avg_ctr:.2f}%"),          unsafe_allow_html=True)
    k7.markdown(_kpi("Facebook Likes", _fmt_int(fb_likes)),        unsafe_allow_html=True)
    k8.markdown(_kpi("IG Profile Visits", _fmt_int(ig_visits)),    unsafe_allow_html=True)

    st.write("")

    # ── Total Budget by Annonceur (donut) + Investment rate per Objective (bar)
    c1, c2 = st.columns(2)

    ANNONCEUR_COLORS = ["#B6A0F2", "#F0A6C9", "#7AA8F2", "#86E4C0", "#FBC78A", "#7DD3DC"]
    OBJECTIVE_COLORS = ["#B6A0F2", "#F0A6C9", "#7AA8F2", "#86E4C0", "#FBC78A",
                        "#7DD3DC", "#FFA8A8", "#C4B5FD"]

    with c1:
        st.markdown("#### 💰 Total budget by annonceur")
        if "Annonceur" not in fdf.columns or "Budget" not in fdf.columns:
            st.caption("Columns `Annonceur` and `Budget` are required.")
        else:
            by_ann = (fdf.groupby("Annonceur", dropna=True)["Budget"].sum()
                      .reset_index().sort_values("Budget", ascending=False))
            by_ann = by_ann[by_ann["Budget"] > 0]
            if by_ann.empty:
                st.caption("No budget data.")
            else:
                color_map = {a: ANNONCEUR_COLORS[i % len(ANNONCEUR_COLORS)]
                             for i, a in enumerate(by_ann["Annonceur"])}
                total_budget = by_ann["Budget"].sum()
                fig = px.pie(
                    by_ann, names="Annonceur", values="Budget", hole=0.62,
                    color="Annonceur", color_discrete_map=color_map,
                )
                fig.update_traces(
                    textposition="outside", textinfo="label+percent",
                    textfont=dict(color="#F5F3FF", size=13),
                    marker=dict(line=dict(color="#0E0B1F", width=3)),
                    pull=[0.02] * len(by_ann),
                    hovertemplate="<b>%{label}</b><br>%{value:,.2f} DT<br>%{percent}<extra></extra>",
                )
                fig.update_layout(
                    height=420,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                    showlegend=True,
                    legend=dict(orientation="h", y=-0.08, x=0.5, xanchor="center"),
                    margin=dict(t=10, b=20, l=10, r=10),
                    annotations=[dict(
                        text=f"<b>{total_budget:,.0f} DT</b><br>"
                             f"<span style='font-size:11px;color:#C4B5FD'>total budget</span>",
                        x=0.5, y=0.5, font=dict(size=18, color="#F5F3FF"),
                        showarrow=False,
                    )],
                    hoverlabel=dict(bgcolor="#1A1330", bordercolor="#A78BFA",
                                   font=dict(color="#F5F3FF")),
                )
                st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("#### 🎯 Investment rate per objective")
        st.caption("Share of each annonceur's budget allocated to each objective.")
        if not {"Annonceur", "Objective", "Budget"}.issubset(fdf.columns):
            st.caption("Columns `Annonceur`, `Objective` and `Budget` are required.")
        else:
            inv = (fdf.dropna(subset=["Objective"])
                   .groupby(["Annonceur", "Objective"], dropna=True)["Budget"]
                   .sum().reset_index())
            inv = inv[inv["Budget"] > 0]
            if inv.empty:
                st.caption("No budget data per objective.")
            else:
                totals = inv.groupby("Annonceur")["Budget"].transform("sum")
                inv["Rate"] = inv["Budget"] / totals * 100
                objectives = sorted(inv["Objective"].unique())
                obj_colors = {o: OBJECTIVE_COLORS[i % len(OBJECTIVE_COLORS)]
                              for i, o in enumerate(objectives)}
                fig = px.bar(
                    inv, x="Annonceur", y="Rate", color="Objective",
                    barmode="group",
                    color_discrete_map=obj_colors,
                    text="Rate",
                    custom_data=["Budget"],
                )
                fig.update_traces(
                    texttemplate="%{text:.1f}%", textposition="outside",
                    marker=dict(line=dict(width=0), cornerradius=8),
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Objective : %{fullData.name}<br>"
                        "Share : %{y:.1f}%<br>"
                        "Budget : %{customdata[0]:,.2f} DT"
                        "<extra></extra>"
                    ),
                )
                fig.update_layout(
                    height=420,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                    xaxis=dict(title="", gridcolor="rgba(167,139,250,0.12)"),
                    yaxis=dict(title="Investment rate (%)",
                               gridcolor="rgba(167,139,250,0.12)",
                               ticksuffix="%"),
                    legend=dict(orientation="h", y=-0.18, x=0.5, xanchor="center",
                                title=""),
                    bargap=0.2, bargroupgap=0.08,
                    margin=dict(t=20, b=20, l=10, r=10),
                    hoverlabel=dict(bgcolor="#1A1330", bordercolor="#A78BFA",
                                    font=dict(color="#F5F3FF")),
                )
                st.plotly_chart(fig, use_container_width=True)

    # ── Top campaigns by selected metric ─────────────────────────────────
    st.markdown("#### 🏆 Campaigns overview")
    if "Campaign name" not in fdf.columns:
        st.caption("Column `Campaign name` is missing.")
    else:
        # Map of friendly metric label -> source column in fdf
        METRIC_OPTIONS = {
            "Impressions":         "Impressions",
            "Reach":               "Reach",
            "Clicks":              "Clicks (all)",
            "Post engagements":    "Post engagements",
            "ThruPlays":           "ThruPlays",
            "Facebook likes":      "Facebook likes",
            "IG profile visits":   "Instagram profile visits",
            "Avg CTR (%)":         "CTR (all)",
        }
        available = {lbl: col for lbl, col in METRIC_OPTIONS.items() if col in fdf.columns}
        if not available:
            st.caption("No metric columns available.")
            return

        col_a, col_b = st.columns([2, 1])
        with col_a:
            sel_metric = st.selectbox(
                "Rank campaigns by",
                options=list(available.keys()),
                index=0,
                key="paid_campaigns_metric",
            )
        with col_b:
            top_n = st.slider("Top N", min_value=5, max_value=25, value=12, step=1,
                              key="paid_campaigns_topn")

        metric_col = available[sel_metric]
        is_ctr = sel_metric == "Avg CTR (%)"
        agg_func = "mean" if is_ctr else "sum"

        agg_cols = {
            "Impressions": ("Impressions", "sum"),
            "Reach":       ("Reach", "sum"),
            "Clicks":      ("Clicks (all)", "sum"),
            "Engagements": ("Post engagements", "sum"),
        }
        agg_cols = {k: v for k, v in agg_cols.items() if v[0] in fdf.columns}
        agg_cols["_metric"] = (metric_col, agg_func)

        agg = (fdf.groupby("Campaign name", dropna=True)
               .agg(**agg_cols)
               .reset_index()
               .sort_values("_metric", ascending=False)
               .head(top_n)
               .sort_values("_metric", ascending=True))

        if is_ctr:
            agg["_metric"] = agg["_metric"] * 100  # to %

        if agg.empty:
            st.caption("No campaigns to display.")
        else:
            agg["short"] = agg["Campaign name"].apply(
                lambda s: (s[:60] + "…") if len(str(s)) > 60 else s
            )
            for _c in ("Reach", "Clicks", "Engagements", "Impressions"):
                if _c not in agg.columns:
                    agg[_c] = 0
            seen: dict = {}
            uniq = []
            for s in agg["short"]:
                if s in seen:
                    seen[s] += 1
                    uniq.append(f"{s} ({seen[s]})")
                else:
                    seen[s] = 0
                    uniq.append(s)
            agg["short"] = uniq

            value_fmt = ".2f" if is_ctr else ",.0f"
            tick_fmt = ".2f" if is_ctr else ",.0f"
            x_title = sel_metric

            fig = px.bar(
                agg, x="_metric", y="short", orientation="h",
                color="_metric",
                color_continuous_scale=["#6366F1", "#A78BFA", "#F0A6C9"],
                custom_data=["Impressions", "Reach", "Clicks", "Engagements"],
            )
            fig.update_traces(
                marker=dict(line=dict(width=0), cornerradius=10),
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    f"{sel_metric} : %{{x:{value_fmt}}}"
                    + ("%" if is_ctr else "") + "<br>"
                    "Impressions : %{customdata[0]:,.0f}<br>"
                    "Reach : %{customdata[1]:,.0f}<br>"
                    "Clicks : %{customdata[2]:,.0f}<br>"
                    "Engagements : %{customdata[3]:,.0f}"
                    "<extra></extra>"
                ),
            )
            fig.update_layout(
                height=max(460, 42 * len(agg)),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#F5F3FF", family="Inter, sans-serif"),
                xaxis=dict(gridcolor="rgba(167,139,250,0.12)",
                           title=x_title, tickformat=tick_fmt),
                yaxis=dict(title="", tickfont=dict(size=11)),
                coloraxis_showscale=False,
                bargap=0.22,
                margin=dict(t=10, b=10, l=10, r=20),
                hoverlabel=dict(bgcolor="#1A1330", bordercolor="#A78BFA",
                                font=dict(color="#F5F3FF")),
            )
            st.plotly_chart(fig, use_container_width=True)

    # ── Key insights ─────────────────────────────────────────────────────
    insights: list[dict] = []
    try:
        if "Annonceur" in fdf.columns and "Impressions" in fdf.columns and impr > 0:
            by_a = fdf.groupby("Annonceur")["Impressions"].sum().sort_values(ascending=False)
            share = by_a.iloc[0] / by_a.sum() * 100
            insights.append({
                "icon": "👑", "label": "Top annonceur",
                "value": str(by_a.index[0]),
                "sub": f"{share:.1f}% of impressions ({_fmt_int(by_a.iloc[0])})",
            })
        if "Campaign name" in fdf.columns and "Impressions" in fdf.columns and impr > 0:
            by_c = fdf.groupby("Campaign name")["Impressions"].sum().sort_values(ascending=False)
            top_name = str(by_c.index[0])
            short = (top_name[:38] + "…") if len(top_name) > 38 else top_name
            insights.append({
                "icon": "🚀", "label": "Best campaign (impressions)",
                "value": short,
                "sub": f"{_fmt_int(by_c.iloc[0])} impressions",
            })
        if "Campaign name" in fdf.columns and "CTR (all)" in fdf.columns:
            ctr_by_c = (fdf.groupby("Campaign name")["CTR (all)"].mean()
                        .dropna().sort_values(ascending=False))
            if not ctr_by_c.empty and ctr_by_c.iloc[0] > 0:
                top_name = str(ctr_by_c.index[0])
                short = (top_name[:38] + "…") if len(top_name) > 38 else top_name
                insights.append({
                    "icon": "🎯", "label": "Best CTR campaign",
                    "value": f"{ctr_by_c.iloc[0]*100:.2f}%",
                    "sub": short,
                })
        if reach > 0 and impr > 0:
            freq = impr / reach
            insights.append({
                "icon": "🔁", "label": "Avg frequency",
                "value": f"{freq:.2f}×",
                "sub": f"{_fmt_int(impr)} impr. / {_fmt_int(reach)} reach",
            })
    except Exception:
        pass
    if insights:
        _render_insight_cards("✨ Key insights", insights)

    st.caption(
        f"Source: `{Path(active['path']).name}` — "
        f"{len(df):,} rows • last upload {active['uploaded_at']}"
    )


def render_section(section: str) -> None:
    icon = SECTION_ICONS.get(section, "📁")
    st.markdown(f"## {icon} {section}")

    campaign_options: list[str] | None = None  # None → free text

    if section == "Media":
        render_media()
        # Media keeps the free-text campaign field (per request)
    elif section == "Paid":
        render_paid()
        # Build dropdown from "Campaign name" column of the active Paid Excel
        try:
            active = _active_paid_meta()
            if active is not None:
                pdf_ = load_paid_df(active["path"], active["uploaded_at"])
                if "Campaign name" in pdf_.columns:
                    campaign_options = sorted({
                        str(c).strip()
                        for c in pdf_["Campaign name"].dropna().tolist()
                        if str(c).strip()
                    })
        except Exception:
            campaign_options = None
    else:
        upload_panel(section)
        st.divider()
        rows = load_index()
        render_calendar(section, rows)
        # PDF-calendar sections: dropdown of distinct event names uploaded
        try:
            campaign_options = sorted({
                str(r.get("event_name", "")).strip()
                for r in rows
                if r.get("section") == section and str(r.get("event_name", "")).strip()
            })
            if not campaign_options:
                campaign_options = None
        except Exception:
            campaign_options = None

    # Notes block — available in every section
    st.divider()
    render_notes_panel(section, campaign_options=campaign_options)


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
