import { useState, useEffect, useRef, FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { authApi } from "../services/api";
import { Activity, Eye, EyeOff } from "lucide-react";

export function Login() {
  const { login, loginWithToken } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    authApi.config().then((res) => {
      const clientId = res.data.google_client_id;
      if (!clientId || cancelled) return;

      const renderButton = () => {
        const g = (window as any).google;
        if (!g?.accounts?.id || !googleBtnRef.current) return;
        g.accounts.id.initialize({
          client_id: clientId,
          callback: async (resp: { credential: string }) => {
            try {
              const r = await authApi.googleLogin(resp.credential);
              await loginWithToken(r.data.access_token);
              navigate("/");
            } catch {
              setError("Falha no login com Google.");
            }
          },
        });
        g.accounts.id.renderButton(googleBtnRef.current, {
          theme: "filled_black",
          size: "large",
          width: 320,
          text: "signin_with",
          locale: "pt-BR",
        });
      };

      if ((window as any).google?.accounts?.id) {
        renderButton();
      } else {
        const script = document.createElement("script");
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true;
        script.onload = renderButton;
        document.head.appendChild(script);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      navigate("/");
    } catch {
      setError("Usuário ou senha incorretos.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 bg-blue-600 rounded-2xl mb-4">
            <Activity size={28} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-white">AnomalyDetect</h1>
          <p className="text-gray-400 text-sm mt-1">Monitoramento Inteligente com IA</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Usuário</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-white text-sm placeholder-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
              placeholder="seu_usuario"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 mb-1.5">Senha</label>
            <div className="relative">
              <input
                type={showPass ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 pr-10 text-white text-sm placeholder-gray-600 focus:outline-none focus:border-blue-500 transition-colors"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPass(!showPass)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300"
              >
                {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {error && (
            <p className="text-red-400 text-xs bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-medium rounded-lg py-2.5 text-sm transition-colors"
          >
            {loading ? "Entrando..." : "Entrar"}
          </button>

          <div ref={googleBtnRef} className="flex justify-center" />

          <p className="text-center text-xs text-gray-500">
            Não tem conta?{" "}
            <Link to="/register" className="text-blue-400 hover:text-blue-300">
              Criar conta
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}
