import { create } from "zustand";

const storageKey = "automem-admin-key";
const initialApiKey =
  typeof window !== "undefined" ? sessionStorage.getItem(storageKey) ?? "" : "";
const initialEndpoint = typeof window !== "undefined" ? window.location.origin : "";

type ConnectionState = "idle" | "connected" | "error";

interface SessionState {
  apiKey: string;
  connectionState: ConnectionState;
  endpoint: string;
  setApiKey: (value: string) => void;
  hydrate: () => void;
  setConnectionState: (value: ConnectionState) => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  apiKey: initialApiKey,
  connectionState: "idle",
  endpoint: initialEndpoint,
  setApiKey: (value) => {
    sessionStorage.setItem(storageKey, value);
    set({ apiKey: value });
  },
  hydrate: () => {
    const saved = sessionStorage.getItem(storageKey) ?? "";
    set({ apiKey: saved, endpoint: window.location.origin });
  },
  setConnectionState: (value) => set({ connectionState: value }),
}));
