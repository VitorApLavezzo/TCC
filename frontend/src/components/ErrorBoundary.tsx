import { Component, ErrorInfo, ReactNode } from "react";

/**
 * Rede de segurança para erro de renderização, que antes resultava em tela
 * branca sem nenhuma pista para o usuário.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Erro não tratado na interface:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas p-6">
        <div className="w-full max-w-md rounded-panel border border-hairline bg-surface">
          <div className="px-5 py-5">
            <h1 className="text-md font-semibold text-fg">Esta tela não conseguiu carregar</h1>
            <p className="mt-2 text-sm leading-relaxed text-fg-2">
              Nada foi perdido — seus computadores continuam sendo monitorados. Recarregue a página para tentar de novo.
            </p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 inline-flex h-8 items-center rounded-control bg-inverse px-3 text-sm font-medium text-inverse-fg hover:opacity-90"
            >
              Recarregar a página
            </button>
          </div>
          <details className="border-t border-hairline px-5 py-3">
            <summary className="cursor-pointer select-none text-xs text-fg-3">Detalhes técnicos</summary>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-micro text-fg-2">
              {this.state.error.message}
            </pre>
          </details>
        </div>
      </div>
    );
  }
}
