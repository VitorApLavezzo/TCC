import { useEffect, useRef, useState } from "react";

interface WSMessage {
  type: "metric" | "anomaly";
  data: any;
}

export type WSStatus = "idle" | "connecting" | "open" | "closed";

/**
 * Conexão em tempo real com reconexão automática.
 *
 * Devolve o estado da conexão para a interface poder dizer a verdade: antes o
 * selo "AO VIVO" acendia na primeira mensagem e nunca mais apagava, então um
 * agente morto continuava aparecendo como ao vivo.
 *
 * Corrige também dois defeitos da versão anterior: o ping de 25s era limpo no
 * `onopen` (ou seja, nunca era enviado), e o `onclose` reagendava a conexão
 * mesmo depois de o componente desmontar.
 */
export function useWebSocket(path: string | null, onMessage: (msg: WSMessage) => void): WSStatus {
  const [status, setStatus] = useState<WSStatus>("idle");
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!path) {
      setStatus("idle");
      return;
    }
    const token = localStorage.getItem("token");
    if (!token) {
      setStatus("idle");
      return;
    }

    let disposed = false;
    let ws: WebSocket | null = null;
    let pingId: ReturnType<typeof setInterval> | null = null;
    let retryId: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const clearPing = () => {
      if (pingId) clearInterval(pingId);
      pingId = null;
    };

    const connect = () => {
      if (disposed) return;
      setStatus("connecting");

      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${protocol}://${window.location.host}${path}?token=${token}`);

      ws.onopen = () => {
        if (disposed) return;
        attempt = 0;
        setStatus("open");
        clearPing();
        pingId = setInterval(() => {
          if (ws?.readyState === WebSocket.OPEN) ws.send("ping");
        }, 25000);
      };

      ws.onmessage = (e) => {
        if (disposed) return;
        try {
          onMessageRef.current(JSON.parse(e.data) as WSMessage);
        } catch {
          // Mensagem que não é JSON (o "pong" do servidor) — ignorar.
        }
      };

      ws.onclose = () => {
        clearPing();
        if (disposed) return;
        setStatus("closed");
        // Recuo progressivo até 30s, para não martelar um servidor fora do ar.
        const delay = Math.min(3000 * 2 ** attempt++, 30000);
        retryId = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // O `onclose` sempre vem depois e é lá que reagendamos.
      };
    };

    connect();

    return () => {
      disposed = true;
      clearPing();
      if (retryId) clearTimeout(retryId);
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [path]);

  return status;
}
