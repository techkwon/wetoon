const ideaState = {
  schoolLevels: [],
  subjectsByLevel: {},
  featuredIdeas: [],
};

const schoolLevelSelect = document.querySelector("#school-level");
const subjectExampleSelect = document.querySelector("#subject-example");
const subjectInput = document.querySelector("#subject-input");
const applyExampleButton = document.querySelector("#apply-example-button");
const unitInput = document.querySelector("#unit");
const periodsInput = document.querySelector("#periods");
const teachingGoalInput = document.querySelector("#teaching-goal");
const ideaButton = document.querySelector("#idea-button");
const providerStatus = document.querySelector("#provider-status");
const curatedIdeas = document.querySelector("#curated-ideas");
const expandedIdea = document.querySelector("#expanded-idea");
const posterFrame = document.querySelector("#poster-frame");
const posterImage = document.querySelector("#poster-image");

function bindPosterImage() {
  if (!posterFrame || !posterImage) {
    return;
  }
  if (posterImage.complete && posterImage.naturalWidth > 0) {
    posterFrame.classList.add("has-poster");
  }
  posterImage.addEventListener("load", () => {
    posterFrame.classList.add("has-poster");
  });
  posterImage.addEventListener("error", () => {
    posterFrame.classList.remove("has-poster");
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "요청 처리에 실패했습니다.");
  }
  return data;
}

function fillSchoolLevels(levels) {
  schoolLevelSelect.innerHTML = "";
  levels.forEach((level) => {
    const option = document.createElement("option");
    option.value = level;
    option.textContent = level;
    schoolLevelSelect.appendChild(option);
  });
}

function fillSubjects(level) {
  subjectExampleSelect.innerHTML = "";
  (ideaState.subjectsByLevel[level] || []).forEach((subject) => {
    const option = document.createElement("option");
    option.value = subject;
    option.textContent = subject;
    subjectExampleSelect.appendChild(option);
  });
}

function renderCuratedIdeas(items) {
  curatedIdeas.innerHTML = "";
  items.forEach((item) => {
    const article = document.createElement("article");
    article.className = "idea-card";
    article.innerHTML = `
      <p class="idea-meta">${item.school_level} · ${item.subject}</p>
      <h4>${item.title}</h4>
      <p>${item.summary}</p>
      <ul>
        <li><strong>위툰 포인트</strong> ${item.wetoon_point}</li>
        <li><strong>산출물</strong> ${item.student_output}</li>
      </ul>
    `;
    curatedIdeas.appendChild(article);
  });
}

function renderExpandedIdea(payload) {
  const data = payload.expanded_idea;
  const flow = (data.lesson_flow || []).map((item) => `<li>${item}</li>`).join("");
  const prep = (data.teacher_prep || []).map((item) => `<li>${item}</li>`).join("");
  const assessment = (data.assessment_points || []).map((item) => `<li>${item}</li>`).join("");
  const features = (data.wetoon_features || []).map((item) => `<li>${item}</li>`).join("");

  expandedIdea.className = "expanded-card";
  expandedIdea.innerHTML = `
    <p class="idea-meta">${data.target || `${schoolLevelSelect.value} ${subjectInput.value || subjectExampleSelect.value}`} · ${data.recommended_periods || periodsInput.value}</p>
    <h4>${data.lesson_title}</h4>
    <p>${data.why_wetoon}</p>
    <div class="expanded-grid">
      <section>
        <h5>차시 흐름</h5>
        <ol>${flow}</ol>
      </section>
      <section>
        <h5>교사 준비</h5>
        <ul>${prep}</ul>
      </section>
      <section>
        <h5>학생 산출물</h5>
        <p>${data.student_output}</p>
      </section>
      <section>
        <h5>평가 포인트</h5>
        <ul>${assessment}</ul>
      </section>
      <section>
        <h5>위툰 활용 기능</h5>
        <ul>${features}</ul>
      </section>
      <section>
        <h5>안전 / 지도 메모</h5>
        <p>${data.safety_note}</p>
      </section>
    </div>
  `;

  providerStatus.textContent = payload.provider_status.message;
  providerStatus.dataset.mode = payload.provider_status.mode;
}

async function refreshIdeas() {
  providerStatus.textContent = "수업안을 생성하는 중입니다.";
  try {
    const subject = subjectInput.value.trim();
    if (!subject) {
      providerStatus.textContent = "실제 생성 과목을 입력하거나 예시 과목을 복사해 주세요.";
      providerStatus.dataset.mode = "local-fallback";
      return;
    }
    const payload = await api("/api/lesson-ideas/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        school_level: schoolLevelSelect.value,
        subject,
        unit: unitInput.value,
        periods: periodsInput.value,
        teaching_goal: teachingGoalInput.value,
      }),
    });
    renderCuratedIdeas(payload.curated_ideas);
    renderExpandedIdea(payload);
  } catch (error) {
    providerStatus.textContent = error.message;
    providerStatus.dataset.mode = "error";
  }
}

async function bootstrap() {
  const seeds = await api("/api/lesson-ideas/seeds");
  ideaState.schoolLevels = seeds.school_levels;
  ideaState.subjectsByLevel = seeds.subjects_by_level;
  ideaState.featuredIdeas = seeds.featured_ideas;
  fillSchoolLevels(ideaState.schoolLevels);
  fillSubjects(schoolLevelSelect.value);
  if (!subjectInput.value.trim()) {
    subjectInput.value = subjectExampleSelect.value;
  }
  renderCuratedIdeas(ideaState.featuredIdeas);
  await refreshIdeas();
}

schoolLevelSelect.addEventListener("change", () => {
  fillSubjects(schoolLevelSelect.value);
});
subjectExampleSelect.addEventListener("change", () => {
  providerStatus.textContent = "예시 과목이 바뀌었습니다. 필요하면 아래 버튼으로 실제 과목 입력칸에 넣어 주세요.";
  providerStatus.dataset.mode = "local-fallback";
});
applyExampleButton.addEventListener("click", () => {
  subjectInput.value = subjectExampleSelect.value;
  refreshIdeas();
});
subjectInput.addEventListener("change", refreshIdeas);
ideaButton.addEventListener("click", refreshIdeas);

bootstrap().catch((error) => {
  providerStatus.textContent = error.message;
  providerStatus.dataset.mode = "error";
});

bindPosterImage();
