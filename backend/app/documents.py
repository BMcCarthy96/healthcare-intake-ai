from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
import pymupdf

from app.config import get_settings
from app.schemas import EvidenceBox


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDocument:
    sha256: str
    storage_key: str
    page_texts: list[str]
    size_bytes: int
    page_metadata: list[dict]


class DocumentStore(Protocol):
    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> None: ...

    def get(self, key: str) -> bytes: ...


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def get(self, key: str) -> bytes:
        try:
            return (self.root / key).read_bytes()
        except FileNotFoundError as error:
            raise DocumentError("Stored document asset was not found.") from error


class S3DocumentStore:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.s3_endpoint_url or not settings.s3_access_key or not settings.s3_secret_key:
            raise DocumentError("S3 storage requires endpoint URL and access credentials.")
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
        )
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            self.client.create_bucket(Bucket=self.bucket)

    def put(self, key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType=content_type)

    def get(self, key: str) -> bytes:
        try:
            return bytes(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())
        except Exception as error:
            raise DocumentError("Stored document asset was not found.") from error


def get_document_store() -> DocumentStore:
    settings = get_settings()
    if settings.document_storage_backend == "s3":
        return S3DocumentStore()
    return LocalDocumentStore(settings.document_storage_path)


def validate_pdf(content: bytes, filename: str) -> None:
    settings = get_settings()
    if not filename.lower().endswith(".pdf"):
        raise DocumentError("Only synthetic PDF files are supported.")
    if not content.startswith(b"%PDF"):
        raise DocumentError("Uploaded file is not a valid PDF.")
    if len(content) > settings.max_upload_bytes:
        raise DocumentError(f"File exceeds the {settings.max_upload_bytes} byte upload limit.")


def safe_filename(filename: str) -> str:
    stem = Path(filename).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", stem).strip(".-") or "intake-packet"
    return f"{cleaned[:80]}.pdf"


