from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from models import BuildPdfResponse, CoverInfo, SessionImage, SessionStateResponse
from services.book_pdf import PageSource, build_book_pdf

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_BYTES = 300 * 1024 * 1024
MAX_IMAGE_COUNT = 200
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
DEFAULT_BOOK_TITLE = "위툰 작품집"


class SessionError(Exception):
    def __init__(self, detail: str, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def natural_key(value: str) -> list[object]:
    parts = re.split(r"(\d+)", value)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp_text() -> str:
    return utc_now().strftime("%Y%m%d-%H%M%S")


def normalize_book_title(value: str | None) -> str:
    title = re.sub(r"\s+", " ", (value or "").strip())
    return title or DEFAULT_BOOK_TITLE


def title_to_file_stem(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", title).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned or "위툰-작품집"


class UploadSessionStore:
    def __init__(self, project_dir: Path, work_dir: Path | None = None) -> None:
        self.project_dir = Path(project_dir)
        self.work_dir = Path(work_dir) if work_dir is not None else self._default_work_dir()
        self.uploads_dir = self.work_dir / "uploads"
        self.output_dir = self.work_dir / "output"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _default_work_dir(self) -> Path:
        if os.getenv("VERCEL"):
            return Path(tempfile.gettempdir()) / "wetoon"
        return self.project_dir / "work"

    def cleanup_stale_sessions(self, max_age: timedelta = timedelta(hours=24)) -> None:
        cutoff = utc_now() - max_age
        for session_dir in self.uploads_dir.iterdir():
            if not session_dir.is_dir():
                continue
            manifest_path = session_dir / "manifest.json"
            if not manifest_path.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
                continue
            manifest = self._read_manifest(manifest_path)
            updated_at = datetime.fromisoformat(manifest["updated_at"])
            if updated_at >= cutoff:
                continue
            generated_pdf = manifest.get("generated_pdf")
            if generated_pdf:
                pdf_path = self.output_dir / generated_pdf["file_name"]
                if pdf_path.exists():
                    pdf_path.unlink()
            shutil.rmtree(session_dir, ignore_errors=True)

    def create_session(self) -> SessionStateResponse:
        session_id = uuid.uuid4().hex
        session_dir = self._session_dir(session_id)
        (session_dir / "images").mkdir(parents=True, exist_ok=True)
        manifest = {
            "session_id": session_id,
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
            "book_title": DEFAULT_BOOK_TITLE,
            "cover": None,
            "images": [],
            "generated_pdf": None,
        }
        self._write_manifest(session_id, manifest)
        return self._manifest_to_response(manifest)

    def get_session(self, session_id: str) -> SessionStateResponse:
        manifest = self._load_manifest(session_id)
        return self._manifest_to_response(manifest)

    def save_cover(self, session_id: str, filename: str, content: bytes) -> SessionStateResponse:
        manifest = self._load_manifest(session_id)
        suffix, original_name = self._validate_image_file(filename, content)
        session_dir = self._session_dir(session_id)
        old_cover = manifest.get("cover")
        if old_cover:
            old_path = session_dir / old_cover["stored_name"]
            if old_path.exists():
                old_path.unlink()
        stored_name = f"cover{suffix}"
        (session_dir / stored_name).write_bytes(content)
        manifest["cover"] = {
            "stored_name": stored_name,
            "original_name": original_name,
        }
        manifest["generated_pdf"] = None
        manifest["updated_at"] = utc_now().isoformat()
        self._write_manifest(session_id, manifest)
        return self._manifest_to_response(manifest)

    def add_images(self, session_id: str, files: list[tuple[str, bytes]]) -> SessionStateResponse:
        if not files:
            raise SessionError("본문 이미지를 한 개 이상 선택하세요.")

        manifest = self._load_manifest(session_id)
        if len(manifest["images"]) + len(files) > MAX_IMAGE_COUNT:
            raise SessionError(f"이미지는 최대 {MAX_IMAGE_COUNT}개까지 업로드할 수 있습니다.")

        session_dir = self._session_dir(session_id)
        total_bytes = self._current_size_bytes(manifest, session_dir)
        for filename, content in files:
            suffix, original_name = self._validate_image_file(filename, content)
            total_bytes += len(content)
            if total_bytes > MAX_TOTAL_BYTES:
                raise SessionError("전체 업로드 용량 한도를 초과했습니다.")
            item_id = uuid.uuid4().hex[:12]
            stored_name = f"{item_id}{suffix}"
            image_path = session_dir / "images" / stored_name
            image_path.write_bytes(content)
            manifest["images"].append(
                {
                    "id": item_id,
                    "stored_name": stored_name,
                    "original_name": original_name,
                    "label": Path(original_name).stem or item_id,
                }
            )

        manifest["images"].sort(key=lambda item: natural_key(Path(item["original_name"]).stem))
        manifest["generated_pdf"] = None
        manifest["updated_at"] = utc_now().isoformat()
        self._write_manifest(session_id, manifest)
        return self._manifest_to_response(manifest)

    def update_images(
        self,
        session_id: str,
        items: list[dict[str, str]],
        book_title: str | None = None,
    ) -> SessionStateResponse:
        manifest = self._load_manifest(session_id)
        existing = {item["id"]: item for item in manifest["images"]}
        incoming_ids = [item["id"] for item in items]
        if set(incoming_ids) != set(existing):
            raise SessionError("파일 목록이 현재 세션 상태와 다릅니다. 새로고침 후 다시 시도하세요.")

        updated_images = []
        for item in items:
            current = dict(existing[item["id"]])
            label = item.get("label", "").strip() or Path(current["original_name"]).stem
            current["label"] = label
            updated_images.append(current)

        manifest["images"] = updated_images
        manifest["book_title"] = normalize_book_title(book_title or manifest.get("book_title"))
        manifest["generated_pdf"] = None
        manifest["updated_at"] = utc_now().isoformat()
        self._write_manifest(session_id, manifest)
        return self._manifest_to_response(manifest)

    def build_pdf(self, session_id: str) -> BuildPdfResponse:
        manifest = self._load_manifest(session_id)
        if not manifest.get("cover"):
            raise SessionError("표지 이미지를 먼저 업로드하세요.")
        if not manifest["images"]:
            raise SessionError("본문 이미지를 먼저 업로드하세요.")

        session_dir = self._session_dir(session_id)
        cover_path = session_dir / manifest["cover"]["stored_name"]
        page_sources = [
            PageSource(
                image_path=session_dir / "images" / item["stored_name"],
                label=item["label"],
            )
            for item in manifest["images"]
        ]
        book_title = normalize_book_title(manifest.get("book_title"))
        file_name = f"{title_to_file_stem(book_title)}-{timestamp_text()}.pdf"
        output_path = self.output_dir / file_name
        build_book_pdf(cover_path, page_sources, output_path, title=book_title, author="위툰")

        manifest["generated_pdf"] = {
            "file_name": file_name,
            "created_at": utc_now().isoformat(),
        }
        manifest["updated_at"] = utc_now().isoformat()
        self._write_manifest(session_id, manifest)
        return BuildPdfResponse(
            download_url=f"/api/session/{session_id}/download",
            file_name=file_name,
        )

    def get_download_path(self, session_id: str) -> Path:
        manifest = self._load_manifest(session_id)
        generated_pdf = manifest.get("generated_pdf")
        if not generated_pdf:
            raise SessionError("아직 생성된 PDF가 없습니다.", status_code=404)
        pdf_path = self.output_dir / generated_pdf["file_name"]
        if not pdf_path.exists():
            raise SessionError("PDF 파일을 찾을 수 없습니다.", status_code=404)
        return pdf_path

    def _manifest_to_response(self, manifest: dict) -> SessionStateResponse:
        cover = manifest.get("cover")
        response = SessionStateResponse(
            session_id=manifest["session_id"],
            book_title=normalize_book_title(manifest.get("book_title")),
            cover=CoverInfo(original_name=cover["original_name"]) if cover else None,
            images=[
                SessionImage(
                    id=item["id"],
                    original_name=item["original_name"],
                    label=item["label"],
                    position=index,
                )
                for index, item in enumerate(manifest["images"], start=1)
            ],
            download_url=(
                f"/api/session/{manifest['session_id']}/download"
                if manifest.get("generated_pdf")
                else None
            ),
            pdf_file_name=manifest["generated_pdf"]["file_name"] if manifest.get("generated_pdf") else None,
        )
        return response

    def _current_size_bytes(self, manifest: dict, session_dir: Path) -> int:
        total = 0
        cover = manifest.get("cover")
        if cover:
            cover_path = session_dir / cover["stored_name"]
            if cover_path.exists():
                total += cover_path.stat().st_size
        for item in manifest["images"]:
            image_path = session_dir / "images" / item["stored_name"]
            if image_path.exists():
                total += image_path.stat().st_size
        return total

    def _validate_image_file(self, filename: str, content: bytes) -> tuple[str, str]:
        original_name = Path(filename).name
        if not original_name:
            raise SessionError("파일 이름이 올바르지 않습니다.")
        suffix = Path(original_name).suffix.lower()
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            raise SessionError("PNG, JPG, JPEG, WEBP 파일만 업로드할 수 있습니다.")
        if not content:
            raise SessionError("빈 파일은 업로드할 수 없습니다.")
        if len(content) > MAX_FILE_BYTES:
            raise SessionError("파일 하나의 크기가 너무 큽니다.")
        return suffix, original_name

    def _load_manifest(self, session_id: str) -> dict:
        session_dir = self._session_dir(session_id)
        manifest_path = session_dir / "manifest.json"
        if not manifest_path.exists():
            raise SessionError("세션을 찾을 수 없습니다.", status_code=404)
        return self._read_manifest(manifest_path)

    def _write_manifest(self, session_id: str, manifest: dict) -> None:
        manifest_path = self._session_dir(session_id) / "manifest.json"
        temp_path = manifest_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(manifest_path)

    def _read_manifest(self, manifest_path: Path) -> dict:
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _session_dir(self, session_id: str) -> Path:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise SessionError("세션 ID가 올바르지 않습니다.", status_code=404)
        return self.uploads_dir / session_id
