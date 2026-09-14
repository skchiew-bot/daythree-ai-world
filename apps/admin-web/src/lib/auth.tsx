import { createContext, useContext, useState, type ReactNode } from "react";

import { api, getStoredToken, setStoredToken } from "@/api/client";
import { useCurrentUser } from "@/api/hooks";
import type { CurrentUser } from "@/types/api";

interface AuthContextValue {
  user: CurrentUser | undefined;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  loginError: string | null;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [hasToken, setHasToken] = useState(!!getStoredToken());
  const [loginError, setLoginError] = useState<string | null>(null);
  const { data: user, isLoading, isError } = useCurrentUser(hasToken);

  async function login(email: string, password: string) {
    setLoginError(null);
    try {
      const { access_token } = await api.login(email, password);
      setStoredToken(access_token);
      setHasToken(true);
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Login failed.");
      throw err;
    }
  }

  function logout() {
    setStoredToken(null);
    setHasToken(false);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: hasToken && !isError && !!user,
        isLoading: hasToken && isLoading,
        login,
        logout,
        loginError,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
