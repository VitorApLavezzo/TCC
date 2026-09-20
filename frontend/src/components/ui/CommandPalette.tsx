import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { machinesApi, anomaliesApi } from "../../services/api";
import { ANOMALY_TYPE_LABELS } from "../../types";

type Item = { id: string; label: string; hint?: string; to: string };

const PAGINAS: Item[] = [
  { id: "p-painel", label: "Painel", to: "/" },
  { id: "p-maquinas", label: "Computadores", to: "/machines" },
  { id: "p-avisos", label: "Avisos", to: "/anomalies" },
  { id: "p-pergunte", label: "Pergunte ao seu computador", to: "/pergunte" },
  { id: "p-conta", label: "Sua conta", to: "/account" },
  { id: "p-pesquisa", label: "Pesquisa", hint: "avançado", to: "/pesquisa" },
  { id: "p-demo", label: "Demonstração", hint: "avançado", to: "/demonstracao" },
  { id: "p-estudo", label: "Estudo de compreensão", hint: "avançado", to: "/estudo" },
];

/**
 * Ir direto ao ponto, com Ctrl+K.
 *
 * Com uma máquina, navegar pelo menu é rápido. Com doze e uma lista de
 * avisos, a pessoa passa mais tempo procurando a tela do que lendo o que
 * está nela. Aqui páginas, computadores e avisos em aberto ficam no mesmo
 * campo de busca — o mesmo gesto que já existe no editor de quem programa e
 * na busca do sistema operacional.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [busca, setBusca] = useState("");
  const [dinamicos, setDinamicos] = useState<Item[]>([]);
  const [indice, setIndice] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setBusca("");
    setIndice(0);
    inputRef.current?.focus();
    // Carregado ao abrir, e não a cada tecla: a lista é curta e a busca
    // acontece na memória, sem ida ao servidor por caractere digitado.
    Promise.all([machinesApi.list(), anomaliesApi.list({ hours: 168, unresolved_only: true })])
      .then(([m, a]) => {
        setDinamicos([
          ...m.data.map((x: any) => ({
            id: `m-${x.id}`, label: x.name, hint: "computador", to: `/machines/${x.id}`,
          })),
          ...a.data.slice(0, 20).map((x: any) => ({
            id: `a-${x.id}`,
            label: ANOMALY_TYPE_LABELS[x.anomaly_type] || x.anomaly_type,
            hint: "aviso em aberto",
            to: `/anomalies/${x.id}`,
          })),
        ]);
      })
      .catch(() => setDinamicos([]));
  }, [open]);

  const itens = useMemo(() => {
    const todos = [...PAGINAS, ...dinamicos];
    const termo = busca.trim().toLowerCase();
    if (!termo) return todos.slice(0, 8);
    return todos.filter((i) => i.label.toLowerCase().includes(termo)).slice(0, 12);
  }, [busca, dinamicos]);

  if (!open) return null;

  const ir = (item?: Item) => {
    if (!item) return;
    onClose();
    navigate(item.to);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div role="dialog" aria-modal="true" aria-label="Buscar no sistema"
           className="w-full max-w-lg overflow-hidden rounded-panel border border-edge bg-surface shadow-float">
        <div className="flex items-center gap-2 border-b border-hairline px-3">
          <Search size={15} className="flex-shrink-0 text-fg-3" aria-hidden="true" />
          <input
            ref={inputRef}
            value={busca}
            onChange={(e) => { setBusca(e.target.value); setIndice(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setIndice((i) => Math.min(i + 1, itens.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setIndice((i) => Math.max(i - 1, 0)); }
              if (e.key === "Enter") { e.preventDefault(); ir(itens[indice]); }
              if (e.key === "Escape") onClose();
            }}
            placeholder="Buscar computador, aviso ou tela..."
            aria-label="Buscar computador, aviso ou tela"
            className="h-12 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-3"
          />
          <kbd className="hidden flex-shrink-0 rounded border border-edge px-1.5 py-0.5 font-mono text-micro text-fg-3 sm:block">
            esc
          </kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto py-1">
          {itens.length === 0 && <li className="px-4 py-6 text-center text-sm text-fg-3">Nada encontrado.</li>}
          {itens.map((item, i) => (
            <li key={item.id}>
              <button
                type="button"
                onMouseEnter={() => setIndice(i)}
                onClick={() => ir(item)}
                className={`flex w-full items-baseline justify-between gap-3 px-4 py-2 text-left text-sm ${
                  i === indice ? "bg-raised text-fg" : "text-fg-2"
                }`}
              >
                <span className="truncate">{item.label}</span>
                {item.hint && <span className="flex-shrink-0 text-micro text-fg-3">{item.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
