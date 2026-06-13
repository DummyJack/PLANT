import { create } from "zustand";
import type { ChatMessage } from "@/types/api";

interface ChatState {
  messages: ChatMessage[];
  appendMessage: (msg: ChatMessage) => void;
  setMessages: (msgs: ChatMessage[]) => void;
  trimTrailingRunStatusMessages: () => void;
  clearMessages: () => void;
}

function isTrailingRunStatusMessage(message: ChatMessage) {
  if (message.status === "failed") return true;
  return message.role === "system" && message.kind === "stage";
}

function isDuplicateStagePill(a: ChatMessage, b: ChatMessage) {
  return (
    a.role === "system" &&
    b.role === "system" &&
    a.kind === "stage" &&
    b.kind === "stage" &&
    a.status === "running" &&
    b.status === "running" &&
    a.stage === b.stage &&
    a.text.trim() === b.text.trim()
  );
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  appendMessage: (msg) =>
    set((s) => {
      if (s.messages.some((m) => m.id === msg.id)) return s;
      if (s.messages.some((m) => isDuplicateStagePill(m, msg))) return s;
      return { messages: [...s.messages, msg] };
    }),
  setMessages: (messages) => set({ messages }),
  trimTrailingRunStatusMessages: () =>
    set((s) => {
      let end = s.messages.length;
      while (end > 0 && isTrailingRunStatusMessage(s.messages[end - 1])) {
        end -= 1;
      }
      if (end === s.messages.length) return s;
      return { messages: s.messages.slice(0, end) };
    }),
  clearMessages: () => set({ messages: [] }),
}));
