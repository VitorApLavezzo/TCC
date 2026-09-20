import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage, studyApi } from "../services/api";
import { PageHeader, Section, Panel } from "../components/ui/Layout";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";

type Item = {
  session_id: number;
  item_index: number;
  arm: "ai" | "raw";
  total_items: number;
  machine: string | null;
  raw: { measurements: { label: string; value: number; unit: string }[]; process: string | null };
  cause_options: { value: string; label: string }[];
  action_options: string[];
  explanation?: { summary: string; detailed: string; causes: string[]; recommendations: string[] };
};

const ESCALA = [1, 2, 3, 4, 5];

/**
 * Aplicação do estudo de compreensão.
 *
 * Esta tela é usada com o participante na frente, e por isso ela é a única do
 * sistema que esconde deliberadamente informação: nada de menu, de outras
 * páginas ou de "acertou/errou" entre os itens. Saber o resultado no meio
 * mudaria o comportamento nos itens seguintes e contaminaria a medida.
 */
export function Study() {
  const toast = useToast();
  const navigate = useNavigate();
  const [fase, setFase] = useState<"inicio" | "item" | "sus" | "fim">("inicio");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [item, setItem] = useState<Item | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [susItens, setSusItens] = useState<string[]>([]);
  const [susRespostas, setSusRespostas] = useState<number[]>([]);
  const [form, setForm] = useState({ participant_code: "", expertise: "leigo", items: 6 });
  const [resposta, setResposta] = useState({ cause: "", action: "", confidence: 0, helpful: 0 });

  useEffect(() => {
    studyApi
      .config()
      .then((r) => {
        setSusItens(r.data.sus_items);
        setSusRespostas(new Array(r.data.sus_items.length).fill(3));
      })
      .catch(() => setSusItens([]));
  }, []);

  const proximo = useCallback(async (id: number) => {
    setCarregando(true);
    try {
      const r = await studyApi.next(id);
      if (r.data?.done) {
        setFase("sus");
        setItem(null);
      } else {
        setItem(r.data);
        setResposta({ cause: "", action: "", confidence: 0, helpful: 0 });
        setFase("item");
      }
    } finally {
      setCarregando(false);
    }
  }, []);

  async function comecar() {
    try {
      const r = await studyApi.create(form);
      setSessionId(r.data.session_id);
      proximo(r.data.session_id);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function responder() {
    if (!sessionId || !item || !resposta.cause) {
      toast.error("Escolha o que você acha que está acontecendo.");
      return;
    }
    try {
      await studyApi.answer(sessionId, {
        item_index: item.item_index,
        chosen_cause: resposta.cause,
        chosen_action: resposta.action || null,
        confidence: resposta.confidence || null,
        helpful: resposta.helpful || null,
      });
      proximo(sessionId);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function encerrar() {
    if (!sessionId) return;
    try {
      await studyApi.finish(sessionId, { sus_answers: susRespostas });
      setFase("fim");
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  if (fase === "inicio") {
    return (
      <div className="space-y-8">
        <PageHeader
          title="Estudo de compreensão"
          description="Aplique a um participante. Ele vê seis avisos reais: metade com a explicação da IA, metade só com os números, em ordem sorteada."
        />
        <Section title="Novo participante">
          <Panel className="max-w-lg p-4">
            <label className="block text-xs text-fg-2">
              Código do participante (anônimo)
              <input
                value={form.participant_code}
                onChange={(e) => setForm({ ...form, participant_code: e.target.value })}
                placeholder="P01"
                className="mt-1 h-9 w-full rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
              />
            </label>
            <label className="mt-3 block text-xs text-fg-2">
              Familiaridade com informática (autodeclarada)
              <select
                value={form.expertise}
                onChange={(e) => setForm({ ...form, expertise: e.target.value })}
                className="mt-1 h-9 w-full rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
              >
                <option value="leigo">Leigo — uso o computador, não mexo por dentro</option>
                <option value="intermediario">Intermediário — me viro com configurações</option>
                <option value="tecnico">Técnico — trabalho com isso</option>
              </select>
            </label>
            <Button className="mt-4" variant="primary" onClick={comecar}>
              Começar
            </Button>
            <p className="mt-3 max-w-prose text-micro leading-relaxed text-fg-3">
              Nada que identifique a pessoa é gravado: só o código, o perfil declarado e as
              respostas. O tempo de cada resposta é cronometrado.
            </p>
          </Panel>
        </Section>
      </div>
    );
  }

  if (fase === "item") {
    if (carregando || !item) return <Skeleton className="h-64" />;
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <PageHeader
          title={`Situação ${item.item_index + 1} de ${item.total_items}`}
          description={item.machine ? `Computador: ${item.machine}` : undefined}
        />

        <Panel className="p-4">
          {item.arm === "ai" && item.explanation ? (
            <>
              <p className="font-display text-sm font-semibold text-fg">{item.explanation.summary}</p>
              <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">
                {item.explanation.detailed}
              </p>
              {item.explanation.causes?.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-fg-2">
                  {item.explanation.causes.slice(0, 3).map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <>
              <p className="channel-label">Medidas do computador</p>
              <dl className="mt-2 divide-y divide-hairline">
                {item.raw.measurements.map((m) => (
                  <div key={m.label} className="flex justify-between gap-4 py-2 text-sm">
                    <dt className="text-fg-2">{m.label}</dt>
                    <dd className="tnum font-mono text-fg">
                      {m.value}
                      {m.unit}
                    </dd>
                  </div>
                ))}
              </dl>
              {item.raw.process && (
                <p className="mt-2 text-xs text-fg-3">
                  Programa que mais consome: <span className="font-mono">{item.raw.process}</span>
                </p>
              )}
            </>
          )}
        </Panel>

        <fieldset>
          <legend className="text-sm font-semibold text-fg">O que você acha que está acontecendo?</legend>
          <div className="mt-2 space-y-2">
            {item.cause_options.map((o) => (
              <label
                key={o.value}
                className="flex cursor-pointer items-center gap-2 rounded-panel border border-hairline p-3 text-sm text-fg-2 hover:border-edge"
              >
                <input
                  type="radio"
                  name="causa"
                  checked={resposta.cause === o.value}
                  onChange={() => setResposta({ ...resposta, cause: o.value })}
                  className="h-4 w-4 accent-accent"
                />
                {o.label}
              </label>
            ))}
          </div>
        </fieldset>

        <label className="block text-sm text-fg-2">
          O que você faria?
          <select
            value={resposta.action}
            onChange={(e) => setResposta({ ...resposta, action: e.target.value })}
            className="mt-1 h-9 w-full rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
          >
            <option value="">Escolha uma ação</option>
            {item.action_options.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>

        <fieldset>
          <legend className="text-sm text-fg-2">Quanta confiança você tem na sua resposta? (1 pouca, 5 muita)</legend>
          <div className="mt-2 flex gap-2">
            {ESCALA.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setResposta({ ...resposta, confidence: n })}
                aria-pressed={resposta.confidence === n}
                className={`h-9 w-9 rounded-control border text-sm ${
                  resposta.confidence === n ? "border-accent bg-accent/10 text-fg" : "border-edge text-fg-2"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </fieldset>

        <Button variant="primary" onClick={responder}>
          Responder e ver a próxima
        </Button>
      </div>
    );
  }

  if (fase === "sus") {
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <PageHeader
          title="Últimas dez perguntas"
          description="Diga o quanto concorda com cada frase: 1 discordo totalmente, 5 concordo totalmente."
        />
        <ol className="space-y-4">
          {susItens.map((frase, i) => (
            <li key={i}>
              <p className="text-sm text-fg-2">{frase}</p>
              <div className="mt-2 flex gap-2">
                {ESCALA.map((n) => (
                  <button
                    key={n}
                    type="button"
                    aria-pressed={susRespostas[i] === n}
                    onClick={() =>
                      setSusRespostas(susRespostas.map((v, idx) => (idx === i ? n : v)))
                    }
                    className={`h-9 w-9 rounded-control border text-sm ${
                      susRespostas[i] === n ? "border-accent bg-accent/10 text-fg" : "border-edge text-fg-2"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ol>
        <Button variant="primary" onClick={encerrar}>
          Encerrar a sessão
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-lg space-y-4 py-12 text-center">
      <h1 className="font-display text-xl font-bold text-fg">Sessão concluída</h1>
      <p className="text-sm leading-relaxed text-fg-2">
        As respostas foram gravadas. O resultado agregado — acerto e tempo em cada condição, com o
        teste estatístico — aparece na página de pesquisa.
      </p>
      <div className="flex justify-center gap-2">
        <Button variant="primary" onClick={() => { setFase("inicio"); setSessionId(null); }}>
          Próximo participante
        </Button>
        <Button variant="secondary" onClick={() => navigate("/pesquisa")}>
          Ver os resultados
        </Button>
      </div>
    </div>
  );
}
