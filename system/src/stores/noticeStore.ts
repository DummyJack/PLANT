import { create } from "zustand";

export type NoticeTone = "error" | "success" | "info";

export interface Notice {
  id: string;
  tone: NoticeTone;
  title: string;
  message?: string;
  createdAt: number;
}

interface NoticeState {
  notices: Notice[];
  pushNotice: (notice: Omit<Notice, "id" | "createdAt">) => void;
  dismissNotice: (id: string) => void;
}

export const useNoticeStore = create<NoticeState>((set) => ({
  notices: [],
  pushNotice: (notice) =>
    set((state) => ({
      notices: [
        ...state.notices,
        {
          ...notice,
          id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
          createdAt: Date.now(),
        },
      ].slice(-4),
    })),
  dismissNotice: (id) =>
    set((state) => ({
      notices: state.notices.filter((notice) => notice.id !== id),
    })),
}));
