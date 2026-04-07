function resolveApiBase() {
  try {
    const override = localStorage.getItem("apiBaseOverride");
    if (typeof override === "string" && override.trim()) {
      return override.trim().replace(/\/+$/, "");
    }
  } catch {
    // ignore storage access errors and fall back to location-derived API base
  }

  if (window.location.protocol === "file:") {
    return "http://localhost:8000/api";
  }

  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  const host = window.location.hostname || "localhost";
  const port = window.location.port || "";

  // Standalone static frontend mode: serve the page from any host/port, but keep
  // the FastAPI backend on the same host at :8000.
  if (port && port !== "80" && port !== "443" && port !== "8000") {
    return `${protocol}//${host}:8000/api`;
  }

  // Reverse-proxy/single-domain mode: API is served from the current origin.
  // This also keeps localhost/127.0.0.1 working when the page is hosted on :8000.
  if (window.location.origin && window.location.origin !== "null") {
    return `${window.location.origin.replace(/\/+$/, "")}/api`;
  }

  return `${protocol}//${host}:8000/api`;
}

const API_BASE = resolveApiBase();
const SESSION_STORAGE_KEY = "chatSessionsV2";
const ACTIVE_SESSION_KEY = "activeChatSessionIdV2";
const PREDICTION_TEMPLATE_STORAGE_KEY = "predictionTemplatesV1";
const MAX_SESSIONS = 30;
const MAX_MESSAGES_PER_SESSION = 120;
const SIDEBAR_BREAKPOINT = 900;
const RIGHT_SIDEBAR_TABS = new Set(["attachments", "citations"]);

const app = document.getElementById("app");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebarBackdrop = document.getElementById("sidebarBackdrop");

const welcomePanel = document.getElementById("welcomePanel");
const chat = document.getElementById("chat");
const panelFiles = document.getElementById("panelFiles");
const panelContractReview = document.getElementById("panelContractReview");
const panelOpponentPrediction = document.getElementById("panelOpponentPrediction");
const panelStatus = document.getElementById("panelStatus");
const citationSidebar = document.getElementById("citationSidebar");
const citationSidebarBody = document.getElementById("citationSidebarBody");
const citationSidebarTitle = document.getElementById("citationSidebarTitle");
const citationSidebarClose = document.getElementById("citationSidebarClose");
const citationSidebarResize = document.getElementById("citationSidebarResize");
const composerWrap = document.getElementById("composerWrap");

const composer = document.getElementById("composer");
const input = document.getElementById("input");
const reviewUploadBtn = document.getElementById("reviewUploadBtn");
const chatAttachmentInput = document.getElementById("chatAttachmentInput");
const reviewContractInput = document.getElementById("reviewContractInput");
const chatAttachmentTray = document.getElementById("chatAttachmentTray");
const rightSidebarAttachmentsBody = document.getElementById("rightSidebarAttachmentsBody");
const contractReviewModeToggle = document.getElementById("contractReviewModeToggle");
const opponentPredictionModeToggle = document.getElementById("opponentPredictionModeToggle");
const similarCaseModeToggle = document.getElementById("similarCaseModeToggle");
const historyList = document.getElementById("historyList");

const menuFiles = document.getElementById("menuFiles");
const menuContractReview = document.getElementById("menuContractReview");
const menuOpponentPrediction = document.getElementById("menuOpponentPrediction");
const menuStatus = document.getElementById("menuStatus");
const uploadArea = document.getElementById("uploadArea");
const fileFeedback = document.getElementById("fileFeedback");
const templateUploadArea = document.getElementById("templateUploadArea");
const templateFileInput = document.getElementById("templateFileInput");
const templateFeedback = document.getElementById("templateFeedback");
const templateList = document.getElementById("templateList");
const templateListCount = document.getElementById("templateListCount");
const predictionCaseNameInput = document.getElementById("predictionCaseNameInput");
const predictionOpponentCorpusArea = document.getElementById("predictionOpponentCorpusArea");
const predictionOpponentCorpusInput = document.getElementById("predictionOpponentCorpusInput");
const predictionOpponentCorpusFiles = document.getElementById("predictionOpponentCorpusFiles");
const predictionCaseMaterialArea = document.getElementById("predictionCaseMaterialArea");
const predictionCaseMaterialInput = document.getElementById("predictionCaseMaterialInput");
const predictionCaseMaterialFiles = document.getElementById("predictionCaseMaterialFiles");
const predictionTemplateSaveBtn = document.getElementById("predictionTemplateSaveBtn");
const predictionTemplateActionHint = document.getElementById("predictionTemplateActionHint");
const predictionTemplateFeedback = document.getElementById("predictionTemplateFeedback");
const predictionTemplateList = document.getElementById("predictionTemplateList");
const predictionTemplateListCount = document.getElementById("predictionTemplateListCount");

const CITATION_SIDEBAR_MIN_WIDTH = 280;
const CITATION_SIDEBAR_DEFAULT_WIDTH = 360;
const CITATION_SIDEBAR_MAX_WIDTH = 720;
const rightSidebarTabButtons = Array.from(document.querySelectorAll("[data-right-sidebar-tab]"));
const rightSidebarAttachmentsPanel = document.getElementById("rightSidebarAttachmentsPanel");
const rightSidebarCitationsPanel = document.getElementById("rightSidebarCitationsPanel");

let chatSessions = loadSessions();
let activeSessionId = localStorage.getItem(ACTIVE_SESSION_KEY) || null;
let draftSessionMode = "chat";
const pendingAttachmentFilesBySession = new Map();
const pendingUploadEntriesBySession = new Map();
const reviewTempFileObjectsBySession = new Map();
const filePreviewUrlsBySession = new Map();
const promotedChatAttachmentIdsBySession = new Map();
const warnedMissingReviewFilesBySession = new Set();
const reviewFileSyncPromisesBySession = new Map();
const reviewSelectionLocksBySession = new Set();
let predictionTemplates = loadPredictionTemplates();
let pendingPredictionOpponentCorpusFiles = [];
let pendingPredictionCaseMaterialFiles = [];

function parseApiTimestamp(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return Date.now();
}

function normalizePredictionTemplateAsset(asset) {
  if (!asset || typeof asset !== "object") return null;
  const id =
    typeof asset.asset_id === "string" && asset.asset_id.trim()
      ? asset.asset_id.trim()
      : typeof asset.id === "string" && asset.id.trim()
        ? asset.id.trim()
        : null;
  const name =
    typeof asset.file_name === "string" && asset.file_name.trim()
      ? asset.file_name.trim()
      : typeof asset.name === "string" && asset.name.trim()
        ? asset.name.trim()
        : null;
  if (!id || !name) return null;

  return {
    id,
    name,
    size:
      Number.isFinite(asset.size_bytes) && asset.size_bytes >= 0
        ? asset.size_bytes
        : Number.isFinite(asset.size)
          ? asset.size
          : 0,
    type:
      typeof asset.mime_type === "string"
        ? asset.mime_type
        : typeof asset.type === "string"
          ? asset.type
          : "",
    lastModified: parseApiTimestamp(asset.updated_at ?? asset.updatedAt ?? asset.created_at ?? asset.createdAt),
    contentPreview:
      typeof asset.content_preview === "string"
        ? asset.content_preview
        : typeof asset.contentPreview === "string"
          ? asset.contentPreview
          : "",
    assetKind:
      typeof asset.asset_kind === "string" && asset.asset_kind.trim()
        ? asset.asset_kind.trim()
        : typeof asset.assetKind === "string" && asset.assetKind.trim()
          ? asset.assetKind.trim()
          : "",
  };
}

function getPredictionCaseMaterialCount(template) {
  if (!template || typeof template !== "object") return 0;
  if (Number.isFinite(template.caseMaterialCount)) return template.caseMaterialCount;
  return Array.isArray(template.caseMaterials) ? template.caseMaterials.length : 0;
}

function getPredictionOpponentCorpusCount(template) {
  if (!template || typeof template !== "object") return 0;
  if (Number.isFinite(template.opponentCorpusCount)) return template.opponentCorpusCount;
  return Array.isArray(template.opponentCorpus) ? template.opponentCorpus.length : 0;
}

function normalizeComposerMode(mode) {
  if (mode === "contract-review" || mode === "opponent-prediction" || mode === "similar-case") {
    return mode;
  }
  return "chat";
}

function normalizePredictionTemplateFileMeta(file) {
  if (!file || typeof file !== "object") return null;
  const name = typeof file.name === "string" && file.name.trim() ? file.name.trim() : null;
  if (!name) return null;

  return {
    id:
      typeof file.id === "string" && file.id.trim()
        ? file.id.trim()
        : `pf_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    name,
    size: Number.isFinite(file.size) ? file.size : 0,
    type: typeof file.type === "string" ? file.type : "",
    lastModified: Number.isFinite(file.lastModified) ? file.lastModified : Date.now(),
  };
}

function normalizePredictionTemplate(template) {
  if (!template || typeof template !== "object") return null;
  const id =
    typeof template.id === "string" && template.id.trim()
      ? template.id.trim()
      : typeof template.template_id === "string" && template.template_id.trim()
        ? template.template_id.trim()
        : null;
  const caseName =
    typeof template.caseName === "string" && template.caseName.trim()
      ? template.caseName.trim()
      : typeof template.case_name === "string" && template.case_name.trim()
        ? template.case_name.trim()
        : null;

  if (!id || !caseName) return null;

  let caseMaterials = Array.isArray(template.caseMaterials)
    ? template.caseMaterials.map(normalizePredictionTemplateAsset).filter(Boolean)
    : [];
  let opponentCorpus = Array.isArray(template.opponentCorpus)
    ? template.opponentCorpus.map(normalizePredictionTemplateAsset).filter(Boolean)
    : [];

  if (Array.isArray(template.assets)) {
    const assets = template.assets.map(normalizePredictionTemplateAsset).filter(Boolean);
    caseMaterials = assets.filter((asset) => asset.assetKind === "case_material");
    opponentCorpus = assets.filter((asset) => asset.assetKind === "opponent_corpus");
  }

  const caseMaterialCount =
    Number.isFinite(template.caseMaterialCount) && template.caseMaterialCount >= 0
      ? template.caseMaterialCount
      : Number.isFinite(template.case_material_count) && template.case_material_count >= 0
        ? template.case_material_count
        : caseMaterials.length;
  const opponentCorpusCount =
    Number.isFinite(template.opponentCorpusCount) && template.opponentCorpusCount >= 0
      ? template.opponentCorpusCount
      : Number.isFinite(template.opponent_corpus_count) && template.opponent_corpus_count >= 0
        ? template.opponent_corpus_count
        : opponentCorpus.length;

  if (caseMaterialCount === 0 && caseMaterials.length === 0) return null;

  return {
    id,
    caseName,
    caseMaterials,
    opponentCorpus,
    caseMaterialCount,
    opponentCorpusCount,
    createdAt: parseApiTimestamp(template.createdAt ?? template.created_at),
    updatedAt: parseApiTimestamp(template.updatedAt ?? template.updated_at),
  };
}

function loadPredictionTemplates() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PREDICTION_TEMPLATE_STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.map(normalizePredictionTemplate).filter(Boolean).sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

function persistPredictionTemplates() {
  predictionTemplates = predictionTemplates
    .map(normalizePredictionTemplate)
    .filter(Boolean)
    .sort((a, b) => b.updatedAt - a.updatedAt);
  localStorage.setItem(PREDICTION_TEMPLATE_STORAGE_KEY, JSON.stringify(predictionTemplates));
}

async function loadPredictionTemplatesRemote(options = {}) {
  const { silent = false } = options;
  const response = await fetch(`${API_BASE}/prediction/templates`);
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `加载案件模板失败 (${response.status})`);
  }

  const payload = await response.json();
  predictionTemplates = Array.isArray(payload)
    ? payload.map(normalizePredictionTemplate).filter(Boolean).sort((a, b) => b.updatedAt - a.updatedAt)
    : [];
  persistPredictionTemplates();
  renderPredictionTemplateList();

  if (!silent) {
    showPredictionTemplateFeedback(
      predictionTemplates.length > 0 ? `已同步 ${predictionTemplates.length} 个案件模板` : "当前暂无案件模板",
      "info",
      2200
    );
  }
  return predictionTemplates;
}

async function savePredictionTemplateRemote() {
  const caseName = typeof predictionCaseNameInput?.value === "string" ? predictionCaseNameInput.value.trim() : "";
  if (!caseName) {
    showPredictionTemplateFeedback("保存失败：案件名称必填。", "error", 5000);
    syncPredictionTemplateFormState();
    return false;
  }
  if (pendingPredictionCaseMaterialFiles.length === 0) {
    showPredictionTemplateFeedback("保存失败：请至少选择一份案情材料。", "error", 5000);
    syncPredictionTemplateFormState();
    return false;
  }

  const formData = new FormData();
  formData.append("case_name", caseName);
  const activeSession = getActiveSession();
  if (activeSession?.id) {
    formData.append("session_id", activeSession.id);
  }
  pendingPredictionCaseMaterialFiles.forEach((file) => {
    formData.append("case_materials", file);
  });
  pendingPredictionOpponentCorpusFiles.forEach((file) => {
    formData.append("opponent_corpus", file);
  });

  if (predictionTemplateSaveBtn) {
    predictionTemplateSaveBtn.disabled = true;
  }
  showPredictionTemplateFeedback("正在保存案件模板...", "info", 0);

  try {
    const response = await fetch(`${API_BASE}/prediction/templates`, {
      method: "POST",
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `保存失败 (${response.status})`);
    }
    const detail = normalizePredictionTemplate(await response.json());
    if (detail) {
      predictionTemplates = [detail, ...predictionTemplates.filter((template) => template.id !== detail.id)];
      persistPredictionTemplates();
      renderPredictionTemplateList();
    } else {
      await loadPredictionTemplatesRemote({ silent: true });
    }
    clearPredictionTemplateForm();
    showPredictionTemplateFeedback(`已保存案件模板：${caseName}`, "success", 3200);
    return true;
  } catch (err) {
    showPredictionTemplateFeedback(`保存失败：${err.message || err}`, "error", 6000);
    return false;
  } finally {
    syncPredictionTemplateFormState();
  }
}

async function deletePredictionTemplateRemote(templateId) {
  const target = predictionTemplates.find((template) => template.id === templateId);
  if (!target) {
    showPredictionTemplateFeedback("删除失败：未找到对应案件模板。", "error", 5000);
    return false;
  }

  const shouldDelete = window.confirm(`确认删除案件模板“${target.caseName}”？该操作会删除后端中的对应模板。`);
  if (!shouldDelete) {
    return false;
  }

  try {
    const response = await fetch(`${API_BASE}/prediction/templates/${encodeURIComponent(templateId)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `删除失败 (${response.status})`);
    }

    predictionTemplates = predictionTemplates.filter((template) => template.id !== templateId);
    persistPredictionTemplates();
    let activeSessionNeedsRefresh = false;
    chatSessions.forEach((session) => {
      if (!session) return;
      const wasSelected = session.predictionSelectedTemplateId === templateId;
      session.predictionTemplateCandidates = Array.isArray(session.predictionTemplateCandidates)
        ? session.predictionTemplateCandidates.filter((template) => template?.id !== templateId)
        : [];
      if (wasSelected) {
        session.predictionSelectedTemplateId = null;
        removeLatestPredictionTemplateMatchMessage(session);
        queuePredictionSelectionInvalidatedMessages(session, target);
        if (session.id === activeSessionId) {
          activeSessionNeedsRefresh = true;
        }
      }
    });
    persistSessions();
    renderPredictionTemplateList();
    showPredictionTemplateFeedback(`已删除案件模板：${target.caseName}`, "success", 2600);
    if (activeSessionNeedsRefresh) {
      const current = getActiveSession();
      if (current) {
        renderSessionMessages(current);
      }
    }
    return true;
  } catch (err) {
    showPredictionTemplateFeedback(`删除失败：${err.message || err}`, "error", 6000);
    return false;
  }
}

function getSelectedPredictionTemplateId(session) {
  const rawId = session?.predictionSelectedTemplateId;
  return typeof rawId === "string" && rawId.trim() ? rawId.trim() : null;
}

