import { UI_TEXT } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";
import type { ChatMessage, FileTreeNode } from "@/types/api";

export interface FlowItem {
  id: string;
  title: string;
  detail: string;
  dedupeKey: string;
  children?: FlowItem[];
  orderHint?: number;
  messageIndex?: number;
  outputPath?: string;
  scrollTargetId?: string;
  rawTitle?: string;
  tone: "action" | "decision" | "output" | "designRationale" | "srs" | "status";
}

function snippet(text: string, fallback: string) {
  const compact = text.replace(/\s+/g, " ").trim();
  if (!compact) return fallback;
  return compact.length > 48 ? `${compact.slice(0, 48)}...` : compact;
}

function tx() {
  return UI_TEXT[useUiStore.getState().language];
}

function statusText(status?: ChatMessage["status"]) {
  const t = tx();
  if (status === "done") return t.flowComplete;
  if (status === "failed") return t.flowFailed;
  if (status === "waiting") return t.flowWaiting;
  if (status === "running") return t.flowRunning;
  return t.flowComplete;
}

function actionKey(value: string) {
  return value.replace(/^(?:[a-z_]+(?:\.\w+_\d+)?\.)+/i, "");
}

function stageTitle(stage?: string) {
  const t = tx();
  if (!stage) return "";
  const value = stage.toLowerCase();
  if (value === "init") return t.initialAnalysis;
  if (value === "elicitation") return t.elicitationMeeting;
  if (value === "conflict_review") return t.conflictDetection;
  if (value === "research_domain") return t.domainResearch;
  if (value === "system_model") return t.systemModelGeneration;
  if (value === "draft") return t.draftCreation;
  if (value === "formal_meeting") return t.stageLabels.general_meeting;
  if (value === "document_generation") return t.specification;
  if (value === "export") return t.exportOutputs;
  return "";
}

function actionDisplay(msg: ChatMessage): { title: string; detail: string } {
  const t = tx();
  const raw = msg.action ?? msg.text;
  const key = actionKey(raw);
  const running = statusText(msg.status);
  const round = /formal_meeting\.round_(\d+)\.run_meeting/i.exec(raw)?.[1];

  const table: Record<string, { title: string; running: string; done: string }> = {
    suggest_stakeholders: {
      title: t.selectStakeholders,
      running: t.generatingStakeholderCandidates,
      done: t.stakeholderCandidatesGenerated,
    },
    write_stakeholder_text: {
      title: t.stakeholderStatements,
      running: t.organizingStakeholderRequirements,
      done: t.stakeholderRequirementsOrganized,
    },
    analyze_scenario: {
      title: t.analyzeInitialIdea,
      running: t.organizingScenarioScope,
      done: t.scenarioScopeOrganized,
    },
    analyze_requirements: {
      title: t.initialRequirementAnalysis,
      running: t.organizingRequirementCandidates,
      done: t.requirementCandidatesOrganized,
    },
    generate_scope: {
      title: t.defineSystemScope,
      running: t.organizingSystemScope,
      done: t.updatedScope,
    },
    extract_requirements: {
      title: t.elicitationMeeting,
      running: t.extractingUserRequirements,
      done: t.userRequirementsExtracted,
    },
    merge_requirements: {
      title: t.mergeRequirements,
      running: t.mergingRequirements,
      done: t.updatedRequirements,
    },
    run_review: {
      title: t.conflictDetection,
      running: t.detectingRequirementConflicts,
      done: t.requirementConflictsDetected,
    },
    research_domain: {
      title: t.domainResearch,
      running: t.organizingDomainResearch,
      done: t.updatedDomainResearch,
    },
    read_reference_docs: {
      title: t.domainResearch,
      running: t.readingReferenceDocs,
      done: t.referenceDocsRead,
    },
    research_issue: {
      title: t.domainResearch,
      running: t.researchingExternalConstraints,
      done: t.researchEvidenceOrganized,
    },
    update_feedback: {
      title: t.domainResearch,
      running: t.updatingDomainResearch,
      done: t.updatedDomainResearch,
    },
    system_modeling: {
      title: t.systemModelGeneration,
      running: t.generatingSystemModel,
      done: t.updatedSystemModels,
    },
    create_model: {
      title: t.systemModelGeneration,
      running: t.generatingSystemModel,
      done: t.updatedSystemModels,
    },
    update_model: {
      title: t.systemModelGeneration,
      running: t.updatingSystemModel,
      done: t.updatedSystemModels,
    },
    default_update_draft: {
      title: t.draftCreation,
      running: t.updatingDraft,
      done: t.updatedDraft,
    },
    general_update_draft: {
      title: t.draftCreation,
      running: t.updatingDraftFromMeeting,
      done: t.updatedDraft,
    },
    generate_dr: {
      title: t.stageLabels.DR,
      running: t.generatingDesignRationale,
      done: t.updatedDesignRationale,
    },
    generate_srs: {
      title: t.stageLabels.SRS,
      running: t.generatingSpecDocument,
      done: t.updatedSrs,
    },
  };

  if (round) {
    return {
      title: t.meetingRoundTitle(round),
      detail: `${running}: ${t.discussionInProgress}`,
    };
  }

  const matched = table[key];
  if (matched) {
    return {
      title: matched.title,
      detail: `${running}: ${msg.status === "done" ? matched.done : matched.running}`,
    };
  }

  const fallbackTitle = stageTitle(msg.stage) || msg.label || msg.speaker || t.agentExecution;
  return {
    title: fallbackTitle,
    detail: `${running}: ${snippet(msg.text, key || t.processingFallback)}`,
  };
}

