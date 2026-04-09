const state = {
  sessionId: null,
  cover: null,
  images: [],
  bookTitle: "위툰 작품집",
  downloadUrl: null,
  pdfFileName: null,
  busy: false,
};

const coverInput = document.querySelector("#cover-input");
const imagesInput = document.querySelector("#images-input");
const coverStatus = document.querySelector("#cover-status");
const coverName = document.querySelector("#cover-name");
const imageCount = document.querySelector("#image-count");
const emptyState = document.querySelector("#empty-state");
const listWrap = document.querySelector("#list-wrap");
const buildButton = document.querySelector("#build-button");
const saveOrderButton = document.querySelector("#save-order-button");
const downloadLink = document.querySelector("#download-link");
const flash = document.querySelector("#flash");
const newSessionButton = document.querySelector("#new-session-button");
const bookTitleInput = document.querySelector("#book-title-input");

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const message =
      typeof data === "string" ? data : data.detail || "요청 처리에 실패했습니다.";
    throw new Error(message);
  }

  return data;
}

function setBusy(nextBusy) {
  state.busy = nextBusy;
  buildButton.disabled = nextBusy;
  saveOrderButton.disabled = nextBusy || !state.images.length;
  coverInput.disabled = nextBusy;
  imagesInput.disabled = nextBusy;
  newSessionButton.disabled = nextBusy;
}

function setFlash(message, isError = false) {
  flash.textContent = message;
  flash.dataset.tone = isError ? "error" : "info";
}

function applySession(session) {
  state.sessionId = session.session_id;
  state.cover = session.cover;
  state.images = (session.images || []).map((item) => ({ ...item }));
  state.bookTitle = session.book_title || "위툰 작품집";
  state.downloadUrl = session.download_url;
  state.pdfFileName = session.pdf_file_name;
  render();
}

function render() {
  coverStatus.textContent = state.cover ? "등록됨" : "미등록";
  coverStatus.dataset.active = String(Boolean(state.cover));
  coverName.textContent = state.cover
    ? `현재 표지: ${state.cover.original_name}`
    : "아직 업로드된 표지가 없습니다.";

  imageCount.textContent = `${state.images.length}장`;
  if (bookTitleInput.value !== state.bookTitle) {
    bookTitleInput.value = state.bookTitle;
  }
  emptyState.classList.toggle("hidden", state.images.length > 0);
  listWrap.innerHTML = "";

  if (state.images.length) {
    const list = document.createElement("div");
    list.className = "file-list";

    state.images.forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "file-row";
      row.dataset.id = item.id;

      row.innerHTML = `
        <div class="file-order">${index + 1}</div>
        <div class="file-main">
          <div class="file-name">${item.original_name}</div>
          <label class="index-editor">
            <span>색인</span>
            <input type="text" value="${escapeHtml(item.label)}" data-role="label" />
          </label>
        </div>
        <div class="row-actions">
          <button type="button" class="mini-button" data-role="up" ${
            index === 0 ? "disabled" : ""
          }>위로</button>
          <button type="button" class="mini-button" data-role="down" ${
            index === state.images.length - 1 ? "disabled" : ""
          }>아래로</button>
        </div>
      `;

      list.appendChild(row);
    });

    listWrap.appendChild(list);
  }

  if (state.downloadUrl && state.pdfFileName) {
    downloadLink.href = `${state.downloadUrl}?v=${Date.now()}`;
    downloadLink.download = state.pdfFileName;
    downloadLink.textContent = `${state.bookTitle} PDF 다운로드`;
    downloadLink.classList.remove("hidden");
  } else {
    downloadLink.classList.add("hidden");
    downloadLink.removeAttribute("href");
  }

  saveOrderButton.disabled = state.busy || !state.images.length;
  buildButton.disabled = state.busy || !state.cover || !state.images.length;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function moveImage(index, direction) {
  const nextIndex = index + direction;
  if (nextIndex < 0 || nextIndex >= state.images.length) {
    return;
  }
  const [item] = state.images.splice(index, 1);
  state.images.splice(nextIndex, 0, item);
  render();
}

