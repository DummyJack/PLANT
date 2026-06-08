import { create } from "zustand";
import type { ChatMessage } from "@/types/api";

interface ChatState {
  messages: ChatMessage[];
  appendMessage: (msg: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  clearMessages: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  appendMessage: (msg) =>
    set((s) => {
      if (s.messages.some((m) => m.id === msg.id)) return s;
      return { messages: [...s.messages, msg] };
    }),
  setMessages: (messages) => set({ messages }),
  clearMessages: () => set({ messages: [] }),
}));