function outputLabel(path?: string, text?: string) {
  const t = tx();
  if (!path) return snippet(text ?? "", t.artifact);
  if (/project\.json$/i.test(path)) return "Project";
  if (/scope\.json$/i.test(path)) return "Scope";
  if (/meeting\/elicitation_meeting\.json$/i.test(path)) return t.elicitationMeeting;
  const meetingRound = meetingRoundFromPath(path);
  if (meetingRound) return t.meetingRoundTitle(meetingRound);
  if (/requirements\.json$/i.test(path)) return "Requirements";
  if (/feedback\.json$/i.test(path)) return t.domainResearch;
  if (/system_models\.json$/i.test(path)) return t.systemModelGeneration;
  if (/result\.json$/i.test(path)) return "Conflict";
  const draft = /draft_v(\d+)/i.exec(path)?.[1];
  if (draft) return `Draft v${draft}`;
  if (/srs\.(html|md)$/i.test(path)) return t.stageLabels.SRS;
  if (/design_rationale\.(html|md)$/i.test(path)) return t.stageLabels.DR;
  if (/models\/.+\.(png|svg|plantuml|puml)$/i.test(path)) return t.systemModelGeneration;
  return snippet(text ?? path, path);
}

function meetingRoundFromPath(path?: string) {
  const value = /(?:formal_meeting_r|\/R)(\d+)/i.exec(path ?? "")?.[1];
  return value ? Number(value) : null;
}

function meetingRoundFromTitle(title?: string) {
  const value = /第\s*(\d+)\s*輪會議/.exec(title ?? "")?.[1] ??
    /Round\s*(\d+)\s*Meeting/i.exec(title ?? "")?.[1];
  return value ? Number(value) : null;
}

function outputTone(label: string): FlowItem["tone"] {
  if (label === "Design Rationale" || label === "設計緣由") return "designRationale";
  if (label === "SRS" || label === "規格書" || label === "規格化") return "srs";
  return "output";
}

function draftVersionFromPath(path?: string) {
  const value = /draft_v(\d+)/i.exec(path ?? "")?.[1];
  return value ? Number(value) : null;
}

function isPrimaryOutput(path?: string) {
  if (!path) return false;
  return (
    /meeting\/elicitation_meeting\.json$/i.test(path) ||
    /feedback\.json$/i.test(path) ||
    /system_models\.json$/i.test(path) ||
    /srs\.(?:html|md)$/i.test(path) ||
    /design_rationale\.(?:html|md)$/i.test(path) ||
    /models\/.+\.(?:png|svg|plantuml|puml)$/i.test(path)
  );
}

function isPrimaryAction(msg: ChatMessage) {
  const raw = msg.action ?? msg.text;
  const key = actionKey(raw);
  return (
    key === "write_stakeholder_text" ||
    key === "analyze_requirements" ||
    key === "generate_scope" ||
    key === "extract_requirements" ||
    key === "run_review" ||
    key === "research_domain" ||
    key === "read_reference_docs" ||
    key === "research_issue" ||
    key === "update_feedback" ||
    key === "system_modeling" ||
    key === "create_model" ||
    key === "update_model" ||
    key === "default_update_draft" ||
    key === "general_update_draft" ||
    key === "generate_dr" ||
    key === "generate_srs" ||
    /^formal_meeting\.round_\d+\.run_meeting$/i.test(raw)
  );
}

