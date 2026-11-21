import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountApi } from "../../services/api";
import { OnboardingData, OnboardingWizard } from "./OnboardingWizard";

type OpenRequest = () => void;
const listeners = new Set<(onClose: OpenRequest) => void>();

/** Reabre a configuração inicial (botão em Sua conta); resolve quando ela fecha. */
export function openOnboarding(): Promise<void> {
  return new Promise((resolve) => listeners.forEach((open) => open(resolve)));
}

/** Contas novas passam pela configuração antes de conectar o primeiro computador. */
export function OnboardingGate() {
  const navigate = useNavigate();
  const [data, setData] = useState<OnboardingData | null>(null);
  const [firstRun, setFirstRun] = useState(false);
  const onCloseRef = useRef<OpenRequest | null>(null);

  const load = useCallback(async (): Promise<OnboardingData> => {
    const res = await accountApi.preferences();
    return {
      preferences: res.data.preferences,
      channels: res.data.channels_available ?? {},
      telegramLinked: !!res.data.telegram_linked,
    };
  }, []);

  useEffect(() => {
    let alive = true;
    // Sem as preferências o painel segue normal: a configuração nunca pode travar a entrada.
    load()
      .then((loaded) => {
        if (alive && loaded.preferences.onboarding_done === false) {
          setFirstRun(true);
          setData(loaded);
        }
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [load]);

  useEffect(() => {
    const open = (onClose: OpenRequest) => {
      load()
        .then((loaded) => {
          onCloseRef.current = onClose;
          setFirstRun(false);
          setData(loaded);
        })
        .catch(() => onClose());
    };
    listeners.add(open);
    return () => {
      listeners.delete(open);
    };
  }, [load]);

  if (!data) return null;
  return (
    <OnboardingWizard
      data={data}
      firstRun={firstRun}
      onFinish={() => {
        setData(null);
        onCloseRef.current?.();
        onCloseRef.current = null;
        if (firstRun) navigate("/welcome");
      }}
    />
  );
}
