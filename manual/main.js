const jsonModal = document.querySelector("#jsonModal");
const jsonModalTitle = document.querySelector("#jsonModalTitle");
const jsonModalDescription = document.querySelector("#jsonModalDescription");
const jsonModalFlow = document.querySelector("#jsonModalFlow");
const jsonModalActionFlow = document.querySelector("#jsonModalActionFlow");
const jsonModalContent = document.querySelector("#jsonModalContent");
const jsonModalFrame = document.querySelector("#jsonModalFrame");
const mediaModal = document.querySelector("#mediaModal");
const mediaModalTitle = document.querySelector("#mediaModalTitle");
const mediaModalImage = document.querySelector("#mediaModalImage");
const fileModal = document.querySelector("#fileModal");
const fileModalTitle = document.querySelector("#fileModalTitle");
const fileListPane = document.querySelector("#fileListPane");
const filePreviewContent = document.querySelector("#filePreviewContent");
const manualDownloadButton = document.querySelector("[data-manual-download]");
const filterSteps = Array.from(document.querySelectorAll("[data-stage-filter]"));
const stageCards = Array.from(document.querySelectorAll(".stage-card"));
const fileLists = Array.from(document.querySelectorAll("[data-file-list]"));
let fileManifest = {};
let fileBrowserItems = [];
let agentActionsMap = null;

function normalizeManualDataKey(href) {
  const raw = String(href || "").trim();
  if (!raw) return "";
  try {
    const url = new URL(raw, window.location.href);
    const path = decodeURIComponent(url.pathname || "");
    const marker = "/manual/";
    const markerIndex = path.indexOf(marker);
    if (markerIndex >= 0) {
      return path.slice(markerIndex + marker.length).replace(/^\/+/, "");
    }
    return path.split("/").filter(Boolean).join("/");
  } catch {
    return raw.replace(/^[.\/]+/, "");
  }
}

function embeddedManualText(href) {
  const files = window.PLANT_MANUAL_FILES || {};
  const key = normalizeManualDataKey(href);
  if (Object.prototype.hasOwnProperty.call(files, key)) {
    return files[key];
  }
  return null;
}

async function readManualText(href) {
  const embedded = embeddedManualText(href);
  if (embedded !== null) return embedded;
  const response = await fetch(href);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.text();
}

async function readManualJson(href) {
  return JSON.parse(await readManualText(href));
}

const AGENT_PROMPT_SKILL_PATTERN =
  /^# Skill:\s*(.+?)\n\n([\s\S]*?)\n\n((?:# Context\n[\s\S]*?\n\n)?)# 任務\n\n?([\s\S]*)$/;

const PROMPT_CONTEXT_HEADINGS = new Set([
  "Context",
  "Related Context",
  "Observation",
  "Input",
  "Elicitation Context",
]);

const PROMPT_OUTPUT_HEADINGS = new Set([
  "Output",
  "Output Format",
  "Output JSON",
  "輸出",
  "輸出 JSON",
  "輸出要求",
]);

