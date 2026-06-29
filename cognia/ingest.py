import logging
import re
from pathlib import Path
from typing import List

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rs", ".cpp", ".c", ".h", ".cs",
    ".html", ".css", ".json", ".yaml", ".yml", ".toml",
    ".sql", ".sh", ".ps1", ".bat", ".cfg", ".ini",
    ".rb", ".php", ".swift", ".kt", ".r", ".scala",
}

_MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
_CHUNK_CHARS = 600


def _chunk_text(text: str) -> List[str]:
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current_len + len(para) > _CHUNK_CHARS and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para)
    if current:
        chunks.append("\n\n".join(current))
    return [c for c in chunks if len(c.strip()) >= 40]


def _chunk_text_with_offsets(text: str):
    """Lossless variant of _chunk_text: returns (chunk_text, char_start, char_end)
    where chunk_text == text[char_start:char_end] EXACTLY, so a ContextMap
    'file' pointer re-read by offset matches byte for byte. Same grouping as
    _chunk_text, but tracked over the ORIGINAL text instead of stripped copies.
    """
    # 1) paragraph spans in the original text, tracking offsets
    para_spans = []
    pos = 0
    for sep in re.finditer(r"\n{2,}", text):
        seg = text[pos:sep.start()]
        if seg.strip():
            lead = len(seg) - len(seg.lstrip())
            trail = len(seg) - len(seg.rstrip())
            para_spans.append((pos + lead, sep.start() - trail))
        pos = sep.end()
    seg = text[pos:len(text)]
    if seg.strip():
        lead = len(seg) - len(seg.lstrip())
        trail = len(seg) - len(seg.rstrip())
        para_spans.append((pos + lead, len(text) - trail))

    # 2) group consecutive paragraphs into ~_CHUNK_CHARS chunks (as _chunk_text)
    spans = []
    group_start = None
    group_end = None
    current_len = 0
    for (s, e) in para_spans:
        plen = e - s
        if group_start is not None and current_len + plen > _CHUNK_CHARS:
            spans.append((group_start, group_end))
            group_start, group_end, current_len = s, e, plen
        else:
            if group_start is None:
                group_start = s
            group_end = e
            current_len += plen
    if group_start is not None:
        spans.append((group_start, group_end))

    # 3) raw slice per chunk; drop short ones (same threshold as _chunk_text)
    result = []
    for (s, e) in spans:
        chunk_text = text[s:e]
        if len(chunk_text.strip()) >= 40:
            result.append((chunk_text, s, e))
    return result


def _read_raw(path: Path) -> str:
    if path.stat().st_size > _MAX_FILE_BYTES:
        raise ValueError(f"Archivo demasiado grande (max {_MAX_FILE_BYTES // 1024 // 1024} MB)")
    ext = path.suffix.lower()
    if ext == ".pdf":
        try:
            import pdfplumber
        except ImportError:
            raise RuntimeError("pdfplumber no instalado: pip install pdfplumber")
        pages = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    pages.append(t)
        return "\n\n".join(pages)
    return path.read_text(encoding="utf-8", errors="replace")


def _make_label(path: Path, project_name: str = None) -> str:
    if project_name:
        return f"proyecto:{project_name}"
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
                 ".cpp", ".c", ".h", ".cs", ".rb", ".php", ".swift", ".kt"}
    doc_exts  = {".md", ".txt", ".rst", ".pdf"}
    ext = path.suffix.lower()
    if ext in code_exts:
        return f"codigo:{path.stem.lower()}"
    if ext in doc_exts:
        return f"documento:{path.stem.lower()}"
    return f"archivo:{path.stem.lower()}"


def _store_chunks(ai, chunks: List[str], label: str) -> None:
    """Store chunks directly into episodic memory without triggering retrieval.

    Using ai.episodic.store() directly avoids the full observe() pipeline,
    which calls retrieve_similar() and rebuilds VectorCache once per chunk.
    VectorCache is marked dirty on each store but only rebuilt on the next
    retrieval call — so N chunks → 1 rebuild instead of N.
    """
    for chunk in chunks:
        vec = ai.perception.extract_features(chunk)["vector"]
        ai.episodic.store(chunk, label, vec, confidence=0.65, importance=1.2)


