import { useState, FormEvent } from "react";
import { useNavigate, Link } from "react-router-dom";
import { authApi, errorMessage } from "../services/api";
import { Eye, EyeOff } from "lucide-react";
import { Button } from "../components/ui/Button";

const MIN_PASSWORD = 8;

export function Register() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPass, setShowPass] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const longEnough = password.length >= MIN_PASSWORD;
  const matches = confirm.length > 0 && password === confirm;
  const canSubmit = email && username && longEnough && matches;

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    if (!longEnough) {
      setError(`A senha precisa ter pelo menos ${MIN_PASSWORD} caracteres.`);
      return;
    }
    if (password !== confirm) {
      setError("As duas senhas não são iguais.");
      return;
    }

    setLoading(true);
    try {
      await authApi.register(email, username, password);
      // Antes a pessoa era mandada para /login sem nenhum aviso e achava que
      // havia dado erro. Agora o login explica que a conta foi criada.
      navigate("/login?conta=criada");
    } catch (err) {
      setError(errorMessage(err, "Não foi possível criar a conta."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
      <div className="w-full max-w-[22rem]">
        <header className="mb-7">
          <div className="flex items-center gap-2">
            <span className="h-4 w-1 rounded-full bg-fg" aria-hidden="true" />
            <span className="text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
          </div>
          <h1 className="mt-5 text-lg font-semibold tracking-tight text-fg">Criar sua conta</h1>
          <p className="mt-1.5 text-sm text-fg-2">Depois disso você conecta seus computadores em três passos.</p>
        </header>

        <form onSubmit={handleSubmit} className="space-y-4" noValidate>
          <Field
            id="email"
            label="E-mail"
            type="email"
            autoComplete="email"
            value={email}
            onChange={setEmail}
            hint="Usamos apenas para identificar sua conta."
          />
          <Field
            id="username"
            label="Usuário"
            type="text"
            autoComplete="username"
            value={username}
            onChange={setUsername}
            hint="É com ele que você vai entrar."
          />

          <div>
            <label htmlFor="password" className="mb-1.5 block text-xs text-fg-2">
              Senha
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPass ? "text" : "password"}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                aria-describedby="password-req"
                className="field pr-10"
              />
              <button
                type="button"
                onClick={() => setShowPass((v) => !v)}
                aria-label={showPass ? "Ocultar as senhas" : "Mostrar as senhas"}
                className="absolute right-1.5 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-control text-fg-3 hover:text-fg"
              >
                {showPass ? <EyeOff size={15} aria-hidden="true" /> : <Eye size={15} aria-hidden="true" />}
              </button>
            </div>
            <p id="password-req" className={`mt-1.5 text-xs ${longEnough ? "text-ok" : "text-fg-3"}`}>
              Pelo menos {MIN_PASSWORD} caracteres
            </p>
          </div>

          <div>
            <label htmlFor="confirm" className="mb-1.5 block text-xs text-fg-2">
              Repita a senha
            </label>
            <input
              id="confirm"
              type={showPass ? "text" : "password"}
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
              className={`field ${confirm.length > 0 && !matches ? "border-crit/60" : ""}`}
            />
            {confirm.length > 0 && !matches && <p className="mt-1.5 text-xs text-crit">As duas senhas não são iguais.</p>}
          </div>

          {error && (
            <p role="alert" className="rounded-control border border-crit/30 bg-crit/8 px-3 py-2 text-xs text-crit">
              {error}
            </p>
          )}

          <Button
            type="submit"
            variant="primary"
            className="h-9 w-full"
            disabled={!canSubmit}
            loading={loading}
            loadingLabel="Criando a conta..."
          >
            Criar conta
          </Button>

          <p className="pt-1 text-center text-xs text-fg-3">
            Já tem conta?{" "}
            <Link to="/login" className="text-accent hover:underline">
              Entrar
            </Link>
          </p>
        </form>
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  type,
  autoComplete,
  value,
  onChange,
  hint,
}: {
  id: string;
  label: string;
  type: string;
  autoComplete: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs text-fg-2">
        {label}
      </label>
      <input
        id={id}
        type={type}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="field"
      />
      {hint && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-fg-3">
          {hint}
        </p>
      )}
    </div>
  );
}
