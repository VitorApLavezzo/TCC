import { useCallback, useEffect, useState } from "react";
import { errorMessage, pushApi } from "../../services/api";
import { Section, Panel } from "../ui/Layout";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";

type Device = { id: number; user_agent: string | null; created_at: string; last_ok_at: string | null };

/** Converte a chave do servidor (base64 de URL) para os bytes que o navegador exige. */
function urlBase64ToBytes(base64: string): ArrayBuffer {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const normal = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normal);
  const bytes = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i);
  return bytes.buffer;
}

/**
 * Notificação no celular pelo próprio sistema. O botão de teste existe porque
 * ninguém confia num canal de aviso que nunca viu funcionar.
 */
export function PushDevices() {
  const toast = useToast();
  const [config, setConfig] = useState<{
    enabled: boolean;
    public_key: string | null;
    library_installed?: boolean;
    keys_configured?: boolean;
  } | null>(null);
  const [devices, setDevices] = useState<Device[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [c, d] = await Promise.all([pushApi.config(), pushApi.devices()]);
      setConfig(c.data);
      setDevices(d.data.devices);
    } catch {
      setConfig(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Fora de HTTPS (ou localhost) o navegador nem expõe Service Worker e
  // PushManager: separa esse caso do "navegador não aceita".
  const secure = window.isSecureContext;
  const supported = secure && "serviceWorker" in navigator && "PushManager" in window;

  async function enable() {
    if (!config?.public_key) return;
    setBusy(true);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        toast.error("O navegador não autorizou os avisos.", "Permita as notificações deste site e tente de novo.");
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToBytes(config.public_key),
      });
      await pushApi.subscribe(subscription.toJSON());
      toast.success("Este aparelho vai receber os avisos.");
      load();
    } catch (e) {
      toast.error(errorMessage(e, "Não foi possível ativar os avisos neste aparelho."));
    } finally {
      setBusy(false);
    }
  }

  async function sendTest() {
    try {
      const r = await pushApi.test();
      if (r.data.delivered) toast.success("Aviso de teste enviado.");
      else toast.error("Nenhum aparelho recebeu.", "Ative os avisos neste aparelho primeiro.");
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  return (
    <Section title="Avisos no celular" description="Instale o painel pela tela inicial e receba as notificações do sistema">
      <Panel className="p-4">
        {!config?.enabled ? (
          <p className="max-w-prose text-sm leading-relaxed text-fg-2">
            {config?.library_installed === false ? (
              <>
                Falta a biblioteca <code className="font-mono text-micro">pywebpush</code> na imagem
                do servidor. Quem administra reconstrói o backend depois de instalar as dependências:{" "}
                <code className="font-mono text-micro">docker compose up -d --build backend</code>.
              </>
            ) : (
              <>
                Este servidor ainda não recebeu as chaves de notificação. Quem administra gera o par
                com{" "}
                <code className="font-mono text-micro">
                  docker compose exec backend python -m app.services.push
                </code>
                , preenche VAPID_PUBLIC_KEY e VAPID_PRIVATE_KEY no .env e reinicia o backend.
              </>
            )}
          </p>
        ) : !secure ? (
          <div className="max-w-prose space-y-2 text-sm leading-relaxed text-fg-2">
            <p>
              Os avisos no celular exigem uma conexão segura. Este painel está sendo aberto por
              HTTP em rede local (<code className="font-mono text-micro">{window.location.host}</code>
              ), e nesse caso o navegador nem oferece o recurso — vale para Chrome no Android e para
              o Safari no iPhone.
            </p>
            <p>Três saídas, da mais rápida à definitiva:</p>
            <ul className="list-disc space-y-1 pl-5">
              <li>
                Para experimentar agora: abra o painel no próprio computador em{" "}
                <code className="font-mono text-micro">http://localhost:3000</code> — endereço local
                conta como seguro.
              </li>
              <li>
                Para usar no celular hoje: um túnel com HTTPS (Cloudflare Tunnel, ngrok) apontando
                para a porta 3000.
              </li>
              <li>
                Em uso real: publique atrás de um proxy com certificado (Caddy ou Nginx com Let's
                Encrypt) e acesse pelo endereço https.
              </li>
            </ul>
            <p className="text-fg-3">
              Instalar o painel pela tela inicial também depende de HTTPS. Os outros canais de aviso
              — Telegram e e-mail — funcionam sem isso.
            </p>
          </div>
        ) : !supported ? (
          <p className="max-w-prose text-sm leading-relaxed text-fg-2">
            Este navegador não aceita notificações em segundo plano. No iPhone, é preciso primeiro
            adicionar o painel à tela de início pelo Compartilhar do Safari.
          </p>
        ) : (
          <>
            <p className="max-w-prose text-sm leading-relaxed text-fg-2">
              {devices.length === 0
                ? "Nenhum aparelho recebendo avisos ainda."
                : `${devices.length} aparelho(s) recebendo avisos.`}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="primary" loading={busy} onClick={enable}>
                Receber avisos neste aparelho
              </Button>
              {devices.length > 0 && (
                <Button variant="secondary" onClick={sendTest}>
                  Enviar um teste
                </Button>
              )}
            </div>
          </>
        )}
      </Panel>
    </Section>
  );
}
