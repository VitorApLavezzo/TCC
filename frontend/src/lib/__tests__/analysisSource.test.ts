import { describe, expect, it } from "vitest";
import { analysisSource } from "../analysisSource";

describe("analysisSource", () => {
  it("nomeia quem escreveu e onde os dados foram", () => {
    expect(analysisSource("cloud", "claude-cli/sonnet")).toBe("analisado pelo Claude (nuvem)");
    expect(analysisSource("local", "ollama/qwen2.5:14b")).toBe("analisado pelo Ollama (local)");
  });

  it("segue o provedor do texto exibido, mesmo se o destino gravado for de outra versão", () => {
    expect(analysisSource("local", "claude-cli/sonnet")).toBe("analisado pelo Claude (nuvem)");
    expect(analysisSource("cloud", "análise local")).toBe("análise local (sem IA)");
  });

  it("não inventa nome para a API em nuvem configurável", () => {
    expect(analysisSource("cloud", "cloud/llama-3.3-70b-versatile")).toBe("analisado na nuvem");
  });

  it("usa o destino quando o provedor é desconhecido ou falta", () => {
    expect(analysisSource("local", "outro/modelo")).toBe("analisado localmente");
    expect(analysisSource("cloud")).toBe("analisado na nuvem");
    expect(analysisSource("none")).toBe("análise local (sem IA)");
  });

  it("sem destino, mostra o provedor como veio ou nada", () => {
    expect(analysisSource(undefined, "outro/modelo")).toBe("outro/modelo");
    expect(analysisSource()).toBeNull();
  });
});
