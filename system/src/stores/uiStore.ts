import { create } from "zustand";
import type { DiscussionMode } from "@/types/api";

interface UiState {
  activeProjectId: string | null;
  selectedOutputPath: string | null;
  scrollTargetMessageId: string | null;
  attachedDocIds: string[];
  stagedReferenceFiles: File[];
  meetingRounds: number;
  discussionMode: DiscussionMode;
  enabledAgents: Record<string, boolean>;
  setActiveProjectId: (id: string | null) => void;
  setSelectedOutputPath: (path: string | null) => void;
  setScrollTargetMessageId: (id: string | null) => void;
  addStagedReferenceFile: (file: File) => void;
  removeStagedReferenceFile: (name: string) => void;
  clearStagedReferenceFiles: () => void;
  toggleAttachedDoc: (id: string) => void;
  clearAttachedDocs: () => void;
  setMeetingRounds: (n: number) => void;
  setDiscussionMode: (m: DiscussionMode) => void;
  setEnabledAgents: (agents: Record<string, boolean>) => void;
  toggleAgent: (agent: string) => void;
}

const defaultAgents: Record<string, boolean> = {
  user: true,
  analyst: true,
  expert: true,
  modeler: true,
  documentor: true,
  mediator: true,
};

export const useUiStore = create<UiState>((set) => ({
  activeProjectId: null,
  selectedOutputPath: null,
  scrollTargetMessageId: null,
  attachedDocIds: [],
  stagedReferenceFiles: [],
  meetingRounds: 1,
  discussionMode: "sequential",
  enabledAgents: { ...defaultAgents },
  setActiveProjectId: (id) => set({ activeProjectId: id, selectedOutputPath: null }),
  setSelectedOutputPath: (path) => set({ selectedOutputPath: path }),
  setScrollTargetMessageId: (id) => set({ scrollTargetMessageId: id }),
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
  setMeetingRounds: (n) => set({ meetingRounds: n }),
  setDiscussionMode: (m) => set({ discussionMode: m }),
  setEnabledAgents: (agents) => set({ enabledAgents: agents }),
  toggleAgent: (agent) =>
    set((s) => {
      if (agent === "mediator") return s;
      return {
        enabledAgents: {
          ...s.enabledAgents,
          [agent]: !s.enabledAgents[agent],
        },
      };
    }),
}));
