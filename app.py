"""3SG Group — Dashboard de pilotage.

Five sections (Media, Social, Influence, ATL, BTL). Each section accepts PDF
event-report uploads (with event date, name, brand) and displays a 12-month
calendar grid for the selected year. Clicking a month reveals every report
filed in that month.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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

SECTIONS = ["Media", "Social", "Influence", "ATL", "BTL"]
SECTION_ICONS = {
    "Media": "📺",
    "Social": "💬",
    "Influence": "✨",
    "ATL": "📡",
    "BTL": "🎪",
}
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

st.set_page_config(
    page_title="3SG Group — Dashboard de pilotage",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
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
# Storage helpers
# ---------------------------------------------------------------------------
def load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        return []
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_index(rows: list[dict]) -> None:
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
    section_dir = REPORTS_DIR / section
    section_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{event_date.isoformat()}_{slugify(event_name)}"
    suffix = Path(original_name).suffix.lower() or ".pdf"
    target = section_dir / f"{stem}{suffix}"
    # Avoid overwriting
    n = 1
    while target.exists():
        n += 1
        target = section_dir / f"{stem}-{n}{suffix}"
    target.write_bytes(file_bytes)

    row = {
        "section": section,
        "event_date": event_date.isoformat(),
        "event_name": event_name.strip(),
        "brand": brand.strip(),
        "filename": target.name,
        "path": str(target.relative_to(APP_DIR)).replace("\\", "/"),
        "original_name": original_name,
        "size_kb": round(len(file_bytes) / 1024, 1),
        "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    rows = load_index()
    rows.append(row)
    save_index(rows)
    return row


def delete_report(row: dict) -> None:
    p = APP_DIR / row["path"]
    try:
        if p.exists():
            p.unlink()
    except OSError:
        pass
    rows = [r for r in load_index() if not (
        r["path"] == row["path"] and r["uploaded_at"] == row["uploaded_at"]
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
        file_path = APP_DIR / r["path"]
        # Build a URL served by Streamlit's static file server.
        # r["path"] is like "static/reports/BTL/foo.pdf"; the URL becomes
        # "app/static/reports/BTL/foo.pdf" (relative to the app root).
        rel_url = r["path"]
        if rel_url.startswith("static/"):
            href = "app/" + rel_url
        else:
            href = rel_url
        with st.container():
            c1, c2, c3 = st.columns([6, 2, 1])
            with c1:
                if file_path.exists():
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
                if file_path.exists():
                    st.download_button(
                        "⬇️ Download",
                        data=file_path.read_bytes(),
                        file_name=r["original_name"],
                        mime="application/pdf",
                        key=f"dl_{section}_{i}_{r['filename']}",
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
    "affichage":  "#FBC78A",  # soft amber
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


def _save_media_file(file_bytes: bytes, original_name: str) -> Path:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(original_name).suffix.lower() or ".xlsx"
    target = MEDIA_DIR / f"plurimedias{suffix}"
    target.write_bytes(file_bytes)
    MEDIA_MANIFEST.write_text(
        json.dumps({
            "filename": target.name,
            "original_name": original_name,
            "uploaded_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "size_kb": round(len(file_bytes) / 1024, 1),
        }, indent=2),
        encoding="utf-8",
    )
    load_media_df.clear()  # type: ignore[attr-defined]
    return target


def _active_media_file() -> Path | None:
    if not MEDIA_MANIFEST.exists():
        return None
    try:
        meta = json.loads(MEDIA_MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    p = MEDIA_DIR / meta.get("filename", "")
    return p if p.exists() else None


@st.cache_data(show_spinner=False)
def load_media_df(path_str: str, mtime: float) -> pd.DataFrame:
    df = pd.read_excel(path_str)
    # Keep only columns we use; coerce numerics
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
                            f"Plurimedia data successfully uploaded — {target.name}",
                        )
                    except Exception as exc:  # pragma: no cover
                        st.session_state[flash_key] = ("err", f"Upload failed: {exc}")
                st.rerun()

    active = _active_media_file()
    if active is None:
        st.info("No Plurimedia file uploaded yet. Use the panel above to add one.")
        return

    df = load_media_df(str(active), active.stat().st_mtime)

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
        f"Source: `{active.name}` — "
        f"{len(df):,} rows • last upload {datetime.fromtimestamp(active.stat().st_mtime):%Y-%m-%d %H:%M}"
    )


def render_section(section: str) -> None:
    icon = SECTION_ICONS.get(section, "📁")
    st.markdown(f"## {icon} {section}")
    if section == "Media":
        render_media()
        return
    upload_panel(section)
    st.divider()
    render_calendar(section, load_index())


# ---------------------------------------------------------------------------
# Header & sidebar
# ---------------------------------------------------------------------------
st.title("📊 Dashboard de pilotage — 3SG Group")
st.caption(
    "Centralised event-report archive across **Media · Social · Influence · ATL · BTL**. "
    "Upload a PDF, attach the event date, and find it later in the monthly calendar."
)

with st.sidebar:
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
    st.caption("Reports are stored locally in `./reports/<section>/`.")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tabs = st.tabs([f"{SECTION_ICONS[s]}  {s}" for s in SECTIONS])
for tab, section in zip(tabs, SECTIONS):
    with tab:
        render_section(section)