function splitAgentPromptSections(text) {
  const source = String(text || "");
  const skillMatch = source.match(AGENT_PROMPT_SKILL_PATTERN);
  if (skillMatch) {
    const contextBody = (skillMatch[3] || "").replace(/^# Context\n/, "").trim();
    return [
      {
        type: "skill",
        title: `Skill：${skillMatch[1].trim()}`,
        body: skillMatch[2].trim(),
        collapsed: true,
      },
      ...splitPromptBodySections(`# 任務\n${skillMatch[4].trim()}`),
    ].filter((section) => section.body);
  }

  return splitPromptBodySections(source);
}

function promptHeadingType(title) {
  const normalized = title.replace(/^#+\s*/, "").trim();
  if (PROMPT_CONTEXT_HEADINGS.has(normalized) || /Context$/i.test(normalized)) {
    return "context";
  }
  if (PROMPT_OUTPUT_HEADINGS.has(normalized)) {
    return "output";
  }
  return "task";
}

function splitPromptBodySections(text) {
  const source = String(text || "").trim();
  if (!source) return [];

  const matches = Array.from(source.matchAll(/^#\s+(.+)$/gm));
  if (!matches.length) {
    return [{ type: "task", title: "", body: source, collapsed: false }];
  }

  const sections = [];
  if (matches[0].index > 0) {
    sections.push({
      type: "task",
      title: "",
      body: source.slice(0, matches[0].index).trim(),
      collapsed: false,
    });
  }

  matches.forEach((match, index) => {
    const start = match.index + match[0].length;
    const end = index + 1 < matches.length ? matches[index + 1].index : source.length;
    const rawTitle = match[1].trim();
    const type = promptHeadingType(rawTitle);
    if (type === "context") return;
    const title = type === "context" ? `Example ${rawTitle}` : `# ${rawTitle}`;
    sections.push({
      type,
      title,
      body: source.slice(start, end).trim(),
      collapsed: type === "context",
    });
  });

  return sections.filter((section) => section.body);
}

function createPromptCollapsible(className, bodyClassName, summaryText, bodyText, open = false) {
  const details = document.createElement("details");
  details.className = className;
  details.open = open;
  const summary = document.createElement("summary");
  summary.textContent = summaryText;
  const body = document.createElement("pre");
  body.className = bodyClassName;
  body.textContent = bodyText;
  details.appendChild(summary);
  details.appendChild(body);
  return details;
}

function createPromptOpenSection(className, bodyClassName, headingText, bodyText) {
  const section = document.createElement("section");
  section.className = className;
  const body = document.createElement("pre");
  body.className = bodyClassName;
  body.textContent = bodyText;
  if (headingText) {
    const heading = document.createElement("div");
    heading.className = `${className}-heading agent-prompt-task-heading`;
    heading.textContent = headingText;
    section.appendChild(heading);
  }
  section.appendChild(body);
  return section;
}

function renderAgentPromptText(text, container) {
  if (!container) return;

  const sections = splitAgentPromptSections(text);
  container.textContent = "";
  container.classList.remove("plain-text", "agent-prompt-view");

  if (!sections.length) {
    container.classList.add("plain-text");
    container.textContent = text;
    return;
  }

  container.classList.add("agent-prompt-view");

  sections.forEach((section) => {
    if (section.type === "skill") {
      container.appendChild(
        createPromptCollapsible(
          "agent-prompt-skill",
          "agent-prompt-skill-body",
          section.title,
          section.body,
          !section.collapsed
        )
      );
      return;
    }
    if (section.type === "output") {
      container.appendChild(
        createPromptOpenSection(
          "agent-prompt-output",
          "agent-prompt-output-body",
          section.title,
          section.body
        )
      );
      return;
    }
    container.appendChild(
      createPromptOpenSection(
        "agent-prompt-task",
        "agent-prompt-task-body",
        section.title,
        section.body
      )
    );
  });
}

initializeManualDownloadButton();
loadFileManifest();

function isDirectHtmlPage(href) {
  const name = String(href || "").split("/").pop() || "";
  return name === "srs.html" || name === "design_rationale.html";
}

function manualDownloadHrefFromPath() {
  if (window.location.protocol === "file:") return "";
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (parts[0] === "manual") return "/api/manual.zip";
  if (parts[0]) return `/api/projects/${encodeURIComponent(parts[0])}/manual.zip`;
  return "";
}

function initializeManualDownloadButton() {
  if (!manualDownloadButton) return;
  const href = manualDownloadHrefFromPath();
  if (!href) {
    manualDownloadButton.hidden = true;
    return;
  }
  manualDownloadButton.href = href;
  manualDownloadButton.hidden = false;
}

function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function downloadManualZip(link) {
  const href = link.getAttribute("href") || "";
  if (!href || href === "#") return;
  const originalText = link.textContent;
  link.textContent = "下載中...";
  link.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(href, { credentials: "same-origin" });
    if (!response.ok) {
      throw new Error(`下載失敗 (${response.status})`);
    }
    const blob = await response.blob();
    const signature = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
    const isZip = signature[0] === 0x50 && signature[1] === 0x4b;
    if (!isZip) {
      throw new Error("伺服器回應不是有效的 zip 檔，請重新登入或重新匯出 Manual 後再下載。");
    }
    triggerBlobDownload(blob, link.getAttribute("download") || "manual.zip");
  } catch (error) {
    window.alert(error instanceof Error ? error.message : "Manual 下載失敗");
  } finally {
    link.textContent = originalText;
    link.removeAttribute("aria-busy");
  }
}

document.addEventListener("click", (event) => {
  const manualDownloadLink = event.target.closest("[data-manual-download]");
  if (manualDownloadLink) {
    event.preventDefault();
    void downloadManualZip(manualDownloadLink);
    return;
  }

  const fileBrowserButton = event.target.closest("[data-open-file-browser]");
  if (fileBrowserButton) {
    openFileBrowser(fileBrowserButton.getAttribute("data-open-file-browser") || "artifact");
    return;
  }

  const filePreviewButton = event.target.closest("[data-preview-file]");
  if (filePreviewButton) {
    const index = Number(filePreviewButton.getAttribute("data-preview-file"));
    const file = fileBrowserItems[index];
    if (file) {
      previewProjectFile(file, filePreviewButton);
    }
    return;
  }

  const agentFileLink = event.target.closest("[data-agent-file]");
  if (agentFileLink) {
    event.preventDefault();
    const href = agentFileLink.getAttribute("href") || "";
    const isSystemPrompt = href.endsWith("system_prompt.txt");
    const flowSteps = parseAgentFlow(agentFileLink.getAttribute("data-agent-flow") || "");
    const flowStyle = agentFileLink.getAttribute("data-agent-flow-style") || "";
    openAgentPromptModal(
      href,
      isSystemPrompt ? "" : (agentFileLink.getAttribute("data-agent-description") || ""),
      {
        title: isSystemPrompt ? "System Prompt" : (agentFileLink.textContent?.trim() || ""),
        flowSteps,
        flowStyle,
        flowAgent: agentFileLink.getAttribute("data-agent-flow-agent") || "",
        flowGroup: agentFileLink.getAttribute("data-agent-flow-group") || "",
      }
    );
    return;
  }

  const agentActionsTab = event.target.closest("[data-agent-actions-tab]");
  if (agentActionsTab) {
    event.preventDefault();
    selectAgentActionsTab(agentActionsTab.getAttribute("data-agent-actions-tab") || "");
    return;
  }

  const agentActionsButton = event.target.closest("[data-agent-actions-href]");
  if (agentActionsButton) {
    event.preventDefault();
    selectAgentActionsStep(agentActionsButton);
    return;
  }

  const flowStepButton = event.target.closest("[data-agent-flow-step]");
  if (flowStepButton) {
    const href = flowStepButton.getAttribute("data-agent-flow-step") || "";
    const description = flowStepButton.getAttribute("data-agent-description") || "";
    if (href) {
      event.preventDefault();
      activateAgentFlowStep(flowStepButton);
      if (jsonModalFlow?.classList.contains("group") && jsonModalTitle) {
        if (jsonModalFlow.dataset.keepParentHeading !== "true") {
          jsonModalTitle.textContent = flowStepButton.textContent?.trim() || jsonModalTitle.textContent;
        }
      }
      const stepDescription =
        jsonModalFlow?.dataset.keepParentHeading === "true"
          ? jsonModalFlow.dataset.parentDescription || description
          : description;
      loadAgentPromptContent(href, stepDescription);
    }
    return;
  }

  const filter = event.target.closest("[data-stage-filter]");
  if (filter) {
    filterStage(filter.getAttribute("data-stage-filter") || "all");
    return;
  }

  const link = event.target.closest("a[href]");
  if (!link) return;

  const href = link.getAttribute("href") || "";
  if (href.startsWith("#")) return;

  if (isImageFile(href)) {
    event.preventDefault();
    openImageModal(href);
    return;
  }

  if (isPlantUmlFile(href)) {
    event.preventDefault();
    openTextModal(href);
    return;
  }

  if (href.endsWith(".html")) {
    if (isDirectHtmlPage(href)) {
      return;
    }
    event.preventDefault();
    openHtmlModal(href);
    return;
  }

  if (href.endsWith(".json")) {
    event.preventDefault();
    openJsonModal(href);
  }
});

function filterStage(stageId) {
  filterSteps.forEach((step) => {
    step.classList.toggle("active", step.getAttribute("data-stage-filter") === stageId);
  });

  stageCards.forEach((card) => {
    card.classList.toggle("hidden", stageId !== "all" && card.dataset.agent !== stageId);
  });
}

async function loadFileManifest() {
  try {
    const manifest = await readManualJson("file.json");
    fileManifest = manifest;
    fileLists.forEach((list) => {
      const key = list.getAttribute("data-file-list");
      const files = manifestFileList(manifest, key);
      syncFileList(list, files);
    });
  } catch {
    // Keep the static fallback links when the manifest is unavailable.
  }
}

function manifestFileList(manifest, key) {
  if (key === "draft_updates") {
    const drafts = Array.isArray(manifest.drafts) ? manifest.drafts : [];
    return drafts
      .filter((file) => !/draft_v0(?:\.html)?$/i.test(String(file.label || file.href || "")))
      .map((file) => {
        const version = String(file.label || file.href || "").match(/draft_v(\d+)/i)?.[1];
        return {
          ...file,
          displayLabel: version ? `v${version}` : file.label,
        };
      });
  }
  if (key === "latest_drafts") {
    const drafts = Array.isArray(manifest.drafts) ? manifest.drafts : [];
    return drafts.map((file) => {
      const version = String(file.label || file.href || "").match(/draft_v(\d+)/i)?.[1];
      return {
        ...file,
        displayLabel: version ? `v${version}` : file.label,
      };
    });
  }
  if (key === "draft_inputs") {
    const drafts = Array.isArray(manifest.drafts) ? manifest.drafts : [];
    const versioned = drafts
      .map((file) => {
        const version = Number(String(file.label || file.href || "").match(/draft_v(\d+)/i)?.[1] ?? -1);
        return { file, version };
      })
      .filter((item) => item.version >= 0)
      .sort((left, right) => left.version - right.version);
    const maxVersion = versioned.length ? Math.max(...versioned.map((item) => item.version)) : -1;
    return versioned
      .filter((item) => item.version < maxVersion)
      .map(({ file, version }) => ({
        ...file,
        displayLabel: `v${version}`,
      }));
  }
  if (key === "formal_meetings") {
    const meetings = Array.isArray(manifest.formal_meetings) ? manifest.formal_meetings : [];
    return meetings.map((file) => {
      const round = String(file.label || file.href || "").match(/formal_meeting_r(\d+)/i)?.[1];
      return {
        ...file,
        displayLabel: round ? `r${round}` : file.label,
      };
    });
  }
  if (key === "conflict_reports_initial" || key === "conflict_reports_updates") {
    const reports = Array.isArray(manifest.conflict_reports) ? manifest.conflict_reports : [];
    const versioned = reports
      .map((file) => {
        const version = Number(String(file.label || file.href || "").match(/conflict_report_v(\d+)/i)?.[1] ?? -1);
        return { file, version };
      })
      .filter((item) => item.version >= 0)
      .sort((left, right) => left.version - right.version);
    const maxVersion = versioned.length ? Math.max(...versioned.map((item) => item.version)) : -1;
    return versioned
      .filter((item) => (key === "conflict_reports_initial" ? item.version < maxVersion : item.version > 0))
      .map(({ file, version }) => {
        return {
          ...file,
          displayLabel: `v${version}`,
        };
      });
  }
  if (key === "conflict_report_html_initial" || key === "conflict_report_html_updates") {
    const reports = Array.isArray(manifest.conflict_report_htmls) ? manifest.conflict_report_htmls : [];
    return reports
      .map((file) => {
        const version = Number(String(file.label || file.href || "").match(/conflict_report_v(\d+)/i)?.[1] ?? -1);
        return { file, version };
      })
      .filter((item) => (key === "conflict_report_html_initial" ? item.version === 0 : item.version > 0))
      .sort((left, right) => left.version - right.version)
      .map(({ file, version }) => ({
        ...file,
        displayLabel: `v${version}`,
      }));
  }
  return Array.isArray(manifest[key]) ? manifest[key] : [];
}

function createFileLink(file) {
  const link = document.createElement("a");
  link.href = file.href;
  link.textContent = file.displayLabel || file.label || file.href.split("/").pop() || file.href;
  return link;
}

function syncFileList(list, files) {
  if (!files.length) {
    list.remove();
    return;
  }
  if (files.length === 1 && list.dataset.keepList !== "true") {
    list.replaceWith(createFileLink(files[0]));
    return;
  }
  renderFileList(list, files);
}

function renderFileList(list, files) {
  const summary = list.querySelector("summary");
  list.textContent = "";
  if (summary) {
    list.appendChild(summary);
  }

  files.forEach((file) => {
    list.appendChild(createFileLink(file));
  });
}

document.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-modal]")) {
    jsonModal?.close();
  }

  if (event.target.closest("[data-close-media]")) {
    mediaModal?.close();
  }

  if (event.target.closest("[data-close-file]")) {
    fileModal?.close();
  }

});

