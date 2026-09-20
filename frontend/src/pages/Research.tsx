import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { evaluationApi } from "../services/api";
import { PageHeader, Section, Panel } from "../components/ui/Layout";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { DetectionBenchmark } from "../components/research/DetectionBenchmark";

/**
 * Página de pesquisa — os dados quantitativos que o TCC precisa sobre a
 * própria ferramenta.
 *
 * Duas perguntas que um trabalho sobre "IA que explica" tem de responder com
 * número, não com opinião: as explicações são factualmente corretas (os números
 * citados existem nos dados?) e são úteis (a pessoa achou que ajudou; uma
 * IA-juíza deu que nota?). Aqui isso vem agregado por provedor, o que também
 * permite comparar modelo local × nuvem.
 */
export function Research() {
  const navigate = useNavigate();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    setLoading(true);
    evaluationApi
      .summary(days)
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [days]);

  const providers = Object.entries(data?.by_provider ?? {});

  return (
    <div className="space-y-8">
      <PageHeader
        title="Pesquisa"
        description="Medidas sobre o próprio sistema: qualidade das explicações por provedor de IA e o modo demonstração."
        aside={
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
          >
            <option value={7}>7 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </select>
        }
      />

      <DetectionBenchmark />

      <Section
        title="Qualidade das explicações"
        description="Precisão factual sai da checagem automática dos números; a nota da juíza é outra IA avaliando o texto"
      >
        {loading ? (
          <Skeleton className="h-32 w-full rounded-panel" />
        ) : providers.length === 0 ? (
          <EmptyState
            title="Nenhuma explicação gerada ainda"
            body="Quando os primeiros avisos forem explicados, as medidas aparecem aqui, separadas por provedor de IA."
          />
        ) : (
          <Panel className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead>
                <tr className="border-b border-hairline text-fg-3">
                  <th className="px-4 py-2.5 font-normal">Provedor</th>
                  <th className="px-4 py-2.5 text-right font-normal">Explicações</th>
                  <th className="px-4 py-2.5 text-right font-normal">Precisão factual</th>
                  <th className="px-4 py-2.5 text-right font-normal">Nota da juíza</th>
                  <th className="px-4 py-2.5 text-right font-normal">Úteis</th>
                  <th className="px-4 py-2.5 text-right font-normal">Tempo médio</th>
                </tr>
              </thead>
              <tbody>
                {providers.map(([name, v]: [string, any]) => (
                  <tr key={name} className="border-b border-hairline last:border-0">
                    <td className="px-4 py-2.5 font-mono text-xs text-fg">{name}</td>
                    <td className="tnum px-4 py-2.5 text-right font-mono text-xs text-fg-2">{v.count}</td>
                    <td className="tnum px-4 py-2.5 text-right font-mono text-xs text-fg-2">
                      {v.factual_accuracy_pct != null ? `${v.factual_accuracy_pct}%` : "—"}
                      {v.unverified_numbers > 0 && (
                        <span className="ml-1 text-warn" title={`${v.unverified_numbers} número(s) sem respaldo`}>
                          ⚠
                        </span>
                      )}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right font-mono text-xs text-fg-2">
                      {v.judge_avg != null ? `${v.judge_avg}/5` : "—"}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right font-mono text-xs text-fg-2">
                      {v.thumbs_up + v.thumbs_down > 0 ? `${v.thumbs_up}👍 ${v.thumbs_down}👎` : "—"}
                    </td>
                    <td className="tnum px-4 py-2.5 text-right font-mono text-xs text-fg-2">
                      {v.avg_duration_ms != null ? `${(v.avg_duration_ms / 1000).toFixed(1)} s` : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        )}
        <p className="mt-3 max-w-prose text-xs leading-relaxed text-fg-3">
          A precisão factual é medida sozinha, sem ninguém avaliar à mão: cada número que a IA escreve precisa bater
          com um dado medido. No detalhe de um aviso dá para pedir a avaliação da IA-juíza e comparar todos os
          provedores na mesma anomalia.
        </p>
      </Section>

      <Section title="Demonstração" description="Injeta anomalias controladas para apresentar o sistema">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-panel border border-hairline bg-surface px-5 py-4">
          <p className="max-w-prose text-sm leading-relaxed text-fg-2">
            Cria um computador de demonstração e injeta leituras sintéticas que passam pela mesma detecção das reais —
            sem precisar travar uma máquina de verdade na frente da banca.
          </p>
          <Button variant="primary" onClick={() => navigate("/demonstracao")}>
            Abrir demonstração
          </Button>
        </div>
      </Section>
    </div>
  );
}