function normalizeChatAttachment(attachment) {
  if (!attachment || typeof attachment !== "object") return null;

  const id = typeof attachment.id === "string" && attachment.id.trim() ? attachment.id : null;
  const fileName =
    typeof attachment.fileName === "string" && attachment.fileName.trim()
      ? attachment.fileName
      : null;

  if (!id || !fileName) return null;

  return {
    id,
    fileName,
    status: typeof attachment.status === "string" && attachment.status.trim() ? attachment.status : "ready",
    size: Number.isFinite(attachment.size) ? attachment.size : null,
    uploadedAt: Number.isFinite(attachment.uploadedAt) ? attachment.uploadedAt : Date.now(),
    contentPreview:
      typeof attachment.contentPreview === "string"
        ? attachment.contentPreview
        : typeof attachment.content_preview === "string"
          ? attachment.content_preview
          : "",
    chatTempFileId:
      typeof attachment.chatTempFileId === "string" && attachment.chatTempFileId.trim()
        ? attachment.chatTempFileId
        : typeof attachment.chat_file_id === "string" && attachment.chat_file_id.trim()
          ? attachment.chat_file_id
          : null,
    promotedReviewFileId:
      typeof attachment.promotedReviewFileId === "string" && attachment.promotedReviewFileId.trim()
        ? attachment.promotedReviewFileId
        : null,
  };
}

function normalizeRightSidebarTab(tab) {
  return RIGHT_SIDEBAR_TABS.has(tab) ? tab : "attachments";
}

function normalizeReviewTempFile(file) {
  if (!file || typeof file !== "object") return null;

  const id =
    typeof file.id === "string" && file.id.trim()
      ? file.id
      : typeof file.file_id === "string" && file.file_id.trim()
        ? file.file_id
        : null;
  const fileName =
    typeof file.fileName === "string" && file.fileName.trim()
      ? file.fileName
      : typeof file.file_name === "string" && file.file_name.trim()
        ? file.file_name
        : null;
  if (!id || !fileName) return null;

  const uploadedAtRaw =
    file.uploadedAt ??
    file.created_at ??
    file.updated_at;
  const uploadedAtValue =
    typeof uploadedAtRaw === "number"
      ? uploadedAtRaw
      : typeof uploadedAtRaw === "string"
        ? Date.parse(uploadedAtRaw)
        : NaN;

  return {
    id,
    fileName,
    status: typeof file.status === "string" && file.status.trim() ? file.status : "ready",
    size: Number.isFinite(file.size) ? file.size : Number.isFinite(file.size_bytes) ? file.size_bytes : null,
    uploadedAt: Number.isFinite(uploadedAtValue) ? uploadedAtValue : Date.now(),
    contentPreview:
      typeof file.contentPreview === "string"
        ? file.contentPreview
        : typeof file.content_preview === "string"
          ? file.content_preview
          : "",
  };
}

function normalizeReviewTemplate(template) {
  if (!template || typeof template !== "object") return null;
  const id = typeof template.id === "string" && template.id.trim() ? template.id : null;
  const name = typeof template.name === "string" && template.name.trim() ? template.name : null;
  if (!id || !name) return null;

  return {
    id,
    name,
    score: Number.isFinite(template.score) ? template.score : null,
    confidence:
      typeof template.confidence === "string" && template.confidence.trim() ? template.confidence : "low",
    semanticScore:
      Number.isFinite(template.semanticScore)
        ? template.semanticScore
        : Number.isFinite(template.semantic_score)
          ? template.semantic_score
          : null,
    titleScore:
      Number.isFinite(template.titleScore)
        ? template.titleScore
        : Number.isFinite(template.title_score)
          ? template.title_score
          : null,
    structureScore:
      Number.isFinite(template.structureScore)
        ? template.structureScore
        : Number.isFinite(template.structure_score)
          ? template.structure_score
          : null,
    reasons: Array.isArray(template.reasons)
      ? template.reasons.filter((item) => typeof item === "string" && item.trim())
      : [],
  };
}

function formatAttachmentSize(size) {
  if (!Number.isFinite(size) || size < 0) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatUploadProgressLabel(progress, stage = "uploading") {
  if (stage === "processing") return "处理中";
  if (!Number.isFinite(progress)) return "上传中";
  return `上传中 ${Math.max(0, Math.min(100, Math.round(progress * 100)))}%`;
}

function formatUploadProgressValue(progress, stage = "uploading") {
  if (stage === "processing") {
    return 0.25;
  }
  if (!Number.isFinite(progress)) return 0;
  return Math.max(0, Math.min(1, progress));
}

function formatUploadProgressText(progress, stage = "uploading") {
  if (stage === "processing") return "…";
  return `${Math.max(0, Math.min(100, Math.round((progress || 0) * 100)))}`;
}

function formatScorePercent(score) {
  if (!Number.isFinite(score)) return "--";
  return `${Math.round(score * 100)}%`;
}

function formatConfidenceLabel(confidence) {
  if (confidence === "high") return "高";
  if (confidence === "medium") return "中";
  return "低";
}

function clearReviewTemplateState(session) {
  if (!session) return;
  session.reviewRecommendedTemplate = null;
  session.reviewTemplateCandidates = [];
  session.reviewSelectedTemplateId = null;
}

function getSelectedReviewTemplate(session) {
  if (!session) return null;

  const candidates = Array.isArray(session.reviewTemplateCandidates) ? session.reviewTemplateCandidates : [];
  const selectedTemplateId =
    typeof session.reviewSelectedTemplateId === "string" && session.reviewSelectedTemplateId.trim()
      ? session.reviewSelectedTemplateId
      : session.reviewRecommendedTemplate?.id || null;

  if (!selectedTemplateId) {
    return normalizeReviewTemplate(session.reviewRecommendedTemplate);
  }

  return (
    candidates.find((template) => template.id === selectedTemplateId) ||
    normalizeReviewTemplate(session.reviewRecommendedTemplate)
  );
}

function findLinkedReviewFileIdForAttachment(session, attachment) {
  if (!session || !attachment) return null;
  if (typeof attachment.promotedReviewFileId === "string" && attachment.promotedReviewFileId.trim()) {
    return attachment.promotedReviewFileId;
  }

  const reviewFiles = Array.isArray(session.reviewTempFiles) ? session.reviewTempFiles : [];
  const matches = reviewFiles.filter(
    (file) => file.fileName === attachment.fileName && String(file.size ?? "") === String(attachment.size ?? "")
  );
  return matches.length === 1 ? matches[0].id : null;
}

function getVisibleSessionFiles(session) {
  if (!session) return [];

  const reviewFiles = Array.isArray(session.reviewTempFiles) ? session.reviewTempFiles : [];
  const reviewFilesById = new Map(reviewFiles.map((file) => [file.id, file]));
  const linkedReviewFileIds = new Set();
  const items = [];

  const chatAttachments = Array.isArray(session.chatAttachments) ? session.chatAttachments : [];
  chatAttachments.forEach((attachment) => {
    const linkedReviewFileId = findLinkedReviewFileIdForAttachment(session, attachment);
    const linkedReviewFile = linkedReviewFileId ? reviewFilesById.get(linkedReviewFileId) : null;
    if (linkedReviewFileId) {
      linkedReviewFileIds.add(linkedReviewFileId);
    }

    items.push({
      id: linkedReviewFile?.id || attachment.id,
      fileName: linkedReviewFile?.fileName || attachment.fileName,
      size: linkedReviewFile?.size ?? attachment.size,
      attachmentId: attachment.id,
      reviewFileId: linkedReviewFile?.id || null,
      contentPreview: linkedReviewFile?.contentPreview || attachment.contentPreview || "",
    });
  });

  reviewFiles.forEach((file) => {
    if (linkedReviewFileIds.has(file.id)) return;
    items.push({
      id: file.id,
      fileName: file.fileName,
      size: file.size,
      attachmentId: null,
      reviewFileId: file.id,
      contentPreview: file.contentPreview || "",
    });
  });

  const pendingUploads = Array.from(pendingUploadEntriesBySession.get(session.id)?.values() || []).sort(
    (left, right) => left.createdAt - right.createdAt
  );
  pendingUploads.forEach((entry) => {
    items.push({
      id: entry.id,
      fileName: entry.fileName,
      size: entry.size,
      attachmentId: null,
      reviewFileId: null,
      isPendingUpload: true,
      progress: entry.progress,
      uploadStage: entry.stage,
      contentPreview: "",
    });
  });

  return items;
}

function buildReviewTemplateMatchSummary(session) {
  const selectedTemplate = getSelectedReviewTemplate(session);
  if (!selectedTemplate) {
    return "当前无可用标准模板。请先在左侧标准模板库上传模板。";
  }

  const candidates = Array.isArray(session?.reviewTemplateCandidates)
    ? session.reviewTemplateCandidates.map(normalizeReviewTemplate).filter(Boolean)
    : [];
  const reviewFileCount = Array.isArray(session?.reviewTempFiles) ? session.reviewTempFiles.length : 0;
  const candidateSummary = candidates
    .slice(0, 3)
    .map((template, index) => `${index + 1}. ${template.name}（综合 ${formatScorePercent(template.score)}）`)
    .join("\n");
  const reasons = Array.isArray(selectedTemplate.reasons) ? selectedTemplate.reasons.slice(0, 3) : [];

  return [
    `已完成标准模板匹配，本次审查将使用《${selectedTemplate.name}》。`,
    `待审文件 ${reviewFileCount} 份，匹配置信度 ${formatConfidenceLabel(selectedTemplate.confidence)}，综合得分 ${formatScorePercent(selectedTemplate.score)}。`,
    reasons.length > 0 ? `匹配依据：${reasons.join("；")}` : "",
    candidateSummary ? `候选模板：\n${candidateSummary}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

function buildReviewTemplateMessageHtml(answer, templateMatch) {
  const selectedTemplateId =
    typeof templateMatch?.selectedTemplateId === "string" && templateMatch.selectedTemplateId.trim()
      ? templateMatch.selectedTemplateId
      : null;
  const recommendedTemplateId =
    typeof templateMatch?.recommendedTemplateId === "string" && templateMatch.recommendedTemplateId.trim()
      ? templateMatch.recommendedTemplateId
      : null;
  const query =
    typeof templateMatch?.query === "string" && templateMatch.query.trim()
      ? templateMatch.query.trim()
      : "";
  const candidates = Array.isArray(templateMatch?.candidates)
    ? templateMatch.candidates.map(normalizeReviewTemplate).filter(Boolean)
    : [];

  const actions =
    query && candidates.length > 0
      ? `
        <div class="review-match-actions">
          ${candidates
            .map((template) => {
              const isSelected = template.id === selectedTemplateId;
              const isRecommended = template.id === recommendedTemplateId;
              return `
                <button
                  class="review-match-option ${isSelected ? "selected" : ""}"
                  type="button"
                  data-review-template-select="${escapeHtml(template.id)}"
                  data-review-query="${escapeHtml(encodeURIComponent(query))}"
                >
                  <span class="review-match-option-name">${escapeHtml(template.name)}</span>
                  <span class="review-match-option-meta">综合 ${escapeHtml(formatScorePercent(template.score))}</span>
                  ${isRecommended ? `<span class="review-match-option-tag">推荐</span>` : ""}
                  ${isSelected ? `<span class="review-match-option-tag">当前</span>` : ""}
                </button>
              `;
            })
            .join("")}
        </div>
      `
      : "";

  return `<div class="answer-title">模板匹配</div><p>${nl2br(answer || "")}</p>${actions}`;
}

function buildPredictionTemplateMatchSummary(session) {
  const selectedTemplateId = getSelectedPredictionTemplateId(session);
  const candidates = Array.isArray(session?.predictionTemplateCandidates)
    ? session.predictionTemplateCandidates.map(normalizePredictionTemplate).filter(Boolean)
    : [];
  const currentTemplate = selectedTemplateId ? candidates.find((template) => template.id === selectedTemplateId) : null;
  const query =
    typeof session?.lastPredictionQuery === "string" && session.lastPredictionQuery.trim()
      ? session.lastPredictionQuery.trim()
      : "";

  if (candidates.length === 0) {
    return "当前无可用案件模板。请先到左侧观点预测页创建案件模板。";
  }

  const listPreview = candidates
    .slice(0, 4)
    .map((template, index) => {
      const materialCount = getPredictionCaseMaterialCount(template);
      const corpusCount = getPredictionOpponentCorpusCount(template);
      return `${index + 1}. ${template.caseName}（案情材料 ${materialCount}，对方语料 ${corpusCount}）`;
    })
    .join("\n");

  return [
    query ? `已收到你的观点预测问题：${query}` : "已收到你的观点预测请求。",
    currentTemplate
      ? `当前将基于《${currentTemplate.caseName}》进入后续预测流程。`
      : "请先在下方选择一个案件模板，再开始后续观点预测流程。",
    listPreview ? `可选案件模板：\n${listPreview}` : "",
  ]
    .filter(Boolean)
    .join("\n\n");
}

function buildPredictionTemplateMessageHtml(answer, templateMatch) {
  const selectedTemplateId =
    typeof templateMatch?.selectedTemplateId === "string" && templateMatch.selectedTemplateId.trim()
      ? templateMatch.selectedTemplateId
      : null;
  const query =
    typeof templateMatch?.query === "string" && templateMatch.query.trim()
      ? templateMatch.query.trim()
      : "";
  const candidates = Array.isArray(templateMatch?.candidates)
    ? templateMatch.candidates.map(normalizePredictionTemplate).filter(Boolean)
    : [];

  const actions =
    query && candidates.length > 0
      ? `
        <div class="prediction-match-actions">
          ${candidates
            .map((template) => {
              const isSelected = template.id === selectedTemplateId;
              const materialCount = getPredictionCaseMaterialCount(template);
              const corpusCount = getPredictionOpponentCorpusCount(template);
              return `
                <button
                  class="prediction-match-option ${isSelected ? "selected" : ""}"
                  type="button"
                  data-prediction-template-select="${escapeHtml(template.id)}"
                  data-prediction-query="${escapeHtml(encodeURIComponent(query))}"
                >
                  <span class="prediction-match-option-name">${escapeHtml(template.caseName)}</span>
                  <span class="prediction-match-option-meta">案情材料 ${materialCount} 份 · 对方语料 ${corpusCount} 份</span>
                  ${isSelected ? `<span class="prediction-match-option-tag">当前</span>` : ""}
                </button>
              `;
            })
            .join("")}
        </div>
      `
      : "";

  return `<div class="answer-title">案件选择</div><p>${nl2br(answer || "")}</p>${actions}`;
}

function appendPredictionTemplateMatchResponse(session, query, save = true) {
  const answer = buildPredictionTemplateMatchSummary(session);
  const templateMatch = {
    query,
    selectedTemplateId: getSelectedPredictionTemplateId(session),
    candidates: Array.isArray(session?.predictionTemplateCandidates)
      ? session.predictionTemplateCandidates.map(normalizePredictionTemplate).filter(Boolean)
      : [],
  };

  appendMessage("", buildPredictionTemplateMessageHtml(answer, templateMatch));

  if (save) {
    pushMessageToActive({ type: "assistant", answer, citations: [], predictionTemplateMatch: templateMatch });
  }
}

async function executePredictionPlaceholder(session, query, options = {}) {
  const { appendUser = true } = options;
  const selectedTemplateId = getSelectedPredictionTemplateId(session);
  const selectedTemplate = Array.isArray(session?.predictionTemplateCandidates)
    ? session.predictionTemplateCandidates
        .map(normalizePredictionTemplate)
        .filter(Boolean)
        .find((template) => template.id === selectedTemplateId)
    : null;

  if (!query) {
    appendErrorMessage("观点预测未启动：请输入你想分析的问题。", true);
    return false;
  }

  if (!selectedTemplate) {
    appendErrorMessage("观点预测未启动：请先在主聊天区选择一个案件模板。", true);
    return false;
  }

  showChat();
  if (appendUser) {
    appendUserMessage(query, true);
  }
  const loadingNode = appendLoadingMessage("观点预测中");
  try {
    const response = await fetch(`${API_BASE}/opponent-prediction/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: session.id,
        template_id: selectedTemplate.id,
        query,
      }),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `请求失败 (${response.status})`);
    }

    const report = normalizePredictionReportResponse(await response.json());
    if (loadingNode?.isConnected) {
      loadingNode.remove();
    }
    if (!report) {
      throw new Error("观点预测结果格式不正确");
    }
    appendPredictionReportResponse(report, true);
    return true;
  } catch (err) {
    if (loadingNode?.isConnected) {
      loadingNode.remove();
    }
    appendErrorMessage(`观点预测失败：${err.message || err}`, true);
    return false;
  }
}