def _store_anchor(ai, path: Path, label: str, chunks: List[str]) -> None:
    """Store a high-importance summary episode explicitly naming the file.

    Without this, asking 'en que consiste app-movil.html' won't find the
    ingested chunks because HTML code has low vector similarity to that
    question phrasing.
    """
    preview = chunks[0][:120].replace("\n", " ").strip() if chunks else ""
    anchor = f"Archivo '{path.name}' leido y guardado en memoria cognitiva."
    if preview:
        anchor += f" Contenido inicial: {preview}"
    vec = ai.perception.extract_features(anchor)["vector"]
    ai.episodic.store(anchor, label, vec, confidence=0.9, importance=2.5)


def _store_pointers(ai, path: Path, text: str, label: str, is_pdf: bool) -> None:
    """Cycle 2: write one ContextMap pointer per chunk + mark coverage.

    Additive to episodic ingestion. For text files the pointer is lossless by
    offset (source_kind='file'); for PDFs the extracted text is not offsetable
    to the .pdf bytes, so the chunk is stored inline (source_kind='text').
    Never raises: episodic ingestion already happened, the context map is a
    best-effort index on top of it.
    """
    try:
        from cognia.context.context_map import ContextMap

        db_path = getattr(ai, "db", None)
        cm = ContextMap(db_path=db_path, project=label)
        spans = _chunk_text_with_offsets(text)
        for ord, (chunk_text, s, e) in enumerate(spans):
            summary = chunk_text[:120].replace("\n", " ").strip()
            if is_pdf:
                cm.add_pointer("text", str(path), inline_text=chunk_text,
                               chunk_ord=ord, label=label, summary=summary)
            else:
                cm.add_pointer("file", str(path), char_start=s, char_end=e,
                               chunk_ord=ord, label=label, summary=summary)
        cm.mark_coverage(str(path), indexed_through=len(text),
                         total_chars=len(text), mtime=path.stat().st_mtime)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "context map pointers skipped for %s: %s", path, exc)


def ingest_file(ai, path_str: str) -> dict:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        return {"error": f"No encontrado: {path}"}
    if not path.is_file():
        return {"error": f"No es un archivo: {path}"}
    try:
        text = _read_raw(path)
        chunks = _chunk_text(text)
    except Exception as exc:
        return {"error": str(exc)}
    if not chunks:
        return {"error": "Archivo vacio o sin contenido legible"}
    label = _make_label(path)
    _store_chunks(ai, chunks, label)
    _store_anchor(ai, path, label, chunks)
    _store_pointers(ai, path, text, label, is_pdf=(path.suffix.lower() == ".pdf"))
    return {
        "archivo":  path.name,
        "label":    label,
        "chunks":   len(chunks),
        "chars":    sum(len(c) for c in chunks),
        "pointers": len(_chunk_text_with_offsets(text)),
    }


def ingest_directory(ai, path_str: str, recursive: bool = True) -> dict:
    path = Path(path_str).expanduser().resolve()
    if not path.exists():
        return {"error": f"No encontrado: {path}"}
    if not path.is_dir():
        return {"error": f"No es un directorio: {path}"}
    project_name = path.name.lower().replace(" ", "_")
    label        = f"proyecto:{project_name}"
    pattern      = "**/*" if recursive else "*"
    files = [
        f for f in path.glob(pattern)
        if f.is_file() and f.suffix.lower() in _TEXT_EXTENSIONS
    ]
    if not files:
        return {"error": "No se encontraron archivos de texto en el directorio"}
    processed      = 0
    total_chunks   = 0
    total_pointers = 0
    error_count    = 0
    for f in files:
        try:
            text   = _read_raw(f)
            chunks = _chunk_text(text)
            if not chunks:
                continue
            _store_chunks(ai, chunks, label)
            _store_anchor(ai, f, label, chunks)
            _store_pointers(ai, f, text, label, is_pdf=(f.suffix.lower() == ".pdf"))
            total_chunks   += len(chunks)
            total_pointers += len(_chunk_text_with_offsets(text))
            processed      += 1
        except Exception:
            error_count += 1
    result = {
        "proyecto": project_name,
        "label":    label,
        "archivos": processed,
        "chunks":   total_chunks,
        "pointers": total_pointers,
    }
    if error_count:
        result["omitidos"] = error_count
    return result
