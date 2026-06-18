import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { DiscussionMode } from "@/types/api";

export interface ScopeReviewDraft {
  in_scope: string[];
  out_of_scope: string[];
}

interface UiState {
  activeProjectId: string | null;
  selectedOutputPath: string | null;
  selectedOutputAnchor: string | null;
  autoFollowOutput: boolean;
  manualOutputLock: boolean;
  currentAutoOutputPath: string | null;
  scrollTargetMessageId: string | null;
  activeFlowMessageId: string | null;
  attachedDocIds: string[];
  stagedReferenceFiles: File[];
  meetingRounds: number;
  meetingMaxIssues: number;
  meetingRoundsOverridden: boolean;
  meetingMaxIssuesOverridden: boolean;
  discussionMode: DiscussionMode;
  enabledAgents: Record<string, boolean>;
  visiblePanels: {
    references: boolean;
    workspace: boolean;
    output: boolean;
  };
  darkMode: boolean;
  dismissedRunCheckpointKeys: Record<string, string>;
  scopeReviewDrafts: Record<string, ScopeReviewDraft>;
  canWrite: boolean;
  setActiveProjectId: (id: string | null) => void;
  setSelectedOutputPath: (path: string | null, source?: "auto" | "manual" | "system", anchor?: string | null) => void;
  setAutoOutputPath: (path: string | null) => void;
  resumeOutputAutoFollow: () => void;
  setScrollTargetMessageId: (id: string | null) => void;
  setActiveFlowMessageId: (id: string | null) => void;
  addStagedReferenceFile: (file: File) => void;
  removeStagedReferenceFile: (name: string) => void;
  clearStagedReferenceFiles: () => void;
  toggleAttachedDoc: (id: string) => void;
  clearAttachedDocs: () => void;
  setMeetingRounds: (n: number) => void;
  setMeetingMaxIssues: (n: number) => void;
  setMeetingDefaults: (rounds?: number | null, maxIssues?: number | null) => void;
  setDiscussionMode: (m: DiscussionMode) => void;
  setEnabledAgents: (agents: Record<string, boolean>) => void;
  toggleAgent: (agent: string) => void;
  togglePanelVisibility: (panel: "references" | "workspace" | "output") => void;
  toggleDarkMode: () => void;
  dismissRunCheckpoint: (projectId: string, checkpointKey: string) => void;
  setScopeReviewDraft: (decisionId: string, draft: ScopeReviewDraft) => void;
  clearScopeReviewDraft: (decisionId: string) => void;
  setCanWrite: (canWrite: boolean) => void;
}

