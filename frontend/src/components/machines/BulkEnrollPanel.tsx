import { useCallback, useEffect, useState } from "react";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Ban, ChevronDown } from "lucide-react";
import { Button, IconButton } from "../ui/Button";
import { Explain } from "../ui/Explain";
import { useToast } from "../ui/Toast";
import { useConfirm } from "../ui/ConfirmDialog";
import { bulkKeysApi, errorMessage } from "../../services/api";
import { pluralize } from "../../lib/format";
import { downloadSilentInstaller, downloadMassDeployScript, serverOneLiner } from "../../utils/installers";

interface BulkKey {
  id: number;
  code: string;
  label?: string | null;
  max_uses?: number | null;
  use_count: number;
  revoked: boolean;
  expires_at: string;
}

/**
 * Instalação em massa: recolhido e abaixo da lista de computadores.
 *
 * Atende à TI de empresa. Antes aparecia acima da lista, o que fazia o usuário
 * doméstico encarar um bloco corporativo antes de ver a própria máquina.
 */
export function BulkEnrollPanel() {
  const toast = useToast();
  const confirm = useConfirm();
  const [open, setOpen] = useState(false);
  const [keys, setKeys] = useState<BulkKey[]>([]);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const fetchKeys = useCallback(async () => {
    try {
      const res = await bulkKeysApi.list();
      setKeys(res.data);
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível carregar as chaves."));
    }
  }, [toast]);

  useEffect(() => {
    if (open) fetchKeys();
  }, [open, fetchKeys]);

  const create = async () => {
    setCreating(true);
    try {
      await bulkKeysApi.create({ label: label || undefined, expires_days: 365 });
      setLabel("");
      await fetchKeys();
      toast.success("Chave criada.", "Use os botões da chave para baixar o instalador ou o script de distribuição.");
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível criar a chave."));
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (key: BulkKey) => {
    const ok = await confirm({
      title: "Revogar esta chave?",
      body: (
        <>
          A chave <strong className="text-fg">{key.label || key.code}</strong> deixa de aceitar novos registros. Os{" "}
          {pluralize(key.use_count, "computador já instalado", "computadores já instalados")} com ela continuam
          funcionando normalmente.
        </>
      ),
      confirmLabel: "Revogar a chave",
      destructive: true,
    });
    if (!ok) return;
    try {
      await bulkKeysApi.revoke(key.id);
      await fetchKeys();
      toast.success("Chave revogada.");
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível revogar a chave."));
    }
  };

  const copyCommand = async (key: BulkKey) => {
    await navigator.clipboard.writeText(serverOneLiner({ code: key.code }));
    setCopiedId(key.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div className="border-t border-hairline pt-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="-mx-2 flex w-[calc(100%+1rem)] items-center justify-between gap-3 rounded-control px-2 py-1.5 text-left transition-colors hover:bg-raised"
      >
        <span>
          <span className="block text-sm font-medium text-fg">Instalar em muitos computadores de uma vez</span>
          <span className="block text-xs text-fg-3">Para equipes de TI com dezenas ou centenas de máquinas</span>
        </span>
        <ChevronDown
          size={15}
          className={`flex-shrink-0 text-fg-3 transition-transform ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div className="mt-4 space-y-4">
          <p className="max-w-prose text-xs leading-relaxed text-fg-2">
            O código individual vale para um computador e expira em 30 minutos. Uma{" "}
            <span className="inline-flex items-center gap-1 text-fg">
              chave de instalação em massa
              <Explain term="chave_massa" />
            </span>{" "}
            serve para quantas máquinas você quiser, sem prazo curto. Embuta a chave no seu método de distribuição —
            GPO do Active Directory, RMM, ou o script de PowerShell abaixo — e os computadores se registram sozinhos.
          </p>

          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[220px] flex-1">
              <label htmlFor="bulk-label" className="mb-1 block text-xs text-fg-2">
                Nome da chave <span className="text-fg-3">(opcional, ajuda a identificar depois)</span>
              </label>
              <input
                id="bulk-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="Notebooks do setor financeiro"
                className="h-8 w-full rounded-control border border-edge bg-surface px-2.5 text-sm text-fg placeholder:text-fg-3 focus:border-accent"
              />
            </div>
            <Button variant="primary" loading={creating} loadingLabel="Criando..." onClick={create}>
              Criar chave
            </Button>
          </div>

          {keys.length === 0 ? (
            <p className="text-xs text-fg-3">
              Nenhuma chave criada ainda. Crie uma acima para receber o instalador silencioso e o script de
              distribuição.
            </p>
          ) : (
            <ul className="divide-y divide-hairline border-y border-hairline">
              {keys.map((key) => (
                <li key={key.id} className={`py-3 ${key.revoked ? "opacity-55" : ""}`}>
                  <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                    <div className="min-w-0">
                      <p className="flex items-baseline gap-2 text-sm text-fg">
                        {key.label || "Chave sem nome"}
                        {key.revoked && <span className="text-xs text-crit">revogada</span>}
                      </p>
                      <p className="tnum mt-0.5 text-xs text-fg-3">
                        <span className="font-mono">{key.code}</span> ·{" "}
                        {pluralize(key.use_count, "computador instalado", "computadores instalados")}
                        {key.max_uses ? ` de ${key.max_uses}` : ""} · válida até{" "}
                        {format(new Date(key.expires_at), "dd/MM/yyyy", { locale: ptBR })}
                      </p>
                    </div>
                    {!key.revoked && (
                      <IconButton
                        label={`Revogar a chave ${key.label || key.code}`}
                        tone="danger"
                        icon={<Ban size={13} aria-hidden="true" />}
                        onClick={() => revoke(key)}
                      />
                    )}
                  </div>

                  {!key.revoked && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        title="Roda sem abrir janelas, como SYSTEM — para distribuir via GPO"
                        onClick={() => downloadSilentInstaller(key.code)}
                      >
                        Instalador silencioso (GPO)
                      </Button>
                      <Button
                        size="sm"
                        title="Instala numa lista de computadores via WinRM, a partir de uma única máquina"
                        onClick={() => downloadMassDeployScript(key.code)}
                      >
                        Script de distribuição (PowerShell)
                      </Button>
                      <Button size="sm" variant="quiet" onClick={() => copyCommand(key)}>
                        {copiedId === key.id ? "Comando copiado" : "Copiar comando Linux"}
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}

          <details>
            <summary className="cursor-pointer select-none text-xs text-fg-2 hover:text-fg">
              Como isso funciona numa empresa, na prática
            </summary>
            <div className="mt-2.5 max-w-prose space-y-2.5 text-xs leading-relaxed text-fg-3">
              <p>
                <span className="text-fg-2">Windows com Active Directory:</span> peça à TI para adicionar o instalador
                silencioso como script de inicialização do computador na GPO. Ele roda no boot, antes do login, em todo
                o parque, sem abrir janela — e assume que o Python já está na imagem padrão.
              </p>
              <p>
                <span className="text-fg-2">Sem GPO, mas com acesso administrativo:</span> use o script de distribuição.
                Ele instala numa lista de computadores por PowerShell Remoting, a partir de uma única máquina.
              </p>
              <p>
                <span className="text-fg-2">Servidores Linux:</span> o comando Linux é o mesmo da instalação individual,
                então funciona com Ansible, script SSH em lote ou qualquer ferramenta de automação.
              </p>
              <p>Revogar uma chave nunca afeta as máquinas já instaladas com ela — só impede novos registros.</p>
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