function decisionDetail(msg: ChatMessage) {
  const t = tx();
  if (decisionContextTitle(msg)) return t.humanSuggestion;
  if (/後續人類介入將自動跳過/.test(msg.text)) return t.autoSkipFutureDecisions;
  if (/已略過/.test(msg.text)) return t.skippedThisDecision;
  const selected = msg.text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !/^(已提交決策|選擇[:：]?|建議[:：]?|議題[:：]?)$/.test(line));
  if (selected.length) {
    return `${selected.slice(0, 2).join("、")}${selected.length > 2 ? "..." : ""}`;
  }
  return decisionCompletionDetail(msg);
}

function decisionTitle(msg: ChatMessage) {
  const t = tx();
  const contextTitle = decisionContextTitle(msg);
  if (contextTitle) return contextTitle;
  return t.humanSuggestion;
}

function isMeetingIssueDecision(msg: ChatMessage) {
  return msg.decision?.kind === "meeting_issue_proposal_review" || /候選議題/i.test(msg.text);
}

function isHumanDecisionMessage(msg: ChatMessage) {
  return msg.decision?.kind === "human_decision" || msg.action === "human_decision_request";
}

function decisionContextTitle(msg: ChatMessage) {
  const t = tx();
  switch (msg.decision?.kind) {
    case "stakeholder_statement_review":
      return t.stakeholderStatements;
    case "domain_research_review":
      return t.domainResearch;
    case "requirements_review":
      return t.initialRequirementAnalysis;
    case "scope_review":
      return t.defineSystemScope;
    default:
      if (/利害關係人.*發言|stakeholder.*statement/i.test(msg.text)) return t.stakeholderStatements;
      if (/領域|研究|Feedback/i.test(msg.text)) return t.domainResearch;
      if (/需求範圍|Scope/i.test(msg.text)) return t.defineSystemScope;
      if (/需求|Requirements?|URL|REQ/i.test(msg.text)) return t.initialRequirementAnalysis;
      return "";
  }
}

function decisionCompletionDetail(msg: ChatMessage) {
  const t = tx();
  switch (msg.decision?.kind) {
    case "requirements_review":
      return t.analysisComplete;
    case "domain_research_review":
      return t.revisionComplete;
    case "scope_review":
      return t.revisionComplete;
    case "stakeholder_statement_review":
      return t.statementComplete;
    default:
      if (/需求範圍|Scope/i.test(msg.text)) return t.revisionComplete;
      if (/需求|Requirements?|URL|REQ/i.test(msg.text)) return t.analysisComplete;
      if (/領域|研究|Feedback/i.test(msg.text)) return t.revisionComplete;
      if (/利害關係人/.test(msg.text)) return t.selectionComplete;
      return t.suggestionComplete;
  }
}

function decisionDedupeKey(msg: ChatMessage) {
  if (msg.decisionId) return `decision:${msg.decisionId}`;
  if (/@資料來源|資料來源_|\.pdf|法令|法規/i.test(msg.text)) return "decision:feedback";
  if (/需求|Requirements?|URL|REQ/i.test(msg.text)) return "decision:requirements";
  if (/領域|研究|Feedback/i.test(msg.text)) return "decision:feedback";
  if (/衝突|Conflict|CR-/i.test(msg.text)) return "decision:conflict";
  return "decision:general";
}

function draftOrderHint(version: number) {
  if (version <= 0) return 60;
  return 70 + (version - 1) * 2 + 1;
}

function actionDedupeKey(msg: ChatMessage) {
  const raw = msg.action ?? msg.text;
  const round = /formal_meeting\.round_(\d+)\.run_meeting/i.exec(raw)?.[1];
  if (round) return `action:formal_meeting:R${round}`;
  return `action:${actionDisplay(msg).title}`;
}

function actionTone(title: string): FlowItem["tone"] {
  if (title === "Design Rationale" || title === "設計緣由") return "designRationale";
  if (title === "SRS" || title === "規格書" || title === "規格化") return "srs";
  return "action";
}

