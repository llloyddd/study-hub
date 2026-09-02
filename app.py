import hashlib
import html
import os
import re
import sqlite3
from datetime import date

import streamlit as st
import streamlit.components.v1 as components
from streamlit_quill import st_quill

DB_PATH = "notes.db"

DEFAULT_SUBJECTS = [
    "Physics",
    "Pre-Col. Algebra",
    "General Biology",
    "Practical Research",
    "Entrepreneurship",
    "FilAkad",
    "Media & Information Literacy",
]

# Keyword hints used to infer a subject from an imported document.
SUBJECT_KEYWORDS = {
    "Physics": [
        "physics", "velocity", "acceleration", "force", "newton", "momentum",
        "energy", "kinetic", "friction", "gravity", "wave", "voltage", "current",
        "quantum", "thermodynamics", "electron",
    ],
    "Pre-Col. Algebra": [
        "algebra", "polynomial", "equation", "quadratic", "function", "exponent",
        "logarithm", "inequality", "factor", "slope", "linear", "coefficient",
        "variable", "graph", "domain", "range",
    ],
    "General Biology": [
        "biology", "cell", "organism", "photosynthesis", "dna", "rna", "evolution",
        "ecosystem", "mitosis", "meiosis", "protein", "enzyme", "membrane",
        "chromosome", "bacteria", "species", "tissue",
    ],
    "Practical Research": [
        "research", "hypothesis", "methodology", "qualitative", "quantitative",
        "sampling", "respondents", "questionnaire", "literature review", "data",
        "variable", "significance of the study", "scope and delimitation",
    ],
    "Entrepreneurship": [
        "entrepreneur", "business", "market", "customer", "profit", "revenue",
        "startup", "product", "marketing", "supply", "demand", "capital",
        "value proposition", "business plan", "cash flow",
    ],
    "FilAkad": [
        "filipino", "akademiko", "sanaysay", "wika", "pananaliksik", "lipunan",
        "kultura", "panitikan", "diskurso", "sulatin", "pahayag", "talata",
    ],
    "Media & Information Literacy": [
        "media", "information", "literacy", "misinformation", "disinformation",
        "propaganda", "digital", "copyright", "netizen", "fake news", "source",
        "bias", "audience", "platform",
    ],
}

HIGHLIGHT_COLORS = ["#fff29c", "#a5d8ff", "#ffc9c9", "#b2f2bb", "#ffd8a8", False]

QUILL_TOOLBAR = [
    ["bold", "italic", "underline", "strike"],
    [{"background": HIGHLIGHT_COLORS}],
    [{"header": [1, 2, 3, False]}],
    [{"list": "bullet"}, {"list": "ordered"}],
    ["clean"],
]

