import { describe, expect, it } from "vitest";
import { bytesPerSec, decimal, formatUptime, gigabytes, pluralize, processName, timeAgo } from "../format";
import { health, worstLevel } from "../health";

/**
 * As funções que decidem o que a pessoa lê na tela.
 *
 * São poucas e puras, e é justamente por isso que erram em silêncio: um
 * plural errado ou um "?" mostrado como nome de programa não quebra build
 * nenhum — só aparece na frente da banca.
 */
describe("format", () => {
  it("mostra tempo ligado em unidade útil", () => {
    expect(formatUptime(0)).toBe("--");
    expect(formatUptime(90)).toBe("1m");
    expect(formatUptime(3 * 3600 + 25 * 60)).toBe("3h 25m");
    expect(formatUptime(2 * 86400 + 5 * 3600)).toBe("2d 5h");
  });

  it("encurta o tempo decorrido sem quebrar a linha", () => {
    const agora = new Date("2026-01-10T12:00:00Z").getTime();
    expect(timeAgo("2026-01-10T11:59:57Z", agora)).toBe("agora");
    expect(timeAgo("2026-01-10T11:59:30Z", agora)).toBe("há 30s");
    expect(timeAgo("2026-01-10T11:30:00Z", agora)).toBe("há 30min");
    expect(timeAgo("2026-01-10T09:00:00Z", agora)).toBe("há 3h");
    expect(timeAgo(null, agora)).toBeNull();
  });

  it("concorda o plural", () => {
    expect(pluralize(1, "máquina")).toBe("1 máquina");
    expect(pluralize(2, "máquina")).toBe("2 máquinas");
    expect(pluralize(0, "aviso")).toBe("0 avisos");
  });

  it("não mostra '?' como se fosse nome de programa", () => {
    // Agentes antigos gravavam "?" quando não conseguiam identificar
    expect(processName({ responsible_process: "?" })).toBeNull();
    expect(processName({ responsible_process: "  " })).toBeNull();
    expect(processName({ responsible_process: " chrome.exe " })).toBe("chrome.exe");
    expect(processName(null)).toBeNull();
  });
});

describe("health", () => {
  it("classifica pelos limites declarados", () => {
    expect(health.cpu(10).level).toBe("ok");
    expect(health.cpu(85).level).toBe("warn");
    expect(health.cpu(95).level).toBe("crit");
    // Medida ausente não é "tudo bem": é desconhecida
    expect(health.cpu(null).level).toBe("unknown");
  });

  it("o veredito da máquina é o pior sinal, não a média", () => {
    expect(worstLevel(["ok", "warn", "crit"])).toBe("crit");
    expect(worstLevel(["ok", "warn"])).toBe("warn");
    expect(worstLevel(["unknown", "ok"])).toBe("ok");
    expect(worstLevel([])).toBe("unknown");
  });
});

/**
 * Número em português usa vírgula. O painel misturava "12.4 GB" e "R$ 12.34"
 * com "96,5%" — o ponto decimal é convenção do inglês.
 */
describe("decimal", () => {
  it("usa vírgula e a quantidade de casas pedida", () => {
    expect(decimal(12.345, 1)).toBe("12,3");
    expect(decimal(8, 2)).toBe("8,00");
    expect(decimal(1234.5, 1)).toBe("1234,5");
  });

  it("vale também para tamanhos e velocidades", () => {
    expect(gigabytes(12.4 * 1024 ** 3)).toBe("12,4 GB");
    expect(bytesPerSec(2.5 * 1024)).toBe("2,5 KB/s");
  });
});