jsonModal?.addEventListener("click", (event) => {
  if (event.target === jsonModal) {
    jsonModal.close();
  }
});

mediaModal?.addEventListener("click", (event) => {
  if (event.target === mediaModal) {
    mediaModal.close();
  }
});

fileModal?.addEventListener("click", (event) => {
  if (event.target === fileModal) {
    fileModal.close();
  }
});

jsonModal?.addEventListener("close", syncModalLock);
mediaModal?.addEventListener("close", syncModalLock);
fileModal?.addEventListener("close", syncModalLock);

function isImageFile(href) {
  return /\.(png|jpe?g|webp|gif)$/i.test(href);
}

function isPlantUmlFile(href) {
  return /\.plantuml$/i.test(href);
}

function openImageModal(href) {
  if (!mediaModal || !mediaModalTitle || !mediaModalImage) {
    window.open(href, "_blank", "noopener");
    return;
  }

  const fileName = href.split("/").pop() || "Image";
  mediaModalTitle.textContent = fileName.replace(/\.[^.]+$/, "");
  mediaModalImage.src = href;
  mediaModalImage.alt = mediaModalTitle.textContent;
  mediaModal.showModal();
  syncModalLock();
}

async function openTextModal(href) {
  if (!jsonModal || !jsonModalTitle || !jsonModalContent) {
    window.location.href = href;
    return;
  }

  setJsonModalHeading(href.split("/").pop() || "Text");
  jsonModalContent.textContent = "讀取中...";
  jsonModal.classList.remove("use-frame");
  jsonModal.classList.add("text-mode");
  if (jsonModalFrame) {
    jsonModalFrame.removeAttribute("src");
  }
  jsonModal.showModal();
  syncModalLock();

  try {
    renderAgentPromptText(await readManualText(href), jsonModalContent);
  } catch (error) {
    jsonModalContent.classList.remove("agent-prompt-view");
    jsonModalContent.classList.add("plain-text");
    jsonModalContent.textContent = `無法讀取 ${href}\n${error.message}`;
  }
}

