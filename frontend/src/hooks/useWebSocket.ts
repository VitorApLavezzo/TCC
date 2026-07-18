import { useEffect, useRef, useCallback } from "react";

interface WSMessage {
  type: "metric" | "anomaly";
  data: any;
}

export function useWebSocket(
  path: string | null,
  onMessage: (msg: WSMessage) => void
) {
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const connect = useCallback(() => {
    if (!path) return;
    const token = localStorage.getItem("token");
    if (!token) return;

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const host = window.location.host;
    const url = `${protocol}://${host}${path}?token=${token}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onmessage = (e) => {
      try {
        const msg: WSMessage = JSON.parse(e.data);
        onMessageRef.current(msg);
      } catch {}
    };

    ws.onclose = () => {
      // Reconecta após 3s se a conexão cair
      setTimeout(connect, 3000);
    };

    // Ping a cada 25s para manter a conexão viva
    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 25000);

    ws.onopen = () => clearInterval(ping);
  }, [path]);

  useEffect(() => {
    connect();
    return () => {
      wsRef.current?.close();
    };
  }, [connect]);
}
