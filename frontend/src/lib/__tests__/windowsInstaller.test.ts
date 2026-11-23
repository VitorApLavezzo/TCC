import { describe, expect, it } from "vitest";
import { windowsInstaller } from "../../utils/installers";

// Caso real (2026-11-23): o winget instalou o Python, mas o instalador do python.org não o põe
// no PATH, e "python" virou o atalho da Microsoft Store. A cada execução o .bat achava que não
// havia Python e pedia para executar de novo.
const bat = () => windowsInstaller("https://exemplo.duckdns.org", { code: "ABCD1234" });

describe("instalador do Windows encontra o Python sem depender do PATH", () => {
  it("não pede para executar o instalador de novo depois de instalar o Python", () => {
    expect(bat()).not.toMatch(/NOVAMENTE/);
  });

  it("não decide pelo 'python --version', que falha com o atalho da Microsoft Store", () => {
    expect(bat()).not.toContain("python --version");
  });

  it("procura o Python 3.12 pelo inicializador e nas pastas onde o instalador o põe", () => {
    const script = bat();
    expect(script).toContain('call :trycmd "py -3.12" "pyw -3.12"');
    expect(script).toContain('call :trydir "%LOCALAPPDATA%\\Programs\\Python\\Python312"');
    expect(script).toContain('call :trydir "%ProgramFiles%\\Python312"');
  });

  it("só aceita um candidato que executa código Python de verdade", () => {
    expect(bat()).toMatch(/-c "import sys; sys\.exit\(0 if \(3, 9\) <= sys\.version_info\[:2\] <= \(3, 13\) else 1\)"/);
  });

  it("procura de novo logo depois do winget, na mesma janela", () => {
    expect(bat()).toMatch(/winget install[^\r\n]*\r\n\s*call :findpy/);
  });

  it("usa o Python encontrado em todos os passos", () => {
    const script = bat();
    expect(script).toContain("%PY% -m pip install");
    expect(script).toContain("%PY% agent.py --enroll-only");
    expect(script).not.toMatch(/^python /m);
  });

  it("o início com o Windows chama o Python sem janela pelo mesmo caminho", () => {
    const script = bat();
    expect(script).toContain('set "PYW_VBS=%PYW:"=""%"');
    expect(script).toContain('echo sh.Run "%PYW_VBS% agent.py", 0, False');
  });
});