function openHtmlModal(href) {
  if (!jsonModal || !jsonModalTitle || !jsonModalContent || !jsonModalFrame) {
    window.open(href, "_blank", "noopener");
    return;
  }

  setJsonModalHeading(href.split("/").pop() || "HTML");
  jsonModalContent.textContent = "";
  jsonModal.classList.remove("text-mode");
  jsonModal.classList.add("use-frame");
  jsonModalFrame.src = href;
  jsonModal.showModal();
  syncModalLock();
}

async function resolveAgentGroupFlowSteps(agent, group) {
  const map = await fetchAgentActionsMap();
  const parent = (map.actions?.[agent] || []).find((item) => item.label === group);
  return (parent?.children || []).map((child) => ({
    label: child.label,
    href: child.href,
    description: child.description || "",
  }));
}

async function openAgentPromptModal(href, description, options = {}) {
  if (!jsonModal || !jsonModalTitle || !jsonModalContent) {
    window.location.href = href;
    return;
  }

  let flowStyle = options.flowStyle || "";
  if (flowStyle === "agent-actions") {
    await openAgentActionsModal();
    return;
  }

  hideAgentActionsUI();

  let flowSteps = options.flowSteps || [];
  if (flowStyle === "agent-group") {
    flowSteps = await resolveAgentGroupFlowSteps(options.flowAgent || "", options.flowGroup || options.title || "");
    flowStyle = "";
  }

  const initialStep = flowSteps[0];
  const initialHref = initialStep?.href || href;
  const initialDescription = initialStep?.description || description;
  const initialTitle = groupFlowStepTitle(flowSteps, flowStyle, options.title, href, description);

  setJsonModalHeading(initialTitle, initialDescription);
  syncGroupFlowHeadingState(flowSteps, flowStyle, description);
  renderAgentFlow(flowSteps, flowStyle);
  jsonModalContent.textContent = "讀取中...";
  jsonModal.classList.remove("use-frame");
  jsonModal.classList.add("text-mode");
  if (jsonModalFrame) {
    jsonModalFrame.removeAttribute("src");
  }
  jsonModal.showModal();
  syncModalLock();

  await loadAgentPromptContent(initialHref, initialDescription);
}

