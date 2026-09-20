import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { PageHeader, Section, Panel, DataList, DataRow } from "../components/ui/Layout";
import { Button } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";
import { accountApi, errorMessage } from "../services/api";
import { GLOSSARY } from "../lib/glossary";
import { LANGUAGE_LEVEL_LABELS, LanguageLevel } from "../types";
import { PushDevices } from "../components/account/PushDevices";
import { AuditLedger } from "../components/account/AuditLedger";
import { Playbooks } from "../components/automation/Playbooks";

const GLOSSARY_ORDER: { term: keyof typeof GLOSSARY; label: string }[] = [
  { term: "cpu", label: "Processador" },
  { term: "memoria", label: "Memória" },
  { term: "disco", label: "Disco" },
  { term: "swap", label: "Memória virtual" },
  { term: "temperatura", label: "Temperatura" },
  { term: "conexoes", label: "Conexões abertas" },
  { term: "saude_bateria", label: "Saúde da bateria" },
  { term: "score", label: "Desvio do padrão" },
];

const SEVERITIES = [
  { value: "low", label: "Tudo (inclusive baixa)" },
  { value: "medium", label: "Média para cima" },
  { value: "high", label: "Só alta e crítica" },
  { value: "critical", label: "Só crítica" },
];

export function Account() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const confirm = useConfirm();
  const navigate = useNavigate();
  const toast = useToast();
  const [prefs, setPrefs] = useState<any>(null);
  const [channels, setChannels] = useState<any>({});
  const [telegramLinked, setTelegramLinked] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    accountApi.preferences().then((r) => {
      setPrefs(r.data.preferences);
      setChannels(r.data.channels_available);
      setTelegramLinked(r.data.telegram_linked);
    }).finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);

  const update = async (changes: Record<string, any>) => {
    try {
      const res = await accountApi.updatePreferences(changes);
      setPrefs(res.data.preferences);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const linkTelegram = async () => {
    try {
      const res = await accountApi.telegramLink();
      if (res.data.deep_link) window.open(res.data.deep_link, "_blank");
      toast.info(`Código: ${res.data.code}`, "Abra o bot no Telegram e envie /start com esse código.");
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const handleLogout = async () => {
    const ok = await confirm({
      title: "Sair da conta?",
      body: "Seus computadores continuam sendo monitorados. Você só precisará entrar de novo para ver o painel.",
      confirmLabel: "Sair da conta",
    });
    if (!ok) return;
    logout();
    navigate("/login");
  };

  return (
    <div className="max-w-2xl space-y-8">
      <PageHeader title="Sua conta" description="Preferências, notificações, aparência e glossário." />

      <Section title="Identificação">
        <Panel className="px-4 py-2">
          <DataList>
            <DataRow label="Usuário" value={user?.username ?? "--"} />
            <DataRow label="E-mail" value={user?.email ?? "--"} />
            {user?.created_at && <DataRow label="Conta criada em" value={format(new Date(user.created_at), "dd/MM/yyyy", { locale: ptBR })} />}
          </DataList>
        </Panel>
      </Section>

      {loading ? (
        <Skeleton className="h-40 w-full rounded-panel" />
      ) : prefs ? (
        <>
          <Section title="Como as explicações são escritas" description="O mesmo aviso, no nível que você preferir">
            <div className="inline-flex overflow-hidden rounded-control border border-edge">
              {(Object.keys(LANGUAGE_LEVEL_LABELS) as LanguageLevel[]).map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => update({ language_level: lvl })}
                  className={`px-3 py-1.5 text-sm transition-colors ${prefs.language_level === lvl ? "bg-raised font-medium text-fg" : "text-fg-3 hover:bg-raised"}`}
                >
                  {LANGUAGE_LEVEL_LABELS[lvl]}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Notificações" description="O painel sempre mostra tudo. Aqui você controla o que é avisado por fora.">
            <div className="space-y-4">
              <label className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-sm text-fg-2">Avisar a partir de qual gravidade</span>
                <select
                  value={prefs.notifications.min_severity}
                  onChange={(e) => update({ notifications: { min_severity: e.target.value } })}
                  className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
                >
                  {SEVERITIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </label>

              <Toggle
                label="Horário silencioso"
                hint={`Segura avisos não-críticos das ${prefs.notifications.quiet_hours.from}h às ${prefs.notifications.quiet_hours.to}h`}
                checked={prefs.notifications.quiet_hours.enabled}
                onChange={(v) => update({ notifications: { quiet_hours: { enabled: v } } })}
              />
              <Toggle
                label="Só avisar se o problema persistir"
                hint="Ignora o que passa sozinho em poucos minutos"
                checked={(prefs.notifications.persist_minutes ?? 0) > 0}
                onChange={(v) => update({ notifications: { persist_minutes: v ? 5 : 0 } })}
              />
              <Toggle
                label="Resumo diário em vez de avisos soltos (baixa prioridade)"
                checked={prefs.notifications.digest.enabled}
                onChange={(v) => update({ notifications: { digest: { enabled: v } } })}
              />

              {channels.telegram && (
                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-hairline pt-4">
                  <div>
                    <p className="text-sm text-fg-2">Telegram {telegramLinked && <span className="text-ok">· conectado</span>}</p>
                    <p className="text-xs text-fg-3">Receba os avisos e responda por botões (encerrar, é normal).</p>
                  </div>
                  {telegramLinked ? (
                    <Button variant="secondary" onClick={() => accountApi.telegramUnlink().then(() => { setTelegramLinked(false); toast.success("Telegram desconectado."); })}>
                      Desconectar
                    </Button>
                  ) : (
                    <Button variant="secondary" onClick={linkTelegram}>Conectar Telegram</Button>
                  )}
                </div>
              )}

              {/* O canal de e-mail vem desligado nas preferências e não tinha
                  controle nesta tela: com o SMTP certo, nenhum e-mail saía. */}
              <div className="space-y-3 border-t border-hairline pt-4">
                {channels.email ? (
                  <>
                    <Toggle
                      label="E-mail"
                      hint={`Envia os avisos para ${prefs.notifications.email || user?.email || "o e-mail da conta"}`}
                      checked={!!prefs.notifications.channels?.email}
                      onChange={(v) => update({ notifications: { channels: { email: v } } })}
                    />
                    {prefs.notifications.channels?.email && (
                      <label className="flex flex-wrap items-center justify-between gap-3">
                        <span className="text-xs text-fg-3">Enviar para outro endereço (vazio = e-mail da conta)</span>
                        <input
                          id="notif-email"
                          type="email"
                          defaultValue={prefs.notifications.email ?? ""}
                          placeholder={user?.email ?? "nome@exemplo.com"}
                          onBlur={(e) => {
                            const value = e.target.value.trim();
                            if (value !== (prefs.notifications.email ?? "")) {
                              update({ notifications: { email: value || null } });
                            }
                          }}
                          className="field h-8 w-64 max-w-full text-sm"
                        />
                      </label>
                    )}
                  </>
                ) : (
                  <div>
                    <p className="text-sm text-fg-2">E-mail · <span className="text-fg-3">não configurado</span></p>
                    <p className="text-xs text-fg-3">
                      Preencha SMTP_HOST, SMTP_USER, SMTP_PASSWORD e SMTP_FROM no .env e rode docker compose up -d backend.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </Section>

          <Section title="Energia" description="Usado para estimar custo e desperdício">
            <label className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-sm text-fg-2">Tarifa de energia (R$ por kWh)</span>
              <input
                type="number"
                step="0.01"
                defaultValue={prefs.energy.tariff_kwh}
                onBlur={(e) => update({ energy: { tariff_kwh: Number(e.target.value) } })}
                className="h-8 w-24 rounded-control border border-edge bg-surface px-2 text-right font-mono text-sm text-fg focus:border-accent"
              />
            </label>
          </Section>

          <Section title="Privacidade">
            <Toggle
              label="Contribuir para a reputação coletiva de programas (anônimo)"
              hint="Ajuda a dizer se um programa é comum ou raro entre computadores — sem identificar você"
              checked={prefs.share_reputation}
              onChange={(v) => update({ share_reputation: v })}
            />
          </Section>
        </>
      ) : null}

      <PushDevices />

      <Playbooks />

      <AuditLedger />

      <Section title="Aparência">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-prose text-sm text-fg-2">O tema escuro é o padrão. O claro costuma ler melhor em ambientes iluminados.</p>
          <Button variant="secondary" onClick={toggle}>Usar tema {theme === "dark" ? "claro" : "escuro"}</Button>
        </div>
      </Section>

      <Section title="O que cada medida significa">
        <DataList className="divide-y divide-hairline">
          {GLOSSARY_ORDER.map(({ term, label }) => (
            <div key={term} className="py-3">
              <dt className="text-sm font-medium text-fg">{label}</dt>
              <dd className="mt-1 max-w-prose text-sm leading-relaxed text-fg-2">{GLOSSARY[term]}</dd>
            </div>
          ))}
        </DataList>
      </Section>

      <Section title="Sessão">
        <Button variant="danger" onClick={handleLogout}>Sair da conta</Button>
      </Section>
    </div>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-3">
      <span className="min-w-0">
        <span className="block text-sm text-fg-2">{label}</span>
        {hint && <span className="block text-xs text-fg-3">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-5 w-9 flex-shrink-0 rounded-full transition-colors ${checked ? "bg-accent" : "bg-sunken"}`}
      >
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-surface transition-transform ${checked ? "left-0.5 translate-x-4" : "left-0.5"}`} />
      </button>
    </label>
  );
}
