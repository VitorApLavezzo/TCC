/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        // Prosa, rótulos, títulos. Archivo é um grotesco de construção
        // industrial — dá voz ao produto sem virar decoração.
        sans: ['Archivo', "system-ui", "-apple-system", "sans-serif"],
        // Regra do produto: TUDO que a máquina mediu é composto aqui.
        // Valor, unidade, horário, identificador técnico, comando.
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        micro: ["0.75rem", { lineHeight: "1.0625rem", letterSpacing: "0.005em" }],
        xs: ["0.8125rem", { lineHeight: "1.1875rem" }],
        sm: ["0.875rem", { lineHeight: "1.3125rem" }],
        base: ["0.9375rem", { lineHeight: "1.4375rem" }],
        md: ["1.0625rem", { lineHeight: "1.5625rem" }],
        lg: ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.015em" }],
        xl: ["1.75rem", { lineHeight: "2rem", letterSpacing: "-0.022em" }],
        // Leitura de instrumento: o número de um canal.
        "readout-sm": ["1.5rem", { lineHeight: "1", letterSpacing: "-0.02em" }],
      },
      letterSpacing: {
        // Rótulo de canal em caixa alta — a única caixa alta do produto.
        channel: "0.09em",
      },
      colors: {
        /*
         * Quatro níveis de superfície. Grafite neutro de verdade (R=G=B):
         * o azul-acinzentado é o que faz todo painel escuro parecer o mesmo
         * painel escuro, e tingir o fundo rouba força das três cores que
         * realmente significam algo.
         */
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        raised: "rgb(var(--raised) / <alpha-value>)",
        sunken: "rgb(var(--sunken) / <alpha-value>)",

        hairline: "rgb(var(--hairline) / <alpha-value>)",
        edge: "rgb(var(--edge) / <alpha-value>)",

        fg: "rgb(var(--fg) / <alpha-value>)",
        "fg-2": "rgb(var(--fg-2) / <alpha-value>)",
        "fg-3": "rgb(var(--fg-3) / <alpha-value>)",

        inverse: "rgb(var(--inverse) / <alpha-value>)",
        "inverse-fg": "rgb(var(--inverse-fg) / <alpha-value>)",

        // Íris: a cor do AnomalyDetect. Só interação e marca de detecção —
        // nunca "saudável", nunca preenchimento de superfície.
        accent: "rgb(var(--accent) / <alpha-value>)",

        // Estado de saúde: a única outra saturação com significado.
        ok: "rgb(var(--ok) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        crit: "rgb(var(--crit) / <alpha-value>)",
      },
      borderRadius: {
        // Raios diferentes por classe de objeto, de propósito: controle é
        // crispo, painel é suave, janela de leitura é reta.
        DEFAULT: "3px",
        control: "3px",
        panel: "5px",
      },
      boxShadow: {
        float: "0 10px 30px -8px rgb(0 0 0 / 0.45), 0 3px 8px -3px rgb(0 0 0 / 0.28)",
        raise: "0 1px 0 0 rgb(var(--hairline) / 1)",
      },
      maxWidth: {
        prose: "68ch",
      },
      transitionTimingFunction: {
        // Aceleração de instrumento: sai rápido, assenta devagar.
        signal: "cubic-bezier(0.22, 0.61, 0.36, 1)",
      },
      keyframes: {
        // Traço se desenhando na montagem — uma vez, não em laço.
        // O caminho usa pathLength=1, então o deslocamento vai de 1 a 0.
        draw: { from: { strokeDashoffset: "1" }, to: { strokeDashoffset: "0" } },
        // Um único anel quando uma leitura nova chega. Não fica piscando.
        ping1: { "0%": { transform: "scale(1)", opacity: "0.55" }, "100%": { transform: "scale(3.2)", opacity: "0" } },
        // Respiração do indicador "ao vivo": lenta e de baixa amplitude.
        breathe: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.45" } },
        rise: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: {
        draw: "draw 700ms cubic-bezier(0.22, 0.61, 0.36, 1) forwards",
        ping1: "ping1 1100ms cubic-bezier(0.22, 0.61, 0.36, 1) forwards",
        breathe: "breathe 3.2s ease-in-out infinite",
        rise: "rise 260ms cubic-bezier(0.22, 0.61, 0.36, 1) both",
      },
    },
  },
  plugins: [],
};