async function fetchAgentActionsMap() {
  if (agentActionsMap) {
    return agentActionsMap;
  }
  agentActionsMap = await readManualJson("agent_actions.json");
  return agentActionsMap;
}

function hideAgentActionsUI() {
  if (!jsonModalActionFlow) return;

  jsonModalActionFlow.textContent = "";
  jsonModalActionFlow.classList.remove("has-steps");
  jsonModalActionFlow.hidden = true;
}

function firstActionEntry(actions = []) {
  const first = actions[0];
  if (!first) {
    return null;
  }
  if (Array.isArray(first.children) && first.children.length) {
    return {
      label: first.children[0].label,
      href: first.children[0].href,
      parentLabel: first.label,
    };
  }
  return { label: first.label, href: first.href, parentLabel: "" };
}

async function openAgentActionsModal() {
  const map = await fetchAgentActionsMap();
  const agents = Array.isArray(map.agents) ? map.agents : [];
  const firstAgent = agents[0] || "Analyst";
  const actions = map.actions?.[firstAgent] || [];
  const firstAction = firstActionEntry(actions);

  setJsonModalHeading(firstAgent, "");
  renderAgentActionTabs(agents, firstAgent);
  renderAgentActionSteps(actions, {
    activeLabel: firstAction?.label || "",
    parentLabel: firstAction?.parentLabel || "",
  });
  jsonModalContent.textContent = "讀取中...";
  jsonModal.classList.remove("use-frame");
  jsonModal.classList.add("text-mode");
  if (jsonModalFrame) {
    jsonModalFrame.removeAttribute("src");
  }
  jsonModal.showModal();
  syncModalLock();

  if (firstAction?.href) {
    await loadAgentPromptContent(firstAction.href, "");
    activateAgentActionsButtons(firstAgent, firstAction.label, firstAction.parentLabel);
  }
}

function renderAgentActionTabs(agents, activeAgent) {
  if (!jsonModalFlow) return;

  jsonModalFlow.textContent = "";
  jsonModalFlow.classList.add("group");
  jsonModalFlow.hidden = !agents.length;
  agents.forEach((agent) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "modal-flow-step";
    button.setAttribute("data-agent-actions-tab", agent);
    button.textContent = agent;
    if (agent === activeAgent) {
      button.classList.add("active");
    }
    jsonModalFlow.appendChild(button);
  });
}

function appendAgentActionArrow(container) {
  const arrow = document.createElement("span");
  arrow.className = "modal-flow-arrow";
  arrow.textContent = "→";
  container.appendChild(arrow);
}

function appendAgentActionDivider(container) {
  const divider = document.createElement("span");
  divider.className = "modal-flow-divider";
  divider.textContent = "|";
  divider.setAttribute("aria-hidden", "true");
  container.appendChild(divider);
}

function createAgentActionButton({ label, href, parentLabel = "", activeLabel = "" }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "modal-flow-step";
  button.setAttribute("data-agent-actions-label", label);
  button.setAttribute("data-agent-actions-href", href);
  if (parentLabel) {
    button.setAttribute("data-agent-actions-parent", parentLabel);
  }
  button.textContent = label;
  const isActive = parentLabel
    ? label === activeLabel
    : label === activeLabel;
  if (isActive) {
    button.classList.add("active");
  }
  return button;
}

function renderAgentActionSteps(actions, { activeLabel = "", parentLabel = "" } = {}) {
  if (!jsonModalActionFlow) return;

  jsonModalActionFlow.textContent = "";
  jsonModalActionFlow.classList.remove("has-steps");

  let afterFlowGroup = false;

  actions.forEach((action) => {
    if (Array.isArray(action.children) && action.children.length) {
      action.children.forEach((child, childIndex) => {
        if (childIndex > 0) {
          appendAgentActionArrow(jsonModalActionFlow);
        }
        jsonModalActionFlow.appendChild(
          createAgentActionButton({
            label: child.label,
            href: child.href,
            parentLabel: action.label,
            activeLabel: parentLabel === action.label ? activeLabel : "",
          })
        );
      });
      afterFlowGroup = true;
      return;
    }

    if (action.href) {
      if (afterFlowGroup) {
        appendAgentActionDivider(jsonModalActionFlow);
        afterFlowGroup = false;
      }
      jsonModalActionFlow.appendChild(
        createAgentActionButton({
          label: action.label,
          href: action.href,
          activeLabel: parentLabel ? "" : activeLabel,
        })
      );
    }
  });

  const hasSteps = jsonModalActionFlow.childElementCount > 0;
  jsonModalActionFlow.hidden = !hasSteps;
  jsonModalActionFlow.classList.toggle("has-steps", hasSteps);
}

