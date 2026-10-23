import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { TokenOut, User } from "@/api/types";

interface AuthState {
  access: string | null;
  refresh: string | null;
  user: User | null;
  setTokens: (t: TokenOut) => void;
  setUser: (u: User) => void;
  clear: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      access: null,
      refresh: null,
      user: null,
      setTokens: (t) => set({ access: t.access_token, refresh: t.refresh_token, user: t.user }),
      setUser: (user) => set({ user }),
      clear: () => set({ access: null, refresh: null, user: null }),
    }),
    { name: "linq-auth" },
  ),
);

/** Срок жизни access-токена из JWT (exp, секунды). Для фейковых токенов моков — null. */
export function tokenExp(token: string | null): number | null {
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof payload.exp === "number" ? payload.exp : null;
  } catch {
    return null;
  }
}
