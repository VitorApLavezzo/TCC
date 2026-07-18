import { useState, useCallback } from "react";
import { machinesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { Machine } from "../types";
import { Card } from "../components/ui/Card";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Monitor, Plus, Copy, CheckCheck, RefreshCw, Trash2, Circle } from "lucide-react";

export function Machines() {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", hostname: "", os_type: "Windows" });
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchMachines = useCallback(async () => {
    const res = await machinesApi.list();
    setMachines(res.data);
  }, []);

  usePolling(fetchMachines, 15000);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await machinesApi.create(form);
      setShowForm(false);
      setForm({ name: "", hostname: "", os_type: "Windows" });
      await fetchMachines();
    } finally {
      setLoading(false);
    }
  };

  const copyToken = async (machine: Machine) => {
    await navigator.clipboard.writeText(machine.agent_token);
    setCopiedId(machine.id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Remover esta máquina e todos os seus dados?")) return;
    await machinesApi.delete(id);
    await fetchMachines();
  };

  const handleRegenToken = async (id: number) => {
    if (!confirm("Regenerar token? O agente precisará ser reconfigurado.")) return;
    await machinesApi.regenerateToken(id);
    await fetchMachines();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Máquinas</h1>
          <p className="text-gray-400 text-sm mt-0.5">{machines.length} registradas</p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <Plus size={16} />
          Nova Máquina
        </button>
      </div>

      {showForm && (
        <div className="bg-gray-900 border border-blue-600/30 rounded-xl p-5">
          <h2 className="text-base font-semibold text-white mb-4">Adicionar Máquina</h2>
          <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1.5">Nome</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                placeholder="Meu PC"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1.5">Hostname</label>
              <input
                value={form.hostname}
                onChange={(e) => setForm({ ...form, hostname: e.target.value })}
                required
                placeholder="DESKTOP-ABC123"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1.5">Sistema</label>
              <select
                value={form.os_type}
                onChange={(e) => setForm({ ...form, os_type: e.target.value })}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
              >
                <option>Windows</option>
                <option>Linux</option>
                <option>macOS</option>
              </select>
            </div>
            <div className="md:col-span-3 flex gap-3">
              <button type="submit" disabled={loading} className="bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors disabled:opacity-50">
                {loading ? "Criando..." : "Criar"}
              </button>
              <button type="button" onClick={() => setShowForm(false)} className="text-gray-400 hover:text-white text-sm px-4 py-2 rounded-lg hover:bg-gray-800 transition-colors">
                Cancelar
              </button>
            </div>
          </form>
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
                    <p className="text-white font-medium text-sm">{m.name}</p>
                    <p className="text-gray-500 text-xs font-mono">{m.hostname} · {m.os_type}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => handleRegenToken(m.id)} title="Regenerar token" className="p-1.5 text-gray-500 hover:text-yellow-400 hover:bg-yellow-400/10 rounded-lg transition-colors">
                    <RefreshCw size={14} />
                  </button>
                  <button onClick={() => handleDelete(m.id)} title="Remover" className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              <div className="bg-gray-800 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-1.5">Token do Agente</p>
                <div className="flex items-center gap-2">
                  <code className="text-xs text-green-400 font-mono flex-1 truncate">{m.agent_token}</code>
                  <button onClick={() => copyToken(m)} className="flex-shrink-0 p-1 text-gray-400 hover:text-white transition-colors">
                    {copiedId === m.id ? <CheckCheck size={14} className="text-green-400" /> : <Copy size={14} />}
                  </button>
                </div>
              </div>

              <div className="bg-gray-800 rounded-lg p-3">
                <p className="text-xs text-gray-500 mb-2">Configurar Agente</p>
                <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap">
{`# Linux/macOS
AGENT_API_URL=http://seu-servidor:8000
AGENT_API_TOKEN=${m.agent_token}
python agent.py

# Windows (PowerShell)
$env:AGENT_API_URL="http://seu-servidor:8000"
$env:AGENT_API_TOKEN="${m.agent_token}"
python agent.py`}
                </pre>
              </div>

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