function activateAgentActionsButtons(agent, actionLabel, parentLabel = "") {
  jsonModalFlow?.querySelectorAll("[data-agent-actions-tab].active").forEach((item) => {
    item.classList.remove("active");
  });
  jsonModalFlow?.querySelector(`[data-agent-actions-tab="${agent}"]`)?.classList.add("active");

  jsonModalActionFlow?.querySelectorAll(".modal-flow-step.active").forEach((item) => {
    item.classList.remove("active");
  });
  if (parentLabel) {
    jsonModalActionFlow
      ?.querySelector(`[data-agent-actions-label="${actionLabel}"][data-agent-actions-parent="${parentLabel}"]`)
      ?.classList.add("active");
    return;
  }
  jsonModalActionFlow
    ?.querySelector(`[data-agent-actions-label="${actionLabel}"][data-agent-actions-href]`)
    ?.classList.add("active");
}

async function selectAgentActionsTab(agent) {
  const map = await fetchAgentActionsMap();
  const actions = map.actions?.[agent] || [];
  const firstAction = firstActionEntry(actions);
  if (!firstAction?.href) {
    return;
  }

  setJsonModalHeading(agent, "");
  renderAgentActionTabs(map.agents || [], agent);
  renderAgentActionSteps(actions, {
    activeLabel: firstAction.label,
    parentLabel: firstAction.parentLabel,
  });
  await loadAgentPromptContent(firstAction.href, "");
  activateAgentActionsButtons(agent, firstAction.label, firstAction.parentLabel);
}

async function selectAgentActionsStep(button) {
  const href = button.getAttribute("data-agent-actions-href");
  const label = button.getAttribute("data-agent-actions-label") || "";
  const parentLabel = button.getAttribute("data-agent-actions-parent") || "";
  const activeAgent =
    jsonModalFlow?.querySelector("[data-agent-actions-tab].active")?.getAttribute("data-agent-actions-tab") || "Analyst";

  if (!href) {
    return;
  }

  const map = await fetchAgentActionsMap();
  renderAgentActionSteps(map.actions?.[activeAgent] || [], {
    activeLabel: label,
    parentLabel,
  });

  await loadAgentPromptContent(href, "");
  activateAgentActionsButtons(activeAgent, label, parentLabel);
}

async function loadAgentPromptContent(href, description = "") {
  if (!jsonModalContent) return;

  if (jsonModalDescription) {
    jsonModalDescription.textContent = description;
    jsonModalDescription.hidden = !description;
  }
  jsonModalContent.textContent = "讀取中...";
  try {
    renderAgentPromptText(await readManualText(href), jsonModalContent);
  } catch (error) {
    jsonModalContent.classList.remove("agent-prompt-view");
    jsonModalContent.classList.add("plain-text");
    jsonModalContent.textContent = `無法讀取 ${href}\n${error.message}`;
  }
}

function usesGroupParentHeading(flowSteps, flowStyle, parentDescription = "") {
  return flowStyle === "group" && flowSteps.length > 0 && parentDescription && !flowSteps.some((step) => step.description);
}

function groupFlowStepTitle(flowSteps, flowStyle, fallbackTitle, href, parentDescription = "") {
  if (usesGroupParentHeading(flowSteps, flowStyle, parentDescription)) {
    return fallbackTitle || href.split("/").pop() || "Agent prompt";
  }
  if (flowStyle === "group" && flowSteps[0]?.label) {
    return flowSteps[0].label;
  }
  return fallbackTitle || href.split("/").pop() || "Agent prompt";
}

function syncGroupFlowHeadingState(flowSteps, flowStyle, parentDescription = "") {
  if (!jsonModalFlow) return;

  const keepParentHeading = usesGroupParentHeading(flowSteps, flowStyle, parentDescription);
  jsonModalFlow.dataset.keepParentHeading = keepParentHeading ? "true" : "false";
  jsonModalFlow.dataset.parentDescription = keepParentHeading ? parentDescription : "";
}

function parseAgentFlow(value) {
  return value
    .split(";")
    .map((chunk) => {
      const [label, href, description = ""] = chunk.split("|");
      return {
        label: (label || "").trim(),
        href: (href || "").trim(),
        description: description.trim(),
      };
    })
    .filter((step) => step.label && step.href);
}

function renderAgentFlow(steps, style = "") {
  if (!jsonModalFlow) return;

  jsonModalFlow.textContent = "";
  jsonModalFlow.classList.toggle("group", style === "group");
  jsonModalFlow.hidden = !steps.length;
  if (!steps.length) return;

  steps.forEach((step, index) => {
    if (index > 0 && style !== "group") {
      const arrow = document.createElement("span");
      arrow.className = "modal-flow-arrow";
      arrow.textContent = "→";
      jsonModalFlow.appendChild(arrow);
    }

    const button = document.createElement("button");
    button.type = "button";
    button.className = "modal-flow-step";
    button.setAttribute("data-agent-flow-step", step.href);
    button.setAttribute("data-agent-description", step.description);
    button.textContent = step.label;
    if (index === 0) {
      button.classList.add("active");
    }
    jsonModalFlow.appendChild(button);
  });
}

function activateAgentFlowStep(button) {
  jsonModalFlow?.querySelectorAll(".modal-flow-step.active").forEach((item) => {
    item.classList.remove("active");
  });
  button.classList.add("active");
}

