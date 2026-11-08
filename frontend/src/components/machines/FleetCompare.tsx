import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { insightsApi } from "../../services/api";
import { Section } from "../ui/Layout";
import { Skeleton } from "../ui/Skeleton";

/**
 * Comparar com máquinas de perfil parecido mostra o que o histórico próprio esconde.
 * Só aparece com três computadores ou mais: abaixo disso a mediana não significa nada.
 */
export function FleetCompare() {
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    insightsApi
      .compare()
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <Skeleton className="h-20 w-full rounded-panel" />;
  if (!data?.ready) return null;

  const insights = data.insights ?? [];

  return (
    <Section
      title="Comparando seus computadores"
      description={`${data.machines_compared} computadores com leituras suficientes na última semana`}
    >
      {insights.length === 0 ? (
        <p className="max-w-prose text-sm text-fg-2">
          Nenhum computador está fora do padrão dos outros de perfil parecido. Quando um passar a gastar bem mais que
          os semelhantes, o aviso aparece aqui.
        </p>
      ) : (
        <ul className="space-y-2.5">
          {insights.slice(0, 6).map((i: any, idx: number) => (
            <li key={idx} className="rounded-panel border border-hairline bg-surface px-4 py-3">
              <button
                type="button"
                onClick={() => navigate(`/machines/${i.machine_id}`)}
                className="block w-full text-left"
              >
                <p className="max-w-prose text-sm leading-relaxed text-fg-2">{i.sentence}</p>
                {i.top_process && (
                  <p className="mt-1 text-xs text-fg-3">
                    Maior diferença: <span className="font-mono text-fg-2">{i.top_process.name}</span> ({i.top_process.mem_percent}% da memória)
                  </p>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