function removeLatestTemplateMatchMessage(session) {
  if (!session || !Array.isArray(session.messages)) return;

  for (let index = session.messages.length - 1; index >= 0; index -= 1) {
    const message = session.messages[index];
    if (message?.type !== "assistant" || !message.templateMatch) continue;
    session.messages.splice(index, 1);
    return;
  }
}

function removeLatestPredictionTemplateMatchMessage(session) {
  if (!session || !Array.isArray(session.messages)) return;

  for (let index = session.messages.length - 1; index >= 0; index -= 1) {
    const message = session.messages[index];
    if (message?.type !== "assistant" || !message.predictionTemplateMatch) continue;
    session.messages.splice(index, 1);
    return;
  }
}

function queuePredictionSelectionInvalidatedMessages(session, deletedTemplate) {
  if (!session || !deletedTemplate) return;

  const query =
    typeof session.lastPredictionQuery === "string" && session.lastPredictionQuery.trim()
      ? session.lastPredictionQuery.trim()
      : "";
  const hasCandidates = Array.isArray(session.predictionTemplateCandidates) && session.predictionTemplateCandidates.length > 0;

  pushMessageToSession(session, {
    type: "assistant",
    answer: hasCandidates
      ? `当前已选案件模板《${deletedTemplate.caseName}》已被删除，本次观点预测流程已中止。请重新选择一个案件模板后再继续。`
      : `当前已选案件模板《${deletedTemplate.caseName}》已被删除，本次观点预测流程已中止，且当前已无可用案件模板。`,
    citations: [],
  });

  if (!query || !hasCandidates) {
    return;
  }

  const answer = buildPredictionTemplateMatchSummary(session);
  pushMessageToSession(session, {
    type: "assistant",
    answer,
    citations: [],
    predictionTemplateMatch: {
      query,
      selectedTemplateId: null,
      candidates: session.predictionTemplateCandidates.map(normalizePredictionTemplate).filter(Boolean),
    },
  });
}

function getPendingAttachmentFileStore(sessionId) {
  if (!sessionId) return null;
  let store = pendingAttachmentFilesBySession.get(sessionId);
  if (!store) {
    store = new Map();
    pendingAttachmentFilesBySession.set(sessionId, store);
  }
  return store;
}

function getPromotedChatAttachmentIds(sessionId) {
  if (!sessionId) return null;
  let ids = promotedChatAttachmentIdsBySession.get(sessionId);
  if (!ids) {
    ids = new Set();
    promotedChatAttachmentIdsBySession.set(sessionId, ids);
  }
  return ids;
}

function getReviewTempFileObjectStore(sessionId) {
  if (!sessionId) return null;
  let store = reviewTempFileObjectsBySession.get(sessionId);
  if (!store) {
    store = new Map();
    reviewTempFileObjectsBySession.set(sessionId, store);
  }
  return store;
}

function getFilePreviewUrlStore(sessionId) {
  if (!sessionId) return null;
  let store = filePreviewUrlsBySession.get(sessionId);
  if (!store) {
    store = new Map();
    filePreviewUrlsBySession.set(sessionId, store);
  }
  return store;
}

function rememberChatAttachmentFiles(sessionId, attachments, files) {
  if (!sessionId || !Array.isArray(attachments) || !Array.isArray(files) || attachments.length !== files.length) {
    return;
  }

  const store = getPendingAttachmentFileStore(sessionId);
  if (!store) return;

  attachments.forEach((attachment, index) => {
    const file = files[index];
    if (attachment?.id && file instanceof File) {
      store.set(attachment.id, file);
    }
  });
}

function rememberReviewTempFiles(sessionId, reviewFiles, files) {
  if (!sessionId || !Array.isArray(reviewFiles) || !Array.isArray(files) || reviewFiles.length !== files.length) {
    return;
  }

  const store = getReviewTempFileObjectStore(sessionId);
  if (!store) return;

  reviewFiles.forEach((reviewFile, index) => {
    const file = files[index];
    if (reviewFile?.id && file instanceof File) {
      store.set(reviewFile.id, file);
    }
  });
}

function forgetChatAttachmentFile(sessionId, attachmentId) {
  if (!sessionId || !attachmentId) return;
  revokeSessionFilePreviewUrl(sessionId, `chat:${attachmentId}`);
  pendingAttachmentFilesBySession.get(sessionId)?.delete(attachmentId);
  promotedChatAttachmentIdsBySession.get(sessionId)?.delete(attachmentId);
}

function forgetReviewTempFile(sessionId, fileId) {
  if (!sessionId || !fileId) return;
  revokeSessionFilePreviewUrl(sessionId, `review:${fileId}`);
  reviewTempFileObjectsBySession.get(sessionId)?.delete(fileId);
}

function revokeSessionFilePreviewUrl(sessionId, previewKey) {
  if (!sessionId || !previewKey) return;
  const store = filePreviewUrlsBySession.get(sessionId);
  const url = store?.get(previewKey);
  if (url) {
    URL.revokeObjectURL(url);
    store.delete(previewKey);
  }
  if (store && store.size === 0) {
    filePreviewUrlsBySession.delete(sessionId);
  }
}

function getSessionFilePreviewUrl(sessionId, previewKey, file) {
  if (!sessionId || !previewKey || !(file instanceof File)) return "";
  const store = getFilePreviewUrlStore(sessionId);
  if (!store) return "";
  const existing = store.get(previewKey);
  if (existing) return existing;
  const next = URL.createObjectURL(file);
  store.set(previewKey, next);
  return next;
}

function resolveVisibleItemLocalFile(session, item) {
  if (!session?.id || !item) return null;
  if (item.reviewFileId) {
    const reviewFile = reviewTempFileObjectsBySession.get(session.id)?.get(item.reviewFileId);
    if (reviewFile instanceof File) return reviewFile;
  }
  if (item.attachmentId) {
    const chatFile = pendingAttachmentFilesBySession.get(session.id)?.get(item.attachmentId);
    if (chatFile instanceof File) return chatFile;
  }
  return null;
}

function isPdfFile(file, fileName = "") {
  if (file instanceof File && file.type === "application/pdf") return true;
  return /\.pdf$/i.test(fileName || file?.name || "");
}

function getPendingUploadStore(sessionId) {
  if (!sessionId) return null;
  let store = pendingUploadEntriesBySession.get(sessionId);
  if (!store) {
    store = new Map();
    pendingUploadEntriesBySession.set(sessionId, store);
  }
  return store;
}

function createPendingUploadEntries(sessionId, files, kind) {
  if (!sessionId || !Array.isArray(files) || files.length === 0) return [];
  const store = getPendingUploadStore(sessionId);
  if (!store) return [];

  const now = Date.now();
  return files.map((file, index) => {
    const entry = {
      id: `pending_${kind}_${now}_${index}_${Math.random().toString(36).slice(2, 8)}`,
      kind,
      fileName: file.name,
      size: file.size,
      progress: 0,
      stage: "uploading",
      createdAt: now + index,
    };
    store.set(entry.id, entry);
    return entry;
  });
}

function updatePendingUploadProgress(sessionId, uploadId, progress) {
  const entry = pendingUploadEntriesBySession.get(sessionId)?.get(uploadId);
  if (!entry) return;
  entry.stage = "uploading";
  entry.progress = Number.isFinite(progress) ? Math.max(0, Math.min(1, progress)) : entry.progress;
}

function markPendingUploadProcessing(sessionId, uploadId) {
  const entry = pendingUploadEntriesBySession.get(sessionId)?.get(uploadId);
  if (!entry) return;
  entry.stage = "processing";
}

function removePendingUploadEntry(sessionId, uploadId) {
  if (!sessionId || !uploadId) return;
  const store = pendingUploadEntriesBySession.get(sessionId);
  if (!store) return;
  store.delete(uploadId);
  if (store.size === 0) {
    pendingUploadEntriesBySession.delete(sessionId);
  }
}

function clearSessionAttachmentBridgeState(sessionId) {
  if (!sessionId) return;
  const previewStore = filePreviewUrlsBySession.get(sessionId);
  if (previewStore) {
    previewStore.forEach((url) => URL.revokeObjectURL(url));
  }
  filePreviewUrlsBySession.delete(sessionId);
  pendingAttachmentFilesBySession.delete(sessionId);
  pendingUploadEntriesBySession.delete(sessionId);
  reviewTempFileObjectsBySession.delete(sessionId);
  promotedChatAttachmentIdsBySession.delete(sessionId);
  warnedMissingReviewFilesBySession.delete(sessionId);
  reviewFileSyncPromisesBySession.delete(sessionId);
}

function collectChatAttachmentsForReviewSync(session) {
  if (!session?.id) {
    return { readyItems: [], missingFileNames: [] };
  }

  const attachments = Array.isArray(session.chatAttachments) ? session.chatAttachments : [];
  const store = pendingAttachmentFilesBySession.get(session.id);
  const promotedIds = getPromotedChatAttachmentIds(session.id);
  const readyItems = [];
  const missingFileNames = [];

  attachments.forEach((attachment) => {
    if (!attachment?.id || promotedIds?.has(attachment.id)) {
      return;
    }

    const file = store?.get(attachment.id);
    if (file instanceof File) {
      readyItems.push({ attachmentId: attachment.id, file });
      return;
    }

    missingFileNames.push(attachment.fileName || "未命名文件");
  });

  return { readyItems, missingFileNames };
}

function warnMissingReviewFiles(sessionId, fileNames) {
  if (!sessionId || !Array.isArray(fileNames) || fileNames.length === 0) return;
  if (warnedMissingReviewFilesBySession.has(sessionId)) return;

  warnedMissingReviewFilesBySession.add(sessionId);
  appendErrorMessage(
    `以下文件是在聊天模式下选择的，但当前浏览器已无法再次读取原始内容；如果要用于合同审查，请重新上传：\n${fileNames.join("\n")}`
  );
}

async function ensureReviewTempFiles(session, options = {}) {
  const { reportMissing = false } = options;
  if (!session?.id) return;

  const existingTask = reviewFileSyncPromisesBySession.get(session.id);
  if (existingTask) {
    await existingTask;
    return;
  }

  const task = (async () => {
    const { readyItems, missingFileNames } = collectChatAttachmentsForReviewSync(session);

    if (readyItems.length === 0) {
      if (reportMissing) {
        warnMissingReviewFiles(session.id, missingFileNames);
      }
      return;
    }

    const uploadedItems = [];
    const uploadErrors = [];
    const promotedIds = [];

    for (const item of readyItems) {
      try {
        const result = await uploadSessionTempFile(session.id, "review_target", item.file);
        const normalized = normalizeReviewTempFile(result);
        if (normalized) {
          uploadedItems.push(normalized);
          promotedIds.push(item.attachmentId);
          rememberReviewTempFiles(session.id, [normalized], [item.file]);
          const linkedAttachment = session.chatAttachments.find((attachment) => attachment.id === item.attachmentId);
          if (linkedAttachment) {
            linkedAttachment.promotedReviewFileId = normalized.id;
          }
        }
      } catch (err) {
        uploadErrors.push(`${item.file.name}：${err.message}`);
      }
    }

    if (promotedIds.length > 0) {
      const promoted = getPromotedChatAttachmentIds(session.id);
      promotedIds.forEach((attachmentId) => promoted?.add(attachmentId));
    }

    if (uploadedItems.length > 0) {
      clearReviewTemplateState(session);
      session.reviewTempFiles = [...session.reviewTempFiles, ...uploadedItems];
      touchSession(session);
      renderHistory();
      renderChatAttachments();
    }

    if (uploadErrors.length > 0) {
      appendErrorMessage(`待审合同上传失败：\n${uploadErrors.join("\n")}`);
    }

    if (reportMissing) {
      warnMissingReviewFiles(session.id, missingFileNames);
    }
  })();

  reviewFileSyncPromisesBySession.set(session.id, task);

  try {
    await task;
  } finally {
    if (reviewFileSyncPromisesBySession.get(session.id) === task) {
      reviewFileSyncPromisesBySession.delete(session.id);
    }
  }
}

function loadSessions() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((s) => s && typeof s.id === "string" && Array.isArray(s.messages))
      .map((s) => ({
        id: s.id,
        title: typeof s.title === "string" && s.title.trim() ? s.title : "新会话",
        updatedAt: Number.isFinite(s.updatedAt) ? s.updatedAt : Date.now(),
        mode: normalizeComposerMode(s.mode),
        chatAttachments: Array.isArray(s.chatAttachments)
          ? s.chatAttachments.map(normalizeChatAttachment).filter(Boolean)
          : [],
        reviewTempFiles: Array.isArray(s.reviewTempFiles)
          ? s.reviewTempFiles.map(normalizeReviewTempFile).filter(Boolean)
          : [],
        reviewRecommendedTemplate: normalizeReviewTemplate(s.reviewRecommendedTemplate),
        reviewTemplateCandidates: Array.isArray(s.reviewTemplateCandidates)
          ? s.reviewTemplateCandidates.map(normalizeReviewTemplate).filter(Boolean)
          : [],
        reviewSelectedTemplateId:
          typeof s.reviewSelectedTemplateId === "string" && s.reviewSelectedTemplateId.trim()
            ? s.reviewSelectedTemplateId
            : null,
        predictionTemplateCandidates: Array.isArray(s.predictionTemplateCandidates)
          ? s.predictionTemplateCandidates.map(normalizePredictionTemplate).filter(Boolean)
          : [],
        predictionSelectedTemplateId:
          typeof s.predictionSelectedTemplateId === "string" && s.predictionSelectedTemplateId.trim()
            ? s.predictionSelectedTemplateId
            : null,
        lastPredictionQuery:
          typeof s.lastPredictionQuery === "string" && s.lastPredictionQuery.trim() ? s.lastPredictionQuery : null,
        lastReviewQuery:
          typeof s.lastReviewQuery === "string" && s.lastReviewQuery.trim() ? s.lastReviewQuery : null,
        rightSidebarTab: normalizeRightSidebarTab(s.rightSidebarTab),
        messages: s.messages
          .filter((m) => m && typeof m.type === "string")
          .slice(-MAX_MESSAGES_PER_SESSION),
      }))
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .slice(0, MAX_SESSIONS);
  } catch {
    return [];
  }
}

function persistSessions() {
  chatSessions.sort((a, b) => b.updatedAt - a.updatedAt);
  chatSessions = chatSessions.slice(0, MAX_SESSIONS);
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(chatSessions));

  if (activeSessionId) {
    localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
  } else {
    localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
}

function getActiveSession() {
  if (!activeSessionId) return null;
  return chatSessions.find((s) => s.id === activeSessionId) || null;
}

function getSessionById(sessionId) {
  return chatSessions.find((session) => session.id === sessionId) || null;
}

function summarizeTitle(text) {
  const clean = String(text).replace(/\s+/g, " ").trim();
  if (!clean) return "新会话";
  return clean.length > 16 ? `${clean.slice(0, 16)}...` : clean;
}

