import { useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { anomaliesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { Anomaly, ANOMALY_TYPE_LABELS } from "../types";
import { SeverityBadge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { AlertTriangle, CheckCircle2, Clock, Filter, ChevronRight } from "lucide-react";

const SEVERITIES = ["", "critical", "high", "medium", "low"];

export function Anomalies() {
  const navigate = useNavigate();
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [severity, setSeverity] = useState("");
  const [hours, setHours] = useState(72);
  const [unresolvedOnly, setUnresolvedOnly] = useState(false);

  const fetchAnomalies = useCallback(async () => {
    const res = await anomaliesApi.list({
      hours,
      severity: severity || undefined,
      unresolved_only: unresolvedOnly,
    });
    setAnomalies(res.data);
  }, [hours, severity, unresolvedOnly]);

  usePolling(fetchAnomalies, 30000);

  const handleResolve = async (e: React.MouseEvent, id: number, isResolved: boolean) => {
    e.stopPropagation();
    await anomaliesApi.resolve(id, !isResolved);
    await fetchAnomalies();
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Anomalias</h1>
        <p className="text-gray-400 text-sm mt-0.5">{anomalies.length} encontradas</p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5 text-gray-500 text-xs">
          <Filter size={13} />
          Filtros:
        </div>
        <select
          value={hours}
          onChange={(e) => setHours(Number(e.target.value))}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          <option value={24}>Últimas 24h</option>
          <option value={72}>Últimas 72h</option>
          <option value={168}>Última semana</option>
          <option value={720}>Último mês</option>
        </select>
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-blue-500"
        >
          <option value="">Todas severidades</option>
          <option value="critical">Crítica</option>
          <option value="high">Alta</option>
          <option value="medium">Média</option>
          <option value="low">Baixa</option>
        </select>
        <label className="flex items-center gap-2 text-sm text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={unresolvedOnly}
            onChange={(e) => setUnresolvedOnly(e.target.checked)}
            className="rounded"
          />
          Não resolvidas
        </label>
      </div>

      <div className="space-y-3">
        {anomalies.map((a) => (
          <Card
            key={a.id}
            onClick={() => navigate(`/anomalies/${a.id}`)}
            className="flex items-start gap-4"
          >
            <div className="flex-shrink-0 mt-0.5">
              {a.is_resolved ? (
                <CheckCircle2 size={18} className="text-green-400" />
              ) : (
                <AlertTriangle size={18} className={a.severity === "critical" ? "text-red-400" : "text-orange-400"} />
              )}
            </div>

            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-white text-sm font-medium">
                  {ANOMALY_TYPE_LABELS[a.anomaly_type] || a.anomaly_type}
                </span>
                <SeverityBadge severity={a.severity} />
                {a.is_resolved && (
                  <span className="text-xs text-green-400 bg-green-400/10 border border-green-400/20 px-2 py-0.5 rounded-full">
                    Resolvida
                  </span>
                )}
              </div>

              {a.explanation?.summary && (
                <p className="text-gray-400 text-xs mt-1 line-clamp-2">{a.explanation.summary}</p>
              )}

              <div className="flex items-center gap-3 mt-2">
                <span className="flex items-center gap-1 text-gray-600 text-xs">
                  <Clock size={10} />
                  {format(new Date(a.detected_at), "dd/MM/yyyy 'às' HH:mm", { locale: ptBR })}
                </span>
                {a.responsible_process && (
                  <span className="text-xs text-gray-600 font-mono bg-gray-800 px-2 py-0.5 rounded">
                    {a.responsible_process}
                  </span>
                )}
                {a.anomaly_score !== undefined && a.anomaly_score !== null && (
                  <span className="text-xs text-gray-600">
                    Score: {a.anomaly_score.toFixed(3)}
                  </span>
                )}
              </div>
            </div>

            <div className="flex-shrink-0 flex items-center gap-2">
              <button
                onClick={(e) => handleResolve(e, a.id, a.is_resolved)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                  a.is_resolved
                    ? "text-gray-500 border-gray-700 hover:border-orange-500 hover:text-orange-400"
                    : "text-green-400 border-green-400/30 hover:bg-green-400/10"
                }`}
              >
                {a.is_resolved ? "Reabrir" : "Resolver"}
              </button>
              <ChevronRight size={16} className="text-gray-600" />
            </div>
          </Card>
        ))}

        {anomalies.length === 0 && (
          <div className="text-center py-16 text-gray-600">
            <CheckCircle2 size={36} className="mx-auto mb-3 text-green-700" />
            <p className="text-gray-400">Nenhuma anomalia encontrada no período.</p>
          </div>
        )}
      </div>
    </div>
  );
}
