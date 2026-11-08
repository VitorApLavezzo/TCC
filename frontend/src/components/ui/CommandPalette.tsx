import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { machinesApi, anomaliesApi } from "../../services/api";
import { ANOMALY_TYPE_LABELS } from "../../types";
import { useDialogFocus } from "../../hooks/useDialogFocus";

type Item = { id: string; label: string; hint?: string; to: string };

const PAGES: Item[] = [
  { id: "p-painel", label: "Painel", to: "/" },
  { id: "p-maquinas", label: "Computadores", to: "/machines" },
  { id: "p-avisos", label: "Avisos", to: "/anomalies" },
  { id: "p-pergunte", label: "Pergunte ao seu computador", to: "/pergunte" },
  { id: "p-conta", label: "Sua conta", to: "/account" },
  { id: "p-pesquisa", label: "Pesquisa", hint: "ferramenta do TCC", to: "/pesquisa" },
  { id: "p-demo", label: "Demonstração", hint: "ferramenta do TCC", to: "/demonstracao" },
  { id: "p-estudo", label: "Estudo de compreensão", hint: "ferramenta do TCC", to: "/estudo" },
];

/** Busca com Ctrl+K: páginas, computadores e avisos em aberto num campo só. */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [dynamicItems, setDynamicItems] = useState<Item[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(open, dialogRef, onClose, inputRef);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    // Carregado ao abrir, e não a cada tecla: a lista é curta e a busca
    // acontece na memória, sem ida ao servidor por caractere digitado.
    Promise.all([machinesApi.list(), anomaliesApi.list({ hours: 168, unresolved_only: true })])
      .then(([m, a]) => {
        setDynamicItems([
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
      .catch(() => setDynamicItems([]));
  }, [open]);

  const items = useMemo(() => {
    const all = [...PAGES, ...dynamicItems];
    const term = query.trim().toLowerCase();
    if (!term) return all.slice(0, 8);
    return all.filter((i) => i.label.toLowerCase().includes(term)).slice(0, 12);
  }, [query, dynamicItems]);

  if (!open) return null;

  const go = (item?: Item) => {
    if (!item) return;
    onClose();
    navigate(item.to);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/50 p-4 pt-[12vh]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Buscar no sistema"
           className="w-full max-w-lg overflow-hidden rounded-panel border border-edge bg-surface shadow-float">
        <div className="flex items-center gap-2 border-b border-hairline px-3">
          <Search size={15} className="flex-shrink-0 text-fg-3" aria-hidden="true" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setActiveIndex(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setActiveIndex((i) => Math.min(i + 1, items.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setActiveIndex((i) => Math.max(i - 1, 0)); }
              if (e.key === "Enter") { e.preventDefault(); go(items[activeIndex]); }
            }}
            placeholder="Buscar computador, aviso ou tela..."
            aria-label="Buscar computador, aviso ou tela"
            role="combobox"
            aria-expanded={items.length > 0}
            aria-controls="paleta-resultados"
            aria-activedescendant={items[activeIndex] ? `paleta-${items[activeIndex].id}` : undefined}
            aria-autocomplete="list"
            className="h-12 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-3"
          />
          <kbd className="hidden flex-shrink-0 rounded border border-edge px-1.5 py-0.5 font-mono text-micro text-fg-3 sm:block">
            esc
          </kbd>
        </div>
        {items.length === 0 && <p className="px-4 py-6 text-center text-sm text-fg-3">Nada encontrado.</p>}
        {/* Lista de opções do campo: o foco fica no campo e as setas movem a
            seleção, que o leitor de tela acompanha pelo activedescendant. */}
        <ul id="paleta-resultados" role="listbox" aria-label="Resultados" className="max-h-[50vh] overflow-y-auto py-1">
          {items.map((item, i) => (
            <li key={item.id} role="presentation">
              <button
                type="button"
                id={`paleta-${item.id}`}
                role="option"
                aria-selected={i === activeIndex}
                tabIndex={-1}
                onMouseEnter={() => setActiveIndex(i)}
                onClick={() => go(item)}
                className={`flex w-full items-baseline justify-between gap-3 px-4 py-2 text-left text-sm ${
                  i === activeIndex ? "bg-raised text-fg" : "text-fg-2"
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
