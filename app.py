import hashlib
import html
import os
import re
import sqlite3
from datetime import date

import streamlit as st
from streamlit_quill import st_quill

DB_PATH = "notes.db"

DEFAULT_SUBJECTS = ["Physics", "Pre-Col. Algebra", "General Biology"]

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
}

HIGHLIGHT_COLORS = ["#fff29c", "#a5d8ff", "#ffc9c9", "#b2f2bb", "#ffd8a8", False]

QUILL_TOOLBAR = [
    ["bold", "italic", "underline", "strike"],
    [{"background": HIGHLIGHT_COLORS}],
    [{"header": [1, 2, 3, False]}],
    [{"list": "bullet"}, {"list": "ordered"}],
    ["clean"],
]


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
    st.set_page_config(page_title="Study Hub Notes", page_icon="📝")
    init_db()

    st.title("📝 Study Hub Notes")

    subjects = subject_list()

    if "selected_subject" not in st.session_state:
        st.session_state.selected_subject = subjects[0]

    cols = st.columns(len(subjects) + 1)

    if cols[0].button("➕", key="add_note_btn", use_container_width=True):
        new_note_dialog(subjects)

    for col, subject in zip(cols[1:], subjects):
        is_active = st.session_state.selected_subject == subject
        if col.button(
            subject,
            key=f"subject_btn_{subject}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state.selected_subject = subject
            st.rerun()

    selected_subject = st.session_state.selected_subject
    st.subheader(selected_subject)

    notes = get_notes(selected_subject)

    if not notes:
        st.info(f"No notes for {selected_subject} yet. Press ➕ to add one.")
        return

    st.caption(f"{len(notes)} note(s)")
    for note in notes:
        with st.expander(f"{note['title']}  —  {note['date_created']}"):
            st.markdown(note["content"], unsafe_allow_html=True)


if __name__ == "__main__":
    main()