# Height (px) of the scrollable notebook area.
SCROLLER_H = 540


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                date_created TEXT NOT NULL
            )
            """
        )


def add_note(subject, title, content, date_created=None):
    date_created = date_created or date.today().isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO notes (subject, title, content, date_created) VALUES (?, ?, ?, ?)",
            (subject.strip(), title.strip(), content, str(date_created)),
        )


def get_subjects():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT subject FROM notes ORDER BY subject COLLATE NOCASE"
        ).fetchall()
    return [row["subject"] for row in rows]


def get_notes(subject=None):
    query = "SELECT id, subject, title, content, date_created FROM notes"
    params = ()
    if subject:
        query += " WHERE subject = ?"
        params = (subject,)
    query += " ORDER BY date_created DESC, id DESC"
    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def subject_list():
    """Default subjects first, then any additional subjects found in the DB."""
    subjects = list(DEFAULT_SUBJECTS)
    for subject in get_subjects():
        if subject not in subjects:
            subjects.append(subject)
    return subjects


def wrap_content(content_html, size_px):
    """Persist the chosen text size by wrapping the note body."""
    return f'<div style="font-size:{int(size_px)}px; line-height:1.5">{content_html}</div>'


# --------------------------------------------------------------------------- #
# Document import
# --------------------------------------------------------------------------- #
def extract_text(uploaded_file):
    name = uploaded_file.name.lower()
    data = uploaded_file.getvalue()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if name.endswith(".docx"):
        import docx
        import io

        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    raise ValueError("Unsupported file type. Upload a .pdf or .docx file.")


def infer_subject(text):
    lowered = text.lower()
    scores = {
        subject: sum(lowered.count(word) for word in words)
        for subject, words in SUBJECT_KEYWORDS.items()
    }
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return DEFAULT_SUBJECTS[0]
    return best


def infer_title(text, filename):
    for line in text.splitlines():
        line = line.strip()
        if 3 <= len(line) <= 90 and not line.endswith("."):
            return line
    return os.path.splitext(os.path.basename(filename))[0]


BULLET_RE = re.compile(r"^\s*([-*•‣◦·▪]|\d+[.)])\s+(.*)")


def extract_bullets(text):
    bullets = []
    for line in text.splitlines():
        match = BULLET_RE.match(line)
        if match and match.group(2).strip():
            bullets.append(match.group(2).strip())

    if not bullets:
        joined = " ".join(l.strip() for l in text.splitlines() if l.strip())
        sentences = re.split(r"(?<=[.!?])\s+", joined)
        bullets = [s.strip() for s in sentences if len(s.strip()) > 30][:8]

    return bullets[:15]


def bullets_to_html(bullets):
    if not bullets:
        return "<p><em>No key points could be extracted.</em></p>"
    items = "".join(f"<li>{html.escape(b)}</li>" for b in bullets)
    return f"<ul>{items}</ul>"


# --------------------------------------------------------------------------- #
# Notebook view (custom component: centred title + collapsible subject folders)
# --------------------------------------------------------------------------- #
NOTEBOOK_TEMPLATE = """
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: transparent; }
  body {
    color: #1f1f1f;
    font-family: "Source Sans Pro", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  @media (prefers-color-scheme: dark) { body { color: #e9e9e9; } }

  #scroller {
    height: __H__px;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 4px 6px 0;
    scroll-behavior: smooth;
  }
  #folders { padding-bottom: 220px; }

  #brand {
    text-align: center;
    padding: 20px 12px 28px;
    background: transparent;      /* no solid fill */
    box-shadow: none;             /* no shadow */
    transition: opacity .2s linear, transform .2s linear;
    will-change: opacity, transform;
  }
  #brand h1 {
    margin: 0;
    font-size: 1.9rem;
    font-weight: 700;
    line-height: 1.15;
  }
  #brand .est {
    margin: 8px 0 0;
    font-size: .95rem;            /* half of the 1.9rem title */
    font-style: italic;
    opacity: .6;
  }

  .folder {
    margin: 0 4px 10px;
    border: 1px solid rgba(128, 128, 128, .3);
    border-radius: 10px;
    background: rgba(128, 128, 128, .05);
    overflow: hidden;
  }
  .folder-header {
    width: 100%;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 13px 15px;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    font-weight: 600;
    text-align: left;
    cursor: pointer;
  }
  .folder-header:hover { background: rgba(128, 128, 128, .12); }
  .chev {
    font-size: .8rem;
    opacity: .65;
    transition: transform .3s ease;
  }
  .folder.open .chev { transform: rotate(90deg); }
  .folder-name { flex: 1; }
  .folder-count {
    font-size: .75rem;
    font-weight: 500;
    opacity: .5;
    white-space: nowrap;
  }

  .folder-body {
    display: grid;
    grid-template-rows: 0fr;
    transition: grid-template-rows .35s ease;
  }
  .folder.open .folder-body { grid-template-rows: 1fr; }
  .folder-body > .inner { overflow: hidden; }
  .folder.open .folder-body > .inner { padding: 2px 15px 14px; }

  .note { border-top: 1px solid rgba(128, 128, 128, .22); padding: 12px 2px; }
  .note:first-child { border-top: 0; }
  .note-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 6px;
  }
  .note-title { font-weight: 600; }
  .note-date { font-size: .74rem; opacity: .5; white-space: nowrap; }
  .note-body :is(h1, h2, h3) { margin: .5em 0 .25em; }
  .note-body p { margin: .35em 0; }
  .empty { margin: 8px 2px; opacity: .55; font-style: italic; }

  #scroller::-webkit-scrollbar { width: 10px; }
  #scroller::-webkit-scrollbar-track { background: transparent; }
  #scroller::-webkit-scrollbar-thumb {
    background: rgba(128, 128, 128, .4);
    border-radius: 6px;
  }
</style>

<div id="scroller">
  <header id="brand">
    <h1>Notes from St. Pedro Calungsod</h1>
    <p class="est">est. 2026 | You can't handle our swag</p>
  </header>
  <div id="folders">
    <!--FOLDERS-->
  </div>
</div>

