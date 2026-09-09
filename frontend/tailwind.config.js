/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "-apple-system", "sans-serif"],
        // Só para conteúdo que é literalmente código: token, comando, caminho.
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
      // Escala pensada para software administrativo, mas legível sem
      // esforço: pequena demais na primeira versão, subiu um degrau
      // inteiro mantendo as proporções entre os níveis.
      fontSize: {
        micro: ["0.75rem", { lineHeight: "1.0625rem", letterSpacing: "0.005em" }],
        xs: ["0.8125rem", { lineHeight: "1.1875rem" }],
        sm: ["0.875rem", { lineHeight: "1.3125rem" }],
        base: ["0.9375rem", { lineHeight: "1.4375rem" }],
        md: ["1.0625rem", { lineHeight: "1.5625rem" }],
        lg: ["1.375rem", { lineHeight: "1.75rem", letterSpacing: "-0.01em" }],
        xl: ["2rem", { lineHeight: "2.25rem", letterSpacing: "-0.02em" }],
      },
      colors: {
        // Neutros: a interface é feita quase inteiramente destes.
        canvas: "rgb(var(--canvas) / <alpha-value>)",
        surface: "rgb(var(--surface) / <alpha-value>)",
        sunken: "rgb(var(--sunken) / <alpha-value>)",
        hairline: "rgb(var(--hairline) / <alpha-value>)",
        edge: "rgb(var(--edge) / <alpha-value>)",
        fg: "rgb(var(--fg) / <alpha-value>)",
        "fg-2": "rgb(var(--fg-2) / <alpha-value>)",
        "fg-3": "rgb(var(--fg-3) / <alpha-value>)",
        // Inverso do primeiro plano — botão primário e superfícies invertidas.
        inverse: "rgb(var(--inverse) / <alpha-value>)",
        "inverse-fg": "rgb(var(--inverse-fg) / <alpha-value>)",
        // Interativo: foco, link, seleção. Nunca significa "saudável".
        accent: "rgb(var(--accent) / <alpha-value>)",
        // Estado de saúde: a única saturação com significado no produto.
        ok: "rgb(var(--ok) / <alpha-value>)",
        warn: "rgb(var(--warn) / <alpha-value>)",
        crit: "rgb(var(--crit) / <alpha-value>)",
      },
      borderRadius: {
        DEFAULT: "4px",
        control: "4px",
        panel: "6px",
      },
      boxShadow: {
        // Uma sombra só, para o que realmente flutua (diálogo, aviso, popover).
        float: "0 8px 24px -6px rgb(0 0 0 / 0.28), 0 2px 6px -2px rgb(0 0 0 / 0.16)",
      },
      maxWidth: {
        prose: "68ch",
      },
    },
  },
  plugins: [],
};
