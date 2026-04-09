from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.groq_client import GroqClient, GroqProviderError


class LessonIdeaService:
    def __init__(self, project_dir: Path, groq_client: GroqClient | None = None) -> None:
        self.project_dir = Path(project_dir)
        self.data_dir = self.project_dir / "data"
        self.knowledge_text = (self.data_dir / "wetoon_knowledge.md").read_text(encoding="utf-8")
        self.seeds = json.loads((self.data_dir / "lesson_idea_seeds.json").read_text(encoding="utf-8"))
        self.groq_client = groq_client or GroqClient()

    def get_seed_payload(self) -> dict[str, Any]:
        school_levels = []
        subjects_by_level: dict[str, list[str]] = {}
        for item in self.seeds:
            if item["school_level"] not in school_levels:
                school_levels.append(item["school_level"])
            subjects = subjects_by_level.setdefault(item["school_level"], [])
            if item["subject"] not in subjects:
                subjects.append(item["subject"])
        featured = self.seeds[:6]
        return {
            "school_levels": school_levels,
            "subjects_by_level": subjects_by_level,
            "featured_ideas": featured,
        }

    def get_curated_ideas(self, school_level: str, subject: str, unit: str) -> list[dict[str, Any]]:
        unit = (unit or "").strip().lower()
        candidates = [
            item
            for item in self.seeds
            if item["school_level"] == school_level and item["subject"] == subject
        ]
        if not candidates:
            candidates = [
                item for item in self.seeds if item["school_level"] == school_level
            ] or self.seeds[:3]

        def score(item: dict[str, Any]) -> tuple[int, int]:
            text = " ".join(
                [
                    item["unit"],
                    item["title"],
                    item["summary"],
                    " ".join(item.get("keywords", [])),
                ]
            ).lower()
            return (
                1 if unit and unit in text else 0,
                sum(1 for keyword in item.get("keywords", []) if keyword.lower() in unit),
            )

        ranked = sorted(candidates, key=score, reverse=True)
        return ranked[:3]

    def build_local_expansion(
        self,
        school_level: str,
        subject: str,
        unit: str,
        periods: str,
        teaching_goal: str,
        curated_ideas: list[dict[str, Any]],
    ) -> dict[str, Any]:
        base = curated_ideas[0]
        return {
            "lesson_title": base["title"],
            "target": f"{school_level} {subject}",
            "why_wetoon": f"{base['summary']} 위툰의 {base['wetoon_point']} 기능을 통해 학생이 계획-생성-수정의 순환을 직접 경험하게 할 수 있습니다.",
            "lesson_flow": [
                f"도입: {unit or base['unit']}와 연결되는 실제 예시를 보고 활동 목표를 분명히 합니다.",
                f"전개 1: 학생이 장면, 인물, 핵심 메시지를 먼저 손으로 정리한 뒤 위툰에서 초안을 생성합니다.",
                f"전개 2: 생성 결과를 비교·수정하며 {base['wetoon_point']}를 중심으로 표현을 다듬습니다.",
                f"정리: 완성본을 발표하고 {teaching_goal or '수업 목표'}와 연결해 스스로 수정 근거를 말하게 합니다.",
            ],
            "student_output": base["student_output"],
            "teacher_prep": base["teacher_prep"] + ([f"추가 목표: {teaching_goal}"] if teaching_goal else []),
            "assessment_points": base["assessment"],
            "safety_note": "학생이 먼저 생각한 내용을 바탕으로 AI를 보조 도구로 사용하게 하고, 결과물을 그대로 수용하지 않고 검토·수정하게 지도합니다.",
            "wetoon_features": [part.strip() for part in base["wetoon_point"].split(",")],
            "recommended_periods": periods or "2차시",
        }

    async def generate(
        self,
        school_level: str,
        subject: str,
        unit: str,
        periods: str,
        teaching_goal: str,
    ) -> dict[str, Any]:
        curated = self.get_curated_ideas(school_level, subject, unit)
        local_plan = self.build_local_expansion(
            school_level,
            subject,
            unit,
            periods,
            teaching_goal,
            curated,
        )
        provider_status = {
            "mode": "local-fallback",
            "message": "자료 기반 추천을 우선 제공합니다.",
        }
        expanded_idea = local_plan

        try:
            expanded_idea = await self.groq_client.generate_lesson_idea(
                self._build_system_prompt(),
                self._build_user_prompt(
                    school_level=school_level,
                    subject=subject,
                    unit=unit,
                    periods=periods,
                    teaching_goal=teaching_goal,
                    curated=curated,
                ),
            )
            provider_status = {
                "mode": "groq",
                "message": "Groq가 자료 기반으로 맞춤 수업안을 확장했습니다.",
            }
        except GroqProviderError as exc:
            provider_status = {
                "mode": "local-fallback",
                "message": str(exc),
            }

        return {
            "curated_ideas": curated,
            "expanded_idea": expanded_idea,
            "provider_status": provider_status,
        }

    def _build_system_prompt(self) -> str:
        return (
            "너는 한국 학교 현장용 위툰 수업 설계 도우미다. "
            "항상 한국어로 답하고, Wetoon의 실제 기능과 교육 철학을 반영해 교사가 바로 수업에 쓸 수 있는 형태로 제안한다. "
            "응답은 반드시 JSON 한 개만 반환한다. "
            "JSON 키는 lesson_title, target, why_wetoon, lesson_flow, student_output, teacher_prep, assessment_points, safety_note, wetoon_features, recommended_periods 이다. "
            "lesson_flow, teacher_prep, assessment_points, wetoon_features는 배열이어야 한다.\n\n"
            f"{self.knowledge_text}"
        )

    def _build_user_prompt(
        self,
        school_level: str,
        subject: str,
        unit: str,
        periods: str,
        teaching_goal: str,
        curated: list[dict[str, Any]],
    ) -> str:
        return (
            f"학교급: {school_level}\n"
            f"교과: {subject}\n"
            f"단원/주제: {unit}\n"
            f"차시: {periods}\n"
            f"추가 목표: {teaching_goal}\n"
            f"우선 참고할 자료 기반 아이디어: {json.dumps(curated, ensure_ascii=False)}\n"
            "교사가 바로 사용할 수 있도록 1~3차시 중심의 현실적인 수업안으로 확장해줘."
        )
