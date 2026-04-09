from __future__ import annotations

import io
from pathlib import Path

import fitz
from PIL import Image
from starlette.testclient import TestClient

from app import ROOT, create_app


def png_bytes(size: tuple[int, int], color: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_index_page_serves() -> None:
    app = create_app(project_dir=ROOT, work_dir=ROOT / "work-test-index")
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "위툰 선생연수" in response.text
    assert "초중고 · 교과 · 단원별 위툰 수업 아이디어" in response.text
    assert "연수 자료 다운로드" in response.text
    assert "예시 과목 보기" in response.text
    assert "내 과목 입력" in response.text
    assert "위툰으로 바로 이동" in response.text


def test_maker_page_serves() -> None:
    app = create_app(project_dir=ROOT, work_dir=ROOT / "work-test-maker")
    with TestClient(app) as client:
        response = client.get("/maker")
    assert response.status_code == 200
    assert "PDF 책 제작소" in response.text
    assert "책 제목" in response.text


def test_lesson_seed_and_fallback_generation() -> None:
    app = create_app(project_dir=ROOT, work_dir=ROOT / "work-test-ideas")
    with TestClient(app) as client:
        seeds = client.get("/api/lesson-ideas/seeds")
        assert seeds.status_code == 200
        seed_payload = seeds.json()
        assert "초등" in seed_payload["school_levels"]
        assert "국어" in seed_payload["subjects_by_level"]["초등"]

        generated = client.post(
            "/api/lesson-ideas/generate",
            json={
                "school_level": "중등",
                "subject": "정보",
                "unit": "프롬프트 작성",
                "periods": "2차시",
                "teaching_goal": "결과 비교까지 하고 싶다",
            },
        )
        assert generated.status_code == 200
        payload = generated.json()
        assert payload["provider_status"]["mode"] == "local-fallback"
        assert payload["curated_ideas"][0]["subject"] == "정보"
        assert payload["expanded_idea"]["lesson_title"]
        assert payload["expanded_idea"]["lesson_flow"]


def test_lesson_generation_with_mock_groq(tmp_path: Path) -> None:
    class MockGroqClient:
        async def generate_lesson_idea(self, system_prompt: str, user_prompt: str) -> dict:
            return {
                "lesson_title": "Groq 확장 수업안",
                "target": "고등 진로",
                "why_wetoon": "위툰의 제작 흐름을 활용해 진로 탐색을 구체화합니다.",
                "lesson_flow": ["도입", "탐색", "제작", "공유"],
                "student_output": "미니 포트폴리오",
                "teacher_prep": ["직무 사례 준비"],
                "assessment_points": ["과정 기록", "역할 이해"],
                "safety_note": "검토와 수정 중심으로 운영합니다.",
                "wetoon_features": ["시나리오 편집", "컷 수정"],
                "recommended_periods": "2차시",
            }

    from services.lesson_ideas import LessonIdeaService

    service = LessonIdeaService(project_dir=ROOT, groq_client=MockGroqClient())
    app = create_app(project_dir=ROOT, work_dir=tmp_path / "work", lesson_idea_service=service)
    with TestClient(app) as client:
        generated = client.post(
            "/api/lesson-ideas/generate",
            json={
                "school_level": "고등",
                "subject": "진로",
                "unit": "AI 콘텐츠 크리에이터",
                "periods": "2차시",
                "teaching_goal": "포트폴리오 예시",
            },
        )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["provider_status"]["mode"] == "groq"
    assert payload["expanded_idea"]["lesson_title"] == "Groq 확장 수업안"


def test_download_resource_route(tmp_path: Path) -> None:
    resource_file = tmp_path / "manual.pdf"
    resource_file.write_bytes(b"%PDF-1.4\n%demo")
    app = create_app(
        project_dir=ROOT,
        work_dir=tmp_path / "work",
        resource_files={"manual": resource_file},
    )
    with TestClient(app) as client:
        response = client.get("/downloads/manual")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")


def test_upload_reorder_build_and_download_pdf(tmp_path: Path) -> None:
    app = create_app(project_dir=ROOT, work_dir=tmp_path / "work")
    with TestClient(app) as client:
        session = client.post("/api/session")
        session_id = session.json()["session_id"]

        cover_response = client.post(
            f"/api/session/{session_id}/cover",
            files={"cover": ("표지.png", png_bytes((900, 1200), "#112244"), "image/png")},
        )
        assert cover_response.status_code == 200

        images_response = client.post(
            f"/api/session/{session_id}/images",
            files=[
                ("images", ("10112.png", png_bytes((560, 1800), "#bb6655"), "image/png")),
                ("images", ("10002.png", png_bytes((560, 1800), "#5577aa"), "image/png")),
            ],
        )
        assert images_response.status_code == 200
        state = images_response.json()
        assert state["book_title"] == "위툰 작품집"
        assert [item["original_name"] for item in state["images"]] == ["10002.png", "10112.png"]

        updated = client.patch(
            f"/api/session/{session_id}/images",
            json={
                "book_title": "2026 위툰 문집",
                "items": [
                    {"id": state["images"][1]["id"], "label": "학생 10112"},
                    {"id": state["images"][0]["id"], "label": "학생 10002"},
                ]
            },
        )
        assert updated.status_code == 200

        build = client.post(f"/api/session/{session_id}/build-pdf")
        assert build.status_code == 200
        payload = build.json()
        assert payload["file_name"].startswith("2026-위툰-문집-")
        assert payload["file_name"].endswith(".pdf")

        download = client.get(payload["download_url"])
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/pdf"

        with fitz.open(stream=download.content, filetype="pdf") as document:
            assert len(document) == 3
            toc = document.get_toc()
            assert [entry[1] for entry in toc] == ["학생 10112", "학생 10002"]
            assert document.metadata["title"] == "2026 위툰 문집"


def test_build_requires_cover_and_body(tmp_path: Path) -> None:
    app = create_app(project_dir=ROOT, work_dir=tmp_path / "work")
    with TestClient(app) as client:
        session = client.post("/api/session")
        session_id = session.json()["session_id"]
        response = client.post(f"/api/session/{session_id}/build-pdf")
    assert response.status_code == 400
    assert response.json()["detail"] == "표지 이미지를 먼저 업로드하세요."
