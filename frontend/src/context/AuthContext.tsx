import { createContext, useContext, useState, useEffect, ReactNode } from "react";
import { User } from "../types";
import { authApi, pushApi } from "../services/api";
import { pararAvisosNesteAparelho } from "../lib/push";

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  loginWithToken: (token: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(localStorage.getItem("token"));
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (token) {
      authApi.me()
        .then((res) => setUser(res.data))
        .catch(() => {
          localStorage.removeItem("token");
          setToken(null);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [token]);

  const login = async (username: string, password: string) => {
    const res = await authApi.login(username, password);
    const newToken = res.data.access_token;
    localStorage.setItem("token", newToken);
    setToken(newToken);
    const meRes = await authApi.me();
    setUser(meRes.data);
  };

  const loginWithToken = async (newToken: string) => {
    localStorage.setItem("token", newToken);
    setToken(newToken);
    const meRes = await authApi.me();
    setUser(meRes.data);
  };

  const logout = () => {
    // A assinatura de avisos é da conta que está saindo: sai junto. O token
    // vai explícito porque some do localStorage antes da requisição sair.
    const tokenAtual = localStorage.getItem("token");
    void pararAvisosNesteAparelho((endpoint) => pushApi.unsubscribe(endpoint, tokenAtual));
    localStorage.removeItem("token");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, loginWithToken, logout, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
