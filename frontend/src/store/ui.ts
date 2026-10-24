import { create } from "zustand";
import { persist } from "zustand/middleware";

type ThemeMode = "light" | "dark";

interface UiState {
  theme: ThemeMode;
  sound: boolean;
  collapsed: boolean;
  toggleTheme: () => void;
  setSound: (v: boolean) => void;
  setCollapsed: (v: boolean) => void;
}

const prefersDark = typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches;

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      theme: prefersDark ? "dark" : "light",
      sound: true,
      collapsed: false,
      toggleTheme: () => set((s) => ({ theme: s.theme === "dark" ? "light" : "dark" })),
      setSound: (sound) => set({ sound }),
      setCollapsed: (collapsed) => set({ collapsed }),
    }),
    { name: "linq-ui" },
  ),
);
