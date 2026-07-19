import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { anomaliesApi, explanationsApi, machinesApi } from "../services/api";
import { Anomaly, ANOMALY_TYPE_LABELS } from "../types";
import { SeverityBadge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import {
  ArrowLeft,
  AlertTriangle,
  Brain,
  Lightbulb,
  Wrench,
  CheckCircle2,
  Clock,
  Cpu,
  Activity,
} from "lucide-react";

export function AnomalyDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [anomaly, setAnomaly] = useState<Anomaly | null>(null);
  const [machineName, setMachineName] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  useEffect(() => {
    if (!id) return;
    anomaliesApi.get(Number(id))
      .then((res) => {
        setAnomaly(res.data);
        machinesApi.get(res.data.machine_id)
          .then((mr) => setMachineName(mr.data.name))
          .catch(() => {});
      })
      .catch(() => navigate("/anomalies"))
      .finally(() => setLoading(false));
    return () => stopPolling();
  }, [id]);

  useEffect(() => {
    if (!anomaly) return;
    const hasCauses = (anomaly.explanation?.possible_causes?.length ?? 0) > 0;
    if (hasCauses) { stopPolling(); return; }

    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const res = await anomaliesApi.get(anomaly.id);
        const updated = res.data;
        if ((updated.explanation?.possible_causes?.length ?? 0) > 0) {
          setAnomaly(updated);
          stopPolling();
        }
      } catch {}
    }, 4000);

    return () => stopPolling();
  }, [anomaly?.id, anomaly?.explanation?.possible_causes?.length]);

  const handleRegenerate = async () => {
    if (!anomaly) return;
    setRegenerating(true);
    try {
      const res = await explanationsApi.regenerate(anomaly.id);
      setAnomaly({ ...anomaly, explanation: res.data });
    } catch (e) {
      alert("Erro ao regenerar. Verifique se o Ollama está rodando.");
    } finally {
      setRegenerating(false);
    }
  };

  const handleResolve = async () => {
    if (!anomaly) return;
    const res = await anomaliesApi.resolve(anomaly.id, !anomaly.is_resolved);
    setAnomaly(res.data);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-2 border-blue-500 border-t-transparent" />
      </div>
    );
  }

  if (!anomaly) return null;

  const exp = anomaly.explanation;

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center gap-4">
        <button onClick={() => navigate("/anomalies")} className="text-gray-400 hover:text-white transition-colors">
          <ArrowLeft size={20} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-xl font-bold text-white">
              {ANOMALY_TYPE_LABELS[anomaly.anomaly_type] || anomaly.anomaly_type}
            </h1>
            <SeverityBadge severity={anomaly.severity} />
            {anomaly.is_resolved && (
              <span className="text-xs text-green-400 bg-green-400/10 border border-green-400/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                <CheckCircle2 size={11} /> Resolvida
              </span>
            )}
          </div>
          <p className="text-gray-500 text-xs mt-1 flex items-center gap-3 flex-wrap">
            {machineName && (
              <span className="flex items-center gap-1 text-blue-300/80">
                <Cpu size={11} />
                {machineName}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Clock size={11} />
              Detectada em {format(new Date(anomaly.detected_at), "dd/MM/yyyy 'às' HH:mm:ss", { locale: ptBR })}
            </span>
          </p>
        </div>
        <button
          onClick={handleResolve}
          className={`text-sm px-4 py-2 rounded-lg border transition-colors font-medium ${
            anomaly.is_resolved
              ? "text-orange-400 border-orange-400/30 hover:bg-orange-400/10"
              : "text-green-400 border-green-400/30 hover:bg-green-400/10"
          }`}
        >
          {anomaly.is_resolved ? "Reabrir" : "Marcar Resolvida"}
        </button>
      </div>

      {/* Urgência em linguagem cotidiana */}
      <div className={`rounded-xl px-4 py-3 border text-sm flex items-center gap-2 ${
        anomaly.severity === "critical" ? "bg-red-400/10 border-red-400/30 text-red-300"
        : anomaly.severity === "high" ? "bg-orange-400/10 border-orange-400/30 text-orange-300"
        : anomaly.severity === "medium" ? "bg-yellow-400/10 border-yellow-400/30 text-yellow-300"
        : "bg-blue-400/10 border-blue-400/30 text-blue-300"
      }`}>
        <AlertTriangle size={15} className="flex-shrink-0" />
        {anomaly.severity === "critical" && "Aja agora: este problema pode travar o computador ou indicar uma ameaça séria."}
        {anomaly.severity === "high" && "Requer atenção hoje: o computador pode ficar lento ou instável se nada for feito."}
        {anomaly.severity === "medium" && "Vale investigar quando puder: não é urgente, mas não deve ser ignorado."}
        {anomaly.severity === "low" && "Apenas informativo: nenhuma ação urgente é necessária."}
      </div>

      {/* O que aconteceu */}
      {exp && (
        <div className="bg-gradient-to-br from-blue-950/50 to-purple-950/50 border border-blue-800/40 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Brain size={16} className="text-blue-400" />
            <span className="text-blue-300 text-sm font-semibold">O que aconteceu?</span>
            {exp.model_used && (
              <span className="text-xs text-gray-600 ml-auto" title="Modelo de IA que gerou esta análise">{exp.model_used}</span>
            )}
          </div>
          <p className="text-white text-sm leading-relaxed">{exp.summary}</p>
          {exp.detailed_explanation && (
            <p className="text-gray-300 text-sm leading-relaxed mt-3 border-t border-blue-800/30 pt-3 whitespace-pre-line">
              {exp.detailed_explanation}
            </p>
          )}
          {exp.severity_justification && (
            <p className="text-gray-400 text-xs mt-3 italic">{exp.severity_justification}</p>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Metrics snapshot */}
        <Card>
          <div className="flex items-center gap-2 mb-4">
            <Activity size={15} className="text-gray-400" />
            <h2 className="text-sm font-semibold text-white">Métricas Afetadas</h2>
          </div>
          {anomaly.affected_metrics && Object.keys(anomaly.affected_metrics).length > 0 ? (
            <div className="space-y-2">
              {Object.entries(anomaly.affected_metrics)
                .filter(([key, val]) => key !== "_behavior" && typeof val !== "object")
                .map(([key, val]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-xs text-gray-400 capitalize">{key.replace(/_/g, " ")}</span>
                  <span className="text-sm font-mono text-white">
                    {typeof val === "number" ? `${val.toFixed(1)}%` : String(val)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-gray-600 text-xs">Nenhuma métrica específica registrada.</p>
          )}
          {anomaly.responsible_process && (
            <div className="mt-3 pt-3 border-t border-gray-800">
              <p className="text-xs text-gray-500">Processo responsável</p>
              <p className="text-sm text-orange-400 font-mono mt-0.5">{anomaly.responsible_process}</p>
            </div>
          )}
          {anomaly.anomaly_score !== null && anomaly.anomaly_score !== undefined && (
            <div className="mt-2">
              <p className="text-xs text-gray-500">Score de anomalia (Isolation Forest)</p>
              <p className="text-sm text-gray-300 font-mono mt-0.5">{anomaly.anomaly_score.toFixed(4)}</p>
            </div>
          )}
        </Card>

        {/* Possible causes */}
        {exp && (!exp.possible_causes || exp.possible_causes.length === 0) && (
          <Card className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex gap-1">
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
              <div>
                <p className="text-sm text-white font-medium">Analisando com IA...</p>
                <p className="text-xs text-gray-500 mt-0.5">O Ollama está processando. Atualiza automaticamente.</p>
              </div>
            </div>
            <button
              onClick={handleRegenerate}
              disabled={regenerating}
              className="flex-shrink-0 text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg transition-colors"
            >
              {regenerating ? "Gerando..." : "Tentar agora"}
            </button>
          </Card>
        )}

        {exp?.possible_causes && exp.possible_causes.length > 0 && (
          <Card>
            <div className="flex items-center gap-2 mb-1">
              <Lightbulb size={15} className="text-yellow-400" />
              <h2 className="text-sm font-semibold text-white">Possíveis Causas</h2>
            </div>
            <p className="text-xs text-gray-500 mb-4">Da mais provável para a menos provável</p>
            <ul className="space-y-2">
              {exp.possible_causes.map((cause, i) => (
                <li key={i} className="flex items-start gap-2 text-xs text-gray-300">
                  <span className="text-yellow-400 font-bold mt-0.5 flex-shrink-0">{i + 1}.</span>
                  {cause}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      {/* Recommendations */}
      {exp?.recommendations && exp.recommendations.length > 0 && (
        <Card>
          <div className="flex items-center gap-2 mb-1">
            <Wrench size={15} className="text-green-400" />
            <h2 className="text-sm font-semibold text-white">O que fazer agora</h2>
          </div>
          <p className="text-xs text-gray-500 mb-4">Siga os passos na ordem — do mais simples para o mais avançado</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {exp.recommendations.map((rec, i) => (
              <div key={i} className="flex items-start gap-3 bg-gray-800/50 rounded-lg px-3 py-2.5">
                <div className="w-5 h-5 rounded-full bg-green-400/20 text-green-400 text-xs font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                  {i + 1}
                </div>
                <p className="text-xs text-gray-300 leading-relaxed">{rec}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {!exp && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center">
          <Brain size={32} className="text-gray-700 mx-auto mb-3" />
          <p className="text-gray-500 text-sm">Explicação da IA ainda não disponível.</p>
          <p className="text-gray-600 text-xs mt-1">Verifique se o Ollama está rodando e o modelo foi baixado.</p>
          <button
            onClick={handleRegenerate}
            disabled={regenerating}
            className="mt-4 text-xs bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg transition-colors"
          >
            {regenerating ? "Gerando..." : "Gerar explicação agora"}
          </button>
        </div>
      )}
    </div>
  );
}
