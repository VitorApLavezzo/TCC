import { useState, useCallback } from "react";
import { machinesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { Machine } from "../types";
import { Card } from "../components/ui/Card";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Monitor, Plus, Copy, CheckCheck, Trash2, Circle, X, Download, Terminal, Pause, Play } from "lucide-react";
import { downloadInstaller, downloadUninstaller, serverOneLiner, isLocalOrigin } from "../utils/installers";

interface EnrollCode {
  code: string;
  expires_at: string;
}

export function Machines() {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [enrollCode, setEnrollCode] = useState<EnrollCode | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [copiedCode, setCopiedCode] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState(false);
  const [loading, setLoading] = useState(false);

  const fetchMachines = useCallback(async () => {
    const res = await machinesApi.list();
    setMachines(res.data);
  }, []);

  usePolling(fetchMachines, 15000);

  const handleNewMachine = async () => {
    setLoading(true);
    try {
      const res = await machinesApi.createEnrollCode();
      setEnrollCode(res.data);
    } finally {
      setLoading(false);
    }
  };

  const copyCode = async () => {
    if (!enrollCode) return;
    await navigator.clipboard.writeText(enrollCode.code);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const copyCmd = async () => {
    if (!enrollCode) return;
    await navigator.clipboard.writeText(serverOneLiner({ code: enrollCode.code }));
    setCopiedCmd(true);
    setTimeout(() => setCopiedCmd(false), 2000);
  };

  const copyToken = async (machine: Machine) => {
    await navigator.clipboard.writeText(machine.agent_token);
    setCopiedId(machine.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Remover esta máquina e todos os seus dados (métricas, anomalias)?")) return;
    try {
      await machinesApi.delete(id);
      await fetchMachines();
    } catch (e) {
      alert("Erro ao remover a máquina. Tente novamente.");
    }
  };

  const handleTogglePause = async (m: Machine) => {
    try {
      await machinesApi.update(m.id, { is_active: !m.is_active });
      await fetchMachines();
    } catch (e) {
      alert("Erro ao alterar o estado da coleta.");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Máquinas</h1>
          <p className="text-gray-400 text-sm mt-0.5">{machines.length} registradas</p>
        </div>
        <button
          onClick={handleNewMachine}
          disabled={loading}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <Plus size={16} />
          {loading ? "Gerando código..." : "Nova Máquina"}
        </button>
      </div>

      {enrollCode && (
        <div className="bg-gray-900 border border-blue-600/30 rounded-xl p-5">
          <div className="flex items-start justify-between mb-4">
            <div>
              <h2 className="text-base font-semibold text-white">Conectar nova máquina</h2>
              <p className="text-gray-400 text-xs mt-1">
                O nome, o hostname e o sistema operacional são detectados automaticamente — você não precisa digitar nada disso.
              </p>
            </div>
            <button onClick={() => setEnrollCode(null)} className="text-gray-500 hover:text-white transition-colors">
              <X size={18} />
            </button>
          </div>

          {isLocalOrigin() && (
            <div className="bg-yellow-400/10 border border-yellow-400/30 rounded-lg px-4 py-3 mb-4">
              <p className="text-xs text-yellow-300">
                ⚠ Você está acessando o painel por <code className="font-mono">localhost</code> — esse endereço não
                funciona em outras máquinas. Ao baixar o instalador, será pedido o endereço de rede do servidor
                (ex: <code className="font-mono">http://192.168.0.10:3000</code>). Dica: acesse o painel direto pelo IP
                para evitar isso.
              </p>
            </div>
          )}

          <div className="space-y-2 text-sm text-gray-300 mb-4">
            <p className="flex gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600/20 text-blue-400 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">1</span>
              Baixe o instalador clicando no botão do sistema da máquina que será monitorada:
            </p>
            <div className="flex gap-3 pl-7 py-1 flex-wrap">
              <button
                onClick={() => downloadInstaller("windows", { code: enrollCode.code })}
                className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                <Download size={15} /> Windows
              </button>
              <button
                onClick={() => downloadInstaller("linux", { code: enrollCode.code })}
                className="flex items-center gap-2 bg-gray-700 hover:bg-gray-600 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
              >
                <Download size={15} /> Linux (desktop)
              </button>
            </div>
            <p className="flex gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600/20 text-blue-400 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">2</span>
              Leve o arquivo para a máquina (pendrive, e-mail, etc.) e dê dois cliques nele. No Linux: <code className="text-green-400 bg-gray-800 px-1.5 rounded">bash instalar-anomalydetect.sh</code>
            </p>
            <p className="flex gap-2">
              <span className="w-5 h-5 rounded-full bg-blue-600/20 text-blue-400 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">3</span>
              Pronto! O instalador configura tudo sozinho e a máquina aparece nesta lista em instantes — monitorando automaticamente a cada inicialização.
            </p>
          </div>

          <div className="bg-gray-800/60 rounded-lg px-4 py-3 mb-3">
            <p className="text-xs text-gray-400 mb-2 flex items-center gap-1.5">
              <Terminal size={12} />
              Servidor sem interface gráfica (só terminal)? Cole este comando único via SSH:
            </p>
            <div className="flex items-center gap-2">
              <code className="text-xs text-green-400 font-mono flex-1 truncate bg-gray-900 rounded px-2 py-1.5">
                {serverOneLiner({ code: enrollCode.code })}
              </code>
              <button onClick={copyCmd} className="flex-shrink-0 p-1 text-gray-400 hover:text-white transition-colors" title="Copiar comando">
                {copiedCmd ? <CheckCheck size={14} className="text-green-400" /> : <Copy size={14} />}
              </button>
            </div>
          </div>

          <details className="bg-gray-800/60 rounded-lg px-4 py-3">
            <summary className="text-xs text-gray-400 cursor-pointer select-none">
              Alternativa manual (avançado): usar o código de pareamento
            </summary>
            <div className="flex flex-col items-center py-4">
              <div className="flex items-center gap-3">
                <span className="text-2xl font-bold font-mono text-blue-400 tracking-widest">{enrollCode.code}</span>
                <button onClick={copyCode} className="p-1.5 text-gray-400 hover:text-white transition-colors" title="Copiar código">
                  {copiedCode ? <CheckCheck size={16} className="text-green-400" /> : <Copy size={16} />}
                </button>
              </div>
              <p className="text-xs text-gray-500 mt-2 text-center">
                Execute <code className="text-green-400">python agent.py</code> na máquina e digite o código quando pedido.
              </p>
            </div>
          </details>
          <p className="text-xs text-gray-600 mt-3">
            Código válido até {format(new Date(enrollCode.expires_at), "HH:mm", { locale: ptBR })} · uso único · gere outro se expirar
          </p>
        </div>
      )}

      <div className="space-y-3">
        {machines.map((m) => {
          const isOnline = m.last_seen && new Date(m.last_seen) > new Date(Date.now() - 120000);
          return (
            <Card key={m.id} className="space-y-4">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="relative">
                    <Monitor size={20} className="text-gray-400" />
                    <Circle
                      size={8}
                      className={`absolute -bottom-0.5 -right-0.5 ${isOnline ? "text-green-400 fill-green-400" : "text-gray-600 fill-gray-600"}`}
                    />
                  </div>
                  <div>
                    <p className="text-white font-medium text-sm flex items-center gap-2">
                      {m.name}
                      {!m.is_active && (
                        <span className="text-xs text-yellow-400 bg-yellow-400/10 border border-yellow-400/20 px-2 py-0.5 rounded-full">
                          Coleta pausada
                        </span>
                      )}
                    </p>
                    <p className="text-gray-500 text-xs font-mono">{m.hostname} · {m.os_type}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleTogglePause(m)}
                    title={m.is_active ? "Pausar coleta" : "Retomar coleta"}
                    className={`p-1.5 rounded-lg transition-colors ${
                      m.is_active
                        ? "text-gray-500 hover:text-yellow-400 hover:bg-yellow-400/10"
                        : "text-yellow-400 hover:text-green-400 hover:bg-green-400/10"
                    }`}
                  >
                    {m.is_active ? <Pause size={14} /> : <Play size={14} />}
                  </button>
                  <button onClick={() => handleDelete(m.id)} title="Remover" className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              <div className="bg-gray-800 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-2">
                  Reinstalar o agente nesta máquina (token já embutido — sem código, sem validade)
                </p>
                <div className="flex gap-2 flex-wrap items-center">
                  <button
                    onClick={() => downloadInstaller("windows", { token: m.agent_token })}
                    className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <Download size={12} /> Windows
                  </button>
                  <button
                    onClick={() => downloadInstaller("linux", { token: m.agent_token })}
                    className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                  >
                    <Download size={12} /> Linux
                  </button>
                  <button
                    onClick={() => navigator.clipboard.writeText(serverOneLiner({ token: m.agent_token }))}
                    className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 text-white text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                    title="Copiar comando de instalação via terminal (servidores)"
                  >
                    <Terminal size={12} /> Copiar comando p/ servidor
                  </button>
                  <button onClick={() => copyToken(m)} className="flex items-center gap-1.5 text-gray-400 hover:text-white text-xs px-2 py-1.5 transition-colors" title="Copiar token">
                    {copiedId === m.id ? <CheckCheck size={12} className="text-green-400" /> : <Copy size={12} />} token
                  </button>
                </div>
              </div>

              <details className="bg-gray-800/60 rounded-lg px-4 py-3">
                <summary className="text-xs text-gray-400 cursor-pointer select-none">
                  Como remover o monitoramento deste computador
                </summary>
                <div className="pt-3 space-y-2 text-xs text-gray-300">
                  <p className="flex gap-2">
                    <span className="w-4 h-4 rounded-full bg-red-400/20 text-red-400 font-bold flex items-center justify-center flex-shrink-0 mt-0.5">1</span>
                    Baixe o desinstalador do sistema correspondente:
                  </p>
                  <div className="flex gap-2 pl-6 py-1 flex-wrap">
                    <button
                      onClick={() => downloadUninstaller("windows", m.agent_token)}
                      className="flex items-center gap-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-300 border border-red-600/30 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                    >
                      <Download size={12} /> Desinstalador Windows
                    </button>
                    <button
                      onClick={() => downloadUninstaller("linux", m.agent_token)}
                      className="flex items-center gap-1.5 bg-red-600/20 hover:bg-red-600/30 text-red-300 border border-red-600/30 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors"
                    >
                      <Download size={12} /> Desinstalador Linux
                    </button>
                  </div>
                  <p className="flex gap-2">
                    <span className="w-4 h-4 rounded-full bg-red-400/20 text-red-400 font-bold flex items-center justify-center flex-shrink-0 mt-0.5">2</span>
                    Execute o arquivo <strong>no computador monitorado</strong> (dois cliques no Windows; no Linux: <code className="text-green-400">bash remover-anomalydetect.sh</code>).
                  </p>
                  <p className="flex gap-2">
                    <span className="w-4 h-4 rounded-full bg-red-400/20 text-red-400 font-bold flex items-center justify-center flex-shrink-0 mt-0.5">3</span>
                    Pronto: ele encerra o agente, apaga todos os arquivos e a máquina <strong>some desta lista automaticamente</strong>, junto com o histórico dela.
                  </p>
                  <p className="text-gray-500 pt-1 border-t border-gray-700/50">
                    O botão de lixeira acima remove a máquina apenas do painel — o agente continua instalado no
                    computador (e será desativado por não conseguir mais se conectar). Para limpeza completa, prefira o desinstalador.
                  </p>
                </div>
              </details>

              {m.last_seen && (
                <p className="text-xs text-gray-600">
                  Último contato: {format(new Date(m.last_seen), "dd/MM/yyyy HH:mm:ss", { locale: ptBR })}
                </p>
              )}
            </Card>
          );
        })}
        {machines.length === 0 && (
          <div className="text-center py-16 text-gray-600">
            <Monitor size={36} className="mx-auto mb-3" />
            <p>Nenhuma máquina registrada ainda.</p>
          </div>
        )}
      </div>
    </div>
  );
}
