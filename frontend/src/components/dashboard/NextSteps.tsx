import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { accountApi, playbooksApi, pushApi } from "../../services/api";
import { Section, Panel } from "../ui/Layout";

type Step = { id: string; label: string; hint: string; to: string; done: boolean };

const DISMISSED_KEY = "nextStepsDismissed";

/**
 * O que fazer depois de conectar o primeiro computador. Cada passo some quando
 * cumprido, e a lista inteira pode ser dispensada.
 */
export function NextSteps() {
  const [steps, setSteps] = useState<Step[]>([]);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISSED_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (dismissed) return;
    Promise.all([
      accountApi.preferences().catch(() => null),
      pushApi.devices().catch(() => null),
      playbooksApi.list().catch(() => null),
    ]).then(([prefs, devices, books]) => {
      const channels = prefs?.data?.notifications?.channels ?? {};
      setSteps([
        {
          id: "avisos",
          label: "Ser avisado fora do painel",
          hint: "Telegram, e-mail ou notificação no celular",
          to: "/account?aba=notificacoes",
          done: Boolean(channels.telegram || channels.email) || (devices?.data?.devices?.length ?? 0) > 0,
        },
        {
          id: "diagnostico",
          label: "Perguntar por que está lento",
          hint: "Escreva a pergunta em português e o sistema responde pelo histórico",
          to: "/pergunte",
          done: false,
        },
        {
          id: "automacao",
          label: "Deixar uma ação pronta",
          hint: "Uma automação que sugere o que fazer quando o aviso voltar",
          to: "/account?aba=automacao",
          done: (books?.data?.playbooks?.length ?? 0) > 0,
        },
      ]);
    });
  }, [dismissed]);

  const pending = steps.filter((p) => !p.done);
  if (dismissed || pending.length === 0) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      /* sem armazenamento: volta na próxima visita, e tudo bem */
    }
    setDismissed(true);
  };

  return (
    <Section
      title="Próximos passos"
      description="Três coisas que mudam o uso no dia a dia"
      actions={
        <button type="button" onClick={dismiss} className="text-xs text-fg-3 hover:text-fg-2">
          Dispensar
        </button>
      }
    >
      <ul className="grid gap-2 sm:grid-cols-3">
        {steps.map((step) => (
          <li key={step.id}>
            <Link to={step.to} className="block h-full">
              <Panel className="h-full p-3.5 transition-colors hover:border-edge">
                <p className="flex items-center gap-2 text-sm font-medium text-fg">
                  <span
                    className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border ${
                      step.done ? "border-ok bg-ok/10" : "border-edge"
                    }`}
                    aria-hidden="true"
                  >
                    {step.done && <Check className="h-2.5 w-2.5 text-ok" strokeWidth={3} />}
                  </span>
                  <span className={step.done ? "text-fg-3 line-through" : ""}>{step.label}</span>
                </p>
                <p className="mt-1 pl-6 text-xs leading-relaxed text-fg-3">{step.hint}</p>
              </Panel>
            </Link>
          </li>
        ))}
      </ul>
    </Section>
  );
}