<script>
  (function () {
    var scroller = document.getElementById('scroller');
    var brand = document.getElementById('brand');

    // Accordion: only one folder open at a time; clicking the open folder
    // (or a different one) closes the previous one.
    document.querySelectorAll('.folder-header').forEach(function (header) {
      header.addEventListener('click', function () {
        var folder = header.parentElement;
        var wasOpen = folder.classList.contains('open');
        document.querySelectorAll('.folder.open').forEach(function (f) {
          f.classList.remove('open');
        });
        if (!wasOpen) {
          folder.classList.add('open');
          folder.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      });
    });

    // Fade the title away once the subject list is scrolled far enough.
    var FADE_START = 20, FADE_END = 120;
    function onScroll() {
      var y = scroller.scrollTop;
      var t = (y - FADE_START) / (FADE_END - FADE_START);
      t = Math.min(1, Math.max(0, t));
      brand.style.opacity = String(1 - t);
      brand.style.transform = 'translateY(' + (-t * 14) + 'px)';
      brand.style.pointerEvents = t > 0.85 ? 'none' : 'auto';
    }
    scroller.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
  })();
</script>
"""

# Rotating quotes shown in the floating footer.
FOOTER_QUOTES = [
    ("To live without hope is to cease to live.", "Fyodor Dostoevsky"),
    ("I came, I saw, I conquered.", "Julius Caesar"),
    (
        "It's not what happens to you, but how you react to it that matters.",
        "Epictetus",
    ),
]


def _footer_html():
    spans = "".join(
        "<span>&ldquo;" + html.escape(quote) + "&rdquo; &mdash; "
        + html.escape(author) + "</span>"
        for quote, author in FOOTER_QUOTES
    )
    return '<div class="spc-footer"><div class="spc-quotes">' + spans + "</div></div>"


PAGE_CHROME = (
    """
<style>
  /* (1) Transparent top header: no solid fill, no shadow. */
  [data-testid="stHeader"],
  header.stAppHeader,
  [data-testid="stToolbar"] {
    background: transparent !important;
    box-shadow: none !important;
    border-bottom: none !important;
  }

  /* Keep the "new note" button compact, but swap its label on hover. */
  div.st-key-add_note_btn button p { font-size: 0; }
  div.st-key-add_note_btn button p::after {
    content: "\\2795";                 /* heavy plus sign */
    font-size: 1.05rem;
    line-height: 1.5;
  }
  div.st-key-add_note_btn button:hover p::after {
    content: "Create a New Note";
    font-size: .92rem;
    font-weight: 600;
  }
  div.st-key-add_note_btn button {
    white-space: nowrap;
    transition: color .15s ease, background-color .15s ease, border-color .15s ease;
  }

  /* (3) Sticky floating footer with small, mobile-friendly rotating quotes. */
  [data-testid="stMainBlockContainer"],
  [data-testid="stAppViewContainer"] .block-container {
    padding-bottom: 4.5rem;
  }
  .spc-footer {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1000;
    display: flex;
    justify-content: center;
    padding: 7px 14px;
    background: transparent;
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
    pointer-events: none;
  }
  .spc-quotes {
    position: relative;
    width: 100%;
    max-width: 760px;
    min-height: 2.6em;
    text-align: center;
    pointer-events: auto;
  }
  .spc-quotes span {
    position: absolute;
    left: 0;
    right: 0;
    margin: 0 auto;
    padding: 0 6px;
    font-size: .72rem;
    line-height: 1.35;
    opacity: 0;
    animation: spcQuote 21s infinite;
  }
  .spc-quotes span:nth-child(2) { animation-delay: 7s; }
  .spc-quotes span:nth-child(3) { animation-delay: 14s; }
  @keyframes spcQuote {
    0%, 1%    { opacity: 0; transform: translateY(5px); }
    4%, 29%   { opacity: .7; transform: translateY(0); }
    33%, 100% { opacity: 0; transform: translateY(-5px); }
  }
  @media (max-width: 640px) {
    .spc-quotes span { font-size: .66rem; }
  }
  @media (prefers-reduced-motion: reduce) {
    .spc-quotes span { animation-duration: 21s; }
  }
</style>
"""
    + _footer_html()
)


def _note_html(row):
    return (
        '<article class="note"><div class="note-head">'
        '<span class="note-title">' + html.escape(row["title"]) + "</span>"
        '<span class="note-date">' + html.escape(str(row["date_created"])) + "</span>"
        "</div>"
        '<div class="note-body">' + row["content"] + "</div>"
        "</article>"
    )


def _folders_html(subjects, open_subject):
    blocks = []
    for subject in subjects:
        notes = get_notes(subject)
        if notes:
            count = f"{len(notes)} note" + ("s" if len(notes) != 1 else "")
            inner = "".join(_note_html(row) for row in notes)
        else:
            count = "empty"
            inner = (
                '<p class="empty">No notes yet &mdash; press the &#65291; button '
                "above to add one.</p>"
            )
        open_cls = " open" if open_subject and subject == open_subject else ""
        blocks.append(
            '<section class="folder' + open_cls + '" data-subject="'
            + html.escape(subject, quote=True) + '">'
            '<button class="folder-header" type="button">'
            '<span class="chev">&#9656;</span>'
            '<span class="folder-name">' + html.escape(subject) + "</span>"
            '<span class="folder-count">' + count + "</span>"
            "</button>"
            '<div class="folder-body"><div class="inner">' + inner + "</div></div>"
            "</section>"
        )
    return "\n".join(blocks)


def render_notebook(subjects, open_subject):
    doc = NOTEBOOK_TEMPLATE.replace("__H__", str(SCROLLER_H)).replace(
        "<!--FOLDERS-->", _folders_html(subjects, open_subject)
    )
    components.html(doc, height=SCROLLER_H + 8, scrolling=False)


# --------------------------------------------------------------------------- #
# Dialog
# --------------------------------------------------------------------------- #
@st.dialog("New note", width="large")
def new_note_dialog(subjects):
    tab_write, tab_import = st.tabs(["✍️ Write", "📄 Import PDF / DOCX"])

    with tab_write:
        subject = st.selectbox("Subject", subjects, accept_new_options=True, key="nn_subject")
        title = st.text_input("Title", key="nn_title")

        size_px = st.slider("Text size", min_value=4, max_value=36, value=14, key="nn_size")
        st.caption("Select text in the editor, then use the toolbar to **bold**, *italic*, or highlight it.")
        content_html = st_quill(
            placeholder="Write your note here...",
            html=True,
            toolbar=QUILL_TOOLBAR,
            key="nn_content",
        )

        if st.button("Save", type="primary", key="nn_save"):
            plain = re.sub(r"<[^>]+>", "", content_html or "").strip()
            if subject and subject.strip() and title.strip() and plain:
                add_note(subject, title, wrap_content(content_html, size_px))
                st.session_state.selected_subject = subject.strip()
                st.rerun()
            else:
                st.error("Subject, title, and content are all required.")

    with tab_import:
        st.write(
            "Upload a **.pdf** or **.docx** file. Its text is extracted, a subject "
            "and title are inferred, key points are pulled into the note body, and "
            "the note is saved automatically."
        )
        uploaded = st.file_uploader(
            "Document", type=["pdf", "docx"], key="nn_upload", label_visibility="collapsed"
        )

        if uploaded is not None:
            file_hash = hashlib.md5(uploaded.getvalue()).hexdigest()
            if st.session_state.get("nn_imported_hash") == file_hash:
                st.success("This document has already been imported.")
                return

            try:
                text = extract_text(uploaded)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read the file: {exc}")
                return

            if not text.strip():
                st.error("No readable text was found in this document.")
                return

            subject = infer_subject(text)
            title = infer_title(text, uploaded.name)
            bullets = extract_bullets(text)
            body = wrap_content(bullets_to_html(bullets), 14)

            add_note(subject, title, body)
            st.session_state.nn_imported_hash = file_hash
            st.session_state.selected_subject = subject

            st.success(f"Imported and saved to **{subject}** as “{title}”.")
            st.markdown("**Key points:**")
            st.markdown(bullets_to_html(bullets), unsafe_allow_html=True)
            if st.button("Done", type="primary", key="nn_import_done"):
                st.rerun()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    st.set_page_config(page_title="Notes from St. Pedro Calungsod", page_icon="📝")
    init_db()

    st.markdown(PAGE_CHROME, unsafe_allow_html=True)

    subjects = subject_list()

    if "selected_subject" not in st.session_state:
        st.session_state.selected_subject = None

    left = st.columns([1, 3])[0]
    if left.button(
        "➕",
        key="add_note_btn",
        help="Create a New Note",
        use_container_width=True,
    ):
        new_note_dialog(subjects)

    render_notebook(subjects, st.session_state.selected_subject)


if __name__ == "__main__":
    main()
