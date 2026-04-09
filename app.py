from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from models import LessonIdeaRequest, UpdateImagesRequest
from services.lesson_ideas import LessonIdeaService
from services.upload_session import SessionError, UploadSessionStore

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
RESOURCE_FILES = {
    "intro": STATIC_DIR / "downloads" / "wetoon-school-intro.pdf",
    "sample": STATIC_DIR / "downloads" / "wetoon-elementary-sample.pdf",
    "manual": STATIC_DIR / "downloads" / "wetoon-user-manual.pdf",
}


def _store(request: Request) -> UploadSessionStore:
    return request.app.state.session_store


def _lesson_service(request: Request) -> LessonIdeaService:
    return request.app.state.lesson_idea_service


async def lecture_page(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "lecture.html")


async def maker_page(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def create_session(request: Request) -> JSONResponse:
    state = _store(request).create_session()
    return JSONResponse(state.model_dump())


async def get_session(request: Request) -> JSONResponse:
    state = _store(request).get_session(request.path_params["session_id"])
    return JSONResponse(state.model_dump())


async def upload_cover(request: Request) -> JSONResponse:
    form = await request.form()
    upload = form.get("cover")
    if not isinstance(upload, UploadFile):
        raise SessionError("표지 파일이 필요합니다.")
    content = await upload.read()
    state = _store(request).save_cover(
        request.path_params["session_id"],
        upload.filename or "cover.png",
        content,
    )
    return JSONResponse(state.model_dump())


async def upload_images(request: Request) -> JSONResponse:
    form = await request.form()
    uploads = [item for item in form.getlist("images") if isinstance(item, UploadFile)]
    files = []
    for upload in uploads:
        files.append((upload.filename or "image.png", await upload.read()))
    state = _store(request).add_images(request.path_params["session_id"], files)
    return JSONResponse(state.model_dump())


async def update_images(request: Request) -> JSONResponse:
    payload = UpdateImagesRequest.model_validate(await request.json())
    state = _store(request).update_images(
        request.path_params["session_id"],
        [item.model_dump() for item in payload.items],
        payload.book_title,
    )
    return JSONResponse(state.model_dump())


async def build_pdf(request: Request) -> JSONResponse:
    response = _store(request).build_pdf(request.path_params["session_id"])
    return JSONResponse(response.model_dump())


async def download_pdf(request: Request) -> FileResponse:
    pdf_path = _store(request).get_download_path(request.path_params["session_id"])
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


async def lesson_seed_data(request: Request) -> JSONResponse:
    return JSONResponse(_lesson_service(request).get_seed_payload())


async def generate_lesson_ideas(request: Request) -> JSONResponse:
    payload = LessonIdeaRequest.model_validate(await request.json())
    result = await _lesson_service(request).generate(
        school_level=payload.school_level,
        subject=payload.subject,
        unit=payload.unit,
        periods=payload.periods,
        teaching_goal=payload.teaching_goal,
    )
    return JSONResponse(result)


async def download_resource(request: Request) -> FileResponse:
    slug = request.path_params["slug"]
    resource_files: dict[str, Path] = request.app.state.resource_files
    resource_path = resource_files.get(slug)
    if resource_path is None or not resource_path.exists():
        raise SessionError("요청한 자료 파일을 찾을 수 없습니다.", status_code=404)
    return FileResponse(resource_path, media_type="application/pdf", filename=resource_path.name)


async def session_error_handler(_: Request, exc: SessionError) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def create_app(
    project_dir: Path | None = None,
    work_dir: Path | None = None,
    lesson_idea_service: LessonIdeaService | None = None,
    resource_files: dict[str, Path] | None = None,
) -> Starlette:
    project_dir = project_dir or ROOT
    store = UploadSessionStore(project_dir=project_dir, work_dir=work_dir)
    lesson_idea_service = lesson_idea_service or LessonIdeaService(project_dir=project_dir)
    resource_files = resource_files or RESOURCE_FILES

    @asynccontextmanager
    async def lifespan(app: Starlette):
        app.state.session_store = store
        app.state.lesson_idea_service = lesson_idea_service
        app.state.resource_files = resource_files
        store.cleanup_stale_sessions()
        yield

    routes = [
        Route("/", lecture_page),
        Route("/lecture", lecture_page),
        Route("/maker", maker_page),
        Route("/api/session", create_session, methods=["POST"]),
        Route("/api/session/{session_id:str}", get_session, methods=["GET"]),
        Route("/api/session/{session_id:str}/cover", upload_cover, methods=["POST"]),
        Route("/api/session/{session_id:str}/images", upload_images, methods=["POST"]),
        Route("/api/session/{session_id:str}/images", update_images, methods=["PATCH"]),
        Route("/api/session/{session_id:str}/build-pdf", build_pdf, methods=["POST"]),
        Route("/api/session/{session_id:str}/download", download_pdf, methods=["GET"]),
        Route("/api/lesson-ideas/seeds", lesson_seed_data, methods=["GET"]),
        Route("/api/lesson-ideas/generate", generate_lesson_ideas, methods=["POST"]),
        Route("/downloads/{slug:str}", download_resource, methods=["GET"]),
        Mount("/static", app=StaticFiles(directory=project_dir / "static"), name="static"),
    ]
    app = Starlette(
        debug=True,
        routes=routes,
        lifespan=lifespan,
        exception_handlers={SessionError: session_error_handler},
    )
    app.state.session_store = store
    app.state.lesson_idea_service = lesson_idea_service
    app.state.resource_files = resource_files
    return app


app = create_app()
