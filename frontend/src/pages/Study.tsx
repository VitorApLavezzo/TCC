import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage, studyApi } from "../services/api";
import { decimal } from "../lib/format";
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

const SCALE = [1, 2, 3, 4, 5];

/**
 * Aplicação do estudo de compreensão, com o participante na frente: nada de
 * menu nem de "acertou/errou" entre os itens, o que contaminaria a medida.
 */
export function Study() {
  const toast = useToast();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<"inicio" | "item" | "sus" | "fim">("inicio");
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [item, setItem] = useState<Item | null>(null);
  const [loading, setLoading] = useState(false);
  const [susItems, setSusItems] = useState<string[]>([]);
  const [susAnswers, setSusAnswers] = useState<number[]>([]);
  const [form, setForm] = useState({ participant_code: "", expertise: "leigo", items: 6 });
  const [, setParams] = useSearchParams();

  // Com o participante respondendo, a moldura some (modo apresentação do AppShell).
  useEffect(() => {
    const inSession = phase === "item" || phase === "sus";
    setParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (inSession) next.set("apresentacao", "1");
        else next.delete("apresentacao");
        return next;
      },
      { replace: true }
    );
  }, [phase, setParams]);
  const [answer, setAnswer] = useState({ cause: "", action: "", confidence: 0, helpful: 0 });

  useEffect(() => {
    studyApi
      .config()
      .then((r) => {
        setSusItems(r.data.sus_items);
        setSusAnswers(new Array(r.data.sus_items.length).fill(3));
      })
      .catch(() => setSusItems([]));
  }, []);

  const loadNext = useCallback(async (id: number) => {
    setLoading(true);
    try {
      const r = await studyApi.next(id);
      if (r.data?.done) {
        setPhase("sus");
        setItem(null);
      } else {
        setItem(r.data);
        setAnswer({ cause: "", action: "", confidence: 0, helpful: 0 });
        setPhase("item");
      }
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível carregar o próximo aviso."));
    } finally {
      setLoading(false);
    }
  }, [toast]);

  async function start() {
    try {
      const r = await studyApi.create(form);
      setSessionId(r.data.session_id);
      loadNext(r.data.session_id);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function submitAnswer() {
    if (!sessionId || !item || !answer.cause) {
      toast.error("Escolha o que você acha que está acontecendo.");
      return;
    }
    try {
      await studyApi.answer(sessionId, {
        item_index: item.item_index,
        chosen_cause: answer.cause,
        chosen_action: answer.action || null,
        confidence: answer.confidence || null,
        helpful: answer.helpful || null,
      });
      loadNext(sessionId);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function finishSession() {
    if (!sessionId) return;
    try {
      await studyApi.finish(sessionId, { sus_answers: susAnswers });
      setPhase("fim");
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  if (phase === "inicio") {
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
            <Button className="mt-4" variant="primary" onClick={start}>
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

  if (phase === "item") {
    if (loading || !item) return <Skeleton className="h-64" />;
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
                      {Number.isInteger(m.value) ? m.value : decimal(m.value, 1)}
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
                  checked={answer.cause === o.value}
                  onChange={() => setAnswer({ ...answer, cause: o.value })}
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
            value={answer.action}
            onChange={(e) => setAnswer({ ...answer, action: e.target.value })}
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
            {SCALE.map((n) => (
              <button
                key={n}
                type="button"
                onClick={() => setAnswer({ ...answer, confidence: n })}
                aria-pressed={answer.confidence === n}
                className={`h-9 w-9 rounded-control border text-sm ${
                  answer.confidence === n ? "border-accent bg-accent/10 text-fg" : "border-edge text-fg-2"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </fieldset>

        <Button variant="primary" onClick={submitAnswer}>
          Responder e ver a próxima
        </Button>
      </div>
    );
  }

  if (phase === "sus") {
    return (
      <div className="mx-auto max-w-2xl space-y-6">
        <PageHeader
          title="Últimas dez perguntas"
          description="Diga o quanto concorda com cada frase: 1 discordo totalmente, 5 concordo totalmente."
        />
        <ol className="space-y-4">
          {susItems.map((sentence, i) => (
            <li key={i}>
              <p className="text-sm text-fg-2">{sentence}</p>
              <div className="mt-2 flex gap-2">
                {SCALE.map((n) => (
                  <button
                    key={n}
                    type="button"
                    aria-pressed={susAnswers[i] === n}
                    onClick={() =>
                      setSusAnswers(susAnswers.map((v, idx) => (idx === i ? n : v)))
                    }
                    className={`h-9 w-9 rounded-control border text-sm ${
                      susAnswers[i] === n ? "border-accent bg-accent/10 text-fg" : "border-edge text-fg-2"
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ol>
        <Button variant="primary" onClick={finishSession}>
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
        <Button variant="primary" onClick={() => { setPhase("inicio"); setSessionId(null); }}>
          Próximo participante
        </Button>
        <Button variant="secondary" onClick={() => navigate("/pesquisa")}>
          Ver os resultados
        </Button>
      </div>
    </div>
  );
}