function messageToFlowItem(msg: ChatMessage): FlowItem | null {
  const t = tx();
  if (msg.role === "user") {
    if (msg.kind === "decision") {
      if (isMeetingIssueDecision(msg) || isHumanDecisionMessage(msg)) return null;
      if (msg.status === "waiting") return null;
      if (msg.decision?.kind === "stakeholder_selection" || msg.action === "stakeholder_selection_request") {
        return null;
      }
      return {
        id: msg.id,
        title: decisionTitle(msg),
        detail: decisionDetail(msg),
        dedupeKey: decisionDedupeKey(msg),
        rawTitle: msg.action,
        tone: "decision",
      };
    }
      return {
        id: msg.id,
        title: t.humanInput,
        detail: snippet(msg.text, t.humanInput),
      dedupeKey: `message:${msg.id}`,
      tone: "decision",
    };
  }

  if (msg.kind === "action") {
    if (!isPrimaryAction(msg)) return null;
    const agent = msg.label ?? msg.speaker ?? "Agent";
    const display = actionDisplay(msg);
    return {
      id: msg.id,
      title: display.title,
      detail: display.detail,
      dedupeKey: actionDedupeKey(msg),
      rawTitle: `${agent}: ${msg.action ?? msg.text}`,
      tone: actionTone(display.title),
    };
  }

  if (msg.kind === "decision") {
    if (isMeetingIssueDecision(msg) || isHumanDecisionMessage(msg)) return null;
    if (msg.status === "waiting") return null;
    if (msg.decision?.kind === "stakeholder_selection" || msg.action === "stakeholder_selection_request") {
      return null;
    }
    return {
      id: msg.id,
      title: decisionTitle(msg),
      detail: decisionDetail(msg),
      dedupeKey: decisionDedupeKey(msg),
      rawTitle: msg.action,
      tone: "decision",
    };
  }

  if (msg.kind === "output" || msg.outputPath) {
    if (!isPrimaryOutput(msg.outputPath)) return null;
    const label = outputLabel(msg.outputPath, msg.text);
    if (/feedback\.json$/i.test(msg.outputPath ?? "") || /system_models\.json$/i.test(msg.outputPath ?? "")) {
      return {
        id: msg.id,
        title: label,
        detail: t.updated,
        dedupeKey: `output:${label}`,
        outputPath: msg.outputPath,
        rawTitle: msg.action,
        tone: "action",
      };
    }
    if (
      label === "Scope" ||
      /meeting\/elicitation_meeting\.json$/i.test(msg.outputPath ?? "") ||
      label === "Design Rationale" ||
      label === "設計緣由" ||
      label === "SRS" ||
      label === "規格書" ||
      label === "規格化"
    ) {
      return {
        id: msg.id,
        title: label,
        detail: t.updated,
        dedupeKey: msg.outputPath ? `output:${msg.outputPath}` : `message:${msg.id}`,
        outputPath: msg.outputPath,
        rawTitle: msg.action,
        tone: outputTone(label),
      };
    }
    return null;
  }

  if (msg.status === "waiting" || msg.status === "failed") {
    return {
      id: msg.id,
      title: msg.status === "failed" ? t.error : t.waiting,
      detail: snippet(msg.text, msg.status === "failed" ? t.runtimeError : t.waiting),
      dedupeKey: `message:${msg.id}`,
      tone: "status",
    };
  }

  return null;
}

function findFlowTargetMessage(messages: ChatMessage[], title: string, outputPath: string) {
  const targetDraftVersion = draftVersionFromPath(outputPath);
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message) continue;
    if (message.outputPath === outputPath) return { id: message.id, index };
    if (
      targetDraftVersion !== null &&
      draftVersionFromPath(message.outputPath) === targetDraftVersion
    ) {
      return { id: message.id, index };
    }
    if (message.outputPath && outputLabel(message.outputPath, message.text) === title) return { id: message.id, index };
    if (
      targetDraftVersion === null &&
      message.kind === "action" &&
      isPrimaryAction(message) &&
      actionDisplay(message).title === title
    ) {
      return { id: message.id, index };
    }
  }
  return undefined;
}

function applyFlowTarget(
  item: Omit<FlowItem, "scrollTargetId" | "messageIndex">,
  messages: ChatMessage[],
  title: string,
  outputPath: string,
): FlowItem {
  const target = findFlowTargetMessage(messages, title, outputPath);
  return {
    ...item,
    scrollTargetId: target?.id,
    messageIndex: target?.index,
  };
}

