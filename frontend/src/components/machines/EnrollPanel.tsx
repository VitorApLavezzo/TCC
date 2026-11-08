import { useState } from "react";
import { useToast } from "../ui/Toast";
import { copyText, COPY_FAILED } from "../../lib/clipboard";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { X } from "lucide-react";
import { Panel } from "../ui/Layout";
import { Button, IconButton } from "../ui/Button";
import { Explain } from "../ui/Explain";
import { downloadInstaller, serverOneLiner, isLocalOrigin } from "../../utils/installers";

export interface EnrollCode {
  code: string;
  expires_at: string;
}

/** Primeiro o caminho de dois cliques, que serve à maioria; comando de terminal e código manual ficam recolhidos. */
export function EnrollPanel({ enrollCode, onClose }: { enrollCode: EnrollCode; onClose: () => void }) {
  const [copied, setCopied] = useState<"code" | "cmd" | null>(null);
  const toast = useToast();

  const copy = async (what: "code" | "cmd") => {
    const ok = await copyText(what === "code" ? enrollCode.code : serverOneLiner({ code: enrollCode.code }));
    if (!ok) return toast.error(...COPY_FAILED);
    setCopied(what);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <Panel className="px-5 py-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-fg">Conectar um computador</h2>
          <p className="mt-1 max-w-prose text-sm text-fg-2">
            Nome, hostname e sistema operacional são detectados sozinhos. Você não precisa digitar nada disso.
          </p>
        </div>
        <IconButton label="Fechar estas instruções" icon={<X size={15} aria-hidden="true" />} onClick={onClose} />
      </div>

      {isLocalOrigin() && (
        <p className="mt-4 max-w-prose rounded-panel border border-warn/30 bg-warn/[.08] px-3.5 py-2.5 text-xs leading-relaxed text-fg-2">
          <span className="font-medium text-warn">Você abriu o painel por “localhost”.</span> Esse endereço só funciona
          neste computador. Ao baixar o instalador, será pedido o endereço de rede do servidor — algo como{" "}
          <span className="font-mono text-fg">http://192.168.0.10:3000</span>. Para evitar o passo extra, acesse o
          painel pelo endereço de rede do servidor.
        </p>
      )}

      <ol className="mt-5 divide-y divide-hairline border-y border-hairline">
        <Step n={1} title="Baixe o instalador no sistema do computador que será monitorado">
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" size="sm" onClick={() => downloadInstaller("windows", { code: enrollCode.code })}>
              Windows
            </Button>
            <Button size="sm" onClick={() => downloadInstaller("linux", { code: enrollCode.code })}>
              Linux (com tela)
            </Button>
          </div>
        </Step>

        <Step n={2} title="Leve o arquivo até aquele computador e execute">
          <p className="max-w-prose text-xs leading-relaxed text-fg-3">
            Pendrive, e-mail, rede — qualquer forma serve. No Windows são dois cliques. No Linux, abra o terminal na
            pasta do arquivo e rode <code className="font-mono text-fg-2">bash instalar-anomalydetect.sh</code>.
          </p>
        </Step>

        <Step n={3} title="Pronto — ele aparece nesta página em instantes">
          <p className="max-w-prose text-xs leading-relaxed text-fg-3">
            O instalador configura tudo sozinho e passa a monitorar a cada vez que o computador liga. A primeira leitura
            chega em até 30 segundos.
          </p>
        </Step>
      </ol>

      <div className="mt-4 space-y-2">
        <details className="group">
          <summary className="cursor-pointer select-none text-xs text-fg-2 hover:text-fg">
            É um servidor só com terminal, sem tela?
          </summary>
          <div className="mt-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-control bg-sunken px-2.5 py-2 font-mono text-xs text-fg-2">
              {serverOneLiner({ code: enrollCode.code })}
            </code>
            <Button size="sm" variant="secondary" onClick={() => copy("cmd")}>
              {copied === "cmd" ? "Copiado" : "Copiar"}
            </Button>
          </div>
        </details>

        <details>
          <summary className="flex cursor-pointer select-none items-center gap-1.5 text-xs text-fg-2 hover:text-fg">
            Prefere digitar o código manualmente?
            <Explain term="codigo_pareamento" />
          </summary>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span className="tnum font-mono text-lg font-medium tracking-[0.18em] text-fg">{enrollCode.code}</span>
            <Button size="sm" variant="secondary" onClick={() => copy("code")}>
              {copied === "code" ? "Copiado" : "Copiar código"}
            </Button>
            <span className="text-xs text-fg-3">
              Rode <code className="font-mono text-fg-2">python agent.py</code> no computador e digite o código.
            </span>
          </div>
        </details>
      </div>

      <p className="tnum mt-4 text-xs text-fg-3">
        Válido até {format(new Date(enrollCode.expires_at), "HH:mm", { locale: ptBR })} · serve para um computador ·
        gere outro se expirar
      </p>
    </Panel>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3 py-3">
      <span className="tnum w-4 flex-shrink-0 text-sm text-fg-3">{n}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm text-fg">{title}</p>
        <div className="mt-2">{children}</div>
      </div>
    </li>
  );
}
