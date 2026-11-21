import { ReactNode, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { CheckCircle2 } from "lucide-react";
import { accountApi, errorMessage } from "../../services/api";
import { useTheme } from "../../context/ThemeContext";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { Button, TextButton } from "../ui/Button";
import { Severity as SeverityChip } from "../ui/Badge";
import { SignalMark } from "../ui/SignalMark";
import { useToast } from "../ui/Toast";
import { LANGUAGE_LEVEL_LABELS, LanguageLevel } from "../../types";
import { LEVEL_SAMPLES, NotificationChoices, Outcome, outcomeFor, SAMPLE_DAY, Severity } from "../../lib/onboarding";

export interface OnboardingData {
  preferences: any;
  channels: { telegram?: boolean; email?: boolean };
  telegramLinked: boolean;
}

const LEVEL_HINTS: Record<LanguageLevel, string> = {
  leigo: "Sem termos técnicos, dizendo onde clicar.",
  intermediario: "Com os números e os nomes certos, explicados.",
  tecnico: "Direto ao ponto, com métricas e jargão.",
};

const SEVERITY_CHOICES: { value: Severity; label: string; hint: string }[] = [
  { value: "low", label: "Tudo, até o que é pequeno", hint: "Para quem gosta de acompanhar de perto." },
  { value: "medium", label: "Da gravidade média para cima", hint: "O recomendado: avisa o que pede atenção." },
  { value: "high", label: "Só o que é sério", hint: "Gravidade alta e crítica." },
  { value: "critical", label: "Só emergências", hint: "Apenas gravidade crítica." },
];

const HOURS = Array.from({ length: 24 }, (_, h) => h);

const STEPS = ["Explicações", "Quando avisar", "Por onde avisar", "Últimos detalhes"];

export function OnboardingWizard({
  data,
  firstRun,
  onFinish,
}: {
  data: OnboardingData;
  /** Conta nova: termina na tela de conectar o computador. Reaberta pela conta: só fecha. */
  firstRun: boolean;
  onFinish: () => void;
}) {
  const toast = useToast();
  const { theme, toggle } = useTheme();
  const [prefs, setPrefs] = useState<any>(data.preferences);
  const [step, setStep] = useState(0);
  const [done, setDone] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Esc não fecha: sair sem querer pularia a configuração inteira.
  useDialogFocus(true, dialogRef, () => {}, headingRef);
  useEffect(() => headingRef.current?.focus(), [step, done]);

  const update = async (changes: Record<string, any>) => {
    try {
      const res = await accountApi.updatePreferences(changes);
      setPrefs(res.data.preferences);
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível salvar essa escolha."));
    }
  };
  const updateNotifications = (changes: Record<string, any>) => update({ notifications: changes });

  const finish = async () => {
    setFinishing(true);
    try {
      await accountApi.updatePreferences({ onboarding_done: true });
      onFinish();
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível concluir. Tente de novo."));
      setFinishing(false);
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

  const notif: NotificationChoices = prefs.notifications;
  const level: LanguageLevel = prefs.language_level;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
      className="fixed inset-0 z-50 overflow-y-auto overscroll-contain bg-canvas"
    >
      <div className="mx-auto flex min-h-full w-full max-w-5xl flex-col px-4 py-6 sm:px-8 sm:py-8">
        <header className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-2.5">
            <SignalMark />
            <span className="text-sm font-semibold tracking-tight text-fg">Configurar sua conta</span>
          </span>
          {!done && (
            <TextButton onClick={finish} disabled={finishing}>
              {firstRun ? "Pular e usar o padrão" : "Fechar"}
            </TextButton>
          )}
        </header>

        {!done && <Progress step={step} />}

        <main className="flex-1 py-8">
          {done ? (
            <Finished
              headingRef={headingRef}
              summary={<Summary prefs={prefs} data={data} theme={theme} />}
            />
          ) : (
            <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-12">
              <section className="min-w-0">
                {step === 0 && (
                  <>
                    <StepHeading headingRef={headingRef} title="Como você quer ler as explicações?">
                      Quando algo sair do normal, o AnomalyDetect explica o que houve e o que fazer. Escolha o jeito
                      que for mais confortável. A prévia mostra o mesmo aviso no nível escolhido.
                    </StepHeading>
                    <ChoiceGroup label="Nível das explicações">
                      {(Object.keys(LANGUAGE_LEVEL_LABELS) as LanguageLevel[]).map((lvl) => (
                        <Choice
                          key={lvl}
                          selected={level === lvl}
                          onSelect={() => update({ language_level: lvl })}
                          title={LANGUAGE_LEVEL_LABELS[lvl]}
                          hint={LEVEL_HINTS[lvl]}
                        />
                      ))}
                    </ChoiceGroup>
                  </>
                )}

                {step === 1 && (
                  <>
                    <StepHeading headingRef={headingRef} title="Quando devemos te avisar?">
                      O painel sempre mostra tudo. Aqui você escolhe o que merece um aviso fora dele. O dia de exemplo
                      mostra o efeito de cada escolha.
                    </StepHeading>
                    <ChoiceGroup label="Gravidade mínima para avisar">
                      {SEVERITY_CHOICES.map((c) => (
                        <Choice
                          key={c.value}
                          selected={notif.min_severity === c.value}
                          onSelect={() => updateNotifications({ min_severity: c.value })}
                          title={c.label}
                          hint={c.hint}
                        />
                      ))}
                    </ChoiceGroup>
                    <div className="mt-6 space-y-4 border-t border-hairline pt-5">
                      <Switch
                        label="Só avisar se o problema continuar"
                        hint="Espera 5 minutos e ignora o que passa sozinho, como um pico rápido."
                        checked={notif.persist_minutes > 0}
                        onChange={(v) => updateNotifications({ persist_minutes: v ? 5 : 0 })}
                      />
                      <Switch
                        label="Horário silencioso"
                        hint="Segura os avisos até o fim do horário. Os críticos chegam mesmo assim."
                        checked={notif.quiet_hours.enabled}
                        onChange={(v) => updateNotifications({ quiet_hours: { enabled: v } })}
                      />
                      {notif.quiet_hours.enabled && (
                        <div className="flex flex-wrap items-center gap-2 pl-0.5 text-sm text-fg-2">
                          <span>Das</span>
                          <HourSelect
                            label="Início do horário silencioso"
                            value={notif.quiet_hours.from}
                            onChange={(h) => updateNotifications({ quiet_hours: { from: h } })}
                          />
                          <span>às</span>
                          <HourSelect
                            label="Fim do horário silencioso"
                            value={notif.quiet_hours.to}
                            onChange={(h) => updateNotifications({ quiet_hours: { to: h } })}
                          />
                        </div>
                      )}
                    </div>
                  </>
                )}

                {step === 2 && (
                  <>
                    <StepHeading headingRef={headingRef} title="Por onde os avisos chegam?">
                      Escolha onde quer ser encontrado. Dá para mudar tudo isso depois em Sua conta.
                    </StepHeading>
                    <div className="space-y-5">
                      {data.channels.telegram && (
                        <ChannelRow
                          title="Telegram"
                          hint="Recebe os avisos e responde por botões, como encerrar um programa."
                          status={data.telegramLinked ? "conectado" : undefined}
                        >
                          {!data.telegramLinked && (
                            <Button variant="secondary" size="sm" onClick={linkTelegram}>
                              Conectar Telegram
                            </Button>
                          )}
                        </ChannelRow>
                      )}
                      {data.channels.email && (
                        <Switch
                          label="E-mail"
                          hint="Envia os avisos para o e-mail da sua conta."
                          checked={!!notif.channels?.email}
                          onChange={(v) => updateNotifications({ channels: { email: v } })}
                        />
                      )}
                      <Switch
                        label="Resumo diário"
                        hint={`Junta os avisos abaixo da gravidade escolhida numa mensagem só, às ${notif.digest.hour ?? 8}h.`}
                        checked={notif.digest.enabled}
                        onChange={(v) => updateNotifications({ digest: { enabled: v } })}
                      />
                      <p className="max-w-prose border-t border-hairline pt-4 text-xs leading-relaxed text-fg-3">
                        Avisos no celular ou neste navegador se ligam em Sua conta, na aba Notificações, depois que
                        você terminar aqui.
                      </p>
                    </div>
                  </>
                )}

                {step === 3 && (
                  <>
                    <StepHeading headingRef={headingRef} title="Últimos detalhes">
                      Três ajustes rápidos. Se não souber, pode deixar como está.
                    </StepHeading>
                    <div className="space-y-5">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <span className="text-sm text-fg-2">Aparência</span>
                        <div className="inline-flex overflow-hidden rounded-control border border-edge">
                          {(["light", "dark"] as const).map((t) => (
                            <button
                              key={t}
                              type="button"
                              aria-pressed={theme === t}
                              onClick={() => theme !== t && toggle()}
                              className={clsx(
                                "px-3 py-1.5 text-sm transition-colors",
                                theme === t ? "bg-raised font-medium text-fg" : "text-fg-3 hover:bg-raised"
                              )}
                            >
                              {t === "light" ? "Claro" : "Escuro"}
                            </button>
                          ))}
                        </div>
                      </div>
                      <Switch
                        label="Ajudar a identificar programas desconhecidos"
                        hint="Conta, sem identificar você, quais programas aparecem nos seus computadores. Assim todos sabem se um programa é comum ou raro."
                        checked={prefs.share_reputation}
                        onChange={(v) => update({ share_reputation: v })}
                      />
                      <label className="flex flex-wrap items-center justify-between gap-3">
                        <span className="min-w-0">
                          <span className="block text-sm text-fg-2">Preço da energia (R$ por kWh)</span>
                          <span className="block text-xs text-fg-3">Está na sua conta de luz. Serve para estimar o gasto de cada computador.</span>
                        </span>
                        <input
                          type="number"
                          step="0.01"
                          min="0"
                          defaultValue={prefs.energy.tariff_kwh}
                          onBlur={(e) => {
                            const value = Number(e.target.value);
                            if (value > 0 && value !== prefs.energy.tariff_kwh) update({ energy: { tariff_kwh: value } });
                          }}
                          className="h-8 w-24 rounded-control border border-edge bg-surface px-2 text-right font-mono text-sm text-fg focus:border-accent"
                        />
                      </label>
                    </div>
                  </>
                )}
              </section>

              <aside aria-label="Prévia" className="min-w-0">
                {step === 0 && <LevelPreview level={level} />}
                {(step === 1 || step === 2) && <DayPreview prefs={notif} />}
                {step === 3 && <Summary prefs={prefs} data={data} theme={theme} />}
              </aside>
            </div>
          )}
        </main>

        <footer className="flex items-center justify-between gap-3 border-t border-hairline pt-5">
          {done ? (
            <>
              <span />
              <Button variant="primary" loading={finishing} loadingLabel="Salvando..." onClick={finish}>
                Conectar meu primeiro computador
              </Button>
            </>
          ) : (
            <>
              <Button variant="secondary" onClick={() => setStep((s) => s - 1)} disabled={step === 0}>
                Voltar
              </Button>
              <Button
                variant="primary"
                loading={finishing}
                onClick={() => (step < STEPS.length - 1 ? setStep((s) => s + 1) : firstRun ? setDone(true) : finish())}
              >
                {step < STEPS.length - 1 ? "Continuar" : "Concluir"}
              </Button>
            </>
          )}
        </footer>
      </div>
    </div>
  );
}

function Progress({ step }: { step: number }) {
  return (
    <div className="mt-6">
      <p className="text-xs text-fg-3">
        Passo {step + 1} de {STEPS.length}: <span className="text-fg-2">{STEPS[step]}</span>
      </p>
      <ol className="mt-2 grid grid-cols-4 gap-1.5" aria-hidden="true">
        {STEPS.map((name, i) => (
          <li
            key={name}
            className={clsx(
              "h-1.5 rounded-full motion-safe:transition-colors motion-safe:duration-300",
              i <= step ? "bg-accent" : "bg-sunken"
            )}
          />
        ))}
      </ol>
    </div>
  );
}

function StepHeading({
  headingRef,
  title,
  children,
}: {
  headingRef: React.RefObject<HTMLHeadingElement>;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-6">
      <h1
        id="onboarding-title"
        ref={headingRef}
        tabIndex={-1}
        className="font-display text-2xl font-semibold tracking-tight text-fg outline-none"
      >
        {title}
      </h1>
      <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">{children}</p>
    </div>
  );
}

function ChoiceGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div role="radiogroup" aria-label={label} className="space-y-2">
      {children}
    </div>
  );
}

