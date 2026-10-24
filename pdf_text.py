from __future__ import annotations

from pathlib import Path


class PdfTextError(RuntimeError):
    pass


def extract_pdf_text(path: Path) -> str:
    """Read text from a local PDF. Tries PyMuPDF, then pypdf."""
    file = Path(path)
    if not file.is_file():
        raise PdfTextError(f"PDF not found: {file}")
    errors: list[str] = []
    try:
        import fitz

        with fitz.open(file) as doc:
            text = "\n".join(page.get_text() for page in doc).strip()
        if text:
            return text
        errors.append("PyMuPDF found no text.")
    except ImportError:
        pass
    except Exception as error:
        errors.append(str(error))
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(file))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
        if text:
            return text
        errors.append("pypdf found no text (maybe a scanned PDF).")
    except ImportError:
        errors.append("Install pypdf or PyMuPDF to read PDF text.")
    except Exception as error:
        errors.append(str(error))
    raise PdfTextError(" ".join(errors) or "Could not read PDF text.")
