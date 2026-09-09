import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "../components/ui/Button";

/**
 * Antes, qualquer endereço desconhecido era redirecionado ao painel em
 * silêncio — a pessoa nunca descobria que havia digitado ou salvo algo errado.
 */
export function NotFound() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <div className="max-w-lg py-4">
      <h1 className="text-lg font-semibold tracking-tight text-fg">Esta página não existe</h1>
      <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">
        Não encontramos nada em <span className="font-mono text-fg">{pathname}</span>. O endereço pode ter mudado, ou o
        link estar incompleto.
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => navigate("/")}>
          Ir para o painel
        </Button>
        <Button variant="secondary" onClick={() => navigate("/anomalies")}>
          Ver os avisos
        </Button>
      </div>
    </div>
  );
}