function Choice({ selected, onSelect, title, hint }: { selected: boolean; onSelect: () => void; title: string; hint: string }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={clsx(
        "flex w-full items-start gap-3 rounded-control border px-4 py-3 text-left transition-colors",
        selected ? "border-accent bg-accent/[.08]" : "border-edge hover:bg-raised"
      )}
    >
      <span
        aria-hidden="true"
        className={clsx(
          "mt-0.5 flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border",
          selected ? "border-accent" : "border-edge"
        )}
      >
        {selected && <span className="h-2 w-2 rounded-full bg-accent" />}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-medium text-fg">{title}</span>
        <span className="block text-xs text-fg-3">{hint}</span>
      </span>
    </button>
  );
}

function Switch({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-3">
      <span className="min-w-0">
        <span className="block text-sm text-fg-2">{label}</span>
        {hint && <span className="block max-w-prose text-xs text-fg-3">{hint}</span>}
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

function HourSelect({ label, value, onChange }: { label: string; value: number; onChange: (h: number) => void }) {
  return (
    <select
      aria-label={label}
      value={value % 24}
      onChange={(e) => onChange(Number(e.target.value))}
      className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
    >
      {HOURS.map((h) => (
        <option key={h} value={h}>
          {h}h
        </option>
      ))}
    </select>
  );
}

function ChannelRow({ title, hint, status, children }: { title: string; hint: string; status?: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <span className="min-w-0">
        <span className="block text-sm text-fg-2">
          {title} {status && <span className="text-ok">· {status}</span>}
        </span>
        <span className="block max-w-prose text-xs text-fg-3">{hint}</span>
      </span>
      {children}
    </div>
  );
}

function PreviewFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-panel border border-edge bg-surface p-5">
      <p className="text-xs font-medium text-fg-3">{title}</p>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function LevelPreview({ level }: { level: LanguageLevel }) {
  const sample = LEVEL_SAMPLES[level];
  return (
    <PreviewFrame title="Assim chega um aviso para você">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-base font-semibold text-fg">Memória subindo sem parar</span>
        <SeverityChip severity="medium" />
      </div>
      <p className="mt-1 text-xs text-fg-3">Notebook da sala, há 2 minutos</p>
      <h3 className="mt-4 text-sm font-medium text-fg">O que aconteceu</h3>
      <p className="mt-1 text-sm leading-relaxed text-fg-2">{sample.what}</p>
      <h3 className="mt-4 text-sm font-medium text-fg">O que fazer agora</h3>
      <p className="mt-1 text-sm leading-relaxed text-fg-2">{sample.todo}</p>
    </PreviewFrame>
  );
}

const OUTCOME_STYLE: Record<Outcome["kind"], { dot: string; text: string }> = {
  now: { dot: "bg-accent", text: "text-fg" },
  later: { dot: "bg-warn", text: "text-warn" },
  digest: { dot: "border border-fg-3 bg-transparent", text: "text-fg-3" },
  panel: { dot: "border border-edge bg-transparent", text: "text-fg-3" },
  settled: { dot: "border border-edge bg-transparent", text: "text-fg-3" },
};

function outcomeText(outcome: Outcome, digestHour: number): string {
  switch (outcome.kind) {
    case "now":
      return "Avisa na hora";
    case "later":
      return `Avisa às ${outcome.at}h`;
    case "digest":
      return `Vai no resumo das ${digestHour}h`;
    case "panel":
      return "Fica só no painel";
    case "settled":
      return "Passou sozinho, sem aviso";
  }
}

/** Dia de exemplo: cada aviso mostra o que aconteceria com as escolhas atuais. */
function DayPreview({ prefs }: { prefs: NotificationChoices }) {
  const rows = SAMPLE_DAY.map((alert) => ({ alert, outcome: outcomeFor(alert, prefs) }));
  const delivered = rows.filter((r) => r.outcome.kind === "now" || r.outcome.kind === "later").length;
  const quiet = prefs.quiet_hours;
  const bands: [number, number][] = !quiet.enabled
    ? []
    : quiet.from === 0 && quiet.to >= 24
      ? [[0, 24]]
      : quiet.from < quiet.to
        ? [[quiet.from, quiet.to]]
        : [[quiet.from, 24], [0, quiet.to % 24]];

  return (
    <PreviewFrame title="Um dia de exemplo">
      <p className="text-sm text-fg" aria-live="polite">
        Num dia como este, você receberia{" "}
        <span className="font-semibold">
          {delivered} {delivered === 1 ? "aviso" : "avisos"}
        </span>{" "}
        de {SAMPLE_DAY.length}.
      </p>

      <div className="relative mt-5 h-8" aria-hidden="true">
        <div className="absolute inset-x-0 top-1/2 h-px bg-edge" />
        {bands.map(([from, to]) => (
          <div
            key={from}
            className="absolute inset-y-0 rounded-sm bg-sunken"
            style={{ left: `${(from / 24) * 100}%`, width: `${((to - from) / 24) * 100}%` }}
          />
        ))}
        {rows.map(({ alert, outcome }) => (
          <span
            key={alert.title}
            className={clsx(
              "absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full motion-safe:transition-colors",
              OUTCOME_STYLE[outcome.kind].dot
            )}
            style={{ left: `${((alert.hour + alert.minute / 60) / 24) * 100}%` }}
          />
        ))}
      </div>
      <div className="mt-1 flex justify-between font-mono text-micro text-fg-3" aria-hidden="true">
        <span>0h</span>
        <span>6h</span>
        <span>12h</span>
        <span>18h</span>
        <span>24h</span>
      </div>
      {bands.length > 0 && <p className="mt-1 text-xs text-fg-3">Faixa cinza: horário silencioso.</p>}

      <ul className="mt-4 divide-y divide-hairline">
        {rows.map(({ alert, outcome }) => (
          <li key={alert.title} className="flex items-center gap-3 py-2">
            <span className="tnum w-11 flex-shrink-0 font-mono text-xs text-fg-3">
              {String(alert.hour).padStart(2, "0")}:{String(alert.minute).padStart(2, "0")}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm leading-snug text-fg-2">{alert.title}</span>
              <span className="text-micro text-fg-3">Gravidade {severityWord(alert.severity)}</span>
            </span>
            <span className={clsx("flex-shrink-0 text-right text-xs", OUTCOME_STYLE[outcome.kind].text)}>
              {outcomeText(outcome, prefs.digest.hour ?? 8)}
            </span>
          </li>
        ))}
      </ul>
    </PreviewFrame>
  );
}

function severityWord(severity: Severity): string {
  return { low: "baixa", medium: "média", high: "alta", critical: "crítica" }[severity];
}

function Summary({ prefs, data, theme }: { prefs: any; data: OnboardingData; theme: string }) {
  const notif = prefs.notifications;
  const severity = SEVERITY_CHOICES.find((c) => c.value === notif.min_severity)?.label ?? notif.min_severity;
  const where = [
    "painel",
    data.telegramLinked && "Telegram",
    data.channels.email && notif.channels?.email && "e-mail",
    notif.digest.enabled && "resumo diário",
  ].filter(Boolean);
  const items: [string, string][] = [
    ["Explicações", LANGUAGE_LEVEL_LABELS[prefs.language_level as LanguageLevel]],
    ["Avisar", severity],
    ["Só se continuar", notif.persist_minutes > 0 ? "Sim" : "Não"],
    ["Horário silencioso", notif.quiet_hours.enabled ? `Das ${notif.quiet_hours.from}h às ${notif.quiet_hours.to}h` : "Desligado"],
    ["Por onde", where.join(", ")],
    ["Aparência", theme === "dark" ? "Escuro" : "Claro"],
  ];
  return (
    <PreviewFrame title="Sua configuração">
      <dl className="divide-y divide-hairline">
        {items.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-4 py-2">
            <dt className="text-sm text-fg-3">{label}</dt>
            <dd className="text-right text-sm text-fg">{value}</dd>
          </div>
        ))}
      </dl>
    </PreviewFrame>
  );
}

function Finished({ headingRef, summary }: { headingRef: React.RefObject<HTMLHeadingElement>; summary: ReactNode }) {
  return (
    <div className="mx-auto max-w-xl">
      <CheckCircle2 size={40} className="text-ok" aria-hidden="true" />
      <h1
        id="onboarding-title"
        ref={headingRef}
        tabIndex={-1}
        className="mt-4 font-display text-2xl font-semibold tracking-tight text-fg outline-none"
      >
        Sua conta está pronta
      </h1>
      <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">
        Falta só uma coisa: conectar o primeiro computador. Leva cerca de dois minutos. Tudo o que você escolheu aqui
        pode ser mudado depois em Sua conta.
      </p>
      <div className="mt-6">{summary}</div>
    </div>
  );
}
