import { describe, expect, it } from "vitest";
import { pageTitle } from "../title";

/**
 * O título da aba diz em que tela a pessoa está. Era "AnomalyDetect" em todas:
 * com três abas abertas, não dava para saber qual era qual, e o leitor de
 * tela não anunciava a troca de página.
 */
describe("pageTitle", () => {
  it("nomeia cada tela principal", () => {
    expect(pageTitle("/")).toBe("Painel · AnomalyDetect");
    expect(pageTitle("/machines")).toBe("Computadores · AnomalyDetect");
    expect(pageTitle("/anomalies")).toBe("Avisos · AnomalyDetect");
  });

  it("usa o nome do item quando a página informa", () => {
    expect(pageTitle("/machines/3", "PC da sala")).toBe("PC da sala · AnomalyDetect");
  });

  it("tem um nome genérico para os detalhes antes de carregar", () => {
    expect(pageTitle("/anomalies/12")).toBe("Aviso · AnomalyDetect");
  });

  it("endereço desconhecido ainda tem título", () => {
    expect(pageTitle("/qualquer-coisa")).toBe("AnomalyDetect");
  });
});