function artifactFlowItems(
  items: FileTreeNode[],
  messages: ChatMessage[],
  hideGeneratedDocuments = false,
): FlowItem[] {
  const t = tx();
  const paths = new Set(
    items
      .filter((item) => item.kind === "file")
      .map((item) => item.path),
  );
  const hasModel =
    paths.has("artifact/system_models.json") ||
    Array.from(paths).some((path) => /^artifact\/models\/.+/i.test(path));
  const meetingPaths = Array.from(paths)
    .filter((path) => /^artifact\/meeting\/formal_meeting_r\d+\.json$/i.test(path) || /^results\/MoM\/R\d+-M\d+\.html$/i.test(path))
    .sort((a, b) => {
      const aRound = Number(/(?:formal_meeting_r|\/R)(\d+)/i.exec(a)?.[1] ?? 0);
      const bRound = Number(/(?:formal_meeting_r|\/R)(\d+)/i.exec(b)?.[1] ?? 0);
      return aRound - bRound || a.localeCompare(b);
    });
  const flowItems: FlowItem[] = [];

  if (paths.has("artifact/project.json")) {
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-project",
      title: t.humanInput,
      detail: t.projectCreated,
      dedupeKey: "output:project",
      outputPath: "artifact/project.json",
      tone: "decision",
    }, messages, t.humanInput, "artifact/project.json"));
  }
  if (paths.has("artifact/requirements.json")) {
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-requirements",
      title: t.initialRequirementAnalysis,
      detail: t.updatedRequirements,
      dedupeKey: "output:requirements",
      outputPath: "artifact/requirements.json",
      tone: "action",
    }, messages, t.initialRequirementAnalysis, "artifact/requirements.json"));
  }
  if (paths.has("artifact/meeting/elicitation_meeting.json")) {
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-elicitation",
      title: t.elicitationMeeting,
      detail: t.updated,
      dedupeKey: "output:elicitation",
      outputPath: "artifact/meeting/elicitation_meeting.json",
      tone: "action",
    }, messages, t.elicitationMeeting, "artifact/meeting/elicitation_meeting.json"));
  }
  if (paths.has("artifact/result.json") || Array.from(paths).some((path) => /conflict_report_v\d+\.(?:html|md|json)$/i.test(path))) {
    const outputPath = firstExistingPath(paths, ["artifact/result.json"]) ??
      latestVersionedPath(paths, /conflict_report_v(\d+)\.(?:html|md|json)$/i);
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-conflict",
      title: t.conflictDetection,
      detail: t.updated,
      dedupeKey: "output:conflict",
      outputPath,
      tone: "action",
    }, messages, t.conflictDetection, outputPath ?? ""));
  }
  if (paths.has("artifact/feedback.json")) {
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-feedback",
      title: t.domainResearch,
      detail: t.updated,
      dedupeKey: "output:feedback",
      outputPath: "artifact/feedback.json",
      tone: "action",
    }, messages, t.domainResearch, "artifact/feedback.json"));
  }
  if (hasModel) {
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-system-models",
      title: t.systemModelGeneration,
      detail: t.updated,
      dedupeKey: "output:system_models",
      outputPath: "artifact/system_models.json",
      tone: "action",
    }, messages, t.systemModelGeneration, "artifact/system_models.json"));
  }
  const seenDraftVersions = new Set<number>();
  Array.from(paths)
    .map((path) => ({ path, version: draftVersionFromPath(path) }))
    .filter((item): item is { path: string; version: number } => item.version !== null)
    .sort((a, b) => {
      const versionDiff = a.version - b.version;
      if (versionDiff) return versionDiff;
      return Number(b.path.startsWith("artifact/")) - Number(a.path.startsWith("artifact/"));
    })
    .forEach(({ path, version }) => {
      if (seenDraftVersions.has(version)) return;
      seenDraftVersions.add(version);
      const isInitialDraft = version === 0;
      const title = isInitialDraft ? t.draftCreation : `Draft v${version}`;
      flowItems.push(applyFlowTarget({
        id: `artifact-flow-draft-v${version}`,
        title,
        detail: t.updatedDraft,
        dedupeKey: isInitialDraft ? "output:draft" : `output:draft:v${version}`,
        orderHint: draftOrderHint(version),
        outputPath: path,
        tone: "action",
      }, messages, title, path));
    });
  const seenRounds = new Set<number>();
  meetingPaths.forEach((path) => {
    const round = Number(/(?:formal_meeting_r|\/R)(\d+)/i.exec(path)?.[1] ?? 0);
    if (!round || seenRounds.has(round)) return;
    seenRounds.add(round);
    flowItems.push(applyFlowTarget({
      id: `artifact-flow-meeting-r${round}`,
      title: t.meetingRoundTitle(round),
      detail: t.completed,
      dedupeKey: `output:formal_meeting:R${round}`,
      outputPath: path,
      tone: "action",
    }, messages, t.meetingRoundTitle(round), path));
  });
  const drPath = hideGeneratedDocuments
    ? undefined
    : firstExistingPath(paths, ["results/design_rationale.html", "output/design_rationale.md"]);
  if (drPath) {
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-design-rationale",
      title: t.stageLabels.DR,
      detail: t.updated,
      dedupeKey: "output:design_rationale",
      outputPath: drPath,
      tone: "designRationale",
    }, messages, t.stageLabels.DR, drPath));
  }
  const srsPath = hideGeneratedDocuments
    ? undefined
    : firstExistingPath(paths, ["results/srs.html", "output/srs.md"]);
  if (srsPath) {
    flowItems.push(applyFlowTarget({
      id: "artifact-flow-srs",
      title: t.stageLabels.SRS,
      detail: t.updated,
      dedupeKey: "output:srs",
      outputPath: srsPath,
      tone: "srs",
    }, messages, t.stageLabels.SRS, srsPath));
  }
  return flowItems;
}

