import { ReactElement, useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { PageHeader, Section, Panel, DataList, DataRow } from "../components/ui/Layout";
import { Button } from "../components/ui/Button";
import { LoadError } from "../components/ui/LoadError";
import { setResearchTools, useResearchTools } from "../lib/researchTools";
import { Skeleton } from "../components/ui/Skeleton";
import { useToast } from "../components/ui/Toast";
import { accountApi, errorMessage } from "../services/api";
import { GLOSSARY } from "../lib/glossary";
import { LANGUAGE_LEVEL_LABELS, LanguageLevel } from "../types";
import { applyDisplay, getDisplay } from "../lib/display";
import { setLocale, useLocale } from "../lib/i18n";
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

const TABS = [
  { id: "perfil", label: "Perfil" },
  { id: "notificacoes", label: "Notificações" },
  { id: "privacidade", label: "Privacidade" },
  { id: "automacao", label: "Automação" },
  { id: "ajuda", label: "Ajuda" },
];

/** Endereços com os nomes antigos das abas continuam abrindo a certa. */
const LEGACY_TABS: Record<string, string> = { avisos: "notificacoes", avancado: "automacao" };

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
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setLoadFailed(false);
    accountApi
      .preferences()
      .then((r) => {
        setPrefs(r.data.preferences);
        setChannels(r.data.channels_available);
        setTelegramLinked(r.data.telegram_linked);
      })
      // Sem isto as abas que dependem das preferências ficam em branco.
      .catch(() => setLoadFailed(true))
      .finally(() => setLoading(false));
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

  const [params, setParams] = useSearchParams();
  const requested = params.get("aba") || "perfil";
  const tab = LEGACY_TABS[requested] ?? requested;

  // Recebe uma função: a aba lê prefs.*, e montá-la antes de as preferências chegarem quebrava a tela
  const guarded = (render: () => ReactElement) =>
    loading ? (
      <Skeleton className="h-40 w-full rounded-panel" />
    ) : prefs ? (
      render()
    ) : loadFailed ? (
      <LoadError what="suas preferências" onRetry={load} />
    ) : null;

  return (
    <div className="max-w-2xl space-y-8">
      <PageHeader title="Sua conta" description="Tudo o que é seu: identificação, notificações, privacidade e o que o sistema pode fazer sozinho." />

      <div role="tablist" aria-label="Seções da conta" className="flex flex-wrap gap-1 border-b border-hairline">
        {TABS.map((a) => (
          <button
            key={a.id}
            type="button"
            role="tab"
            aria-selected={tab === a.id}
            onClick={() => setParams({ aba: a.id }, { replace: true })}
            className={`relative px-3 py-2 text-sm transition-colors ${
              tab === a.id ? "font-medium text-fg" : "text-fg-3 hover:text-fg-2"
            }`}
          >
            {a.label}
            {tab === a.id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      {tab === "perfil" && (
        <div className="space-y-8">
      <Section title="Identificação">
        <Panel className="px-4 py-2">
          <DataList>
            <DataRow label="Usuário" value={user?.username ?? "--"} />
            <DataRow label="E-mail" value={user?.email ?? "--"} />
            {user?.created_at && <DataRow label="Conta criada em" value={format(new Date(user.created_at), "dd/MM/yyyy", { locale: ptBR })} />}
          </DataList>
        </Panel>
      </Section>
          <Appearance theme={theme} onToggleTheme={toggle} />
          <ResearchToolsSection />

          <Section title="Sessão">
            <Button variant="danger" onClick={handleLogout}>Sair da conta</Button>
          </Section>
        </div>
      )}

      {tab === "notificacoes" && (
        <div className="space-y-8">
          {guarded(() => (
            <div className="space-y-8">
          <Section title="Como as explicações são escritas" description="O mesmo aviso, no nível que você preferir">
            <div className="inline-flex overflow-hidden rounded-control border border-edge">
              {(Object.keys(LANGUAGE_LEVEL_LABELS) as LanguageLevel[]).map((lvl) => (
                <button
                  key={lvl}
                  type="button"
                  onClick={() => update({ language_level: lvl })}
                  aria-pressed={prefs.language_level === lvl}
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
                    <Button
                      variant="secondary"
                      onClick={() =>
                        accountApi
                          .telegramUnlink()
                          .then(() => {
                            setTelegramLinked(false);
                            toast.success("Telegram desconectado.");
                          })
                          .catch((err) => toast.error(errorMessage(err, "Não foi possível desconectar o Telegram.")))
                      }
                    >
                      Desconectar
                    </Button>
                  ) : (
                    <Button variant="secondary" onClick={linkTelegram}>Conectar Telegram</Button>
                  )}
                </div>
              )}

              {/* O canal de e-mail vem desligado por padrão nas preferências. */}
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
                    <p className="max-w-prose text-xs leading-relaxed text-fg-3">
                      O envio de e-mail ainda não foi ligado neste servidor. Quem administra o sistema liga isso
                      preenchendo os dados de SMTP no arquivo <code className="font-mono">.env</code>.
                    </p>
                  </div>
                )}
              </div>
            </div>
          </Section>
            </div>
          ))}
          <PushDevices />
        </div>
      )}

      {tab === "privacidade" && (
        <div className="space-y-8">
          {guarded(() => (
            <div className="space-y-8">
          <Section title="Privacidade">
            <Toggle
              label="Contribuir para a reputação coletiva de programas (anônimo)"
              hint="Ajuda a dizer se um programa é comum ou raro entre computadores — sem identificar você"
              checked={prefs.share_reputation}
              onChange={(v) => update({ share_reputation: v })}
            />
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
            </div>
          ))}
        </div>
      )}

      {tab === "automacao" && (
        <div className="space-y-8">
          <Playbooks />
          <AuditLedger />
        </div>
      )}

      {tab === "ajuda" && (
        <div className="space-y-8">
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
          <Section title="Atalhos de teclado" description="Pressione ? em qualquer tela para ver esta lista">
            <p className="max-w-prose text-sm leading-relaxed text-fg-2">
              <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-micro">Ctrl K</kbd> abre a busca
              de computadores, avisos e telas. <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-micro">g</kbd>{" "}
              seguido de <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-micro">p</kbd>,{" "}
              <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-micro">c</kbd>,{" "}
              <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-micro">a</kbd> ou{" "}
              <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-micro">q</kbd> leva direto a uma
              seção.
            </p>
          </Section>
        </div>
      )}
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

/** Liga as telas do TCC no menu. Escondidas por padrão: não são do dia a dia. */
function ResearchToolsSection() {
  const enabled = useResearchTools();
  return (
    <Section title="Ferramentas do TCC" description="Pesquisa, Demonstração e Estudo de compreensão">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-prose text-sm text-fg-2">
          Telas usadas no trabalho de conclusão de curso, não no acompanhamento do dia a dia. Mesmo escondidas do
          menu, a busca (Ctrl K) chega nelas.
        </p>
        <Button variant="secondary" aria-pressed={enabled} onClick={() => setResearchTools(!enabled)}>
          {enabled ? "Esconder do menu" : "Mostrar no menu"}
        </Button>
      </div>
    </Section>
  );
}

function Appearance({ theme, onToggleTheme }: { theme: string; onToggleTheme: () => void }) {
  const [display, setDisplay] = useState(getDisplay());
  const locale = useLocale();

  const change = (patch: Parameters<typeof applyDisplay>[0]) => {
    applyDisplay(patch);
    setDisplay(getDisplay());
  };

  const groupClass = "inline-flex overflow-hidden rounded-control border border-edge";
  const buttonClass = (active: boolean) =>
    `px-3 py-1.5 text-sm transition-colors ${active ? "bg-raised font-medium text-fg" : "text-fg-3 hover:bg-raised"}`;

  return (
    <Section title="Aparência e leitura" description="Vale para este aparelho, e fica guardado nele">
      <div className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-prose text-sm text-fg-2">
            O tema escuro é o padrão. O claro costuma ler melhor em ambientes iluminados.
          </p>
          <Button variant="secondary" onClick={onToggleTheme}>
            Usar tema {theme === "dark" ? "claro" : "escuro"}
          </Button>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-fg-2">Tamanho da letra</span>
          <div className={groupClass}>
            {([["normal", "Normal"], ["grande", "Grande"], ["maior", "Maior"]] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => change({ scale: value })}
                aria-pressed={display.scale === value}
                className={buttonClass(display.scale === value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-fg-2">Espaçamento</span>
          <div className={groupClass}>
            {([["compacta", "Compacto"], ["confortavel", "Confortável"]] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => change({ density: value })}
                aria-pressed={display.density === value}
                className={buttonClass(display.density === value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-fg-2">Idioma da interface</span>
          <div className={groupClass}>
            {([["pt-BR", "Português"], ["en", "English (parcial)"]] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setLocale(value)}
                aria-pressed={locale === value}
                className={buttonClass(locale === value)}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs leading-relaxed text-fg-3">
          A tradução para o inglês cobre a navegação e as telas de entrada; o resto aparece em português
          enquanto as demais telas não são migradas.
        </p>
      </div>
    </Section>
  );
}
