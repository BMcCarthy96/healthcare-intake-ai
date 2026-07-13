from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import boto3
import fitz

from app.config import get_settings


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedDocument:
    sha256: str
    storage_key: str
    page_texts: list[str]
    size_bytes: int


class DocumentStore(Protocol):
    def put(self, key: str, content: bytes) -> None: ...


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, key: str, content: bytes) -> None:
        destination = self.root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


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

    def put(self, key: str, content: bytes) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content, ContentType="application/pdf")


def get_document_store() -> DocumentStore:
    settings = get_settings()
    if settings.document_storage_backend == "s3":
        return S3DocumentStore()
    return LocalDocumentStore(settings.document_storage_path)


def validate_pdf(content: bytes, filename: str) -> None:
    settings = get_settings()
    if not filename.lower().endswith(".pdf"):
        raise DocumentError("Only digitally generated PDF files are supported.")
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
    get_document_store().put(key, content)
    try:
        pdf = fitz.open(stream=content, filetype="pdf")
        pages = [page.get_text("text").strip() for page in pdf]
    except Exception as error:  # PyMuPDF exposes several native exception types.
        raise DocumentError("PDF could not be parsed as a text-based document.") from error
    if not pages or not any(pages):
        raise DocumentError("PDF has no extractable text. OCR is intentionally out of scope.")
    return ParsedDocument(
        sha256=digest,
        storage_key=key,
        page_texts=pages,
        size_bytes=len(content),
    )


def verify_evidence(page_texts: list[str], page_number: int, quote: str) -> bool:
    if page_number < 1 or page_number > len(page_texts):
        return False
    normalized_page = " ".join(page_texts[page_number - 1].split())
    normalized_quote = " ".join(quote.split())
    return bool(normalized_quote) and normalized_quote in normalized_page