function setJsonModalHeading(title, description = "") {
  if (jsonModalTitle) {
    jsonModalTitle.textContent = title;
  }
  if (jsonModalDescription) {
    jsonModalDescription.textContent = description;
    jsonModalDescription.hidden = !description;
  }
  renderAgentFlow([]);
}

function syncModalLock() {
  const hasOpenModal = Boolean(jsonModal?.open || mediaModal?.open || fileModal?.open);
  document.body.classList.toggle("modal-open", hasOpenModal);
}

function isArtifactHtmlBrowserFile(href) {
  const path = String(href || "");
  if (!path.includes("/results/") && !path.includes("/output/")) {
    return false;
  }
  if (!/\.html$/i.test(path)) {
    return false;
  }
  const name = path.split("/").pop() || "";
  if (path.includes("/drafts/") && /^draft_v/i.test(name)) {
    return true;
  }
  if (path.includes("/MoM/")) {
    return true;
  }
  if (path.includes("/report/") && name.startsWith("conflict_report")) {
    return true;
  }
  return false;
}

function isOutputBrowserFile(href) {
  const path = String(href || "");
  if (!path.includes("/results/") && !path.includes("/output/")) {
    return false;
  }
  const name = path.split("/").pop() || "";
  if (name === "srs.html" || name === "design_rationale.html") {
    return true;
  }
  return path.includes("/models/") && /\.png$/i.test(name);
}

function resolveFileBrowserItems(mode) {
  const manifestKey = mode === "output" ? "output_files" : "artifact_files";
  if (Array.isArray(fileManifest[manifestKey]) && fileManifest[manifestKey].length) {
    return fileManifest[manifestKey];
  }

  const allFiles = Array.isArray(fileManifest.all_files) ? fileManifest.all_files : [];
  if (mode === "output") {
    return allFiles.filter((file) => isOutputBrowserFile(file.href));
  }
  return allFiles.filter(
    (file) =>
      String(file.href || "").includes("/artifact/") ||
      isArtifactHtmlBrowserFile(file.href),
  );
}

function openFileBrowser(mode = "artifact") {
  if (!fileModal || !fileListPane || !filePreviewContent) return;

  const browserMode = mode === "output" ? "output" : "artifact";
  fileBrowserItems = resolveFileBrowserItems(browserMode);
  if (fileModalTitle) {
    fileModalTitle.textContent = browserMode === "output" ? "輸出結果" : "Artifact";
  }
  renderFileBrowserList(fileBrowserItems);
  renderEmptyFilePreview(filePreviewContent);
  fileModal.showModal();
  syncModalLock();
}

function renderFileBrowserList(files) {
  if (!fileListPane) return;

  renderBrowserList(fileListPane, files, "data-preview-file");
}

function renderBrowserList(pane, files, previewAttribute) {
  pane.textContent = "";
  if (!files.length) {
    pane.textContent = "沒有可顯示的檔案。";
    return;
  }

  pane.appendChild(createFileTree(files, previewAttribute));
}

function createFileTree(files, previewAttribute = "data-preview-file") {
  const root = { dirs: new Map(), files: [] };
  files.forEach((file, index) => {
    const label = file.label || file.href;
    const parts = label.split("/").filter(Boolean);
    let current = root;
    parts.slice(0, -1).forEach((part) => {
      if (!current.dirs.has(part)) {
        current.dirs.set(part, { dirs: new Map(), files: [] });
      }
      current = current.dirs.get(part);
    });
    current.files.push({ file, index, name: parts.at(-1) || label });
  });

  return renderFileTreeNode(root, 0, previewAttribute);
}

function renderFileTreeNode(node, depth, previewAttribute) {
  const container = document.createElement("div");
  container.className = depth === 0 ? "file-tree" : "file-tree-children";

  Array.from(node.dirs.entries()).forEach(([name, child]) => {
    const details = document.createElement("details");
    details.className = "file-tree-folder";
    details.open = false;

    const summary = document.createElement("summary");
    summary.textContent = name;
    details.appendChild(summary);
    details.appendChild(renderFileTreeNode(child, depth + 1, previewAttribute));
    container.appendChild(details);
  });

  node.files.forEach(({ file, index, name }) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "file-browser-item";
    button.setAttribute(previewAttribute, String(index));
    button.textContent = name;
    container.appendChild(button);
  });

  return container;
}

async function previewProjectFile(file, sourceButton) {
  await previewFile(file, sourceButton, filePreviewContent);
}

async function previewFile(file, sourceButton, previewContent) {
  if (!previewContent) return;

  sourceButton?.closest(".file-modal")?.querySelectorAll(".file-browser-item.active").forEach((item) => {
    item.classList.remove("active");
  });
  sourceButton?.classList.add("active");

  const href = file.href;
  const fileName = file.label || href.split("/").pop() || href;
  previewContent.className = "file-preview-content loading";
  previewContent.textContent = "讀取中...";

  try {
    if (isImageFile(href)) {
      renderImagePreview(href, fileName, previewContent);
      return;
    }

    if (href.endsWith(".html") || fileName.toLowerCase().endsWith(".html")) {
      renderHtmlPreview(href, previewContent);
      return;
    }

    if (href.endsWith(".json")) {
      previewContent.className = "file-preview-content code";
      renderJsonTree(await readManualJson(href), previewContent);
      return;
    }

    renderTextPreview(await readManualText(href), previewContent);
  } catch (error) {
    previewContent.textContent = `無法讀取 ${href}\n${error.message}`;
  }
}