function createSession(firstQuery = "") {
  const session = {
    id: `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    title: summarizeTitle(firstQuery),
    updatedAt: Date.now(),
    mode: draftSessionMode,
    chatAttachments: [],
    reviewTempFiles: [],
    reviewRecommendedTemplate: null,
    reviewTemplateCandidates: [],
    reviewSelectedTemplateId: null,
    predictionTemplateCandidates: [],
    predictionSelectedTemplateId: null,
    lastPredictionQuery: null,
    lastReviewQuery: null,
    rightSidebarTab: "attachments",
    messages: [],
  };
  chatSessions.unshift(session);
  activeSessionId = session.id;
  persistSessions();
  return session;
}

function ensureActiveSession(firstQuery = "") {
  const current = getActiveSession();
  if (current) return current;
  return createSession(firstQuery);
}

function touchSession(session) {
  session.updatedAt = Date.now();
  persistSessions();
}

function getRightSidebarTab() {
  return normalizeRightSidebarTab(getActiveSession()?.rightSidebarTab);
}

function renderRightSidebarAttachments() {
  if (!rightSidebarAttachmentsBody) return;
  const session = getActiveSession();
  const attachments = getVisibleSessionFiles(session).filter((item) => !item.isPendingUpload);

  if (attachments.length === 0) {
    rightSidebarAttachmentsBody.className = "right-sidebar-empty";
    rightSidebarAttachmentsBody.textContent = "上传文件后，这里会显示当前会话附件。";
    return;
  }

  rightSidebarAttachmentsBody.className = "right-sidebar-attachment-list";
  rightSidebarAttachmentsBody.innerHTML = attachments
    .map((attachment) => {
      const localFile = resolveVisibleItemLocalFile(session, attachment);
      const pdfPreview =
        localFile && isPdfFile(localFile, attachment.fileName)
          ? `
            <iframe
              class="right-sidebar-attachment-viewer"
              src="${escapeHtml(getSessionFilePreviewUrl(session.id, `${attachment.reviewFileId ? "review" : "chat"}:${attachment.reviewFileId || attachment.attachmentId || attachment.id}`, localFile))}#toolbar=0&navpanes=0"
              title="${escapeHtml(attachment.fileName)}"
            ></iframe>
          `
          : "";
      const previewBody =
        pdfPreview ||
        `<pre class="right-sidebar-attachment-preview">${escapeHtml(
          attachment.contentPreview || "当前附件暂无可展示的文本内容。"
        )}</pre>`;

      return `
        <article class="right-sidebar-attachment-item">
          <div class="right-sidebar-attachment-head">
            <strong class="right-sidebar-attachment-name" title="${escapeHtml(attachment.fileName)}">${escapeHtml(attachment.fileName)}</strong>
            <div class="right-sidebar-attachment-meta">${escapeHtml(formatAttachmentSize(attachment.size)) || "未知大小"}</div>
          </div>
          <div class="right-sidebar-attachment-stage">${previewBody}</div>
        </article>
      `;
    })
    .join("");
}

function syncRightSidebarTabUi() {
  const tab = getRightSidebarTab();

  rightSidebarTabButtons.forEach((button) => {
    const active = button.dataset.rightSidebarTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });

  if (rightSidebarAttachmentsPanel) {
    rightSidebarAttachmentsPanel.classList.toggle("hidden", tab !== "attachments");
  }
  if (rightSidebarCitationsPanel) {
    rightSidebarCitationsPanel.classList.toggle("hidden", tab !== "citations");
  }
}

function setRightSidebarTab(tab) {
  const nextTab = normalizeRightSidebarTab(tab);
  const session = getActiveSession();
  if (session) {
    session.rightSidebarTab = nextTab;
    persistSessions();
  }
  renderRightSidebarAttachments();
  syncRightSidebarTabUi();
}

function openRightSidebar(tab) {
  if (tab) {
    setRightSidebarTab(tab);
  } else {
    renderRightSidebarAttachments();
    syncRightSidebarTabUi();
  }
  citationSidebar.classList.remove("hidden");
  citationSidebar.classList.add("open");
}

function renderChatAttachments() {
  if (!chatAttachmentTray) return;

  const session = getActiveSession();
  const visibleItems = getVisibleSessionFiles(session);

  if (visibleItems.length === 0) {
    chatAttachmentTray.innerHTML = "";
    chatAttachmentTray.classList.add("hidden");
    renderRightSidebarAttachments();
    return;
  }

  chatAttachmentTray.innerHTML = visibleItems
    .map(
      (item) => {
        const progressLabel = item.isPendingUpload
          ? formatUploadProgressLabel(item.progress, item.uploadStage)
          : formatAttachmentSize(item.size);
        const progressValue = formatUploadProgressValue(item.progress, item.uploadStage);
        const progressText = formatUploadProgressText(item.progress, item.uploadStage);

        return `
        <div class="composer-attachment-chip" data-attachment-id="${escapeHtml(item.id)}">
          <div class="composer-attachment-meta">
            <span class="composer-attachment-name" title="${escapeHtml(item.fileName)}">${escapeHtml(item.fileName)}</span>
            <span class="composer-attachment-size">${escapeHtml(progressLabel)}</span>
          </div>
          ${
            item.isPendingUpload
              ? `
                <div
                  class="composer-attachment-progress ${item.uploadStage === "processing" ? "processing" : ""}"
                  style="--progress:${progressValue}"
                  aria-label="${escapeHtml(progressLabel)}"
                  title="${escapeHtml(progressLabel)}"
                >
                  <span>${escapeHtml(progressText)}</span>
                </div>
              `
              : `
                <button
                  class="composer-attachment-remove"
                  type="button"
                  data-remove-attachment="${item.attachmentId ? escapeHtml(item.attachmentId) : ""}"
                  data-remove-review-file="${item.reviewFileId ? escapeHtml(item.reviewFileId) : ""}"
                  aria-label="移除附件"
                >×</button>
              `
          }
        </div>
      `
      }
    )
    .join("");
  chatAttachmentTray.classList.remove("hidden");
  renderRightSidebarAttachments();
}

async function addChatAttachments(files) {
  if (!Array.isArray(files) || files.length === 0) return;

  const session = ensureActiveSession(input.value.trim());
  activeSessionId = session.id;
  persistSessions();
  renderHistory();
  showChat();

  const nextAttachments = [];
  const successfulFiles = [];
  const errors = [];
  const pendingEntries = createPendingUploadEntries(session.id, files, "chat");
  renderChatAttachments();

  for (const [index, file] of files.entries()) {
    const pendingEntry = pendingEntries[index];
    try {
      const result = await uploadSessionTempFile(session.id, "chat_attachment", file, {
        onProgress: (progress) => {
          if (!pendingEntry) return;
          updatePendingUploadProgress(session.id, pendingEntry.id, progress);
          renderChatAttachments();
        },
        onUploadSent: () => {
          if (!pendingEntry) return;
          markPendingUploadProcessing(session.id, pendingEntry.id);
          renderChatAttachments();
        },
      });
      const normalized = normalizeReviewTempFile(result);
      nextAttachments.push({
        id: `a_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
        fileName: file.name,
        status: "ready",
        size: file.size,
        uploadedAt: Date.now(),
        contentPreview: normalized?.contentPreview || "",
        chatTempFileId: normalized?.id || null,
      });
      successfulFiles.push(file);
    } catch (err) {
      errors.push(`${file.name}：${err.message}`);
    } finally {
      if (pendingEntry) {
        removePendingUploadEntry(session.id, pendingEntry.id);
        renderChatAttachments();
      }
    }
  }

  if (nextAttachments.length > 0) {
    rememberChatAttachmentFiles(session.id, nextAttachments, successfulFiles);
    session.chatAttachments = [...session.chatAttachments, ...nextAttachments];
    touchSession(session);
    renderHistory();
    renderChatAttachments();
    openRightSidebar("attachments");
  }

  if (errors.length > 0) {
    appendErrorMessage(`聊天附件上传失败：\n${errors.join("\n")}`);
  }
}

function addReviewTempFiles(files) {
  return uploadReviewTempFiles(files);
}

async function removeChatAttachment(attachmentId) {
  const session = getActiveSession();
  if (!session || !Array.isArray(session.chatAttachments)) return;

  const target = session.chatAttachments.find((attachment) => attachment.id === attachmentId);
  if (!target) return;

  if (target.chatTempFileId) {
    try {
      await deleteSessionTempFile(target.chatTempFileId);
    } catch (err) {
      const rawMessage = String(err?.message || err || "");
      const message = rawMessage.toLowerCase();
      const statusCode = Number.isFinite(err?.status) ? err.status : null;
      const missing = statusCode === 404 || message.includes("not found") || message.includes("(404)");
      if (!missing) {
        appendErrorMessage(`移除聊天附件失败：${rawMessage}`);
        return;
      }
    }
  }

  session.chatAttachments = session.chatAttachments.filter((attachment) => attachment.id !== attachmentId);
  forgetChatAttachmentFile(session.id, attachmentId);
  touchSession(session);
  renderChatAttachments();

  if (session.chatAttachments.length === 0 && getRightSidebarTab() === "attachments") {
    closeCitationSidebar();
  }
}

async function removeReviewTempFile(fileId) {
  const session = getActiveSession();
  if (!session || !Array.isArray(session.reviewTempFiles)) return;

  const target = session.reviewTempFiles.find((file) => file.id === fileId);
  if (!target) return;

  try {
    await deleteSessionTempFile(fileId);
  } catch (err) {
    const rawMessage = String(err?.message || err || "");
    const message = rawMessage.toLowerCase();
    const statusCode = Number.isFinite(err?.status) ? err.status : null;
    const missing = statusCode === 404 || message.includes("not found") || message.includes("(404)");
    if (!missing) {
      appendErrorMessage(`移除待审合同失败：${rawMessage}`);
      return;
    }
  }

  session.reviewTempFiles = session.reviewTempFiles.filter((file) => file.id !== fileId);
  forgetReviewTempFile(session.id, fileId);
  session.chatAttachments.forEach((attachment) => {
    if (attachment.promotedReviewFileId === fileId) {
      attachment.promotedReviewFileId = null;
    }
  });
  if (session.reviewTempFiles.length === 0) {
    clearReviewTemplateState(session);
  }
  touchSession(session);
  renderChatAttachments();
}

async function removeSessionFile(options = {}) {
  const { attachmentId = "", reviewFileId = "" } = options;
  const reviewPromise = reviewFileId ? removeReviewTempFile(reviewFileId) : Promise.resolve();
  const attachmentPromise = attachmentId ? removeChatAttachment(attachmentId) : Promise.resolve();
  await reviewPromise;
  await attachmentPromise;
}

function getComposerMode() {
  return getActiveSession()?.mode || draftSessionMode;
}

function hasReadyChatAttachments(session) {
  return Boolean(session && Array.isArray(session.chatAttachments) && session.chatAttachments.length > 0);
}

function buildSimilarCaseQuery(rawQuery) {
  const query = typeof rawQuery === "string" ? rawQuery.trim() : "";
  if (query) return query;
  return "请基于我上传的案件材料，与数据库中的案例进行相似性检索，优先给出最相近的案件并说明相似点与差异点。";
}

function syncComposerModeUi() {
  const mode = getComposerMode();
  const isReviewMode = mode === "contract-review";
  const isPredictionMode = mode === "opponent-prediction";
  const isSimilarCaseMode = mode === "similar-case";
  contractReviewModeToggle.classList.toggle("active", isReviewMode);
  contractReviewModeToggle.setAttribute("aria-pressed", String(isReviewMode));
  opponentPredictionModeToggle.classList.toggle("active", isPredictionMode);
  opponentPredictionModeToggle.setAttribute("aria-pressed", String(isPredictionMode));
  similarCaseModeToggle.classList.toggle("active", isSimilarCaseMode);
  similarCaseModeToggle.setAttribute("aria-pressed", String(isSimilarCaseMode));
  reviewUploadBtn.disabled = isPredictionMode;
  reviewUploadBtn.setAttribute("aria-disabled", String(isPredictionMode));
  reviewUploadBtn.title = isReviewMode
    ? "上传待审合同"
    : isPredictionMode
      ? "请在左侧观点预测页管理模板材料"
      : isSimilarCaseMode
        ? "上传待比对案件材料"
        : "上传聊天附件";
  reviewUploadBtn.setAttribute(
    "aria-label",
    isReviewMode
      ? "上传待审合同"
      : isPredictionMode
        ? "请在左侧观点预测页管理模板材料"
        : isSimilarCaseMode
          ? "上传待比对案件材料"
          : "上传聊天附件"
  );
  chatAttachmentInput.disabled = isReviewMode || isPredictionMode;
  reviewContractInput.disabled = !isReviewMode;
  input.placeholder = isReviewMode
    ? "输入审查要求..."
    : isPredictionMode
      ? "输入你想预测的问题..."
      : isSimilarCaseMode
        ? "输入检索要求，留空则按上传材料自动检索..."
        : "发消息...";
  renderChatAttachments();
}

function setComposerMode(mode) {
  const nextMode = normalizeComposerMode(mode);
  const session = getActiveSession();

  if (session) {
    session.mode = nextMode;
    touchSession(session);
    renderHistory();
  } else {
    draftSessionMode = nextMode;
  }

  syncComposerModeUi();

  if (nextMode === "contract-review" && session) {
    void ensureReviewTempFiles(session);
  }
}

function setMenuActive(target) {
  [menuFiles, menuContractReview, menuOpponentPrediction, menuStatus].forEach((el) => el.classList.remove("active"));
  if (target === "files") menuFiles.classList.add("active");
  if (target === "contract-review") menuContractReview.classList.add("active");
  if (target === "opponent-prediction") menuOpponentPrediction.classList.add("active");
  if (target === "status") menuStatus.classList.add("active");
}

function hidePanels() {
  panelFiles.classList.add("hidden");
  panelContractReview.classList.add("hidden");
  panelOpponentPrediction.classList.add("hidden");
  panelStatus.classList.add("hidden");
}

function showWelcome() {
  hidePanels();
  closeCitationSidebar();
  welcomePanel.style.display = "";
  chat.style.display = "none";
  composerWrap.classList.remove("hidden");
  setMenuActive(null);
}

function showChat() {
  hidePanels();
  welcomePanel.style.display = "none";
  chat.style.display = "block";
  composerWrap.classList.remove("hidden");
  setMenuActive(null);
}

function showPanel(view) {
  closeCitationSidebar();
  welcomePanel.style.display = "none";
  chat.style.display = "none";
  composerWrap.classList.add("hidden");

  panelFiles.classList.toggle("hidden", view !== "files");
  panelContractReview.classList.toggle("hidden", view !== "contract-review");
  panelOpponentPrediction.classList.toggle("hidden", view !== "opponent-prediction");
  panelStatus.classList.toggle("hidden", view !== "status");
  setMenuActive(view);

  if (view === "files") {
    loadDocumentList();
  }

  if (view === "contract-review") {
    loadTemplateList();
  }

  if (view === "opponent-prediction") {
    renderPredictionTemplatePlaceholder();
    void loadPredictionTemplatesRemote({ silent: true }).catch((err) => {
      showPredictionTemplateFeedback(`加载案件模板失败：${err.message || err}`, "error", 6000);
    });
  }

  if (view === "status") {
    checkSystemStatus();
  }
}

function restoreConversationView() {
  const session = getActiveSession();
  if (session && session.messages.length > 0) {
    renderSessionMessages(session);
    showChat();
  } else {
    showWelcome();
  }
  syncComposerModeUi();
  renderRightSidebarAttachments();
  syncRightSidebarTabUi();
}

let fileFeedbackTimer = null;
let templateFeedbackTimer = null;
let predictionTemplateFeedbackTimer = null;

function renderPredictionTemplatePlaceholder() {
  renderPredictionTemplateList();
}

function showFileFeedback(message, type = "info", autoHideMs = 4500) {
  if (!fileFeedback) return;
  if (fileFeedbackTimer) {
    clearTimeout(fileFeedbackTimer);
    fileFeedbackTimer = null;
  }
  fileFeedback.className = `file-feedback ${type}`;
  fileFeedback.textContent = message;
  fileFeedback.classList.remove("hidden");

  if (autoHideMs > 0) {
    fileFeedbackTimer = setTimeout(() => {
      fileFeedback.classList.add("hidden");
    }, autoHideMs);
  }
}

function setUploadBusy(isBusy) {
  const fileInput = document.getElementById("docFileInput");
  if (fileInput) {
    fileInput.disabled = isBusy;
  }
  if (uploadArea) {
    uploadArea.classList.toggle("uploading", isBusy);
  }
}

function showTemplateFeedback(message, type = "info", autoHideMs = 4500) {
  if (!templateFeedback) return;
  if (templateFeedbackTimer) {
    clearTimeout(templateFeedbackTimer);
    templateFeedbackTimer = null;
  }
  templateFeedback.className = `file-feedback ${type}`;
  templateFeedback.textContent = message;
  templateFeedback.classList.remove("hidden");

  if (autoHideMs > 0) {
    templateFeedbackTimer = setTimeout(() => {
      templateFeedback.classList.add("hidden");
    }, autoHideMs);
  }
}

function showPredictionTemplateFeedback(message, type = "info", autoHideMs = 4500) {
  if (!predictionTemplateFeedback) return;
  if (predictionTemplateFeedbackTimer) {
    clearTimeout(predictionTemplateFeedbackTimer);
    predictionTemplateFeedbackTimer = null;
  }
  predictionTemplateFeedback.className = `file-feedback ${type}`;
  predictionTemplateFeedback.textContent = message;
  predictionTemplateFeedback.classList.remove("hidden");

  if (autoHideMs > 0) {
    predictionTemplateFeedbackTimer = setTimeout(() => {
      predictionTemplateFeedback.classList.add("hidden");
    }, autoHideMs);
  }
}

