"use strict";

const $ = (id) => document.getElementById(id);
const state = { app: null, kind: null, offset: 0, busy: false };
const fieldNames = {
  nama: "Nama lengkap",
  nik: "NIK",
  tanggal_lahir: "Tanggal lahir (YYYY-MM-DD)",
  alamat: "Alamat",
  pendidikan_terakhir: "Pendidikan terakhir",
  nomor_dokumen: "Nomor dokumen",
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

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function notice(message, error = false) {
  $("notice").hidden = false;
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
}

function badge(value) {
  return element("span", value, `badge ${value}`);
}

function currentDocument() {
  return state.app?.documents[state.kind];
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

async function run(action) {
  if (state.busy) return;
  state.busy = true;
  const controls = [
    ...document.querySelectorAll("button,input,select,textarea"),
  ];
  const disabled = controls.map((control) => control.disabled);
  controls.forEach((control) => {
    control.disabled = true;
  });
  try {
    await action();
  } catch (error) {
    notice(
      error.status === 409
        ? "Data telah berubah. Klik Muat ulang, periksa kembali data terbaru, lalu ulangi aksi. Perubahan ini belum disimpan."
        : error.message,
      true,
    );
  } finally {
    controls.forEach((control, index) => {
      control.disabled = disabled[index];
    });
    state.busy = false;
  }
}

async function listApplications() {
  const applications = await api(
    `/applications?limit=20&offset=${state.offset}`,
  );
  $("applications").replaceChildren();
  for (const application of applications) {
    const button = element(
      "button",
      undefined,
      `app-item${
        application.application_id === state.app?.application_id ? " active" : ""
      }`,
    );
    button.append(
      element("div", application.application_id.slice(0, 12), "mono"),
      element("div", application.rule_version_id, "muted"),
      badge(application.outcome),
    );
    button.onclick = () => {
      if (
        hasUnsavedReview() &&
        !confirm("Pindah pendaftaran dan buang isian review yang belum disimpan?")
      ) {
        return;
      }
      run(() => selectApplication(application.application_id));
    };
    $("applications").append(button);
  }
  if (!applications.length) {
    $("applications").append(
      element("p", "Belum ada pendaftaran pada halaman ini.", "muted"),
    );
  }
  $("prev").hidden = state.offset === 0;
  $("next").hidden = applications.length < 20;
}

async function selectApplication(applicationId) {
  state.app = await api(`/applications/${encodeURIComponent(applicationId)}`);
  if (!state.app.documents[state.kind]) {
    state.kind = Object.keys(state.app.documents)[0] || null;
  }
  renderApplication();
  await listApplications();
}

function renderApplication() {
  const application = state.app;
  $("empty").hidden = true;
  $("workspace").hidden = false;
  $("app-name").textContent = application.data?.nama || "Peserta baru";
  $("app-meta").textContent =
    `${application.application_id} · Revision ${application.revision}`;
  $("profile").textContent =
    `${application.rule_version_id} · 18–30 TAHUN · MINIMAL SMA`;
  $("outcome").textContent = application.outcome;
  $("outcome").className = `badge ${application.outcome}`;
  $("missing").textContent = application.missing_documents.length
    ? `Belum diupload: ${application.missing_documents.join(", ")}`
    : "Semua jenis dokumen wajib telah diupload. Status verifikasi diperiksa terpisah.";

  $("rules").replaceChildren();
  for (const rule of application.evaluation?.results || []) {
    const card = element("div", undefined, "rule");
    const top = element("div", undefined, "rule-top");
    top.append(
      element("span", ruleNames[rule.rule_code] || rule.rule_code),
      badge(rule.result),
    );
    card.append(top, element("p", rule.reason));
    if (rule.next_action) {
      card.append(element("p", `Tindak lanjut: ${rule.next_action}`));
    }
    $("rules").append(card);
  }
  if (!application.evaluation) {
    $("rules").append(
      element(
        "p",
        "Belum dievaluasi. Upload dan proses dokumen untuk memulai.",
        "muted",
      ),
    );
  }

  $("reject-area").hidden = application.outcome !== "FLAGGED";
  $("tabs").replaceChildren();
  for (const [documentType, document] of Object.entries(application.documents)) {
    const button = element(
      "button",
      documentType + (document.review_status === "verified" ? " ✓" : ""),
      documentType === state.kind ? "active" : "",
    );
    button.onclick = () => {
      if (state.busy) return;
      if (
        hasUnsavedReview() &&
        !confirm("Pindah dokumen dan buang isian review yang belum disimpan?")
      ) {
        return;
      }
      state.kind = documentType;
      renderApplication();
    };
    $("tabs").append(button);
  }
  renderDocument();

  $("history").replaceChildren();
  for (const review of [...application.history].reverse()) {
    const item = element("div", undefined, "history-item");
    item.append(
      element(
        "strong",
        `${review.action_type} · Revision ${review.resulting_revision}`,
      ),
      element("p", review.reason),
      element("small", review.created_at, "muted"),
    );
    $("history").append(item);
  }
  if (!application.history.length) {
    $("history").append(element("p", "Belum ada review admin.", "muted"));
  }
}

function hasUnsavedReview() {
  return Boolean(
    $("reason").value ||
      [...document.querySelectorAll("[data-field]")].some(
        (input) => input.value !== input.dataset.initial,
      ),
  );
}

function highlight(evidenceIds) {
  const image = $("document-image");
  const overlay = $("overlay");
  overlay.replaceChildren();
  if (!image.naturalWidth) return;
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

function renderDocument() {
  const document = currentDocument();
  $("doc-empty").hidden = Boolean(document);
  $("doc-workspace").hidden = !document;
  $("reason").value = "";
  $("confirmed").checked = false;
  $("fields").replaceChildren();
  $("blocks").replaceChildren();
  $("overlay").replaceChildren();
  if (!document) return;

  $("doc-meta").textContent =
    `${state.kind} · Versi ${document.version_number} · ${document.review_status}`;
  $("process").textContent = Object.keys(document.fields).length
    ? "Proses ulang OCR + LLM"
    : "Jalankan OCR + LLM";
  const source = `/api/v1/documents/${document.version_id}/content`;
  $("document-image").src = source;
  $("original").href = source;
  $("document-image").onerror = () =>
    notice(
      "Gambar gagal dimuat. Buka ukuran asli atau muat ulang pendaftaran.",
      true,
    );

  for (const [key, label] of Object.entries(fieldNames)) {
    const field = document.fields[key] || {};
    const wrapper = element("div", undefined, "field");
    const fieldLabel = element("label", label);
    fieldLabel.htmlFor = `field-${key}`;
    const input = element("input");
    input.id = `field-${key}`;
    input.dataset.field = key;
    input.value = field.value ?? "";
    input.dataset.initial = input.value;
    input.maxLength = 2000;
    wrapper.append(
      fieldLabel,
      input,
      element(
        "p",
        (field.status || "Belum diekstrak") +
          (field.raw_text ? ` · OCR: ${field.raw_text}` : ""),
        "muted",
      ),
    );
    for (const evidenceId of field.evidence_ids || []) {
      const button = element("button", `Bukti ${evidenceId}`, "evidence");
      button.type = "button";
      button.onclick = () => highlight([evidenceId]);
      wrapper.append(button);
    }
    if (field.source_kind === "review") {
      wrapper.append(
        element("p", "Sumber nilai: koreksi admin pada gambar.", "muted"),
      );
    }
    $("fields").append(wrapper);
  }

  for (const block of document.blocks) {
    const button = element(
      "button",
      `${block.block_id} · ${block.text} · skor OCR ${Number(block.confidence).toFixed(3)}`,
      "block",
    );
    button.type = "button";
    button.onclick = () => highlight([block.block_id]);
    $("blocks").append(button);
  }
  if (!document.blocks.length) {
    $("blocks").append(element("p", "Belum ada bukti OCR.", "muted"));
  }
}

function applicationPath(suffix) {
  return `/applications/${state.app.application_id}${suffix}`;
}

async function refresh() {
  if (
    hasUnsavedReview() &&
    !confirm("Muat ulang dan buang isian review yang belum disimpan?")
  ) {
    return;
  }
  if (state.app) {
    await selectApplication(state.app.application_id);
  } else {
    await listApplications();
  }
  notice("Data terbaru dimuat.");
}

$("refresh").onclick = () => run(refresh);
$("prev").onclick = () =>
  run(async () => {
    state.offset = Math.max(0, state.offset - 20);
    await listApplications();
  });
$("next").onclick = () =>
  run(async () => {
    state.offset += 20;
    await listApplications();
  });
$("new").onclick = () => {
  if (!state.busy) $("create-dialog").showModal();
};
$("cancel-create").onclick = () => $("create-dialog").close();

$("create-form").onsubmit = (event) => {
  event.preventDefault();
  run(async () => {
    const application = await api("/applications", {
      rule_version_id: $("create-profile").value,
    });
    $("create-dialog").close();
    state.offset = 0;
    await selectApplication(application.application_id);
    notice("Pendaftaran dibuat. Upload dokumen sintetis untuk memulai.");
  });
};

$("upload-form").onsubmit = (event) => {
  event.preventDefault();
  const file = $("upload-file").files[0];
  if (!file) return;
  const documentType = $("upload-kind").value;
  if (
    state.app.documents[documentType] &&
    !confirm(`Upload versi baru ${documentType}? Versi baru harus diperiksa kembali.`)
  ) {
    return;
  }
  run(async () => {
    const body = new FormData();
    body.append("file", file);
    body.append("document_type", documentType);
    body.append("expected_revision", state.app.revision);
    const result = await api(applicationPath("/documents"), body);
    state.kind = documentType;
    $("upload-file").value = "";
    await selectApplication(state.app.application_id);
    notice(
      result.deduplicated
        ? "File yang sama sudah tersedia."
        : "Upload berhasil. Jalankan pemrosesan atau tinjau gambar.",
    );
  });
};

$("process").onclick = () => {
  const document = currentDocument();
  if (
    (Object.keys(document.fields).length || document.review_status === "verified") &&
    !confirm(
      "Proses ulang akan menghapus koreksi aktif dan status verifikasi dokumen ini. Lanjutkan?",
    )
  ) {
    return;
  }
  run(async () => {
    notice(
      "Memproses dokumen. Tunggu respons OCR dan LLM; jangan tutup atau kirim ulang.",
    );
    const result = await api(`/documents/${document.version_id}/process`, {
      expected_revision: state.app.revision,
    });
    await selectApplication(state.app.application_id);
    notice(
      result.status === "SUCCEEDED"
        ? "Ekstraksi selesai. Periksa gambar dan nilai sebelum verifikasi."
        : result.status === "MANUAL_ONLY"
        ? "Dokumen ini memerlukan pemeriksaan manual."
        : `Pemrosesan belum berhasil: ${result.error_code || result.status}`,
      result.status === "FAILED",
    );
  });
};

async function review(action) {
  if (!$("reason").value.trim()) {
    notice("Isi catatan review terlebih dahulu.", true);
    return;
  }
  if (action === "verify" && !$("confirmed").checked) {
    notice("Periksa gambar dan centang konfirmasi terlebih dahulu.", true);
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
      ? `Review disimpan. Hasil administrasi: ${state.app.outcome}`
      : "Permintaan upload ulang dicatat.",
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
      hasUnsavedReview() &&
      !confirm("Evaluasi ulang dan buang isian review yang belum disimpan?")
    ) {
      return;
    }
    await api(applicationPath("/evaluate"), {
      expected_revision: state.app.revision,
    });
    await selectApplication(state.app.application_id);
    notice(`Evaluasi diperbarui: ${state.app.outcome}`);
  });
$("reject").onclick = () => {
  const reason = $("reject-reason").value.trim();
  if (!reason) {
    notice("Isi alasan konfirmasi terlebih dahulu.", true);
    return;
  }
  if (
    !confirm(
      "Konfirmasi tidak memenuhi syarat administrasi berdasarkan evaluasi ini?",
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
    await selectApplication(state.app.application_id);
    notice("Konfirmasi admin disimpan.");
  });
};

run(listApplications);
