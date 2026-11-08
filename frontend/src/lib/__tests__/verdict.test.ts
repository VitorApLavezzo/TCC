import { describe, expect, it } from "vitest";
import { verdictTone } from "../verdict";

const anomaly = (severity: string) => ({ severity });

/** O selo do veredito é o pior entre o que foi medido e o que foi avisado. */
describe("verdictTone", () => {
  it("não rebaixa uma leitura crítica por causa de um aviso menos grave", () => {
    expect(verdictTone("crit", [anomaly("high")])).toBe("crit");
  });

  it("aviso em aberto eleva uma leitura normal para atenção", () => {
    expect(verdictTone("ok", [anomaly("medium")])).toBe("warn");
  });

  it("aviso crítico é crítico mesmo com as leituras normais", () => {
    expect(verdictTone("ok", [anomaly("critical")])).toBe("crit");
  });

  it("sem leitura e sem aviso, não inventa estado", () => {
    expect(verdictTone("unknown", [])).toBe("unknown");
  });

  it("sem aviso, vale a leitura", () => {
    expect(verdictTone("warn", [])).toBe("warn");
  });
});