function collectImagePayload() {
  return {
    book_title: state.bookTitle.trim(),
    items: state.images.map((item) => ({
      id: item.id,
      label: item.label.trim(),
    })),
  };
}

async function ensureSession() {
  if (state.sessionId) {
    return state.sessionId;
  }
  const session = await api("/api/session", { method: "POST" });
  applySession(session);
  return state.sessionId;
}

async function saveOrderAndLabels() {
  if (!state.sessionId || !state.images.length) {
    return;
  }
  const session = await api(`/api/session/${state.sessionId}/images`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collectImagePayload()),
  });
  applySession(session);
}

async function handleCoverUpload() {
  const file = coverInput.files?.[0];
  if (!file) {
    return;
  }

  try {
    setBusy(true);
    await ensureSession();
    const body = new FormData();
    body.append("cover", file);
    const session = await api(`/api/session/${state.sessionId}/cover`, {
      method: "POST",
      body,
    });
    applySession(session);
    setFlash("표지를 업로드했습니다.");
  } catch (error) {
    setFlash(error.message, true);
  } finally {
    setBusy(false);
    coverInput.value = "";
  }
}

async function handleBodyUpload() {
  const files = Array.from(imagesInput.files || []);
  if (!files.length) {
    return;
  }

  try {
    setBusy(true);
    await ensureSession();
    const body = new FormData();
    files.forEach((file) => body.append("images", file));
    const session = await api(`/api/session/${state.sessionId}/images`, {
      method: "POST",
      body,
    });
    applySession(session);
    setFlash(`${files.length}개의 본문 이미지를 업로드했습니다.`);
  } catch (error) {
    setFlash(error.message, true);
  } finally {
    setBusy(false);
    imagesInput.value = "";
  }
}

async function handleBuild() {
  try {
    setBusy(true);
    await saveOrderAndLabels();
    const result = await api(`/api/session/${state.sessionId}/build-pdf`, {
      method: "POST",
    });
    state.downloadUrl = result.download_url;
    state.pdfFileName = result.file_name;
    render();
    setFlash("PDF 생성이 끝났습니다. 다운로드 링크를 확인하세요.");
  } catch (error) {
    setFlash(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function startNewSession() {
  try {
    setBusy(true);
    const session = await api("/api/session", { method: "POST" });
    applySession(session);
    setFlash("새 작업 세션을 만들었습니다.");
  } catch (error) {
    setFlash(error.message, true);
  } finally {
    setBusy(false);
  }
}

coverInput.addEventListener("change", handleCoverUpload);
imagesInput.addEventListener("change", handleBodyUpload);

saveOrderButton.addEventListener("click", async () => {
  try {
    setBusy(true);
    await saveOrderAndLabels();
    setFlash("순서와 색인을 저장했습니다.");
  } catch (error) {
    setFlash(error.message, true);
  } finally {
    setBusy(false);
  }
});

buildButton.addEventListener("click", handleBuild);
newSessionButton.addEventListener("click", startNewSession);

listWrap.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || target.dataset.role !== "label") {
    return;
  }
  const row = target.closest(".file-row");
  if (!row) {
    return;
  }
  const item = state.images.find((candidate) => candidate.id === row.dataset.id);
  if (item) {
    item.label = target.value;
  }
});

bookTitleInput.addEventListener("input", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }
  state.bookTitle = target.value;
});

listWrap.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }
  const row = target.closest(".file-row");
  if (!row) {
    return;
  }
  const index = state.images.findIndex((item) => item.id === row.dataset.id);
  if (index === -1) {
    return;
  }
  if (target.dataset.role === "up") {
    moveImage(index, -1);
  }
  if (target.dataset.role === "down") {
    moveImage(index, 1);
  }
});

startNewSession();