function flowItemOrder(item: FlowItem) {
  if (item.orderHint !== undefined) return item.orderHint;
  const value = `${item.title} ${item.detail}`;
  const isHumanDecision = item.tone === "decision";
  const meetingRound = meetingRoundFromTitle(item.title);
  if (meetingRound) return 70 + (Number(meetingRound) - 1) * 2;
  if (item.dedupeKey === "output:draft") return 60;
  const draftVersion = /Draft v(\d+)/i.exec(item.title)?.[1] ??
    /draft_v(\d+)/i.exec(item.outputPath ?? "")?.[1];
  if (draftVersion !== undefined) return draftOrderHint(Number(draftVersion));
  if (item.dedupeKey === "output:project" || item.dedupeKey.startsWith("message:")) return 0;
  if (item.dedupeKey === "decision:feedback") return 46;
  if (item.dedupeKey === "decision:conflict" || item.dedupeKey === "decision:requirements") return 21;
  if (item.dedupeKey === "decision:stakeholder_selection") return 11;
  if (/選擇利害關係人/.test(value)) return 10;
  if (isHumanDecision && /利害關係人/.test(value)) return 11;
  if (/利害關係人發言/.test(value)) return 10;
  if (/需求分析|需求候選/.test(value)) return 20;
  if (isHumanDecision && /議題/.test(value)) return 71;
  if (isHumanDecision && /@資料來源|資料來源_|\.pdf|法令|法規|領域|研究/.test(value)) return 46;
  if (isHumanDecision && /衝突|Conflict|CR-/.test(value)) return 21;
  if (isHumanDecision) return 21;
  if (/需求擷取會議/.test(value)) return 30;
  if (/run_review/i.test(item.rawTitle ?? item.dedupeKey)) return 44;
  if (
    item.dedupeKey === "output:conflict" ||
    /artifact\/result\.json|conflict_report/i.test(item.outputPath ?? "") ||
    /衝突報告|Conflict Report|Report v\d+/i.test(value)
  ) {
    return 46;
  }
  if (/衝突辨識|衝突解決/.test(value)) return 45;
  if (/領域研究|Feedback/.test(value)) return 47;
  if (/系統模型生成|模型生成|系統模型|System Models/.test(value)) return 50;
  if (/Draft|草稿/.test(value)) return 60;
  if (/正式會議/.test(value)) return 70;
  if (/Design Rationale|設計緣由/.test(value)) return 80;
  if (/\bSRS\b|規格書|規格化/.test(value)) return 85;
  return 100;
}

function stageCardStatus(item: FlowItem) {
  const t = tx();
  const detail = item.detail.trim();
  if (/失敗|failed/i.test(detail)) return t.failed;
  if (/等待|waiting/i.test(detail)) return t.waiting;
  if (/執行中|正在|running|in progress/i.test(detail)) return t.inProgress;
  if (/選擇完成|已選擇|已產生候選利害關係人|selection complete/i.test(detail)) return t.selectionComplete;
  if (/發言完成|已整理利害關係人|statement complete/i.test(detail)) return t.statementComplete;
  if (/人類建議|suggestion complete/i.test(detail)) return t.suggestionComplete;
  if (/需求分析|需求候選|Requirements|analysis complete/i.test(`${item.title} ${detail}`)) return t.analysisComplete;
  if (/修正完成|已更新|updated|Scope|領域研究|System Models|Draft|Design Rationale|設計緣由|SRS|規格書|規格化|revision complete/i.test(detail)) return t.revisionComplete;
  if (/已完成|完成|completed|done/i.test(detail)) return t.generationComplete;
  return t.generationComplete;
}

export function stageCardSummary(item: FlowItem) {
  const detail = item.detail
    .replace(/^(?:完成|失敗|等待你決議|執行中|等待中|進行中)\s*[:：]\s*/g, "")
    .trim();
  if (!detail || detail === stageCardStatus(item)) {
    if (item.outputPath) return outputLabel(item.outputPath, item.title);
    return item.rawTitle || item.title;
  }
  return detail.length > 54 ? `${detail.slice(0, 54)}...` : detail;
}

export function isHumanFlowItem(item: FlowItem) {
  return item.tone === "decision";
}

