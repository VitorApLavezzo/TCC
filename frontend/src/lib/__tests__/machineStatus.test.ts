import { describe, expect, it } from "vitest";
import { statusByMachine } from "../machineStatus";
import type { Anomaly } from "../../types";

const aviso = (id: number, machine_id: number, severity: string) => ({ id, machine_id, severity }) as Anomaly;

/** O que a lista de computadores mostra em cada linha: quantos avisos e o pior. */
describe("statusByMachine", () => {
  it("conta os avisos de cada computador e guarda o mais grave", () => {
    const st = statusByMachine([aviso(1, 10, "medium"), aviso(2, 10, "critical"), aviso(3, 10, "high"), aviso(4, 20, "low")]);
    expect(st[10].open).toBe(3);
    expect(st[10].worst?.id).toBe(2);
    expect(st[20]).toEqual({ open: 1, worst: aviso(4, 20, "low") });
  });

  it("computador sem aviso não aparece", () => {
    expect(statusByMachine([])[10]).toBeUndefined();
  });
});
