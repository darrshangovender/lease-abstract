"""Read a lease from disk: plain text always, PDF when ``pdfplumber`` is installed."""

from __future__ import annotations

from pathlib import Path


class PDFSupportMissing(RuntimeError):
    pass


def load_text(path: str | Path) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        return load_pdf(p)
    return p.read_text(encoding="utf-8", errors="replace")


def load_pdf(path: Path) -> str:
    try:
        import pdfplumber  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise PDFSupportMissing(
            "PDF input needs the optional extra: pip install 'lease-abstract[pdf]'"
        ) from exc
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:  # pragma: no cover - optional path
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n\f\n".join(pages)


__all__ = ["PDFSupportMissing", "load_pdf", "load_text"]