function latestVersionedPath(paths: Set<string>, pattern: RegExp) {
  return Array.from(paths)
    .map((path) => ({ path, version: Number(pattern.exec(path)?.[1] ?? -1) }))
    .filter((item) => item.version >= 0)
    .sort((a, b) => b.version - a.version)[0]?.path;
}

function firstExistingPath(paths: Set<string>, candidates: string[]) {
  return candidates.find((path) => paths.has(path));
}

function outputPathForFlowItem(item: FlowItem, paths: Set<string>) {
  if (item.outputPath && paths.has(item.outputPath)) return item.outputPath;
  const value = `${item.title} ${item.detail} ${item.dedupeKey}`;
  const meetingRound = meetingRoundFromTitle(item.title);

  if (item.dedupeKey === "output:project" || item.dedupeKey === "decision:stakeholder_selection") {
    return firstExistingPath(paths, ["artifact/project.json"]);
  }
  if (/decision:requirements/.test(value) || item.dedupeKey === "output:requirements") {
    return firstExistingPath(paths, ["artifact/requirements.json"]);
  }
  if (item.dedupeKey === "output:elicitation") {
    return firstExistingPath(paths, ["artifact/meeting/elicitation_meeting.json"]);
  }
  if (/衝突報告|衝突辨識|衝突解決|Conflict|CR-|decision:conflict/.test(value)) {
    return firstExistingPath(paths, ["artifact/result.json"]) ??
      latestVersionedPath(paths, /conflict_report_v(\d+)\.(?:html|md|json)$/i);
  }
  if (/Feedback|decision:feedback|output:feedback/.test(value)) {
    return firstExistingPath(paths, ["artifact/feedback.json"]);
  }
  if (/System Models|output:system_models/.test(value)) {
    return firstExistingPath(paths, ["artifact/system_models.json"]) ??
      Array.from(paths).find((path) => /^artifact\/models\/.+\.(?:png|svg|plantuml|puml)$/i.test(path));
  }
  if (/Draft|草稿/.test(value)) {
    return firstExistingPath(paths, [
      "artifact/drafts/draft_v0.md",
      "results/drafts/draft_v0.html",
    ]);
  }
  if (meetingRound) {
    return firstExistingPath(paths, [
      `artifact/meeting/formal_meeting_r${meetingRound}.json`,
      `results/MoM/R${meetingRound}-M1.html`,
      `artifact/MoM/R${meetingRound}-M1.md`,
    ]) ?? latestVersionedPath(paths, new RegExp(`R${meetingRound}-M(\\d+)\\.(?:html|md)$`, "i"));
  }
  if (/Design Rationale|設計緣由/.test(value)) {
    return firstExistingPath(paths, ["results/design_rationale.html", "output/design_rationale.md"]);
  }
  if (/\bSRS\b|規格書|規格化/.test(value)) {
    return firstExistingPath(paths, ["results/srs.html", "output/srs.md"]);
  }
  return undefined;
}

function flowIdentity(item: FlowItem) {
  const meetingRound = meetingRoundFromTitle(item.title);
  if (meetingRound) return `meeting:R${meetingRound}`;
  const identityByTitle = new Map<string, string>([
    [tx().initialRequirementAnalysis, "artifact:requirements"],
    [tx().defineSystemScope, "artifact:scope"],
    ["Scope", "artifact:scope"],
    [tx().elicitationMeeting, "artifact:elicitation"],
    [tx().conflictDetection, "artifact:conflict"],
    [tx().domainResearch, "artifact:feedback"],
    [tx().systemModelGeneration, "artifact:system_models"],
    [tx().draftCreation, "artifact:draft"],
  ]);
  const artifactIdentity = identityByTitle.get(item.title);
  if (artifactIdentity && (item.dedupeKey.startsWith("action:") || item.dedupeKey.startsWith("output:"))) {
    return artifactIdentity;
  }
  const draftVersion = /Draft v(\d+)/i.exec(item.title)?.[1] ??
    /draft_v(\d+)/i.exec(item.outputPath ?? "")?.[1];
  if (draftVersion) return `draft:v${draftVersion}`;
  if (item.title === "Design Rationale" || item.title === "設計緣由" || /design_rationale/i.test(item.outputPath ?? "")) {
    return "document:design_rationale";
  }
  if (item.title === "SRS" || item.title === "規格書" || item.title === "規格化" || /(?:^|\/)srs\.(?:html|md)$/i.test(item.outputPath ?? "")) {
    return "document:srs";
  }
  if (item.dedupeKey === "output:system_models") return "artifact:system_models";
  if (item.dedupeKey === "output:feedback") return "artifact:feedback";
  if (item.dedupeKey === "output:conflict") return "artifact:conflict";
  if (item.dedupeKey === "output:elicitation") return "artifact:elicitation";
  if (item.dedupeKey === "output:requirements") return "artifact:requirements";
  if (item.dedupeKey === "output:project") return "artifact:project";
  return item.dedupeKey;
}

