import { describe, expect, it } from "vitest";
import { inQuietHours, outcomeFor, NotificationChoices, SampleAlert } from "../onboarding";

const base: NotificationChoices = {
  min_severity: "medium",
  quiet_hours: { enabled: false, from: 22, to: 7 },
  persist_minutes: 0,
  digest: { enabled: false },
};

const alert = (over: Partial<SampleAlert>): SampleAlert => ({
  hour: 14, minute: 0, severity: "high", title: "Teste", fadesQuickly: false, ...over,
});

describe("inQuietHours (mesma regra de notifications._in_quiet_hours)", () => {
  it("atravessa a meia-noite", () => {
    const quiet = { enabled: true, from: 22, to: 7 };
    expect(inQuietHours(23, quiet)).toBe(true);
    expect(inQuietHours(3, quiet)).toBe(true);
    expect(inQuietHours(7, quiet)).toBe(false);
    expect(inQuietHours(14, quiet)).toBe(false);
  });

  it("0h às 24h é o dia inteiro", () => {
    expect(inQuietHours(15, { enabled: true, from: 0, to: 24 })).toBe(true);
  });

  it("desligado nunca silencia", () => {
    expect(inQuietHours(23, { enabled: false, from: 22, to: 7 })).toBe(false);
  });
});

describe("outcomeFor", () => {
  it("abaixo da gravidade mínima fica só no painel", () => {
    expect(outcomeFor(alert({ severity: "low" }), base)).toEqual({ kind: "panel" });
  });

  it("abaixo da gravidade mínima vai para o resumo quando ele está ligado", () => {
    expect(outcomeFor(alert({ severity: "low" }), { ...base, digest: { enabled: true } })).toEqual({ kind: "digest" });
  });

  it("no horário silencioso o aviso espera o fim do silêncio", () => {
    const prefs = { ...base, quiet_hours: { enabled: true, from: 22, to: 7 } };
    expect(outcomeFor(alert({ hour: 23 }), prefs)).toEqual({ kind: "later", at: 7 });
  });

  it("crítico fura o horário silencioso", () => {
    const prefs = { ...base, quiet_hours: { enabled: true, from: 22, to: 7 } };
    expect(outcomeFor(alert({ hour: 23, severity: "critical" }), prefs)).toEqual({ kind: "now" });
  });

  it("com 'só se persistir', o que passa sozinho não vira aviso", () => {
    const prefs = { ...base, persist_minutes: 5 };
    expect(outcomeFor(alert({ fadesQuickly: true }), prefs)).toEqual({ kind: "settled" });
    expect(outcomeFor(alert({ fadesQuickly: false }), prefs)).toEqual({ kind: "now" });
  });

  it("sem 'só se persistir', o que passa sozinho avisa mesmo assim", () => {
    expect(outcomeFor(alert({ fadesQuickly: true }), base)).toEqual({ kind: "now" });
  });
});