function formatPredictionFileSize(size) {
  if (!Number.isFinite(size) || size <= 0) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatPredictionTemplateTime(timestamp) {
  if (!Number.isFinite(timestamp)) return "刚刚更新";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "刚刚更新";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function buildPredictionTemplateItem(template) {
  const templateId = escapeHtml(template.id);
  const caseName = escapeHtml(template.caseName || "未命名案件");
  const caseMaterialCount = getPredictionCaseMaterialCount(template);
  const opponentCorpusCount = getPredictionOpponentCorpusCount(template);
  const updatedTime = escapeHtml(formatPredictionTemplateTime(template.updatedAt));

  return `
    <article class="template-item" data-prediction-template-id="${templateId}">
      <div class="template-item-info">
        <strong title="${caseName}">${caseName}</strong>
        <span>案情材料 ${caseMaterialCount} 份 · 对方语料 ${opponentCorpusCount} 份 · 更新于 ${updatedTime}</span>
      </div>
      <button class="template-delete" type="button" data-prediction-template-delete="${templateId}">删除</button>
    </article>
  `;
}

function renderPredictionTemplateList() {
  if (!predictionTemplateList) return;
  if (!Array.isArray(predictionTemplates) || predictionTemplates.length === 0) {
    predictionTemplateList.innerHTML = `<div class="template-empty">暂无案件模板</div>`;
    if (predictionTemplateListCount) {
      predictionTemplateListCount.textContent = "0 个";
    }
    return;
  }

  predictionTemplateList.innerHTML = predictionTemplates.map((template) => buildPredictionTemplateItem(template)).join("");
  if (predictionTemplateListCount) {
    predictionTemplateListCount.textContent = `${predictionTemplates.length} 个`;
  }
}

function renderPredictionPendingFiles(target, files, emptyText) {
  if (!target) return;
  if (!Array.isArray(files) || files.length === 0) {
    target.className = "prediction-upload-list prediction-upload-list-empty";
    target.textContent = emptyText;
    return;
  }

  target.className = "prediction-upload-list";
  target.innerHTML = files
    .map((file) => {
      const fileName = escapeHtml(file.name || "未命名文件");
      const details = [formatPredictionFileSize(file.size)];
      if (file.type) {
        details.push(escapeHtml(file.type));
      }
      return `
        <div class="prediction-upload-file">
          <strong title="${fileName}">${fileName}</strong>
          <span>${details.join(" · ")}</span>
        </div>
      `;
    })
    .join("");
}

function syncPredictionTemplateFormState() {
  const caseName = typeof predictionCaseNameInput?.value === "string" ? predictionCaseNameInput.value.trim() : "";
  const hasCaseMaterials = pendingPredictionCaseMaterialFiles.length > 0;
  const canSave = Boolean(caseName) && hasCaseMaterials;

  if (predictionTemplateSaveBtn) {
    predictionTemplateSaveBtn.disabled = !canSave;
  }

  if (predictionCaseMaterialArea) {
    predictionCaseMaterialArea.classList.toggle("has-files", hasCaseMaterials);
  }
  if (predictionOpponentCorpusArea) {
    predictionOpponentCorpusArea.classList.toggle("has-files", pendingPredictionOpponentCorpusFiles.length > 0);
  }

  if (predictionTemplateActionHint) {
    if (!caseName && !hasCaseMaterials) {
      predictionTemplateActionHint.textContent = "填写案件名称并至少选择一份案情材料后可保存。";
    } else if (!caseName) {
      predictionTemplateActionHint.textContent = "案件名称必填。";
    } else if (!hasCaseMaterials) {
      predictionTemplateActionHint.textContent = "案情材料必填，至少需要一份。";
    } else {
      predictionTemplateActionHint.textContent = "已满足保存条件。保存后将写入后端案件模板库。";
    }
  }
}

function clearPredictionTemplateForm() {
  pendingPredictionOpponentCorpusFiles = [];
  pendingPredictionCaseMaterialFiles = [];
  if (predictionCaseNameInput) {
    predictionCaseNameInput.value = "";
  }
  if (predictionOpponentCorpusInput) {
    predictionOpponentCorpusInput.value = "";
  }
  if (predictionCaseMaterialInput) {
    predictionCaseMaterialInput.value = "";
  }
  renderPredictionPendingFiles(predictionOpponentCorpusFiles, [], "尚未选择对方语料");
  renderPredictionPendingFiles(predictionCaseMaterialFiles, [], "尚未选择案情材料");
  syncPredictionTemplateFormState();
}

function setTemplateUploadBusy(isBusy) {
  if (templateFileInput) {
    templateFileInput.disabled = isBusy;
  }
  if (templateUploadArea) {
    templateUploadArea.classList.toggle("uploading", isBusy);
  }
}

function escapeHtml(text) {
  const map = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return String(text).replace(/[&<>"']/g, (m) => map[m]);
}

function nl2br(text) {
  return escapeHtml(text).replace(/\n/g, "<br>");
}

function encodeCitations(citations) {
  return escapeHtml(encodeURIComponent(JSON.stringify(citations || [])));
}

function decodeCitations(encoded) {
  try {
    const parsed = JSON.parse(decodeURIComponent(encoded || ""));
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function getCitationSidebarMaxWidth() {
  return Math.max(
    CITATION_SIDEBAR_MIN_WIDTH,
    Math.min(CITATION_SIDEBAR_MAX_WIDTH, window.innerWidth - 280)
  );
}

function setCitationSidebarWidth(width) {
  const clamped = Math.min(Math.max(width, CITATION_SIDEBAR_MIN_WIDTH), getCitationSidebarMaxWidth());
  citationSidebar.style.width = `${clamped}px`;
  citationSidebar.style.minWidth = `${clamped}px`;
}

function buildCitationHtml(citations) {
  if (Array.isArray(citations) && citations.length > 0) {
    return `
      <div class="citation-wrap">
        <button class="citation-trigger" type="button" data-citations="${encodeCitations(citations)}">
          <span>引用来源（${citations.length}）</span>
          <span class="citation-toggle-text">点击查看</span>
        </button>
      </div>
    `;
  }

  return "";
}

function collectRelatedFileNames(citations, limit = 8) {
  if (!Array.isArray(citations) || citations.length === 0) return [];
  const scoreByFile = new Map();
  citations.forEach((item) => {
    const fileName = typeof item?.file_name === "string" ? item.file_name.trim() : "";
    if (!fileName) return;
    const score = Number.isFinite(item?.similarity_score) ? item.similarity_score : 0;
    const prev = scoreByFile.get(fileName);
    if (prev === undefined || score > prev) {
      scoreByFile.set(fileName, score);
    }
  });
  return Array.from(scoreByFile.entries())
    .sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0], "zh-CN"))
    .slice(0, Math.max(1, limit))
    .map(([fileName]) => fileName);
}

function buildRelatedFileNamesHtml(citations) {
  const fileNames = collectRelatedFileNames(citations, 8);
  if (fileNames.length === 0) return "";
  const items = fileNames.map((name, index) => `${index + 1}. ${escapeHtml(name)}`).join("<br>");
  return `<div class="answer-source-notice"><strong>命中PDF文件名：</strong><br>${items}</div>`;
}

function buildCitationListHtml(citations) {
  if (!Array.isArray(citations) || citations.length === 0) {
    return `<p class="panel-text">当前回答没有可显示的引用案例。</p>`;
  }

  let html = `<div class="citation-list">`;
  citations.forEach((c, index) => {
    const lineStart = Number.isFinite(c.line_start) ? c.line_start : "-";
    const lineEnd = Number.isFinite(c.line_end) ? c.line_end : "-";
    const score = Number.isFinite(c.similarity_score) ? `${(c.similarity_score * 100).toFixed(1)}%` : "--";
    html += `
      <div class="citation">
        <div class="citation-meta">
          <span class="source-badge">来源${index + 1}</span>
          <span class="source-auth">真实来源</span>
          <span class="citation-origin">${escapeHtml(c.file_name || "来源")} · ${lineStart}-${lineEnd} · ${score}</span>
        </div>
        <div class="citation-snippet">${nl2br((c.snippet || "").trim())}</div>
      </div>
    `;
  });
  html += `</div>`;
  return html;
}

function closeCitationSidebar() {
  citationSidebar.classList.add("hidden");
  citationSidebar.classList.remove("open");
}

function openCitationSidebar(citations) {
  setRightSidebarTab("citations");
  citationSidebarTitle.textContent = `引用案例（${citations.length}）`;
  citationSidebarBody.innerHTML = buildCitationListHtml(citations);
  openRightSidebar();
}

function buildAssistantHtml(answer, citations, options = {}) {
  const { attachmentUsed = false, attachmentFileName = "" } = options;
  const notice =
    attachmentUsed && attachmentFileName
      ? `<div class="answer-source-notice">已基于附件《${escapeHtml(attachmentFileName)}》进行检索</div>`
      : "";
  const fileNamesHtml = buildRelatedFileNamesHtml(citations);
  return `<div class="answer-title">助手回答</div>${notice}${fileNamesHtml}<p>${nl2br(answer || "已收到你的消息。")}</p>${buildCitationHtml(citations)}`;
}

function normalizePredictionReportResponse(report) {
  if (!report || typeof report !== "object") return null;
  const citations = Array.isArray(report.citations)
    ? report.citations.map((c) => ({
        file_name: c.file_name,
        line_start: c.line_start,
        line_end: c.line_end,
        similarity_score: c.similarity_score,
        snippet: c.snippet,
      }))
    : [];
  const predictedArguments = Array.isArray(report.predicted_arguments ?? report.predictedArguments)
    ? (report.predicted_arguments ?? report.predictedArguments)
        .map((item) => {
          if (!item || typeof item !== "object") return null;
          const localCitations = Array.isArray(item.citations)
            ? item.citations.map((c) => ({
                file_name: c.file_name,
                line_start: c.line_start,
                line_end: c.line_end,
                similarity_score: c.similarity_score,
                snippet: c.snippet,
              }))
            : [];
          return {
            title: item.title || "未命名观点",
            basis: item.basis || "",
            counter: item.counter || "",
            opponentStatement: item.opponent_statement || item.opponentStatement || "",
            priority: item.priority || "补充",
            citations: localCitations,
            inferenceOnly: Boolean(item.inference_only ?? item.inferenceOnly),
            label: item.label || "观点",
            category: item.category || "general",
            sortReason: item.sort_reason || item.sortReason || "",
          };
        })
        .filter(Boolean)
    : [];

  return {
    reportId: report.report_id || report.reportId || "",
    taskId: report.task_id || report.taskId || "",
    sessionId: report.session_id || report.sessionId || "",
    templateId: report.template_id || report.templateId || "",
    caseName: report.case_name || report.caseName || "未命名案件",
    query: report.query || "",
    caseSummary: report.case_summary || report.caseSummary || "",
    questionType: report.question_type || report.questionType || "general-opponent-view",
    focusDimension: report.focus_dimension || report.focusDimension || "综合观点",
    answerShape: report.answer_shape || report.answerShape || "general-list",
    answerTitle: report.answer_title || report.answerTitle || "对方最可能提出的观点",
    answerSummary: report.answer_summary || report.answerSummary || "",
    retrievalQueries: Array.isArray(report.retrieval_queries ?? report.retrievalQueries)
      ? (report.retrieval_queries ?? report.retrievalQueries).filter((item) => typeof item === "string" && item.trim())
      : [],
    predictedArguments,
    counterStrategies: Array.isArray(report.counter_strategies ?? report.counterStrategies)
      ? (report.counter_strategies ?? report.counterStrategies)
      : predictedArguments.map((item) => item.counter),
    citations,
    evidenceCount: Number.isFinite(report.evidence_count) ? report.evidence_count : Number.isFinite(report.evidenceCount) ? report.evidenceCount : predictedArguments.filter((item) => !item.inferenceOnly).length,
    inferenceCount: Number.isFinite(report.inference_count) ? report.inference_count : Number.isFinite(report.inferenceCount) ? report.inferenceCount : predictedArguments.filter((item) => item.inferenceOnly).length,
    uncertainties: Array.isArray(report.uncertainties) ? report.uncertainties : [],
    source: "backend",
  };
}

function normalizeSimilarCaseMatchItem(item) {
  if (!item || typeof item !== "object") return null;
  return {
    docId: item.doc_id || item.docId || "",
    fileName: item.file_name || item.fileName || "未命名文档",
    versionId: item.version_id || item.versionId || "",
    finalScore:
      Number.isFinite(item.final_score) ? item.final_score : Number.isFinite(item.finalScore) ? item.finalScore : 0,
    similarityScore:
      Number.isFinite(item.similarity_score) ? item.similarity_score : Number.isFinite(item.similarityScore) ? item.similarityScore : 0,
    matchType: item.match_type || item.matchType || "similar_case",
    matchReason: item.match_reason || item.matchReason || "",
    textOverlapRatio:
      Number.isFinite(item.text_overlap_ratio) ? item.text_overlap_ratio : Number.isFinite(item.textOverlapRatio) ? item.textOverlapRatio : 0,
    fileNameAligned: Boolean(item.file_name_aligned ?? item.fileNameAligned),
    matchedPoints: Array.isArray(item.matched_points ?? item.matchedPoints)
      ? (item.matched_points ?? item.matchedPoints).filter((value) => typeof value === "string" && value.trim())
      : [],
    matchedProfileFields: Array.isArray(item.matched_profile_fields ?? item.matchedProfileFields)
      ? (item.matched_profile_fields ?? item.matchedProfileFields).filter((value) => typeof value === "string" && value.trim())
      : [],
    citations: Array.isArray(item.citations)
      ? item.citations.map((c) => ({
          file_name: c.file_name,
          line_start: c.line_start,
          line_end: c.line_end,
          similarity_score: c.similarity_score,
          snippet: c.snippet,
        }))
      : [],
  };
}

function normalizeSimilarCaseProfile(profile, fallbackFacts = []) {
  if (!profile || typeof profile !== "object") {
    return {
      legalRelationship: "",
      disputeFocuses: [],
      claimTargets: [],
      partyRoles: [],
      keyFacts: Array.isArray(fallbackFacts) ? fallbackFacts : [],
      timeline: [],
      amountTerms: [],
      retrievalIntent: "",
    };
  }
  return {
    legalRelationship: profile.legal_relationship || profile.legalRelationship || "",
    disputeFocuses: Array.isArray(profile.dispute_focuses ?? profile.disputeFocuses)
      ? (profile.dispute_focuses ?? profile.disputeFocuses).filter((item) => typeof item === "string" && item.trim())
      : [],
    claimTargets: Array.isArray(profile.claim_targets ?? profile.claimTargets)
      ? (profile.claim_targets ?? profile.claimTargets).filter((item) => typeof item === "string" && item.trim())
      : [],
    partyRoles: Array.isArray(profile.party_roles ?? profile.partyRoles)
      ? (profile.party_roles ?? profile.partyRoles).filter((item) => typeof item === "string" && item.trim())
      : [],
    keyFacts: Array.isArray(profile.key_facts ?? profile.keyFacts)
      ? (profile.key_facts ?? profile.keyFacts).filter((item) => typeof item === "string" && item.trim())
      : Array.isArray(fallbackFacts)
        ? fallbackFacts
        : [],
    timeline: Array.isArray(profile.timeline)
      ? profile.timeline.filter((item) => typeof item === "string" && item.trim())
      : [],
    amountTerms: Array.isArray(profile.amount_terms ?? profile.amountTerms)
      ? (profile.amount_terms ?? profile.amountTerms).filter((item) => typeof item === "string" && item.trim())
      : [],
    retrievalIntent: profile.retrieval_intent || profile.retrievalIntent || "",
  };
}

function normalizeSimilarCaseResponse(report) {
  if (!report || typeof report !== "object") return null;
  const extractedCasePoints = Array.isArray(report.extracted_case_points ?? report.extractedCasePoints)
    ? (report.extracted_case_points ?? report.extractedCasePoints).filter((item) => typeof item === "string" && item.trim())
    : [];
  return {
    sessionId: report.session_id || report.sessionId || "",
    query: report.query || "",
    comparisonQuery: report.comparison_query || report.comparisonQuery || "",
    attachmentFileNames: Array.isArray(report.attachment_file_names ?? report.attachmentFileNames)
      ? (report.attachment_file_names ?? report.attachmentFileNames).filter((item) => typeof item === "string" && item.trim())
      : [],
    extractedCasePoints,
    caseSearchProfile: normalizeSimilarCaseProfile(report.case_search_profile ?? report.caseSearchProfile, extractedCasePoints),
    exactMatch: normalizeSimilarCaseMatchItem(report.exact_match ?? report.exactMatch),
    nearDuplicateMatches: Array.isArray(report.near_duplicate_matches ?? report.nearDuplicateMatches)
      ? (report.near_duplicate_matches ?? report.nearDuplicateMatches).map(normalizeSimilarCaseMatchItem).filter(Boolean)
      : [],
    similarCaseMatches: Array.isArray(report.similar_case_matches ?? report.similarCaseMatches)
      ? (report.similar_case_matches ?? report.similarCaseMatches).map(normalizeSimilarCaseMatchItem).filter(Boolean)
      : [],
  };
}

function buildPredictionQuestionHint(report) {
  const questionType = report?.questionType || "general-opponent-view";
  if (questionType === "rebuttal-angle") {
    return "当前结果先回答“会从哪些角度辩驳”，再补每个角度下的具体抓手。";
  }
  if (questionType === "evidence-attack") {
    return "当前结果优先展示对方最可能攻击的证据点和对应补强建议。";
  }
  if (questionType === "procedure-attack") {
    return "当前结果只聚焦程序层面的阻断点，不平铺实体争议。";
  }
  if (questionType === "strongest-point") {
    return "当前结果按主打概率和攻击力排序，只保留最值得优先防守的点。";
  }
  if (questionType === "sequence-strategy") {
    return "当前结果强调对方可能先打什么、后打什么。";
  }
  return "当前结果已按本次问题重排，不再只是通用观点清单。";
}

function getPredictionPriorityClass(priority) {
  if (priority === "主打") return "primary";
  if (priority === "次打") return "secondary";
  return "supporting";
}

function buildPredictionReportHtml(report) {
  const argumentsHtml = Array.isArray(report?.predictedArguments)
    ? report.predictedArguments
        .map((item, index) => {
          const localCitations = Array.isArray(item.citations) ? item.citations : [];
          const isInferenceOnly = Boolean(item.inferenceOnly);
          const priorityClass = getPredictionPriorityClass(item.priority);
          return `
            <section class="prediction-report-block ${isInferenceOnly ? "inference" : "evidence"}">
              <div class="prediction-report-block-head">
                <span class="prediction-report-index">${escapeHtml(item.label || `观点 ${index + 1}`)}</span>
                <strong>${escapeHtml(item.title || "未命名观点")}</strong>
                <span class="prediction-report-priority ${priorityClass}">${escapeHtml(item.priority || "补充")}</span>
                <span class="prediction-report-support-tag ${isInferenceOnly ? "inference" : "evidence"}">${isInferenceOnly ? "推断项" : "引用支持"}</span>
              </div>
              <div class="prediction-report-statement">
                <span>对方可能会这样表述</span>
                <blockquote>${nl2br(item.opponentStatement || `对方可能会围绕“${escapeHtml(item.title || "该点")}”组织答辩表述。`)}</blockquote>
              </div>
              <p>${nl2br(item.basis || "")}</p>
              ${item.sortReason ? `<div class="prediction-report-sort-reason">${nl2br(item.sortReason)}</div>` : ""}
              <div class="prediction-report-support ${isInferenceOnly ? "inference" : "evidence"}">
                ${isInferenceOnly ? "当前没有关联 citation，后续需要结合真实检索和材料缺口校准。" : "当前观点已关联引用依据，可在右侧查看来源内容。"}
              </div>
              <div class="prediction-report-counter">
                <span>我方应对</span>
                <p>${nl2br(item.counter || "")}</p>
              </div>
              ${isInferenceOnly ? "" : buildCitationHtml(localCitations)}
            </section>
          `;
        })
        .join("")
    : "";

  const uncertaintiesHtml = Array.isArray(report?.uncertainties) && report.uncertainties.length > 0
    ? `
      <div class="prediction-report-uncertainties">
        <div class="prediction-report-uncertainties-title">当前限制</div>
        ${report.uncertainties.map((item) => `<p>${nl2br(item)}</p>`).join("")}
      </div>
    `
    : "";

  const retrievalQueriesHtml = Array.isArray(report?.retrievalQueries) && report.retrievalQueries.length > 0
    ? `
      <div class="prediction-report-queries">
        <div class="prediction-report-queries-title">本次问题驱动的检索方向</div>
        <div class="prediction-report-queries-list">
          ${report.retrievalQueries.map((item) => `<span class="prediction-report-query-chip">${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
    `
    : "";

  return `
    <div class="prediction-report-card">
      <div class="prediction-report-head">
        <div>
          <div class="answer-title">观点预测报告</div>
          <h4>${escapeHtml(report?.caseName || "未命名案件")}</h4>
        </div>
        <span class="prediction-report-tag">${report?.source === "backend" ? "真实结果" : "前端预览"}</span>
      </div>
      <div class="prediction-report-summary">
        <div class="prediction-report-query">本次问题：${escapeHtml(report?.query || "")}</div>
        <div class="prediction-report-answer-title">${escapeHtml(report?.answerTitle || "对方最可能提出的观点")}</div>
        <div class="prediction-report-answer-summary">${nl2br(report?.answerSummary || buildPredictionQuestionHint(report))}</div>
        <div class="prediction-report-metrics">
          <span class="prediction-report-metric evidence">引用支持 ${escapeHtml(String(report?.evidenceCount ?? 0))}</span>
          <span class="prediction-report-metric inference">推断项 ${escapeHtml(String(report?.inferenceCount ?? 0))}</span>
        </div>
        <p>${nl2br(report?.caseSummary || "")}</p>
      </div>
      ${retrievalQueriesHtml}
      <div class="prediction-report-grid">
        ${argumentsHtml}
      </div>
      ${uncertaintiesHtml}
      <div class="prediction-report-footer">
        ${buildCitationHtml(Array.isArray(report?.citations) ? report.citations : [])}
      </div>
    </div>
  `;
}

function getSimilarCaseTypeLabel(matchType) {
  if (matchType === "exact_duplicate") return "同案命中";
  if (matchType === "near_duplicate") return "高度相似";
  return "类案";
}

function buildSimilarCaseMatchHtml(item, emphasized = false) {
  const finalScoreText = Number.isFinite(item?.finalScore) ? `${(item.finalScore * 100).toFixed(1)}%` : "--";
  const semanticScoreText = Number.isFinite(item?.similarityScore) ? `${(item.similarityScore * 100).toFixed(1)}%` : "--";
  const overlapText = Number.isFinite(item?.textOverlapRatio) ? `${(item.textOverlapRatio * 100).toFixed(1)}%` : "--";
  const chips = Array.isArray(item?.matchedPoints)
    ? item.matchedPoints.map((point) => `<span class="similar-case-chip">${escapeHtml(point)}</span>`).join("")
    : "";
  return `
    <section class="similar-case-match ${emphasized ? "exact" : ""}">
      <div class="similar-case-match-head">
        <div>
          <div class="similar-case-match-type">${escapeHtml(getSimilarCaseTypeLabel(item?.matchType))}</div>
          <strong>${escapeHtml(item?.fileName || "未命名文档")}</strong>
        </div>
        <div class="similar-case-match-metrics">
          <span>综合分 ${escapeHtml(finalScoreText)}</span>
          <span>语义分 ${escapeHtml(semanticScoreText)}</span>
          <span>文本重合 ${escapeHtml(overlapText)}</span>
        </div>
      </div>
      <p class="similar-case-match-reason">${nl2br(item?.matchReason || "")}</p>
      ${chips ? `<div class="similar-case-chip-row">${chips}</div>` : ""}
      ${buildCitationHtml(Array.isArray(item?.citations) ? item.citations : [])}
    </section>
  `;
}

function buildSimilarCaseReportHtml(report) {
  const attachmentText = Array.isArray(report?.attachmentFileNames) && report.attachmentFileNames.length > 0
    ? report.attachmentFileNames.map((item) => `《${escapeHtml(item)}》`).join("、")
    : "当前上传材料";
  const nearHtml = Array.isArray(report?.nearDuplicateMatches) && report.nearDuplicateMatches.length > 0
    ? report.nearDuplicateMatches.map((item) => buildSimilarCaseMatchHtml(item)).join("")
    : "";
  const similarHtml = Array.isArray(report?.similarCaseMatches) && report.similarCaseMatches.length > 0
    ? report.similarCaseMatches.map((item) => buildSimilarCaseMatchHtml(item)).join("")
    : "";
  const hasExact = Boolean(report?.exactMatch);
  const hasNear = Boolean(nearHtml);
  const hasSimilar = Boolean(similarHtml);
  const emptyHtml = !hasExact && !hasNear && !hasSimilar
    ? `<section class="similar-case-report-section"><p class="panel-text">未检索到足够相似的案例。</p></section>`
    : "";
  return `
    <div class="similar-case-report-card">
      <div class="similar-case-report-head">
        <div>
          <div class="answer-title">类案检索结果</div>
          <h4>基于 ${attachmentText} 的独立类案比对</h4>
        </div>
        <span class="similar-case-report-tag">独立链路</span>
      </div>
      ${hasExact ? `<section class="similar-case-report-section">
        <div class="similar-case-report-section-title">同案检测</div>
        ${buildSimilarCaseMatchHtml(report.exactMatch, true)}
      </section>` : ""}
      ${hasNear ? `<section class="similar-case-report-section">
        <div class="similar-case-report-section-title">高度相似候选</div>
        <div class="similar-case-match-list">${nearHtml}</div>
      </section>` : ""}
      ${hasSimilar ? `<section class="similar-case-report-section">
        <div class="similar-case-report-section-title">普通相似案例</div>
        <div class="similar-case-match-list">${similarHtml}</div>
      </section>` : ""}
      ${emptyHtml}
    </div>
  `;
}

function appendMessage(role, html, shouldScroll = true) {
  const el = document.createElement("article");
  el.className = `msg ${role}`.trim();
  el.innerHTML = html;
  chat.appendChild(el);

  if (shouldScroll) {
    chat.scrollTop = chat.scrollHeight;
  }
  return el;
}

function pushMessageToSession(session, message) {
  if (!session || !message || typeof message !== "object") return;
  session.messages.push(message);
  if (session.messages.length > MAX_MESSAGES_PER_SESSION) {
    session.messages = session.messages.slice(-MAX_MESSAGES_PER_SESSION);
  }
}

function pushMessageToActive(message) {
  const session = ensureActiveSession();
  pushMessageToSession(session, message);

  if (message.type === "user" && (!session.title || session.title === "新会话")) {
    session.title = summarizeTitle(message.text || "");
  }

  touchSession(session);
  renderHistory();
}

function appendUserMessage(text, save = true) {
  appendMessage("user", `<p>${nl2br(text)}</p>`);
  if (save) {
    pushMessageToActive({ type: "user", text });
  }
}

function appendLoadingMessage(text = "思考中") {
  return appendMessage("loading-msg", `<p>${escapeHtml(text)}<span class="thinking-dots">...</span></p>`);
}

function appendErrorMessage(message, save = false) {
  appendMessage("error-msg", `<p>${nl2br(message)}</p>`);
  if (save) {
    pushMessageToActive({ type: "error", text: message });
  }
}

function normalizeChatResponse(response) {
  const citations = Array.isArray(response.citations)
    ? response.citations.map((c) => ({
        file_name: c.file_name,
        line_start: c.line_start,
        line_end: c.line_end,
        similarity_score: c.similarity_score,
        snippet: c.snippet,
      }))
    : [];

  const answer = response.answer || "已收到你的消息。";
  return {
    answer,
    citations,
    attachmentUsed: Boolean(response.attachment_used),
    attachmentFileName:
      typeof response.attachment_file_name === "string" && response.attachment_file_name.trim()
        ? response.attachment_file_name.trim()
        : "",
  };
}

function createStreamingAssistantMessage() {
  const node = appendMessage("", `<div class="answer-title">助手回答</div><p></p>`);
  const body = node.querySelector("p");

  return {
    node,
    update(answer) {
      body.innerHTML = nl2br(answer || "");
      chat.scrollTop = chat.scrollHeight;
    },
    finalize(answer, citations, attachmentUsed = false, attachmentFileName = "") {
      node.innerHTML = buildAssistantHtml(answer, citations, { attachmentUsed, attachmentFileName });
      chat.scrollTop = chat.scrollHeight;
    },
  };
}

function appendChatResponse(response, save = true) {
  const { answer, citations, attachmentUsed, attachmentFileName } = normalizeChatResponse(response);
  appendMessage("", buildAssistantHtml(answer, citations, { attachmentUsed, attachmentFileName }));

  if (save) {
    pushMessageToActive({ type: "assistant", answer, citations, attachmentUsed, attachmentFileName });
  }
}

function appendPredictionReportResponse(report, save = true) {
  const normalizedReport = normalizePredictionReportResponse(report) || report;
  appendMessage("", buildPredictionReportHtml(normalizedReport));
  if (save) {
    pushMessageToActive({ type: "assistant", answer: normalizedReport?.caseSummary || "", citations: [], predictionReport: normalizedReport });
  }
}

function appendSimilarCaseReportResponse(report, save = true) {
  const normalizedReport = normalizeSimilarCaseResponse(report) || report;
  appendMessage("", buildSimilarCaseReportHtml(normalizedReport));
  if (save) {
    pushMessageToActive({ type: "assistant", answer: "", citations: [], similarCaseReport: normalizedReport });
  }
}

async function executeSimilarCaseSearch(query) {
  const session = ensureActiveSession(query);
  activeSessionId = session.id;
  persistSessions();
  renderHistory();

  showChat();
  appendUserMessage(query, true);
  let loadingNode = appendLoadingMessage("类案比对中");

  try {
    const response = await fetch(`${API_BASE}/similar-cases/compare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: session.id,
        query,
        top_k_documents: 5,
        top_k_paragraphs: 3,
      }),
    });

    if (!response.ok) {
      if (loadingNode?.isConnected) {
        loadingNode.remove();
      }
      const raw = await response.text();
      let err = {};
      try {
        err = raw ? JSON.parse(raw) : {};
      } catch {
        err = { detail: raw };
      }
      appendErrorMessage(`类案检索失败 (${response.status})：${err.detail || "未知错误"}`, true);
      return;
    }

    const payload = await response.json();
    if (loadingNode?.isConnected) {
      loadingNode.remove();
      loadingNode = null;
    }
    appendSimilarCaseReportResponse(payload, true);
  } catch (err) {
    if (loadingNode?.isConnected) {
      loadingNode.remove();
    }
    appendErrorMessage(`无法连接到后端服务：${err.message}`, true);
  }
}