function renderEmptyFilePreview(previewContent) {
  if (!previewContent) return;

  previewContent.className = "file-preview-content empty";
  previewContent.textContent = "未選擇任何檔案";
}

function renderImagePreview(href, fileName, previewContent = filePreviewContent) {
  if (!previewContent) return;

  previewContent.className = "file-preview-content image";
  previewContent.textContent = "";
  const image = document.createElement("img");
  image.src = href;
  image.alt = fileName.replace(/\.[^.]+$/, "");
  previewContent.appendChild(image);
}

function renderHtmlPreview(href, previewContent = filePreviewContent) {
  if (!previewContent) return;

  previewContent.className = "file-preview-content html";
  previewContent.textContent = "";
  const frame = document.createElement("iframe");
  frame.src = href;
  frame.title = "HTML file preview";
  previewContent.appendChild(frame);
}

function renderTextPreview(text, previewContent = filePreviewContent) {
  if (!previewContent) return;

  previewContent.className = "file-preview-content code";
  previewContent.textContent = "";
  const host = document.createElement("div");
  host.className = "agent-prompt-host";
  renderAgentPromptText(text, host);
  previewContent.appendChild(host);
}

async function openJsonModal(href) {
  if (!jsonModal || !jsonModalTitle || !jsonModalContent) {
    window.location.href = href;
    return;
  }

  setJsonModalHeading(href.split("/").pop() || "JSON");
  jsonModalContent.textContent = "讀取中...";
  jsonModal.classList.remove("use-frame", "text-mode");
  if (jsonModalFrame) {
    jsonModalFrame.removeAttribute("src");
  }
  jsonModal.showModal();
  syncModalLock();

  try {
    renderJsonTree(await readManualJson(href), jsonModalContent);
  } catch (error) {
    if (jsonModalFrame) {
      jsonModal.classList.add("use-frame");
      jsonModalFrame.src = href;
    } else {
      jsonModalContent.textContent = `無法讀取 ${href}\n${error.message}`;
    }
  }
}

function renderJsonTree(data, container) {
  container.textContent = "";
  container.appendChild(createJsonNode(data, undefined, true, true));
}

function createJsonNode(value, key, isLast = true, isRoot = false) {
  const node = document.createElement("div");
  node.className = "json-node";

  if (Array.isArray(value)) {
    node.appendChild(createJsonBranch(key, value, "array", isLast, isRoot));
    return node;
  }

  if (value && typeof value === "object") {
    node.appendChild(createJsonBranch(key, value, "object", isLast, isRoot));
    return node;
  }

  node.classList.add("json-leaf");
  if (key !== undefined) {
    const keyElement = document.createElement("span");
    keyElement.className = "json-key";
    keyElement.textContent = `${JSON.stringify(key)}: `;
    node.appendChild(keyElement);
  }
  node.appendChild(createJsonValue(value));
  if (!isLast) {
    node.appendChild(createJsonPunctuation(","));
  }
  return node;
}

function createJsonBranch(key, value, type, isLast, isRoot) {
  const details = document.createElement("details");
  details.className = "json-branch";
  details.open = true;

  const summary = document.createElement("summary");
  summary.className = "json-summary";

  if (key !== undefined) {
    const label = document.createElement("span");
    label.className = "json-key";
    label.textContent = `${JSON.stringify(key)}: `;
    summary.appendChild(label);
  }

  const open = document.createElement("span");
  open.className = "json-punctuation json-open";
  open.textContent = type === "array" ? "[" : "{";

  const preview = document.createElement("span");
  preview.className = "json-preview";
  preview.textContent = type === "array" ? "..." : "...";

  const close = document.createElement("span");
  close.className = "json-punctuation json-summary-close";
  close.textContent = type === "array" ? "]" : "}";

  summary.append(open, preview, close);
  if (!isLast) {
    const comma = createJsonPunctuation(",");
    comma.classList.add("json-summary-comma");
    summary.appendChild(comma);
  }
  details.appendChild(summary);

  const children = document.createElement("div");
  children.className = "json-children";

  if (Array.isArray(value)) {
    value.forEach((item, index) => {
      children.appendChild(createJsonNode(item, undefined, index === value.length - 1));
    });
  } else {
    const entries = Object.entries(value);
    entries.forEach(([childKey, childValue], index) => {
      children.appendChild(createJsonNode(childValue, childKey, index === entries.length - 1));
    });
  }

  details.appendChild(children);
  const closing = document.createElement("div");
  closing.className = "json-closing";
  closing.textContent = `${type === "array" ? "]" : "}"}${isLast || isRoot ? "" : ","}`;
  details.appendChild(closing);
  return details;
}

function createJsonValue(value) {
  const element = document.createElement("span");
  element.className = `json-value json-${value === null ? "null" : typeof value}`;
  element.textContent = JSON.stringify(value);
  return element;
}

function createJsonPunctuation(text) {
  const element = document.createElement("span");
  element.className = "json-punctuation";
  element.textContent = text;
  return element;
}
