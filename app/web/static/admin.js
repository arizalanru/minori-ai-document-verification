"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  app: null,
  kind: null,
  mainTab: "documents",
  offset: 0,
  busy: false,
  uploads: {},
  highlightedEvidenceIds: [],
};

const fieldNames = {
  nama: "Nama lengkap",
  nik: "NIK",
  tanggal_lahir: "Tanggal lahir (YYYY-MM-DD)",
  alamat: "Alamat",
  pendidikan_terakhir: "Pendidikan terakhir",
  nomor_dokumen: "Nomor dokumen",
  institusi: "Nama institusi pendidikan",
  tanggal_terbit: "Tanggal terbit (YYYY-MM-DD)",
  tanggal_berakhir: "Tanggal berakhir jika tercantum (YYYY-MM-DD)",
  tanggal_pemeriksaan: "Tanggal pemeriksaan (YYYY-MM-DD)",
  kesimpulan_dokter: "Kesimpulan dokter sesuai tulisan pada laporan",
};

const ruleNames = {
  REQUIRED_DOCUMENTS: "Kelengkapan dokumen",
  NIK_FORMAT: "Format NIK",
  NIK_CONSISTENCY: "Konsistensi NIK",
  IDENTITY_CONSISTENCY: "Konsistensi nama",
  BIRTH_DATE: "Tanggal lahir",
  AGE_RANGE: "Rentang usia",
  EDUCATION_MIN: "Pendidikan minimum",
  REQUIRED_FIELDS: "Kelengkapan data",
};

const statusLabels = {
  PENDING: "Belum diperiksa",
  REVIEW: "Perlu ditinjau",
  FLAGGED: "Ada syarat yang tidak terpenuhi",
  ELIGIBLE: "Memenuhi syarat administrasi",
  INELIGIBLE: "Tidak memenuhi syarat",
  PASS: "Sesuai",
  FAIL: "Tidak sesuai",
  UNKNOWN: "Belum dapat dipastikan",
};

const documentStatusLabels = {
  missing: "Belum diunggah",
  uploaded: "Sudah diunggah",
  needs_review: "Perlu diperiksa",
  verified: "Sudah diverifikasi",
};

const fieldStatusLabels = {
  extracted: "Terbaca dari dokumen",
  ambiguous: "Perlu diperiksa",
  not_found: "Tidak ditemukan",
  not_applicable: "Tidak diperlukan",
  reviewed: "Dikoreksi admin",
};

const profileLabels = {
  "demo-core-v1": "Pemeriksaan KTP dan ijazah",
  "demo-full-v1": "Pemeriksaan enam dokumen",
};

const profileDocuments = {
  "demo-core-v1": ["KTP", "IJAZAH"],
  "demo-full-v1": ["KTP", "KK", "IJAZAH", "TRANSKRIP", "SKCK", "MCU"],
};

const documentNames = {
  KTP: "KTP",
  KK: "Kartu Keluarga (KK)",
  IJAZAH: "Ijazah",
  TRANSKRIP: "Transkrip nilai",
  SKCK: "SKCK",
  MCU: "Hasil pemeriksaan kesehatan (MCU)",
};

const reviewActionLabels = {
  verify: "Dokumen diverifikasi",
  request_reupload: "Permintaan unggah ulang dicatat",
  confirm_ineligible: "Hasil tidak memenuhi syarat dikonfirmasi",
  change_profile: "Jenis pemeriksaan diubah",
};

const processingFailureMessages = {
  LLM_KEY_MISSING: "Layanan pembacaan belum dikonfigurasi.",
  LLM_SCHEMA_ERROR: "Format permintaan pembacaan belum didukung layanan.",
  PROVIDER_BAD_REQUEST: "Permintaan pembacaan ditolak layanan.",
  PROVIDER_RATE_LIMIT: "Layanan sedang mencapai batas penggunaan.",
  PROVIDER_BUSY: "Layanan pembacaan sedang sibuk.",
  LLM_TIMEOUT: "Layanan pembacaan terlalu lama merespons.",
  LLM_NETWORK_ERROR: "Jaringan ke layanan pembacaan sedang bermasalah.",
  LLM_ACCESS_DENIED: "Layanan pembacaan belum dapat diakses.",
  MODEL_UNAVAILABLE: "Model pembacaan sedang tidak tersedia.",
  OUTPUT_INVALID: "Hasil pembacaan tidak dapat diverifikasi.",
  OCR_EMPTY: "Tidak ada teks yang dapat dibaca dari gambar.",
  OCR_ERROR: "Gambar belum berhasil dibaca.",
};