const defaultAgents: Record<string, boolean> = {
  user: true,
  analyst: true,
  expert: true,
  modeler: true,
  documentor: true,
  mediator: true,
};

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      activeProjectId: null,
      selectedOutputPath: null,
      selectedOutputAnchor: null,
      autoFollowOutput: true,
      manualOutputLock: false,
      currentAutoOutputPath: null,
      scrollTargetMessageId: null,
      activeFlowMessageId: null,
      attachedDocIds: [],
      stagedReferenceFiles: [],
      meetingRounds: 1,
      meetingMaxIssues: 5,
      meetingRoundsOverridden: false,
      meetingMaxIssuesOverridden: false,
      discussionMode: "sequential",
      enabledAgents: { ...defaultAgents },
      visiblePanels: {
        references: true,
        workspace: true,
        output: true,
      },
      darkMode: false,
      dismissedRunCheckpointKeys: {},
      scopeReviewDrafts: {},
      canWrite: false,
      setActiveProjectId: (id) =>
        set({
          activeProjectId: id,
          selectedOutputPath: null,
          selectedOutputAnchor: null,
          autoFollowOutput: true,
          manualOutputLock: false,
          currentAutoOutputPath: null,
        }),
      setSelectedOutputPath: (path, source = "manual", anchor = null) =>
        set((s) => {
          const nextAutoFollow = source === "manual" ? false : s.autoFollowOutput;
          const nextManualLock = source === "manual" ? true : s.manualOutputLock;
          if (
            s.selectedOutputPath === path &&
            s.selectedOutputAnchor === anchor &&
            s.autoFollowOutput === nextAutoFollow &&
            s.manualOutputLock === nextManualLock
          ) {
            return s;
          }
          return {
            selectedOutputPath: path,
            selectedOutputAnchor: anchor,
            autoFollowOutput: nextAutoFollow,
            manualOutputLock: nextManualLock,
          };
        }),
      setAutoOutputPath: (path) =>
        set((s) => (s.currentAutoOutputPath === path ? s : { currentAutoOutputPath: path })),
      resumeOutputAutoFollow: () =>
        set(() => ({
          autoFollowOutput: true,
          manualOutputLock: false,
        })),
      setScrollTargetMessageId: (id) => set({ scrollTargetMessageId: id }),
      setActiveFlowMessageId: (id) => set({ activeFlowMessageId: id }),
      addStagedReferenceFile: (file) =>
        set((s) => ({
          stagedReferenceFiles: [
            ...s.stagedReferenceFiles.filter((item) => item.name !== file.name),
            file,
          ],
        })),
      removeStagedReferenceFile: (name) =>
        set((s) => ({
          stagedReferenceFiles: s.stagedReferenceFiles.filter((file) => file.name !== name),
        })),
      clearStagedReferenceFiles: () => set({ stagedReferenceFiles: [] }),
      toggleAttachedDoc: (id) =>
        set((s) => ({
          attachedDocIds: s.attachedDocIds.includes(id)
            ? s.attachedDocIds.filter((x) => x !== id)
            : [...s.attachedDocIds, id],
        })),
      clearAttachedDocs: () => set({ attachedDocIds: [] }),
      setMeetingRounds: (n) => set({ meetingRounds: n, meetingRoundsOverridden: true }),
      setMeetingMaxIssues: (n) => set({ meetingMaxIssues: n, meetingMaxIssuesOverridden: true }),
      setMeetingDefaults: (rounds, maxIssues) =>
        set((s) => ({
          meetingRounds: rounds == null ? s.meetingRounds : rounds,
          meetingMaxIssues: maxIssues == null ? s.meetingMaxIssues : maxIssues,
          meetingRoundsOverridden: false,
          meetingMaxIssuesOverridden: false,
        })),
      setDiscussionMode: (m) => set({ discussionMode: m }),
      setEnabledAgents: (agents) => set({ enabledAgents: agents }),
      toggleAgent: (agent) =>
        set((s) => {
          if (agent === "user" || agent === "mediator") return s;
          return {
            enabledAgents: {
              ...s.enabledAgents,
              [agent]: !s.enabledAgents[agent],
            },
          };
        }),
      togglePanelVisibility: (panel) =>
        set((s) => ({
          visiblePanels: {
            ...s.visiblePanels,
            [panel]: !s.visiblePanels[panel],
          },
        })),
      toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
      dismissRunCheckpoint: (projectId, checkpointKey) =>
        set((s) => ({
          dismissedRunCheckpointKeys: {
            ...s.dismissedRunCheckpointKeys,
            [projectId]: checkpointKey,
          },
        })),
      setScopeReviewDraft: (decisionId, draft) =>
        set((s) => ({
          scopeReviewDrafts: {
            ...s.scopeReviewDrafts,
            [decisionId]: draft,
          },
        })),
      clearScopeReviewDraft: (decisionId) =>
        set((s) => {
          if (!s.scopeReviewDrafts[decisionId]) return s;
          const next = { ...s.scopeReviewDrafts };
          delete next[decisionId];
          return { scopeReviewDrafts: next };
        }),
      setCanWrite: (canWrite) => set({ canWrite }),
    }),
    {
      name: "plant-ui-state",
      partialize: (state) => ({
        activeProjectId: state.activeProjectId,
        darkMode: state.darkMode,
        dismissedRunCheckpointKeys: state.dismissedRunCheckpointKeys,
      }),
    },
  ),
);
