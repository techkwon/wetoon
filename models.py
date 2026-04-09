from __future__ import annotations

from pydantic import BaseModel, Field


class CoverInfo(BaseModel):
    original_name: str


class SessionImage(BaseModel):
    id: str
    original_name: str
    label: str
    position: int


class SessionStateResponse(BaseModel):
    session_id: str
    book_title: str
    cover: CoverInfo | None = None
    images: list[SessionImage] = Field(default_factory=list)
    download_url: str | None = None
    pdf_file_name: str | None = None


class UpdateImageItem(BaseModel):
    id: str
    label: str = ""


class UpdateImagesRequest(BaseModel):
    book_title: str = ""
    items: list[UpdateImageItem] = Field(default_factory=list)


class BuildPdfResponse(BaseModel):
    download_url: str
    file_name: str


class LessonIdeaRequest(BaseModel):
    school_level: str
    subject: str
    unit: str = ""
    periods: str = "2차시"
    teaching_goal: str = ""