function appendTemplateMatchResponse(session, query, save = true) {
  const answer = buildReviewTemplateMatchSummary(session);
  const templateMatch = {
    query,
    recommendedTemplateId: session?.reviewRecommendedTemplate?.id || null,
    selectedTemplateId: session?.reviewSelectedTemplateId || null,
    candidates: Array.isArray(session?.reviewTemplateCandidates)
      ? session.reviewTemplateCandidates.map(normalizeReviewTemplate).filter(Boolean)
      : [],
  };

  appendMessage("", buildReviewTemplateMessageHtml(answer, templateMatch));

  if (save) {
    pushMessageToActive({ type: "assistant", answer, citations: [], templateMatch });
  }
}

async function uploadSessionTempFile(sessionId, kind, file, options = {}) {
  const { onProgress, onUploadSent } = options;
  const formData = new FormData();
  formData.append("session_id", sessionId);
  formData.append("kind", kind);
  formData.append("file", file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/session-files/upload`);

    xhr.upload.addEventListener("progress", (event) => {
      if (typeof onProgress !== "function") return;
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
        return;
      }
      onProgress(0);
    });

    xhr.upload.addEventListener("load", () => {
      if (typeof onUploadSent === "function") {
        onUploadSent();
      }
    });

    xhr.addEventListener("load", () => {
      let payload = {};
      try {
        payload = xhr.responseText ? JSON.parse(xhr.responseText) : {};
      } catch {
        payload = {};
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload);
        return;
      }

      reject(new Error(payload.detail || `上传失败 (${xhr.status})`));
    });

    xhr.addEventListener("error", () => {
      reject(new Error("上传失败，网络连接异常"));
    });

    xhr.addEventListener("abort", () => {
      reject(new Error("上传已取消"));
    });

    xhr.send(formData);
  });
}

async function deleteSessionTempFile(fileId) {
  const response = await fetch(`${API_BASE}/session-files/${encodeURIComponent(fileId)}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    const error = new Error(err.detail || `删除失败 (${response.status})`);
    error.status = response.status;
    throw error;
  }

  return response.json();
}

async function clearSessionTempFiles(sessionId, kind) {
  if (!sessionId) return { cleared: 0 };

  const url = new URL(`${API_BASE}/session-files/session/${encodeURIComponent(sessionId)}`);
  if (kind) {
    url.searchParams.set("kind", kind);
  }

  const response = await fetch(url.toString(), {
    method: "DELETE",
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `清理失败 (${response.status})`);
  }

  return response.json();
}