function isRedundantIntroFlowItem(item: FlowItem) {
  return item.dedupeKey === "output:project" || item.title === tx().stakeholderStatements;
}

function isFormalMeetingFlowItem(item: FlowItem) {
  const draftVersion = draftVersionFromPath(item.outputPath);
  return meetingRoundFromTitle(item.title) !== null ||
    (draftVersion !== null && draftVersion > 0);
}

function groupFormalMeetingItems(items: FlowItem[]) {
  const meetingItems = items
    .filter(isFormalMeetingFlowItem)
    .sort((a, b) => {
      const orderDiff = flowItemOrder(a) - flowItemOrder(b);
      if (orderDiff) return orderDiff;
      const aIndex = a.messageIndex ?? Number.MAX_SAFE_INTEGER;
      const bIndex = b.messageIndex ?? Number.MAX_SAFE_INTEGER;
      return aIndex - bIndex;
    });
  if (meetingItems.length === 0) return items;

  const first = meetingItems[0];
  const last = meetingItems[meetingItems.length - 1];
  const group: FlowItem = {
    id: "flow-group-formal-meeting",
    title: tx().formalMeeting,
    detail: tx().meetingItemsOrganized(meetingItems.length),
    dedupeKey: "group:formal_meeting",
    children: meetingItems,
    orderHint: 70,
    messageIndex: first.messageIndex,
    outputPath: first.outputPath,
    scrollTargetId: first.scrollTargetId ?? first.id,
    rawTitle: tx().rangeTo(first.title, last.title),
    tone: "action",
  };

  return [
    ...items.filter((item) => !isFormalMeetingFlowItem(item)),
    group,
  ];
}

export function buildWorkspaceFlowItems(
  messages: ChatMessage[],
  artifactItems: FileTreeNode[],
  hideGeneratedDocuments: boolean,
) {
  const availablePaths = new Set(
    artifactItems
      .filter((item) => item.kind === "file")
      .map((item) => item.path),
  );
  const messageItems: FlowItem[] = [];
  messages.forEach((message, index) => {
    const item = messageToFlowItem(message);
    if (!item) return;
    messageItems.push({
      ...item,
      messageIndex: index,
      scrollTargetId: item.scrollTargetId ?? message.id,
    });
  });

  const byKey = new Map<string, FlowItem>();
  messageItems.forEach((item) => {
    const key = flowIdentity(item);
    const existing = byKey.get(key);
    const keepActionLabel = existing?.dedupeKey.startsWith("action:") && item.dedupeKey.startsWith("output:");
    const displayItem = keepActionLabel && existing ? existing : item;
    byKey.set(key, {
      ...displayItem,
      outputPath: item.outputPath ?? existing?.outputPath,
      scrollTargetId: item.scrollTargetId ?? existing?.scrollTargetId,
      messageIndex: item.messageIndex ?? existing?.messageIndex,
    });
  });
  artifactFlowItems(artifactItems, messages, hideGeneratedDocuments).forEach((item) => {
    const key = flowIdentity(item);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, item);
      return;
    }
    byKey.set(key, {
      ...existing,
      outputPath: item.outputPath ?? existing.outputPath,
      scrollTargetId: item.scrollTargetId ?? existing.scrollTargetId,
      messageIndex: item.messageIndex ?? existing.messageIndex,
    });
  });

  return groupFormalMeetingItems(Array.from(byKey.values()))
    .filter((item) => !isRedundantIntroFlowItem(item))
    .map((item, index) => ({ item, index }))
    .sort((a, b) => {
      const orderDiff = flowItemOrder(a.item) - flowItemOrder(b.item);
      if ((a.item.orderHint !== undefined || b.item.orderHint !== undefined) && orderDiff) return orderDiff;
      if (a.item.messageIndex !== undefined && b.item.messageIndex !== undefined) {
        return a.item.messageIndex - b.item.messageIndex || orderDiff || a.index - b.index;
      }
      if (orderDiff) return orderDiff;
      if (a.item.messageIndex !== undefined) return -1;
      if (b.item.messageIndex !== undefined) return 1;
      return a.index - b.index;
    })
    .map(({ item }) => ({
      ...item,
      outputPath: outputPathForFlowItem(item, availablePaths),
    }));
}