function processingFailureMessage(code) {
  return (
    processingFailureMessages[code] ||
    "Dokumen belum berhasil dibaca karena kendala layanan."
  );
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function clearNotice() {
  $("notice").hidden = true;
  $("notice").textContent = "";
  $("notice").className = "";
}

function notice(message, error = false) {
  $("notice").hidden = false;
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
}

function statusText(status) {
  return statusLabels[status] || status;
}

function statusElement(status, className) {
  return element(
    "span",
    statusText(status),
    `${className} status-${status}`,
  );
}

function currentDocument() {
  return state.app?.documents[state.kind];
}

function requiredDocumentTypes(application) {
  const configured = profileDocuments[application.rule_version_id] || [];
  return [...new Set([...configured, ...application.missing_documents])];
}

function additionalDocumentTypes(application) {
  const required = new Set(requiredDocumentTypes(application));
  return Object.keys(application.documents).filter(
    (documentType) => !required.has(documentType),
  );
}

async function api(path, body) {
  const options = { headers: {} };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Idempotency-Key"] = crypto.randomUUID();
    if (body instanceof FormData) {
      options.body = body;
    } else {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
  }

  const response = await fetch(`/api/v1${path}`, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(
      data.error?.message || JSON.stringify(data.detail || data),
    );
    error.status = response.status;
    throw error;
  }
  return data;
}

function setControlsDisabled(disabled) {
  for (const control of document.querySelectorAll(
    "button,input,select,textarea",
  )) {
    control.disabled = disabled || control.dataset.permanentlyDisabled === "true";
  }
}

async function run(action) {
  if (state.busy) return;
  state.busy = true;
  setControlsDisabled(true);
  try {
    await action();
  } catch (error) {
    notice(
      error.status === 409
        ? "Data sudah berubah. Muat ulang, periksa data terbaru, lalu ulangi tindakan. Perubahan Anda belum disimpan."
        : error.message,
      true,
    );
  } finally {
    state.busy = false;
    setControlsDisabled(false);
  }
}

async function listApplications() {
  const applications = await api(
    `/applications?limit=20&offset=${state.offset}`,
  );
  $("applications").replaceChildren();

  for (const application of applications) {
    const selected = application.application_id === state.app?.application_id;
    const knownName = selected ? state.app?.data?.nama : null;
    const button = element(
      "button",
      undefined,
      `app-item${selected ? " active" : ""}`,
    );
    button.type = "button";
    button.setAttribute("aria-current", selected ? "true" : "false");
    button.append(
      element("span", knownName || "Calon peserta", "app-item-title"),
      element(
        "span",
        `ID ${application.application_id.slice(0, 12)}`,
        "app-item-id mono",
      ),
      statusElement(application.outcome, "app-status"),
    );
    button.onclick = () => {
      if (
        hasPendingChanges() &&
        !confirm("Pindah peserta dan buang perubahan yang belum disimpan?")
      ) {
        return;
      }
      clearNotice();
      run(() => selectApplication(application.application_id));
    };
    $("applications").append(button);
  }

  if (!applications.length) {
    $("applications").append(
      element("p", "Belum ada calon peserta pada halaman ini.", "muted"),
    );
  }
  $("prev").hidden = state.offset === 0;
  $("next").hidden = applications.length < 20;
}

async function selectApplication(applicationId) {
  const participantChanged = state.app?.application_id !== applicationId;
  state.app = await api(`/applications/${encodeURIComponent(applicationId)}`);
  if (participantChanged) {
    $("reject-reason").value = "";
    state.uploads = {};
    state.mainTab = "documents";
  }
  const availableTypes = [
    ...requiredDocumentTypes(state.app),
    ...additionalDocumentTypes(state.app),
  ];
  if (!availableTypes.includes(state.kind)) {
    state.kind = availableTypes[0] || null;
  }
  renderApplication();
  await listApplications();
}

function nextAction(application) {
  if (application.missing_documents.length) {
    return "Lengkapi dokumen yang belum tersedia untuk melanjutkan pemeriksaan.";
  }

  const hasUnverified = Object.values(application.documents).some(
    (document) => document.review_status !== "verified",
  );
  if (hasUnverified) {
    return "Pilih dokumen, cocokkan data dengan gambar, lalu simpan hasil pemeriksaan.";
  }

  if (!application.evaluation) {
    return "Pilih Periksa ulang persyaratan untuk membuat hasil evaluasi.";
  }

  if (application.outcome === "FLAGGED") {
    return "Periksa dasar hasil, lalu konfirmasi hanya jika hasil sudah ditinjau.";
  }

  if (application.outcome === "REVIEW") {
    const unknownRule = application.evaluation.results.find(
      (rule) => rule.result === "UNKNOWN",
    );
    return (
      unknownRule?.next_action ||
      "Periksa dokumen dan lengkapi data yang masih belum pasti."
    );
  }

  if (["ELIGIBLE", "INELIGIBLE"].includes(application.outcome)) {
    return "Lanjutkan sesuai proses seleksi internal yang berlaku.";
  }

  return "Lengkapi dan periksa dokumen peserta.";
}

function renderApplication() {
  const application = state.app;
  const profileLabel =
    profileLabels[application.rule_version_id] || application.rule_version_id;

  $("empty").hidden = true;
  $("workspace").hidden = false;
  $("app-name").textContent = application.data?.nama || "Calon peserta";
  $("profile").textContent = profileLabel;
  $("profile-note").textContent =
    "Profil menggunakan asumsi aturan demonstrasi, bukan kebijakan resmi.";
  $("technical-application-id").textContent = application.application_id;
  $("technical-revision").textContent = application.revision;
  $("technical-profile").textContent = application.rule_version_id;

  $("outcome").textContent = statusText(application.outcome);
  $("outcome").className = `status-label status-${application.outcome}`;
  $("next-action").textContent = nextAction(application);

  $("missing").textContent = application.missing_documents.length
    ? `Masih perlu diunggah: ${application.missing_documents.join(", ")}.`
    : "Semua dokumen wajib sudah tersedia.";
  $("completeness-summary").textContent = application.missing_documents.length
    ? `${application.missing_documents.length} belum tersedia`
    : "Lengkap";
  const completeness = $("document-completeness");
  if (completeness.dataset.applicationId !== application.application_id) {
    completeness.dataset.applicationId = application.application_id;
    completeness.open = application.missing_documents.length > 0;
  }

  renderRules(application);
  renderDocumentList(application);
  renderDocumentTabs(application);
  renderDocument();
  renderHistory(application);
  $("reject-area").hidden = application.outcome !== "FLAGGED";
  activateMainTab(state.mainTab);
}

function renderRules(application) {
  $("rules").replaceChildren();
  for (const rule of application.evaluation?.results || []) {
    const row = element("article", undefined, "rule");
    const top = element("div", undefined, "rule-top");
    top.append(
      element("span", ruleNames[rule.rule_code] || rule.rule_code, "rule-name"),
      statusElement(rule.result, "rule-status"),
    );
    row.append(top);

    if (rule.next_action) {
      row.append(element("p", `Tindakan: ${rule.next_action}`, "rule-action"));
    }

    const details = element("details");
    const detailSummary = element("summary", "Lihat alasan dari sistem");
    let reason = rule.reason;
    if (rule.rule_code === "REQUIRED_DOCUMENTS" && rule.result === "PASS") {
      reason = "Dokumen wajib tersedia dan telah diverifikasi.";
    } else if (rule.rule_code === "BIRTH_DATE" && rule.result === "FAIL") {
      reason = "Tanggal yang dikonfirmasi tidak valid atau berada di masa depan.";
    } else if (rule.rule_code === "NIK_FORMAT") {
      reason = "Pemeriksaan ini hanya mencakup format 16 digit dan konfirmasi admin.";
    }
    details.append(detailSummary, element("p", reason));
    row.append(details);
    $("rules").append(row);
  }

  if (!application.evaluation) {
    $("rules").append(
      element(
        "p",
        "Belum ada hasil persyaratan. Lengkapi dokumen untuk memulai pemeriksaan.",
        "muted",
      ),
    );
  }
}

function renderDocumentList(application) {
  const list = $("document-list");
  list.replaceChildren();
  appendDocumentGroup(
    "Dokumen wajib",
    requiredDocumentTypes(application),
    application,
  );
  const additional = additionalDocumentTypes(application);
  if (additional.length) {
    appendDocumentGroup("Dokumen tambahan", additional, application, true);
  }
}

function appendDocumentGroup(label, documentTypes, application, additional = false) {
  const list = $("document-list");
  list.append(
    element(
      "p",
      label,
      `document-group-label${additional ? " additional" : ""}`,
    ),
  );
  const header = element("div", undefined, "document-list-header");
  header.append(
    element("span", "Dokumen"),
    element("span", "Status"),
    element("span", "Tindakan"),
  );
  list.append(header);
  for (const documentType of documentTypes) {
    list.append(renderDocumentRow(documentType, application));
  }
}

function renderDocumentRow(documentType, application) {
  const document = application.documents[documentType];
  const displayStatus = document
    ? document.review_status === "verified"
      ? "verified"
      : "needs_review"
    : "missing";
  const row = element(
    "div",
    undefined,
    `document-row${documentType === state.kind ? " active" : ""}`,
  );
  const name = element(
    "span",
    documentNames[documentType] || documentType,
    "document-name",
  );
  const status = element(
    "span",
    documentStatusLabels[displayStatus] || displayStatus,
    `document-status status-${displayStatus}`,
  );

  const fileInput = element("input", undefined, "document-file-input");
  fileInput.type = "file";
  fileInput.accept = "image/png,image/jpeg";
  fileInput.dataset.uploadInput = documentType;
  fileInput.setAttribute(
    "aria-label",
    `Pilih berkas ${documentNames[documentType] || documentType}`,
  );
  fileInput.onchange = () => {
    const file = fileInput.files[0];
    if (!file) return;
    state.uploads[documentType] = {
      file,
      replacing: Boolean(document),
      uploading: false,
      error: null,
    };
    $("document-completeness").open = true;
    renderDocumentList(state.app);
  };

  const actions = element("div", undefined, "document-actions");
  const primaryAction = element(
    "button",
    document
      ? document.review_status === "verified"
        ? "Lihat"
        : "Periksa"
      : "Unggah",
    "primary",
  );
  primaryAction.type = "button";
  primaryAction.setAttribute(
    "aria-label",
    document
      ? `${primaryAction.textContent} ${documentNames[documentType] || documentType}`
      : `Unggah ${documentNames[documentType] || documentType}`,
  );
  if (document) {
    primaryAction.onclick = () => selectDocument(documentType);
  } else {
    primaryAction.onclick = () => fileInput.click();
  }
  actions.append(primaryAction);

  if (document) {
    const replaceButton = element("button", "Ganti");
    replaceButton.type = "button";
    replaceButton.setAttribute(
      "aria-label",
      `Ganti berkas ${documentNames[documentType] || documentType}`,
    );
    replaceButton.onclick = () => {
      if (
        !confirm(
          `Ganti berkas ${documentNames[documentType] || documentType}? Versi baru perlu diperiksa kembali dan dapat mengubah hasil administrasi.`,
        )
      ) {
        return;
      }
      fileInput.click();
    };
    actions.append(replaceButton);
  }

  row.append(name, status, actions, fileInput);
  const uploadState = state.uploads[documentType];
  if (uploadState) row.append(renderUploadSelection(documentType, uploadState));
  return row;
}

function allDocumentTypes(application) {
  return [
    ...requiredDocumentTypes(application),
    ...additionalDocumentTypes(application),
  ];
}

function renderDocumentTabs(application) {
  const tabs = $("document-tabs");
  tabs.replaceChildren();
  for (const documentType of allDocumentTypes(application)) {
    const document = application.documents[documentType];
    const displayStatus = document
      ? document.review_status === "verified"
        ? "verified"
        : "needs_review"
      : "missing";
    const tab = element("button", undefined, "document-tab");
    tab.type = "button";
    tab.setAttribute("role", "tab");
    tab.dataset.documentTab = documentType;
    tab.setAttribute("aria-controls", document ? "doc-workspace" : "doc-empty");
    tab.setAttribute("aria-selected", String(documentType === state.kind));
    tab.tabIndex = documentType === state.kind ? 0 : -1;
    tab.append(
      element("span", documentNames[documentType] || documentType),
      element("small", documentStatusLabels[displayStatus] || displayStatus),
    );
    tab.onclick = () => selectDocument(documentType);
    tab.onkeydown = (event) => navigateTabs(event, "[data-document-tab]");
    tabs.append(tab);
  }
}

function openFilePicker(documentType) {
  $("document-completeness").open = true;
  const input = [...document.querySelectorAll("[data-upload-input]")].find(
    (candidate) => candidate.dataset.uploadInput === documentType,
  );
  input?.click();
}

function renderUploadSelection(documentType, uploadState) {
  const selection = element("div", undefined, "upload-selection");
  selection.append(
    element(
      "p",
      `${uploadState.replacing ? "Berkas pengganti" : "Berkas"} dipilih: ${uploadState.file.name}`,
      "selected-file",
    ),
  );

  const actions = element("div", undefined, "upload-confirmation-actions");
  const cancelButton = element("button", "Batal");
  cancelButton.type = "button";
  cancelButton.onclick = () => {
    delete state.uploads[documentType];
    renderDocumentList(state.app);
  };
  const uploadButton = element(
    "button",
    uploadState.uploading ? "Mengunggah..." : "Unggah",
    "primary",
  );
  uploadButton.type = "button";
  uploadButton.onclick = () => uploadDocument(documentType);
  actions.append(cancelButton, uploadButton);
  selection.append(actions);

  if (uploadState.error) {
    const error = element("p", uploadState.error, "upload-error");
    error.setAttribute("role", "alert");
    selection.append(error);
  }
  return selection;
}

function selectDocument(documentType) {
  if (state.kind === documentType) {
    $(currentDocument() ? "doc-workspace" : "doc-empty").scrollIntoView({ block: "start" });
    return;
  }
  if (
    hasReviewDraft() &&
    !confirm("Pindah dokumen dan buang perubahan yang belum disimpan?")
  ) {
    return;
  }
  clearNotice();
  state.kind = documentType;
  state.highlightedEvidenceIds = [];
  renderDocumentList(state.app);
  renderDocumentTabs(state.app);
  renderDocument();
  $(currentDocument() ? "doc-workspace" : "doc-empty").scrollIntoView({ block: "start" });
}

async function uploadDocument(documentType) {
  const uploadState = state.uploads[documentType];
  if (!uploadState?.file || uploadState.uploading || state.busy) return;
  if (
    hasReviewDraft() &&
    !confirm(
      "Unggah berkas dan buang perubahan pemeriksaan yang belum disimpan?",
    )
  ) {
    return;
  }

  state.busy = true;
  uploadState.uploading = true;
  uploadState.error = null;
  clearNotice();
  renderDocumentList(state.app);
  setControlsDisabled(true);
  let uploadCompleted = false;

  try {
    const body = new FormData();
    body.append("file", uploadState.file);
    body.append("document_type", documentType);
    body.append("expected_revision", state.app.revision);
    const result = await api(applicationPath("/documents"), body);
    uploadCompleted = true;
    delete state.uploads[documentType];
    state.kind = documentType;
    state.app = await api(
      `/applications/${encodeURIComponent(state.app.application_id)}`,
    );
    renderApplication();
    await listApplications();
    notice(
      result.deduplicated
        ? "Berkas yang sama sudah tersedia. Tidak ada versi baru yang dibuat."
        : "Berkas berhasil diunggah. Periksa dokumen atau baca datanya saat siap.",
    );
  } catch (error) {
    uploadState.error = uploadCompleted
      ? "Berkas mungkin sudah terunggah, tetapi data terbaru gagal dimuat. Gunakan Muat ulang sebelum melanjutkan."
      : error.status === 409
        ? "Data sudah berubah. Muat ulang dan pilih berkas kembali sebelum mengunggah."
        : error.message;
  } finally {
    state.busy = false;
    const currentUpload = state.uploads[documentType];
    if (currentUpload) currentUpload.uploading = false;
    renderDocumentList(state.app);
    setControlsDisabled(false);
  }
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("id-ID", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function renderHistory(application) {
  $("history").replaceChildren();
  for (const review of [...application.history].reverse()) {
    const item = element("article", undefined, "history-item");
    item.append(
      element(
        "div",
        reviewActionLabels[review.action_type] || review.action_type,
        "history-action",
      ),
      element("p", review.reason),
      element(
        "div",
        `${formatDate(review.created_at)} - Versi data ${review.resulting_revision}`,
        "history-meta",
      ),
    );
    $("history").append(item);
  }
  if (!application.history.length) {
    $("history").append(
      element("p", "Belum ada tindakan admin yang tersimpan.", "muted"),
    );
  }
}

function hasReviewDraft() {
  return Boolean(
    $("reason").value ||
      [...document.querySelectorAll("[data-field]")].some(
        (input) => input.value !== input.dataset.initial,
      ),
  );
}

function hasPendingChanges() {
  return Boolean(
    hasReviewDraft() ||
      $("reject-reason").value ||
      Object.keys(state.uploads).length,
  );
}

function highlight(evidenceIds) {
  const image = $("document-image");
  const overlay = $("overlay");
  const imageWrap = image.parentElement;
  state.highlightedEvidenceIds = evidenceIds;
  overlay.replaceChildren();
  if (!image.naturalWidth || !image.naturalHeight) return;
  const scale = Math.min(
    imageWrap.clientWidth / image.naturalWidth,
    imageWrap.clientHeight / image.naturalHeight,
  );
  const renderedWidth = image.naturalWidth * scale;
  const renderedHeight = image.naturalHeight * scale;
  overlay.style.left = `${(imageWrap.clientWidth - renderedWidth) / 2}px`;
  overlay.style.top = `${(imageWrap.clientHeight - renderedHeight) / 2}px`;
  overlay.style.width = `${renderedWidth}px`;
  overlay.style.height = `${renderedHeight}px`;
  overlay.setAttribute(
    "viewBox",
    `0 0 ${image.naturalWidth} ${image.naturalHeight}`,
  );
  for (const block of currentDocument()?.blocks || []) {
    if (!evidenceIds.includes(block.block_id) || !block.polygon) continue;
    const polygon = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "polygon",
    );
    polygon.setAttribute(
      "points",
      block.polygon.map((point) => point.join(",")).join(" "),
    );
    overlay.append(polygon);
  }
}

function fieldPlaceholder(field) {
  if (field.status === "not_found") return "Tidak ditemukan";
  if (field.status === "not_applicable") return "Tidak diperlukan";
  return "Belum terbaca";
}

function renderField(key, selectedDocument) {
  const field = selectedDocument.fields[key] || {};
  const wrapper = element("div", undefined, "field");
  const header = element("div", undefined, "field-header");
  const fieldLabel = element("label", fieldNames[key] || key);
  fieldLabel.htmlFor = `field-${key}`;
  header.append(
    fieldLabel,
    element(
      "span",
      fieldStatusLabels[field.status] || "Belum dibaca",
      "field-status",
    ),
  );

  const input = element(key === "kesimpulan_dokter" ? "textarea" : "input");
  input.id = `field-${key}`;
  input.dataset.field = key;
  input.value = field.value ?? "";
  input.dataset.initial = input.value;
  input.placeholder = fieldPlaceholder(field);
  input.maxLength = 2000;
  wrapper.append(header, input);

  if (state.kind === "KTP" && key === "nik") {
    wrapper.append(element("p", "Nomor dokumen KTP mengikuti NIK.", "field-source"));
  }
  if (field.raw_text || field.evidence_ids?.length) {
    const sourceRow = element("div", undefined, "field-source");
    sourceRow.append(
      element(
        "span",
        field.raw_text ? `Teks terbaca: ${field.raw_text}` : "Teks sumber tersedia",
      ),
    );
    for (const evidenceId of field.evidence_ids || []) {
      const button = element("button", "Lihat teks sumber", "evidence");
      button.type = "button";
      button.title = `Sorot blok ${evidenceId}`;
      button.onclick = () => highlight([evidenceId]);
      sourceRow.append(button);
    }
    wrapper.append(sourceRow);
  } else if (field.source_kind === "review") {
    wrapper.append(element("p", "Nilai berasal dari koreksi admin.", "field-source"));
  }
  return wrapper;
}

function fieldGroups(selectedDocument) {
  const extraGroups = {
    KK: { main: ["nomor_dokumen", "nama", "nik", "tanggal_lahir", "alamat"], additional: [] },
    TRANSKRIP: { main: ["nama", "institusi", "nomor_dokumen"], additional: ["nik", "tanggal_lahir", "pendidikan_terakhir"] },
    SKCK: { main: ["nama", "nomor_dokumen", "tanggal_terbit", "tanggal_berakhir"], additional: ["nik", "tanggal_lahir", "alamat"] },
    MCU: { main: ["nama", "tanggal_pemeriksaan", "kesimpulan_dokter", "nomor_dokumen"], additional: ["nik", "tanggal_lahir"] },
  };
  if (extraGroups[state.kind]) return extraGroups[state.kind];
  if (state.kind === "KTP") {
    return { main: ["nama", "nik", "tanggal_lahir", "alamat"], additional: [] };
  }
  if (state.kind === "IJAZAH") {
    return {
      main: ["nama", "pendidikan_terakhir", "nomor_dokumen"],
      additional: ["nik", "tanggal_lahir"],
    };
  }
  const present = Object.keys(fieldNames).filter((key) => {
    const field = selectedDocument.fields[key];
    return field && (field.value || !["not_found", "not_applicable"].includes(field.status));
  });
  return {
    main: present.includes("nomor_dokumen") ? ["nomor_dokumen"] : present.slice(0, 1),
    additional: present.filter((key) => key !== "nomor_dokumen"),
  };
}

function renderDocument() {
  const selectedDocument = currentDocument();
  $("doc-empty").hidden = Boolean(selectedDocument);
  $("doc-workspace").hidden = !selectedDocument;
  $("reason").value = "";
  $("confirmed").checked = false;
  $("fields").replaceChildren();
  $("blocks").replaceChildren();
  $("overlay").replaceChildren();
  state.highlightedEvidenceIds = [];
  if (!selectedDocument) {
    const name = documentNames[state.kind] || state.kind || "Dokumen";
    $("doc-empty-title").textContent = `${name} belum diunggah`;
    $("doc-empty-text").textContent = "Unggah berkas JPG atau PNG satu halaman untuk mulai memeriksa dokumen ini.";
    $("doc-empty-upload").setAttribute("aria-label", `Unggah ${name}`);
    $("doc-empty-upload").onclick = () => openFilePicker(state.kind);
    return;
  }

  const displayStatus =
    selectedDocument.review_status === "verified" ? "verified" : "needs_review";
  const readableStatus = documentStatusLabels[displayStatus];
  $("document-title").textContent = documentNames[state.kind] || state.kind;
  $("document-status").textContent = readableStatus;
  $("document-status").className = `status-label status-${displayStatus}`;
  $("technical-document-id").textContent = selectedDocument.version_id;
  $("technical-document-version").textContent = selectedDocument.version_number;
  $("technical-document-status").textContent = selectedDocument.review_status;
  $("process").textContent = Object.keys(selectedDocument.fields).length
    ? "Baca ulang dokumen"
    : "Baca data dari dokumen";

  const source = `/api/v1/documents/${selectedDocument.version_id}/content`;
  $("document-image").src = source;
  $("original").href = source;
  $("document-image").onload = () => highlight(state.highlightedEvidenceIds);
  $("document-image").onerror = () =>
    notice(
      "Gambar tidak dapat dimuat. Buka gambar di tab baru atau muat ulang data.",
      true,
    );

  const groups = fieldGroups(selectedDocument);
  if (state.kind === "MCU") {
    $("fields").append(element("p", "Salin kesimpulan yang tertulis. Aplikasi tidak menafsirkan hasil laboratorium atau menentukan kelayakan kesehatan.", "helper-text"));
  }
  if (state.kind === "TRANSKRIP") {
    $("fields").append(element("p", "Ekstraksi dasar identitas dan institusi. Tabel nilai tetap diperiksa manual.", "helper-text"));
  }
  if (state.kind === "KK") {
    $("fields").append(element("p", "Pilih anggota yang merupakan peserta, lalu cocokkan nama dan NIK dengan KTP serta gambar KK. Kepala keluarga tidak dipilih otomatis. Jika bacaan salah, koreksi identitas di bawah.", "helper-text"));
    for (const member of selectedDocument.members || []) {
      const button = element("button", `Pilih ${member.nama.value || "nama belum terbaca"} — ${member.nik.value || "NIK belum terbaca"}`, "button secondary");
      button.type = "button";
      button.disabled = !member.nama.value || !member.nik.value;
      button.onclick = () => {
        if (hasReviewDraft() && !confirm("Pilihan anggota akan mengganti nama, NIK, dan tanggal lahir pada form. Lanjutkan?")) return;
        for (const key of ["nama", "nik", "tanggal_lahir"]) {
          const input = $(`field-${key}`);
          input.value = member[key].value || "";
        }
        $("confirmed").checked = false;
        highlight([...new Set(Object.values(member).flatMap(f => f.evidence_ids || []))]);
        notice("Anggota dipilih pada form, belum disimpan. Cocokkan dengan gambar dan isi catatan pemeriksaan.");
      };
      $("fields").append(button);
    }
  }
  for (const key of groups.main) {
    $("fields").append(renderField(key, selectedDocument));
  }
  if (groups.additional.length) {
    const details = element("details", undefined, "additional-fields");
    const needsReview = groups.additional.some((key) =>
      ["ambiguous", "extracted"].includes(selectedDocument.fields[key]?.status),
    );
    details.append(
      element(
        "summary",
        needsReview ? "Data tambahan - perlu diperiksa" : "Data tambahan",
      ),
    );
    for (const key of groups.additional) {
      details.append(renderField(key, selectedDocument));
    }
    $("fields").append(details);
  }

  for (const block of selectedDocument.blocks) {
    const confidence = Number(block.confidence);
    const score = Number.isFinite(confidence) ? confidence.toFixed(3) : "tidak ada";
    const button = element(
      "button",
      `Blok ${block.block_id}: ${block.text} - skor model ${score}`,
      "block",
    );
    button.type = "button";
    button.onclick = () => highlight([block.block_id]);
    $("blocks").append(button);
  }
  if (!selectedDocument.blocks.length) {
    $("blocks").append(
      element("p", "Belum ada detail teks hasil pembacaan.", "muted"),
    );
  }
}

function applicationPath(suffix) {
  return `/applications/${state.app.application_id}${suffix}`;
}

function navigateTabs(event, selector) {
  const tabs = [...document.querySelectorAll(selector)];
  const currentIndex = tabs.indexOf(event.currentTarget);
  let nextIndex;
  if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
  else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
  else if (event.key === "Home") nextIndex = 0;
  else if (event.key === "End") nextIndex = tabs.length - 1;
  else return;
  event.preventDefault();
  const nextTabName = tabs[nextIndex].dataset.mainTab;
  const nextDocumentType = tabs[nextIndex].dataset.documentTab;
  tabs[nextIndex].click();
  const updatedTab = nextTabName
    ? document.querySelector(`[data-main-tab="${nextTabName}"]`)
    : [...document.querySelectorAll("[data-document-tab]")].find(
        (tab) => tab.dataset.documentTab === nextDocumentType,
      );
  updatedTab?.focus();
}

function activateMainTab(tabName) {
  state.mainTab = tabName;
  for (const tab of document.querySelectorAll("[data-main-tab]")) {
    const active = tab.dataset.mainTab === tabName;
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    $(`panel-${tab.dataset.mainTab}`).hidden = !active;
  }
}

async function refresh() {
  if (
    hasPendingChanges() &&
    !confirm("Muat ulang dan buang perubahan yang belum disimpan?")
  ) {
    return;
  }
  state.uploads = {};
  $("reject-reason").value = "";
  clearNotice();
  if (state.app) {
    await selectApplication(state.app.application_id);
  } else {
    await listApplications();
  }
  notice("Data terbaru sudah dimuat.");
}

$("refresh").onclick = () => run(refresh);
$("prev").onclick = () =>
  run(async () => {
    clearNotice();
    state.offset = Math.max(0, state.offset - 20);
    await listApplications();
  });
$("next").onclick = () =>
  run(async () => {
    clearNotice();
    state.offset += 20;
    await listApplications();
  });
$("new").onclick = () => {
  if (!state.busy) $("create-dialog").showModal();
};
$("cancel-create").onclick = () => $("create-dialog").close();
for (const tab of document.querySelectorAll("[data-main-tab]")) {
  tab.onclick = () => activateMainTab(tab.dataset.mainTab);
  tab.onkeydown = (event) => navigateTabs(event, "[data-main-tab]");
}

$("create-form").onsubmit = (event) => {
  event.preventDefault();
  run(async () => {
    const application = await api("/applications", {
      rule_version_id: $("create-profile").value,
    });
    $("create-dialog").close();
    state.offset = 0;
    await selectApplication(application.application_id);
    notice("Calon peserta ditambahkan. Unggah dokumen sintetis untuk memulai.");
  });
};

$("process").onclick = () => {
  const selectedDocument = currentDocument();
  if (
    (Object.keys(selectedDocument.fields).length ||
      selectedDocument.review_status === "verified") &&
    !confirm(
      "Membaca ulang akan menghapus koreksi aktif dan status verifikasi dokumen ini. Lanjutkan?",
    )
  ) {
    return;
  }
  run(async () => {
    notice(
      "Dokumen sedang dibaca. Tunggu sampai selesai dan jangan mengirim ulang.",
    );
    const result = await api(`/documents/${selectedDocument.version_id}/process`, {
      expected_revision: state.app.revision,
    });
    await selectApplication(state.app.application_id);
    notice(
      result.status === "SUCCEEDED"
        ? "Pembacaan selesai. Cocokkan data dengan gambar sebelum verifikasi."
        : result.status === "MANUAL_ONLY"
          ? "Dokumen ini tidak dibaca otomatis dan perlu diperiksa manual."
          : `${processingFailureMessage(result.error_code)} Hasil ini bukan ketidaklayakan peserta.`,
      result.status === "FAILED",
    );
  });
};

async function review(action) {
  if (!$("reason").value.trim()) {
    notice("Isi catatan pemeriksaan terlebih dahulu.", true);
    return;
  }
  if (action === "verify" && !$("confirmed").checked) {
    notice("Cocokkan data dengan gambar dan centang konfirmasi.", true);
    return;
  }

  const corrections = {};
  if (action === "verify") {
    for (const input of document.querySelectorAll("[data-field]")) {
      if (input.value !== input.dataset.initial) {
        corrections[input.dataset.field] = input.value.trim() || null;
      }
    }
  }

  const body = {
    expected_revision: state.app.revision,
    document_version_id: currentDocument().version_id,
    action,
    corrections,
    reason: $("reason").value.trim(),
    reviewed_page: 1,
  };
  await api(applicationPath("/reviews"), body);
  await selectApplication(state.app.application_id);
  notice(
    action === "verify"
      ? `Pemeriksaan disimpan. Hasil administrasi: ${statusText(state.app.outcome)}.`
      : "Permintaan unggah ulang dicatat di aplikasi. Belum ada notifikasi yang dikirim kepada peserta.",
  );
}

$("review-form").onsubmit = (event) => {
  event.preventDefault();
  run(() => review("verify"));
};
$("reupload").onclick = () => run(() => review("request_reupload"));
$("evaluate").onclick = () =>
  run(async () => {
    if (
      hasPendingChanges() &&
      !confirm("Periksa ulang dan buang perubahan yang belum disimpan?")
    ) {
      return;
    }
    state.uploads = {};
    $("reject-reason").value = "";
    await api(applicationPath("/evaluate"), {
      expected_revision: state.app.revision,
    });
    await selectApplication(state.app.application_id);
    notice(`Persyaratan diperiksa ulang: ${statusText(state.app.outcome)}.`);
  });
$("reject").onclick = () => {
  const reason = $("reject-reason").value.trim();
  if (!reason) {
    notice("Isi alasan konfirmasi terlebih dahulu.", true);
    return;
  }
  if (
    !confirm(
      "Konfirmasi hasil tidak memenuhi syarat berdasarkan evaluasi ini?",
    )
  ) {
    return;
  }
  run(async () => {
    await api(applicationPath("/confirm-ineligible"), {
      expected_revision: state.app.revision,
      evaluation_id: state.app.evaluation.evaluation_id,
      reason,
    });
    $("reject-reason").value = "";
    await selectApplication(state.app.application_id);
    notice("Hasil tidak memenuhi syarat telah dikonfirmasi admin.");
  });
};

run(listApplications);