def persist_and_parse_document(case_id: str, content: bytes, filename: str) -> ParsedDocument:
    validate_pdf(content, filename)
    digest = hashlib.sha256(content).hexdigest()
    key = f"{case_id}/{digest[:16]}-{safe_filename(filename)}"
    store = get_document_store()
    store.put(key, content, "application/pdf")
    try:
        pdf = pymupdf.open(stream=content, filetype="pdf")
        pages: list[str] = []
        page_metadata: list[dict] = []
        settings = get_settings()
        for page_index in range(pdf.page_count):
            page_number = page_index + 1
            page: pymupdf.Page = pdf.load_page(page_index)
            native_text = page.get_text("text").strip()
            words = page.get_text("words")
            source_mode = "native" if native_text else "ocr"
            source_confidence = 1.0 if native_text else None
            page_text = native_text
            if not native_text and settings.ocr_enabled:
                try:
                    import pytesseract
                    from PIL import Image

                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                    image_bytes = pixmap.tobytes("png")
                    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                    ocr = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
                    ocr_lines: dict[tuple[int, int, int], list[str]] = {}
                    ocr_confidences: list[float] = []
                    ocr_words: list[dict] = []
                    for index, token in enumerate(ocr.get("text", [])):
                        token = str(token).strip()
                        if not token:
                            continue
                        try:
                            confidence = max(0.0, min(1.0, float(ocr["conf"][index]) / 100))
                        except (TypeError, ValueError, KeyError):
                            confidence = 0.0
                        ocr_confidences.append(confidence)
                        ocr_words.append(
                            {
                                "text": token,
                                "x0": float(ocr["left"][index]) / pixmap.width,
                                "y0": float(ocr["top"][index]) / pixmap.height,
                                "x1": float(ocr["left"][index] + ocr["width"][index]) / pixmap.width,
                                "y1": float(ocr["top"][index] + ocr["height"][index]) / pixmap.height,
                            }
                        )
                        line_key = (
                            int(ocr.get("block_num", [0])[index] or 0),
                            int(ocr.get("par_num", [0])[index] or 0),
                            int(ocr.get("line_num", [index])[index] or index),
                        )
                        ocr_lines.setdefault(line_key, []).append(token)
                    page_text = "\n".join(" ".join(tokens) for tokens in ocr_lines.values()).strip()
                    source_confidence = (
                        sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else 0.0
                    )
                    words = []
                    page_metadata.append(
                        {
                            "page_number": page_number,
                            "width": float(page.rect.width),
                            "height": float(page.rect.height),
                            "source_mode": "ocr",
                            "source_confidence": source_confidence,
                            "words": ocr_words,
                        }
                    )
                    page_key = f"{case_id}/pages/{digest[:16]}-p{page_number}.png"
                    store.put(page_key, image_bytes, "image/png")
                    page_metadata[-1]["image_key"] = page_key
                except ImportError as error:
                    raise DocumentError("OCR support is unavailable for this scanned PDF.") from error
            if not page_metadata or page_metadata[-1].get("page_number") != page_number:
                native_words = [
                    {
                        "text": str(word[4]),
                        "x0": float(word[0]) / max(float(page.rect.width), 1.0),
                        "y0": float(word[1]) / max(float(page.rect.height), 1.0),
                        "x1": float(word[2]) / max(float(page.rect.width), 1.0),
                        "y1": float(word[3]) / max(float(page.rect.height), 1.0),
                    }
                    for word in words
                ]
                page_metadata.append(
                    {
                        "page_number": page_number,
                        "width": float(page.rect.width),
                        "height": float(page.rect.height),
                        "source_mode": source_mode,
                        "source_confidence": source_confidence,
                        "words": native_words,
                    }
                )
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.25, 1.25), alpha=False)
                page_key = f"{case_id}/pages/{digest[:16]}-p{page_number}.png"
                store.put(page_key, pixmap.tobytes("png"), "image/png")
                page_metadata[-1]["image_key"] = page_key
            pages.append(page_text)
    except Exception as error:  # PyMuPDF exposes several native exception types.
        if isinstance(error, DocumentError):
            raise
        raise DocumentError("PDF could not be parsed.") from error
    if not pages or not any(pages):
        raise DocumentError("PDF has no extractable text, including OCR output.")
    return ParsedDocument(
        sha256=digest,
        storage_key=key,
        page_texts=pages,
        size_bytes=len(content),
        page_metadata=page_metadata,
    )


def evidence_boxes(page_metadata: list[dict], page_number: int, quote: str) -> list[EvidenceBox]:
    """Return normalized boxes for the first matching quote on a page."""
    if page_number < 1 or page_number > len(page_metadata):
        return []
    words = page_metadata[page_number - 1].get("words", [])
    quote_words = [word.lower() for word in re.findall(r"\S+", quote)]
    if not quote_words or not words:
        return []
    normalized = [str(word.get("text", "")).lower() for word in words]
    for start in range(max(0, len(normalized) - len(quote_words) + 1)):
        if normalized[start : start + len(quote_words)] == quote_words:
            match = words[start : start + len(quote_words)]
            return [
                EvidenceBox(
                    x=min(float(item.get("x0", 0)), 1),
                    y=min(float(item.get("y0", 0)), 1),
                    width=max(0.0, min(1.0, float(item.get("x1", 0)) - float(item.get("x0", 0)))),
                    height=max(0.0, min(1.0, float(item.get("y1", 0)) - float(item.get("y0", 0)))),
                )
                for item in match
            ]
    return []


def verify_evidence(page_texts: list[str], page_number: int, quote: str) -> bool:
    if page_number < 1 or page_number > len(page_texts):
        return False
    normalized_page = " ".join(page_texts[page_number - 1].split())
    normalized_quote = " ".join(quote.split())
    return bool(normalized_quote) and normalized_quote in normalized_page
