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

import streamlit as st

# ---------------------------------------------------------------------------
# Config & paths
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).parent
REPORTS_DIR = APP_DIR / "reports"
INDEX_PATH = REPORTS_DIR / "index.json"

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
                    st.error("Please choose a PDF file first.")
                elif not ev_name.strip():
                    st.error("Please enter the event name.")
                elif not brand.strip():
                    st.error("Please enter the brand / client.")
                else:
                    row = save_report(
                        section=section,
                        event_date=ev_date,
                        event_name=ev_name,
                        brand=brand,
                        file_bytes=up.getvalue(),
                        original_name=up.name,
                    )
                    st.success(
                        f"Saved **{row['event_name']}** "
                        f"({row['event_date']}) to {section}."
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
        with st.container():
            c1, c2, c3, c4 = st.columns([4, 2, 2, 1])
            with c1:
                st.markdown(
                    f'<div class="report-card">'
                    f'<div class="r-title">{r["event_name"]}</div>'
                    f'<div class="r-meta">📅 {r["event_date"]}  •  🏷️ {r["brand"]}'
                    f'  •  📄 {r["filename"]}  •  {r["size_kb"]} KB</div>'
                    f"</div>",
                    unsafe_allow_html=True,
                )
            with c2:
                view_key = f"view_{section}_{i}_{r['filename']}"
                if st.button("👁️ Preview", key=view_key, use_container_width=True):
                    st.session_state[f"preview_{section}"] = r["path"]
            with c3:
                file_path = APP_DIR / r["path"]
                if file_path.exists():
                    st.download_button(
                        "⬇️ Download",
                        data=file_path.read_bytes(),
                        file_name=r["original_name"],
                        mime="application/pdf",
                        key=f"dl_{section}_{i}_{r['filename']}",
                        use_container_width=True,
                    )
                else:
                    st.button("⚠️ missing", disabled=True, use_container_width=True,
                              key=f"miss_{section}_{i}")
            with c4:
                if st.button("🗑️", key=f"del_{section}_{i}_{r['filename']}",
                             help="Delete this report", use_container_width=True):
                    delete_report(r)
                    st.rerun()

    # Preview pane
    preview_path = st.session_state.get(f"preview_{section}")
    if preview_path:
        st.markdown("### 📄 Preview")
        full = APP_DIR / preview_path
        if full.exists():
            pdf_preview(full)
            if st.button("Close preview", key=f"close_prev_{section}"):
                st.session_state.pop(f"preview_{section}", None)
                st.rerun()
        else:
            st.error("File not found on disk.")


def render_section(section: str) -> None:
    icon = SECTION_ICONS.get(section, "📁")
    st.markdown(f"## {icon} {section}")
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
