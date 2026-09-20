import { useState, useEffect, useRef, FormEvent } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { authApi, errorMessage } from "../services/api";
import { useT } from "../lib/i18n";
import { Eye, EyeOff } from "lucide-react";
import { Button } from "../components/ui/Button";
import { Wordmark } from "../components/ui/SignalMark";

export function Login() {
  const { login, loginWithToken } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState("");
  // Primeira tela de todas: é por aqui que a tradução começa a valer.
  const tr = useT();
  const [loading, setLoading] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);

  // Explica por que a pessoa está nesta tela. Antes ela chegava aqui sem
  // contexto — depois de criar conta, ou por sessão expirada.
  const justRegistered = params.get("conta") === "criada";
  const sessionExpired = params.get("sessao") === "expirada";

  useEffect(() => {
    let cancelled = false;
    authApi
      .config()
      .then((res) => {
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
              } catch (err) {
                setError(errorMessage(err, "O login com o Google não foi aceito."));
              }
            },
          });
          g.accounts.id.renderButton(googleBtnRef.current, {
            theme: "outline",
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
      })
      .catch(() => {
        // Sem configuração de Google: a entrada por usuário e senha basta.
      });
    return () => {
      cancelled = true;
    };
  }, [loginWithToken, navigate]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username, password);
      navigate("/");
    } catch (err: any) {
      setError(
        err?.response
          ? "Usuário ou senha incorretos."
          : "Não conseguimos falar com o servidor. Verifique se ele está ligado."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-canvas md:flex-row">
      <div className="flex flex-col justify-center gap-4 border-b border-hairline bg-raised px-6 py-10 md:w-[42%] md:border-b-0 md:border-r md:px-12 md:py-0 lg:w-[38%]">
        <Wordmark />
        <p className="max-w-sm font-display text-xl font-semibold leading-snug text-fg">
          A saúde dos seus computadores, explicada em português simples.
        </p>
        <p className="max-w-sm text-sm leading-relaxed text-fg-2">
          Acompanhamos processador, memória, disco e rede — e avisamos quando algo sai do normal, sem jargão técnico.
        </p>
      </div>

      <div className="flex flex-1 items-center justify-center p-4 py-10 sm:p-8">
      <div className="w-full max-w-[22rem]">
        <header className="mb-7">
          <h1 className="font-display text-xl font-bold tracking-tight text-fg">Entrar</h1>
          <p className="mt-1.5 text-sm leading-relaxed text-fg-2">
            Acompanhe a saúde dos seus computadores e entenda, em português, o que fazer quando algo sai do normal.
          </p>
        </header>

        {justRegistered && (
          <p className="mb-4 rounded-panel border border-ok/30 bg-ok/8 px-3.5 py-2.5 text-sm text-ok">
            Conta criada. Entre com o usuário e a senha que você acabou de escolher.
          </p>
        )}
        {sessionExpired && (
          <p className="mb-4 rounded-panel border border-hairline bg-sunken px-3.5 py-2.5 text-sm text-fg-2">
            Sua sessão expirou por segurança. Entre de novo para continuar.
          </p>
        )}

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <div>
            <label htmlFor="usuario" className="mb-1.5 block text-xs text-fg-2">
              Usuário
            </label>
            <input
              id="usuario"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="field"
              placeholder="seu_usuario"
            />
          </div>

          <div>
            <label htmlFor="senha" className="mb-1.5 block text-xs text-fg-2">
              Senha
            </label>
            <div className="relative">
              <input
                id="senha"
                type={showPass ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="field pr-10"
                placeholder="••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPass((v) => !v)}
                aria-label={showPass ? tr("auth.hidePassword", "Ocultar a senha") : tr("auth.showPassword", "Mostrar a senha")}
                className="absolute right-1.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-control text-fg-3 hover:text-fg"
              >
                {showPass ? <EyeOff size={15} aria-hidden="true" /> : <Eye size={15} aria-hidden="true" />}
              </button>
            </div>
          </div>

          {error && (
            <p role="alert" className="rounded-control border border-crit/30 bg-crit/8 px-3 py-2 text-xs text-crit">
              {error}
            </p>
          )}

          <Button type="submit" variant="primary" loading={loading} loadingLabel={tr("auth.signingIn", "Entrando...")} className="h-9 w-full">
            Entrar
          </Button>

          <div ref={googleBtnRef} className="flex justify-center" />

          <p className="pt-1 text-center text-xs text-fg-3">
            Não tem conta?{" "}
            <Link to="/register" className="text-accent hover:underline">
              Criar uma agora
            </Link>
          </p>
        </form>
      </div>
      </div>
    </div>
  );
}
