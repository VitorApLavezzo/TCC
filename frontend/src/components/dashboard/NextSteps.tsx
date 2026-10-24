import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Check } from "lucide-react";
import { accountApi, playbooksApi, pushApi } from "../../services/api";
import { Section, Panel } from "../ui/Layout";

type Passo = { id: string; label: string; hint: string; to: string; done: boolean };

const CHAVE_DISPENSADO = "nextStepsDismissed";

/**
 * O que fazer depois de conectar o primeiro computador.
 *
 * O acolhimento terminava no Welcome: conectada a máquina, a pessoa caía no
 * painel e ficava por conta própria. Os três passos abaixo são os que mudam
 * o uso de verdade — ser avisado fora do painel, ver o sistema responder a
 * um pedido, e deixar uma ação pronta para a próxima vez. Cada um some
 * sozinho quando cumprido, e a lista inteira pode ser dispensada.
 */
export function NextSteps() {
  const [passos, setPassos] = useState<Passo[]>([]);
  const [dispensado, setDispensado] = useState(() => {
    try {
      return localStorage.getItem(CHAVE_DISPENSADO) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (dispensado) return;
    Promise.all([
      accountApi.preferences().catch(() => null),
      pushApi.devices().catch(() => null),
      playbooksApi.list().catch(() => null),
    ]).then(([prefs, devices, books]) => {
      const canais = prefs?.data?.notifications?.channels ?? {};
      setPassos([
        {
          id: "avisos",
          label: "Ser avisado fora do painel",
          hint: "Telegram, e-mail ou notificação no celular",
          to: "/account?aba=notificacoes",
          done: Boolean(canais.telegram || canais.email) || (devices?.data?.devices?.length ?? 0) > 0,
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
  }, [dispensado]);

  const pendentes = passos.filter((p) => !p.done);
  if (dispensado || pendentes.length === 0) return null;

  const dispensar = () => {
    try {
      localStorage.setItem(CHAVE_DISPENSADO, "1");
    } catch {
      /* sem armazenamento: volta na próxima visita, e tudo bem */
    }
    setDispensado(true);
  };

  return (
    <Section
      title="Próximos passos"
      description="Três coisas que mudam o uso no dia a dia"
      actions={
        <button type="button" onClick={dispensar} className="text-xs text-fg-3 hover:text-fg-2">
          Dispensar
        </button>
      }
    >
      <ul className="grid gap-2 sm:grid-cols-3">
        {passos.map((passo) => (
          <li key={passo.id}>
            <Link to={passo.to} className="block h-full">
              <Panel className="h-full p-3.5 transition-colors hover:border-edge">
                <p className="flex items-center gap-2 text-sm font-medium text-fg">
                  <span
                    className={`flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border ${
                      passo.done ? "border-ok bg-ok/10" : "border-edge"
                    }`}
                    aria-hidden="true"
                  >
                    {passo.done && <Check className="h-2.5 w-2.5 text-ok" strokeWidth={3} />}
                  </span>
                  <span className={passo.done ? "text-fg-3 line-through" : ""}>{passo.label}</span>
                </p>
                <p className="mt-1 pl-6 text-xs leading-relaxed text-fg-3">{passo.hint}</p>
              </Panel>
            </Link>
          </li>
        ))}
      </ul>
    </Section>
  );
}
