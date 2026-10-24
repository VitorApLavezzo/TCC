import { useState } from "react";
import { decimal } from "../../lib/format";
import { AIExplanation, Anomaly, Counterfactual, LanguageLevel, LANGUAGE_LEVEL_LABELS, Verification } from "../../types";
import { explanationsApi, errorMessage } from "../../services/api";
import { useToast } from "../ui/Toast";
import { ThumbsUp, ThumbsDown, ShieldCheck, ShieldAlert } from "lucide-react";

/**
 * "Se você fechar X…" — a conta contrafactual que o sistema fez a partir dos
 * processos reais da leitura, não um palpite da IA.
 */
export function CounterfactualCard({ cf, onAct }: { cf: Counterfactual; onAct?: () => void }) {
  return (
    <div className="rounded-panel border border-hairline bg-surface px-4 py-3.5">
      <p className="channel-label mb-1.5">E se eu fechar?</p>
      <p className="max-w-prose text-sm leading-relaxed text-fg">{cf.sentence}</p>
      <div className="mt-2.5 flex flex-wrap gap-x-6 gap-y-1 text-xs text-fg-3">
        <span>
          Memória <span className="tnum font-mono text-fg-2">{cf.mem_now.toFixed(0)}%</span> →{" "}
          <span className="tnum font-mono text-ok">{cf.mem_after.toFixed(0)}%</span>
        </span>
        {cf.mem_freed_gb > 0.1 && <span>Libera ~{decimal(cf.mem_freed_gb, 1)} GB</span>}
      </div>
      {onAct && (
        <button type="button" onClick={onAct} className="mt-2 rounded text-xs font-medium text-accent hover:underline">
          Fechar {cf.process} agora
        </button>
      )}
    </div>
  );
}

/**
 * Selo de confiança nos números: cada valor citado pela IA foi conferido com
 * os dados. Quando algum não bate, a tela avisa em vez de esconder.
 */
export function VerificationBadge({ verification }: { verification?: Verification | null }) {
  if (!verification || verification.claims === 0) return null;
  const ok = verification.passed && verification.unverified.length === 0;
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-xs ${ok ? "text-fg-3" : "text-warn"}`}
      title={
        ok
          ? `${verification.verified} de ${verification.claims} números conferidos com os dados reais`
          : `Números sem respaldo nos dados: ${verification.unverified.join("; ")}`
      }
    >
      {ok ? <ShieldCheck size={12} aria-hidden="true" /> : <ShieldAlert size={12} aria-hidden="true" />}
      {ok ? `${verification.verified}/${verification.claims} números conferidos` : "alguns números não conferem"}
    </span>
  );
}

/** Onde os dados deste aviso foram analisados. Importante para a transparência. */
export function DestinationTag({ destination, provider }: { destination?: string; provider?: string }) {
  if (!destination) return provider ? <span className="text-micro text-fg-3">{provider}</span> : null;
  const label =
    destination === "local"
      ? "analisado localmente"
      : destination === "cloud"
        ? "analisado na nuvem"
        : "análise local (sem IA)";
  return (
    <span className="text-micro text-fg-3" title={provider}>
      {label}
    </span>
  );
}

/** Troca o nível de linguagem da explicação — mesmo aviso, reescrito para o leitor. */
export function LanguageLevelSwitch({
  anomaly,
  current,
  onVariant,
}: {
  anomaly: Anomaly;
  current: LanguageLevel;
  onVariant: (level: LanguageLevel, variant: any) => void;
}) {
  const toast = useToast();
  const [loading, setLoading] = useState<LanguageLevel | null>(null);
  const levels: LanguageLevel[] = ["leigo", "intermediario", "tecnico"];

  const pick = async (level: LanguageLevel) => {
    if (level === current) return;
    setLoading(level);
    try {
      const cached = anomaly.explanation?.variants?.[level];
      if (cached) {
        onVariant(level, cached);
      } else {
        const res = await explanationsApi.variant(anomaly.id, level);
        onVariant(level, res.data.variant);
      }
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível reescrever a explicação."));
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="inline-flex overflow-hidden rounded-control border border-edge">
      {levels.map((level) => (
        <button
          key={level}
          type="button"
          onClick={() => pick(level)}
          disabled={loading !== null}
          aria-pressed={level === current}
          className={`px-2.5 py-1 text-xs transition-colors ${
            level === current ? "bg-raised font-medium text-fg" : "text-fg-3 hover:bg-raised hover:text-fg-2"
          }`}
        >
          {loading === level ? "…" : LANGUAGE_LEVEL_LABELS[level]}
        </button>
      ))}
    </div>
  );
}

/** 👍/👎 na explicação. Alimenta a avaliação para o TCC. */
export function RatingButtons({ anomaly }: { anomaly: Anomaly }) {
  const toast = useToast();
  const [rating, setRating] = useState<number | undefined>(anomaly.explanation?.user_rating);

  const rate = async (value: 1 | -1) => {
    const anterior = rating;
    const next = rating === value ? undefined : value;
    setRating(next);
    // Desmarcar só limpa a tela: não há como apagar a nota no servidor, e
    // agradecer por um clique que desfez a escolha não fazia sentido.
    if (!next) return;
    try {
      await explanationsApi.rate(anomaly.id, value);
      toast.success(value === 1 ? "Obrigado! Que bom que ajudou." : "Obrigado pelo retorno.");
    } catch (err) {
      setRating(anterior);
      toast.error(errorMessage(err, "Não foi possível registrar a avaliação."));
    }
  };

  // Escolhido = fundo tingido, e não só a cor do ícone; alvo de 32 px.
  const estilo = (ativo: boolean, tom: string) =>
    `flex h-8 w-8 items-center justify-center rounded-control transition-colors hover:bg-raised ${
      ativo ? tom : "text-fg-3"
    }`;

  return (
    <span className="inline-flex items-center gap-1">
      <span className="mr-1 text-micro text-fg-3">Esta explicação ajudou?</span>
      <button
        type="button"
        onClick={() => rate(1)}
        aria-label="Ajudou"
        aria-pressed={rating === 1}
        className={estilo(rating === 1, "bg-ok/[.14] text-ok")}
      >
        <ThumbsUp size={12} aria-hidden="true" />
      </button>
      <button
        type="button"
        onClick={() => rate(-1)}
        aria-label="Não ajudou"
        aria-pressed={rating === -1}
        className={estilo(rating === -1, "bg-crit/[.14] text-crit")}
      >
        <ThumbsDown size={12} aria-hidden="true" />
      </button>
    </span>
  );
}