async function fetchReviewTemplateRecommendation(sessionId) {
  const url = new URL(`${API_BASE}/contract-review/template-recommendation`);
  url.searchParams.set("session_id", sessionId);

  const response = await fetch(url.toString());
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `模板推荐失败 (${response.status})`);
  }
  return response.json();
}

async function refreshReviewTemplateRecommendation(sessionId) {
  const session = getSessionById(sessionId);
  if (!session) return;

  if (!Array.isArray(session.reviewTempFiles) || session.reviewTempFiles.length === 0) {
    clearReviewTemplateState(session);
    touchSession(session);
    return;
  }

  try {
    const payload = await fetchReviewTemplateRecommendation(sessionId);
    const currentSession = getSessionById(sessionId);
    if (!currentSession) return;

    const candidates = Array.isArray(payload.candidate_templates)
      ? payload.candidate_templates.map(normalizeReviewTemplate).filter(Boolean)
      : [];
    const recommended = normalizeReviewTemplate(payload.recommended_template);
    const candidateIds = new Set(candidates.map((item) => item.id));
    const nextSelectedTemplateId =
      currentSession.reviewSelectedTemplateId && candidateIds.has(currentSession.reviewSelectedTemplateId)
        ? currentSession.reviewSelectedTemplateId
        : recommended?.id || candidates[0]?.id || null;

    currentSession.reviewRecommendedTemplate = recommended;
    currentSession.reviewTemplateCandidates = candidates;
    currentSession.reviewSelectedTemplateId = nextSelectedTemplateId;
    touchSession(currentSession);
  } catch (err) {
    const currentSession = getSessionById(sessionId);
    if (currentSession) {
      clearReviewTemplateState(currentSession);
      touchSession(currentSession);
    }
    throw err;
  }
}

async function uploadReviewTempFiles(files) {
  if (!Array.isArray(files) || files.length === 0) return;

  const session = ensureActiveSession(input.value.trim());
  activeSessionId = session.id;
  persistSessions();
  renderHistory();
  showChat();

  const uploadedItems = [];
  const errors = [];
  const pendingEntries = createPendingUploadEntries(session.id, files, "review");
  renderChatAttachments();

  for (const [index, file] of files.entries()) {
    const pendingEntry = pendingEntries[index];
    try {
      const result = await uploadSessionTempFile(session.id, "review_target", file, {
        onProgress: (progress) => {
          if (!pendingEntry) return;
          updatePendingUploadProgress(session.id, pendingEntry.id, progress);
          renderChatAttachments();
        },
        onUploadSent: () => {
          if (!pendingEntry) return;
          markPendingUploadProcessing(session.id, pendingEntry.id);
          renderChatAttachments();
        },
      });
      const normalized = normalizeReviewTempFile(result);
      if (normalized) {
        uploadedItems.push(normalized);
        rememberReviewTempFiles(session.id, [normalized], [file]);
      }
    } catch (err) {
      errors.push(`${file.name}：${err.message}`);
    } finally {
      if (pendingEntry) {
        removePendingUploadEntry(session.id, pendingEntry.id);
        renderChatAttachments();
      }
    }
  }

  if (uploadedItems.length > 0) {
    clearReviewTemplateState(session);
    session.reviewTempFiles = [...session.reviewTempFiles, ...uploadedItems];
    touchSession(session);
    renderHistory();
    renderChatAttachments();
  }

  if (errors.length > 0) {
    appendErrorMessage(`待审合同上传失败：\n${errors.join("\n")}`);
  }
}

function executeContractReviewNoFileResponse(query) {
  const session = ensureActiveSession(query);
  activeSessionId = session.id;
  persistSessions();
  renderHistory();

  showChat();
  appendUserMessage(query, true);
  appendChatResponse(
    {
      answer: "当前无合同可审查。请先上传待审合同文件，再发起合同审查。",
      citations: [],
    },
    true
  );
}

function consumeJsonLines(buffer, chunk, onItem) {
  const lines = `${buffer}${chunk}`.split("\n");
  const rest = lines.pop() || "";

  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    onItem(JSON.parse(trimmed));
  });

  return rest;
}

function renderSessionMessages(session) {
  closeCitationSidebar();
  chat.innerHTML = "";

  session.messages.forEach((msg) => {
    if (msg.type === "user") {
      appendMessage("user", `<p>${nl2br(msg.text || "")}</p>`, false);
      return;
    }
    if (msg.type === "assistant") {
      if (msg.templateMatch) {
        appendMessage("", buildReviewTemplateMessageHtml(msg.answer || "", msg.templateMatch), false);
        return;
      }
      if (msg.predictionTemplateMatch) {
        appendMessage("", buildPredictionTemplateMessageHtml(msg.answer || "", msg.predictionTemplateMatch), false);
        return;
      }
      if (msg.predictionReport) {
        appendMessage("", buildPredictionReportHtml(msg.predictionReport), false);
        return;
      }
      if (msg.similarCaseReport) {
        appendMessage("", buildSimilarCaseReportHtml(msg.similarCaseReport), false);
        return;
      }
      appendMessage(
        "",
        buildAssistantHtml(msg.answer || "", msg.citations || [], {
          attachmentUsed: Boolean(msg.attachmentUsed),
          attachmentFileName: msg.attachmentFileName || "",
        }),
        false
      );
      return;
    }
    appendMessage("error-msg", `<p>${nl2br(msg.text || "")}</p>`, false);
  });

  chat.scrollTop = chat.scrollHeight;
}

function renderHistory() {
  historyList.innerHTML = "";

  if (chatSessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = "暂无历史记录";
    historyList.appendChild(empty);
    return;
  }

  chatSessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "history-entry";
    if (session.id === activeSessionId) {
      row.classList.add("active");
    }

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "history-item";
    btn.textContent = session.title;
    btn.title = session.title;
    btn.addEventListener("click", () => {
      activeSessionId = session.id;
      persistSessions();
      renderHistory();
      renderSessionMessages(session);
      showChat();
      syncComposerModeUi();
      closeSidebarOnMobile();
      input.focus();
    });

    const del = document.createElement("button");
    del.type = "button";
    del.className = "history-delete";
    del.setAttribute("aria-label", "删除历史会话");
    del.title = "删除历史会话";
    del.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
        <path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 7h2v8h-2v-8Zm4 0h2v8h-2v-8ZM7 10h2v8H7v-8Z"/>
      </svg>
    `;
    del.addEventListener("click", async (event) => {
      event.stopPropagation();
      try {
        await clearSessionTempFiles(session.id);
      } catch (err) {
        appendErrorMessage(`删除会话临时文件失败：${err.message}`);
        return;
      }

      clearSessionAttachmentBridgeState(session.id);
      chatSessions = chatSessions.filter((s) => s.id !== session.id);
      if (activeSessionId === session.id) {
        activeSessionId = null;
        chat.innerHTML = "";
      }
      persistSessions();
      renderHistory();
      restoreConversationView();
    });

    row.appendChild(btn);
    row.appendChild(del);
    historyList.appendChild(row);
  });
}

async function executeSearch(query) {
  const session = ensureActiveSession(query);
  activeSessionId = session.id;
  persistSessions();
  renderHistory();

  showChat();
  appendUserMessage(query, true);
  let loadingNode = appendLoadingMessage();
  let assistantStream = null;
  let answerText = "";
  let finalized = false;

  try {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        session_id: session.id,
        use_chat_attachment: true,
        top_k_documents: 8,
        top_k_paragraphs: 8,
      }),
    });

    if (!response.ok) {
      if (loadingNode?.isConnected) {
        loadingNode.remove();
      }
      const raw = await response.text();
      let err = {};
      try {
        err = raw ? JSON.parse(raw) : {};
      } catch {
        err = { detail: raw };
      }
      appendErrorMessage(`请求失败 (${response.status})：${err.detail || "未知错误"}`, true);
      return;
    }

    if (!response.body) {
      throw new Error("当前环境不支持流式响应");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const handleStreamItem = (item) => {
      if (item.type === "delta") {
        if (loadingNode?.isConnected) {
          loadingNode.remove();
          loadingNode = null;
        }
        if (!assistantStream) {
          assistantStream = createStreamingAssistantMessage();
        }
        answerText += item.delta || "";
        assistantStream.update(answerText);
        return;
      }

      if (item.type === "done") {
        if (loadingNode?.isConnected) {
          loadingNode.remove();
          loadingNode = null;
        }
        if (!assistantStream) {
          assistantStream = createStreamingAssistantMessage();
        }
        const normalized = normalizeChatResponse(item);
        answerText = normalized.answer || answerText || "已收到你的消息。";
        assistantStream.finalize(
          answerText,
          normalized.citations,
          normalized.attachmentUsed,
          normalized.attachmentFileName
        );
        pushMessageToActive({
          type: "assistant",
          answer: answerText,
          citations: normalized.citations,
          attachmentUsed: normalized.attachmentUsed,
          attachmentFileName: normalized.attachmentFileName,
        });
        finalized = true;
        return;
      }

      if (item.type === "error") {
        throw new Error(item.detail || "流式响应失败");
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer = consumeJsonLines(buffer, decoder.decode(value, { stream: true }), handleStreamItem);
    }

    buffer = consumeJsonLines(buffer, decoder.decode(), handleStreamItem);

    if (!finalized) {
      throw new Error("流式响应提前结束");
    }
  } catch (err) {
    if (loadingNode?.isConnected) {
      loadingNode.remove();
    }
    appendErrorMessage(`无法连接到后端服务：${err.message}`, true);
  }
}

async function executeContractReview(query, templateId, options = {}) {
  const { appendUser = true } = options;
  const session = ensureActiveSession(query);
  activeSessionId = session.id;
  persistSessions();
  renderHistory();

  showChat();
  if (appendUser) {
    appendUserMessage(query, true);
  }
  let loadingNode = appendLoadingMessage();
  let assistantStream = null;
  let answerText = "";
  let finalized = false;

  try {
    const response = await fetch(`${API_BASE}/contract-review/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: session.id,
        template_id: templateId,
        query,
      }),
    });

    if (!response.ok) {
      if (loadingNode?.isConnected) {
        loadingNode.remove();
      }
      const raw = await response.text();
      let err = {};
      try {
        err = raw ? JSON.parse(raw) : {};
      } catch {
        err = { detail: raw };
      }
      appendErrorMessage(`请求失败 (${response.status})：${err.detail || "未知错误"}`, true);
      return;
    }

    if (!response.body) {
      throw new Error("当前环境不支持流式响应");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const handleStreamItem = (item) => {
      if (item.type === "delta") {
        if (loadingNode?.isConnected) {
          loadingNode.remove();
          loadingNode = null;
        }
        if (!assistantStream) {
          assistantStream = createStreamingAssistantMessage();
        }
        answerText += item.delta || "";
        assistantStream.update(answerText);
        return;
      }

      if (item.type === "done") {
        if (loadingNode?.isConnected) {
          loadingNode.remove();
          loadingNode = null;
        }
        if (!assistantStream) {
          assistantStream = createStreamingAssistantMessage();
        }
        const answer = item.answer || answerText || "已收到你的消息。";
        answerText = answer;
        assistantStream.finalize(answerText, []);
        pushMessageToActive({ type: "assistant", answer: answerText, citations: [] });
        finalized = true;
        return;
      }

      if (item.type === "error") {
        throw new Error(item.detail || "流式响应失败");
      }
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer = consumeJsonLines(buffer, decoder.decode(value, { stream: true }), handleStreamItem);
    }

    buffer = consumeJsonLines(buffer, decoder.decode(), handleStreamItem);

    if (!finalized) {
      throw new Error("流式响应提前结束");
    }
  } catch (err) {
    if (loadingNode?.isConnected) {
      loadingNode.remove();
    }
    appendErrorMessage(`无法连接到后端服务：${err.message}`, true);
  }
}

function appendDocToList(data) {
  const docList = document.getElementById("docList");
  const docId = String(data.doc_id || "");
  const existed = docList.querySelector(`[data-doc-id="${docId}"]`);
  if (existed) {
    existed.remove();
  }

  const el = document.createElement("div");
  el.className = "doc-item";
  el.dataset.docId = docId;

  const shortId = escapeHtml(String(data.doc_id || "")).slice(0, 8);
  const paragraphCount = Number.isFinite(data.paragraphs_indexed) ? data.paragraphs_indexed : 0;
  const lineCount = Number.isFinite(data.total_lines) ? data.total_lines : 0;
  const fileName = escapeHtml(String(data.file_name || ""));

  el.innerHTML = `
    <div class="doc-info">
      <strong title="${fileName || shortId}">${fileName || shortId || "未知文件"}</strong>
      <span>${paragraphCount} 段 · ${lineCount} 行</span>
    </div>
    <button class="doc-delete" type="button">删除</button>
  `;

  const deleteBtn = el.querySelector(".doc-delete");
  deleteBtn.addEventListener("click", async () => {
    try {
      await fetch(`${API_BASE}/documents/${encodeURIComponent(data.doc_id)}`, { method: "DELETE" });
      el.remove();
      showEmptyDocHint();
    } catch (err) {
      appendErrorMessage(`删除失败：${err.message}`);
    }
  });

  docList.appendChild(el);
}

function showEmptyDocHint() {
  const docList = document.getElementById("docList");
  if (docList.children.length === 0) {
    docList.innerHTML = `<div class="doc-item"><div class="doc-info"><strong>暂无已上传文件</strong><span>上传后会显示在这里</span></div></div>`;
  }
}

async function handleDocUpload(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `上传失败 (${response.status})`);
  }

  const data = await response.json();
  const docList = document.getElementById("docList");
  const hint = docList.querySelector(".doc-item");
  if (hint && hint.textContent.includes("暂无已上传文件")) {
    docList.innerHTML = "";
  }
  appendDocToList(data);
}

async function loadDocumentList() {
  const docList = document.getElementById("docList");
  docList.innerHTML = "";

  try {
    const response = await fetch(`${API_BASE}/documents?limit=100`);
    if (!response.ok) {
      throw new Error(`加载失败 (${response.status})`);
    }
    const list = await response.json();
    if (!Array.isArray(list) || list.length === 0) {
      showEmptyDocHint();
      return;
    }
    list.forEach((item) => appendDocToList(item));
  } catch (err) {
    docList.innerHTML =
      `<div class="doc-item"><div class="doc-info"><strong>读取失败</strong><span>${escapeHtml(err.message || "请稍后重试")}</span></div></div>`;
  }
}

function updateTemplateListCount(count) {
  if (!templateListCount) return;
  templateListCount.textContent = `${count} 个`;
}

function showTemplateEmptyHint(text = "暂无标准模板") {
  if (!templateList) return;
  templateList.innerHTML = `<div class="template-empty">${escapeHtml(text)}</div>`;
  updateTemplateListCount(0);
}

function buildTemplateItem(data) {
  const docId = String(data.doc_id || "");
  const paragraphCount = Number.isFinite(data.paragraphs_indexed) ? data.paragraphs_indexed : 0;
  const lineCount = Number.isFinite(data.total_lines) ? data.total_lines : 0;
  const fileName = escapeHtml(String(data.file_name || ""));
  const shortId = escapeHtml(String(data.doc_id || "")).slice(0, 8);

  return `
    <article class="template-item" data-template-id="${escapeHtml(docId)}">
      <div class="template-item-info">
        <strong title="${fileName || shortId}">${fileName || shortId || "未知模板"}</strong>
        <span>${paragraphCount} 段 · ${lineCount} 行</span>
      </div>
      <button class="template-delete" type="button" data-template-delete="${escapeHtml(docId)}">删除</button>
    </article>
  `;
}

function renderTemplateList(items) {
  if (!templateList) return;
  if (!Array.isArray(items) || items.length === 0) {
    showTemplateEmptyHint();
    return;
  }

  templateList.innerHTML = items.map((item) => buildTemplateItem(item)).join("");
  updateTemplateListCount(items.length);
}

async function loadTemplateList() {
  if (!templateList) return;
  templateList.innerHTML = `<div class="template-empty">加载中...</div>`;
  updateTemplateListCount(0);

  try {
    const response = await fetch(`${API_BASE}/templates?limit=200`);
    if (!response.ok) {
      throw new Error(`加载失败 (${response.status})`);
    }
    const list = await response.json();
    renderTemplateList(Array.isArray(list) ? list : []);
  } catch (err) {
    showTemplateEmptyHint(`读取失败：${err.message || "请稍后重试"}`);
  }
}

async function uploadTemplateFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/templates/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `上传失败 (${response.status})`);
  }

  return response.json();
}

async function deleteTemplateFile(docId) {
  const response = await fetch(`${API_BASE}/templates/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail || `删除失败 (${response.status})`);
  }
}

async function checkSystemStatus() {
  const setStatus = (id, ready, text) => {
    const item = document.getElementById(id);
    if (!item) return;
    const dot = item.querySelector(".status-dot");
    const label = item.querySelector(".status-text");
    dot.className = `status-dot ${ready ? "ready" : "error"}`;
    label.textContent = text;
  };

  try {
    const response = await fetch(`${API_BASE}/health`);
    if (!response.ok) throw new Error("health request failed");

    const data = await response.json();
    setStatus("statusPG", !!data.postgresql_ready, data.postgresql_ready ? "就绪" : "未就绪");
    setStatus("statusQdrant", !!data.qdrant_ready, data.qdrant_ready ? "就绪" : "未就绪");
    setStatus("statusEmbedding", !!data.embedding_model_ready, data.embedding_model_ready ? "就绪" : "未就绪");
    setStatus("statusReranker", !!data.reranker_model_ready, data.reranker_model_ready ? "就绪" : "未就绪");
  } catch (err) {
    ["statusPG", "statusQdrant", "statusEmbedding", "statusReranker"].forEach((id) => {
      const item = document.getElementById(id);
      if (!item) return;
      const dot = item.querySelector(".status-dot");
      const label = item.querySelector(".status-text");
      dot.className = "status-dot error";
      label.textContent = "后端未连接";
    });
  }
}

renderHistory();
showEmptyDocHint();

const activeSession = getActiveSession();
if (activeSession && activeSession.messages.length > 0) {
  renderSessionMessages(activeSession);
  showChat();
} else {
  showWelcome();
}
syncComposerModeUi();
renderRightSidebarAttachments();
syncRightSidebarTabUi();

composer.addEventListener("submit", async (e) => {
  e.preventDefault();
  const rawQuery = input.value;
  const currentMode = getComposerMode();
  const query = currentMode === "similar-case" ? buildSimilarCaseQuery(rawQuery) : rawQuery.trim();
  if (!query) return;
  input.value = "";

  if (currentMode === "contract-review") {
    const session = ensureActiveSession(query);
    session.lastReviewQuery = query;
    touchSession(session);
    await ensureReviewTempFiles(session, { reportMissing: true });
    const reviewTempFiles = session?.reviewTempFiles || [];
    if (reviewTempFiles.length === 0) {
      executeContractReviewNoFileResponse(query);
      return;
    }

    showChat();
    appendUserMessage(query, true);
    const matchingNode = appendLoadingMessage("标准模板匹配中");

    try {
      await refreshReviewTemplateRecommendation(session.id);
    } catch (err) {
      if (matchingNode?.isConnected) {
        matchingNode.remove();
      }
      appendErrorMessage(`模板匹配失败：${err.message}`, true);
      return;
    }

    if (matchingNode?.isConnected) {
      matchingNode.remove();
    }

    const selectedTemplate = getSelectedReviewTemplate(session);
    if (!selectedTemplate) {
      appendChatResponse(
        {
          answer: "当前无可用标准模板。请先在左侧标准模板库上传模板，或补充更合适的标准合同模板后再发起合同审查。",
          citations: [],
        },
        true
      );
      return;
    }

    appendTemplateMatchResponse(session, query, true);
    return;
  }

  if (currentMode === "opponent-prediction") {
    try {
      await loadPredictionTemplatesRemote({ silent: true });
    } catch (err) {
      appendErrorMessage(`案件模板加载失败：${err.message || err}`, true);
      return;
    }
    const session = ensureActiveSession(query);
    activeSessionId = session.id;
    session.lastPredictionQuery = query;
    session.predictionTemplateCandidates = predictionTemplates.map(normalizePredictionTemplate).filter(Boolean);
    session.predictionSelectedTemplateId = null;
    touchSession(session);
    renderHistory();
    showChat();
    appendUserMessage(query, true);
    if (session.predictionTemplateCandidates.length === 0) {
      appendChatResponse(
        {
          answer: "当前无可用案件模板。请先到左侧观点预测页创建案件模板，然后再发起观点预测。",
          citations: [],
        },
        true
      );
      return;
    }
    appendPredictionTemplateMatchResponse(session, query, true);
    return;
  }

  if (currentMode === "similar-case") {
    const session = ensureActiveSession(query);
    activeSessionId = session.id;
    touchSession(session);
    renderHistory();
    if (!hasReadyChatAttachments(session)) {
      executeSearch(query);
      return;
    }
    await executeSimilarCaseSearch(query);
    return;
  }

  executeSearch(query);
});

document.querySelectorAll(".suggestions button").forEach((btn) => {
  btn.addEventListener("click", () => {
    input.value = btn.textContent || "";
    input.focus();
  });
});

document.getElementById("newChatBtn").addEventListener("click", () => {
  activeSessionId = null;
  draftSessionMode = "chat";
  persistSessions();
  chat.innerHTML = "";
  renderHistory();
  showWelcome();
  syncComposerModeUi();
  closeSidebarOnMobile();
  input.focus();
});

rightSidebarTabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setRightSidebarTab(button.dataset.rightSidebarTab || "attachments");
  });
});

menuFiles.addEventListener("click", () => {
  showPanel("files");
  closeSidebarOnMobile();
});
menuContractReview.addEventListener("click", () => {
  showPanel("contract-review");
  closeSidebarOnMobile();
});
menuOpponentPrediction.addEventListener("click", () => {
  showPanel("opponent-prediction");
  closeSidebarOnMobile();
});
menuStatus.addEventListener("click", () => {
  showPanel("status");
  closeSidebarOnMobile();
});

contractReviewModeToggle.addEventListener("click", () => {
  setComposerMode(getComposerMode() === "contract-review" ? "chat" : "contract-review");
});

opponentPredictionModeToggle.addEventListener("click", () => {
  setComposerMode(getComposerMode() === "opponent-prediction" ? "chat" : "opponent-prediction");
});

similarCaseModeToggle.addEventListener("click", () => {
  setComposerMode(getComposerMode() === "similar-case" ? "chat" : "similar-case");
});

reviewUploadBtn.addEventListener("click", () => {
  if (getComposerMode() === "opponent-prediction") return;
  const targetInput = getComposerMode() === "contract-review" ? reviewContractInput : chatAttachmentInput;
  if (targetInput.disabled) return;
  targetInput.click();
});

chatAttachmentInput.addEventListener("change", async (event) => {
  if (event.target instanceof HTMLInputElement) {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) {
      await addChatAttachments(files);
    }
    event.target.value = "";
  }
});

reviewContractInput.addEventListener("change", async (event) => {
  if (event.target instanceof HTMLInputElement) {
    const files = Array.from(event.target.files || []);
    if (files.length > 0) {
      await addReviewTempFiles(files);
    }
    event.target.value = "";
  }
});

if (predictionCaseNameInput) {
  predictionCaseNameInput.addEventListener("input", () => {
    syncPredictionTemplateFormState();
  });
}

if (predictionOpponentCorpusInput) {
  predictionOpponentCorpusInput.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    pendingPredictionOpponentCorpusFiles = Array.from(event.target.files || []);
    renderPredictionPendingFiles(predictionOpponentCorpusFiles, pendingPredictionOpponentCorpusFiles, "尚未选择对方语料");
    syncPredictionTemplateFormState();
  });
}

if (predictionCaseMaterialInput) {
  predictionCaseMaterialInput.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLInputElement)) return;
    pendingPredictionCaseMaterialFiles = Array.from(event.target.files || []);
    renderPredictionPendingFiles(predictionCaseMaterialFiles, pendingPredictionCaseMaterialFiles, "尚未选择案情材料");
    syncPredictionTemplateFormState();
  });
}

if (predictionTemplateSaveBtn) {
  predictionTemplateSaveBtn.addEventListener("click", async () => {
    await savePredictionTemplateRemote();
  });
}

if (predictionTemplateList) {
  predictionTemplateList.addEventListener("click", async (event) => {
    const trigger = event.target.closest("[data-prediction-template-delete]");
    if (!trigger) return;
    const templateId = trigger.getAttribute("data-prediction-template-delete") || "";
    if (!templateId) return;
    await deletePredictionTemplateRemote(templateId);
  });
}

chatAttachmentTray.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-remove-attachment],[data-remove-review-file]");
  if (!target) return;
  const reviewFileId = target.getAttribute("data-remove-review-file") || "";
  const attachmentId = target.getAttribute("data-remove-attachment") || "";
  if (reviewFileId || attachmentId) {
    await removeSessionFile({ attachmentId, reviewFileId });
  }
});

chat.addEventListener("click", async (event) => {
  const templateTrigger = event.target.closest("[data-review-template-select]");
  if (templateTrigger) {
    const session = getActiveSession();
    const templateId = templateTrigger.getAttribute("data-review-template-select") || "";
    const encodedQuery = templateTrigger.getAttribute("data-review-query") || "";
    const query =
      (encodedQuery ? decodeURIComponent(encodedQuery) : "") ||
      (typeof session?.lastReviewQuery === "string" ? session.lastReviewQuery : "");

    if (!session || !templateId || !query) return;
    if (reviewSelectionLocksBySession.has(session.id)) return;

    reviewSelectionLocksBySession.add(session.id);
    session.reviewSelectedTemplateId = templateId;
    session.lastReviewQuery = query;
    removeLatestTemplateMatchMessage(session);
    touchSession(session);
    renderSessionMessages(session);
    showChat();

    try {
      await executeContractReview(query, templateId, { appendUser: false });
    } finally {
      reviewSelectionLocksBySession.delete(session.id);
    }
    return;
  }

  const predictionTrigger = event.target.closest("[data-prediction-template-select]");
  if (predictionTrigger) {
    const session = getActiveSession();
    const templateId = predictionTrigger.getAttribute("data-prediction-template-select") || "";
    const encodedQuery = predictionTrigger.getAttribute("data-prediction-query") || "";
    const query =
      (encodedQuery ? decodeURIComponent(encodedQuery) : "") ||
      (typeof session?.lastPredictionQuery === "string" ? session.lastPredictionQuery : "");

    if (!session || !templateId || !query) return;

    session.predictionSelectedTemplateId = templateId;
    session.lastPredictionQuery = query;
    session.predictionTemplateCandidates = predictionTemplates.map(normalizePredictionTemplate).filter(Boolean);
    removeLatestPredictionTemplateMatchMessage(session);
    touchSession(session);
    renderSessionMessages(session);
    showChat();
    await executePredictionPlaceholder(session, query, { appendUser: false });
    return;
  }

  const trigger = event.target.closest(".citation-trigger");
  if (!trigger) return;
  const citations = decodeCitations(trigger.dataset.citations || "");
  openCitationSidebar(citations);
});

document.querySelectorAll(".panel-close").forEach((btn) => {
  btn.addEventListener("click", restoreConversationView);
});

citationSidebarClose.addEventListener("click", closeCitationSidebar);

citationSidebarResize.addEventListener("pointerdown", (event) => {
  if (window.innerWidth <= SIDEBAR_BREAKPOINT) return;

  event.preventDefault();
  document.body.classList.add("resizing-citation-sidebar");

  const onPointerMove = (moveEvent) => {
    setCitationSidebarWidth(window.innerWidth - moveEvent.clientX);
  };

  const stopResize = () => {
    document.body.classList.remove("resizing-citation-sidebar");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", stopResize);
    window.removeEventListener("pointercancel", stopResize);
  };

  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", stopResize);
  window.addEventListener("pointercancel", stopResize);
});

document.getElementById("docFileInput").addEventListener("change", async (event) => {
  const files = event.target.files;
  if (!files || files.length === 0) return;

  setUploadBusy(true);
  showFileFeedback(`正在上传 ${files.length} 个文件...`, "info", 0);

  let successCount = 0;
  let failureCount = 0;

  for (const file of files) {
    try {
      await handleDocUpload(file);
      successCount += 1;
      showFileFeedback(`上传成功：${file.name}`, "success", 2200);
    } catch (err) {
      failureCount += 1;
      showFileFeedback(`${file.name} 上传失败：${err.message}`, "error", 8000);
    }
  }

  if (successCount > 0) {
    await loadDocumentList();
  }

  if (failureCount === 0) {
    showFileFeedback(`上传完成：成功 ${successCount} 个`, "success", 3500);
  } else {
    showFileFeedback(`上传完成：成功 ${successCount} 个，失败 ${failureCount} 个`, "error", 9000);
  }

  setUploadBusy(false);
  event.target.value = "";
});

if (templateFileInput) {
  templateFileInput.addEventListener("change", async (event) => {
    const files = event.target.files;
    if (!files || files.length === 0) return;

    setTemplateUploadBusy(true);
    showTemplateFeedback("正在上传模板...", "info", 0);

    try {
      const file = files[0];
      await uploadTemplateFile(file);
      await loadTemplateList();
      showTemplateFeedback(`上传成功：${file.name}`, "success", 3000);
    } catch (err) {
      showTemplateFeedback(`上传失败：${err.message}`, "error", 8000);
    } finally {
      setTemplateUploadBusy(false);
      event.target.value = "";
    }
  });
}

if (templateList) {
  templateList.addEventListener("click", async (event) => {
    const trigger = event.target.closest("[data-template-delete]");
    if (!trigger) return;

    const docId = trigger.getAttribute("data-template-delete") || "";
    if (!docId) return;

    try {
      await deleteTemplateFile(docId);
      await loadTemplateList();
      showTemplateFeedback("模板已删除", "success", 2200);
    } catch (err) {
      showTemplateFeedback(`删除失败：${err.message}`, "error", 8000);
    }
  });
}

document.getElementById("refreshStatusBtn").addEventListener("click", checkSystemStatus);

document.getElementById("bootstrapBtn").addEventListener("click", async () => {
  try {
    const response = await fetch(`${API_BASE}/bootstrap`, { method: "POST" });
    if (!response.ok) {
      throw new Error(`请求失败 (${response.status})`);
    }
    await response.json();
    checkSystemStatus();
  } catch (err) {
    appendErrorMessage(`初始化失败：${err.message}`);
  }
});

function syncSidebarToggleLabel() {
  const isDesktop = window.innerWidth > SIDEBAR_BREAKPOINT;
  const collapsed = app.classList.contains("sidebar-collapsed");
  const opened = app.classList.contains("sidebar-open");
  sidebarToggle.setAttribute(
    "aria-label",
    isDesktop ? (collapsed ? "展开左侧项目栏" : "折叠左侧项目栏") : opened ? "收起左侧项目栏" : "展开左侧项目栏"
  );
}

function closeSidebarOnMobile() {
  if (window.innerWidth > SIDEBAR_BREAKPOINT) return;
  if (!app.classList.contains("sidebar-open")) return;
  app.classList.remove("sidebar-open");
  syncSidebarToggleLabel();
}

sidebarToggle.addEventListener("click", () => {
  if (window.innerWidth > SIDEBAR_BREAKPOINT) {
    app.classList.toggle("sidebar-collapsed");
  } else {
    app.classList.toggle("sidebar-open");
  }

  syncSidebarToggleLabel();
});

if (sidebarBackdrop) {
  sidebarBackdrop.addEventListener("click", closeSidebarOnMobile);
}

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closeSidebarOnMobile();
});

window.addEventListener("resize", () => {
  if (window.innerWidth > SIDEBAR_BREAKPOINT) {
    app.classList.remove("sidebar-open");
    setCitationSidebarWidth(parseFloat(citationSidebar.style.width) || CITATION_SIDEBAR_DEFAULT_WIDTH);
  } else {
    app.classList.remove("sidebar-collapsed");
    citationSidebar.style.removeProperty("width");
    citationSidebar.style.removeProperty("min-width");
  }

  syncSidebarToggleLabel();
});

setCitationSidebarWidth(CITATION_SIDEBAR_DEFAULT_WIDTH);
syncSidebarToggleLabel();
renderPredictionPendingFiles(predictionOpponentCorpusFiles, pendingPredictionOpponentCorpusFiles, "尚未选择对方语料");
renderPredictionPendingFiles(predictionCaseMaterialFiles, pendingPredictionCaseMaterialFiles, "尚未选择案情材料");
renderPredictionTemplatePlaceholder();
syncPredictionTemplateFormState();
void loadPredictionTemplatesRemote({ silent: true }).catch(() => {});
