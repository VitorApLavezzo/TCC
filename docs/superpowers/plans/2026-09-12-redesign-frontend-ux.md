# Redesign do frontend e da UX — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganizar o frontend do AnomalyDetect em revelação progressiva, com identidade visual nova, sem remover nenhuma funcionalidade e sem tocar no backend.

**Architecture:** Substituição do shell lateral por barra superior; o painel vira a tela "Situação", com um bloco de veredito único e a faixa do normal aprendido como elemento-assinatura; os dados brutos, os gráficos e as análises descem para rotas próprias. A troca de tokens é feita com aliases temporários para que toda tarefa intermediária compile.

**Tech Stack:** React 18, TypeScript 5.5, Vite 5, Tailwind 3.4, react-router-dom 6, recharts 2, lucide-react, date-fns, axios.

**Spec:** `docs/superpowers/specs/2026-09-12-redesign-frontend-ux-design.md`

---

## Global Constraints

Valores copiados literalmente da spec. Valem para toda tarefa.

**Escopo intocável.** Nenhuma alteração em `backend/`, `agent/`, banco, autenticação ou ML. Nenhuma chamada de `frontend/src/services/api.ts` removida, renomeada ou com assinatura alterada. Se uma tarefa parecer exigir mudança de backend, ela para e reporta — não improvisa.

**Sem framework de teste.** O projeto não tem testes de frontend e introduzi-los está fora de escopo. O ciclo de verificação de toda tarefa é:

```bash
cd frontend && npx tsc --noEmit && npm run build
```

mais a verificação visual descrita na própria tarefa, com o app rodando (`npm run dev`). Uma tarefa só é dada por concluída depois que os dois comandos passam e a verificação visual foi feita de fato.

**Paleta.** Escuro é o padrão. Cinco neutros e três estados. Não existe cor de marca.

```
                ESCURO (padrão)   CLARO (par)
paper           #0E1518           #FAFBFB
field           #151C20           #FFFFFF
rule            #232C31           #E3E7E9
mute            #8A959B           #5D686E
ink             #E8EDEF           #10161A
ok              #4E9E7A           #1F7A55
warn            #C98A2E           #8A5A08
crit            #D45A56           #B03A38
```

**Tipografia.** Display Bricolage Grotesque (600, 700), corpo Instrument Sans (400, 500, 600), dado Martian Mono (400, 500, eixo `wdth` 87.5). Todo valor medido pela máquina é composto em Martian Mono.

**Escala de tipo.**

```
veredito     34px  Bricolage 650  -0.02em
título       22px  Bricolage 600  -0.015em
leitura      30px  Martian  450   tabular
seção        15px  Instrument 600
corpo        15px  Instrument 400  altura 1.55
apoio        13px  Instrument 400
canal        11px  Instrument 600  caixa alta  0.1em
micro        11px  Instrument 400
```

**Layout.** Barra superior, nunca lateral. Coluna de 760px para prosa; a faixa rompe para 1040px. Base 4 no ritmo vertical. Raio 4px em controles, 8px em painéis. Card com borda só em: linha de máquina, linha de alerta, modal. Profundidade máxima de aninhamento de caixas com borda: 1.

**Movimento.** Um só momento animado no produto: o traço da faixa se desenhando da esquerda para a direita em ~700ms na montagem da Situação. Nada mais anima. `prefers-reduced-motion: reduce` entrega o traço completo.

**Acessibilidade.** Contraste mínimo 4.5:1 em texto, incluindo hover. Foco visível em todo elemento interativo. Navegação completa por teclado. Estado nunca comunicado só por cor — sempre símbolo ou palavra junto. Alvos de toque de no mínimo 44px. `aria-live` nas atualizações de estado.

**Vocabulário.** Um termo por conceito, em toda a interface:

| Conceito | Termo | Nunca |
|---|---|---|
| Detecção fora do normal | **alerta** | aviso, anomalia, detecção, evento |
| Máquina monitorada | **computador** | máquina, host, dispositivo |
| Faixa aprendida | **o normal deste computador** | baseline, envelope |
| Coleta em andamento | **acompanhando** | ativo, coletando, online |
| Coleta interrompida | **pausado** | inativo, desativado |

Botões nomeiam o que acontece e mantêm o mesmo nome do início ao fim do fluxo. Estados vazios são convite à ação. Erros dizem o que aconteceu e como resolver, sem pedir desculpa.

---

## Estrutura de arquivos

**Criados**

| Arquivo | Responsabilidade |
|---|---|
| `src/components/ui/NormalBand.tsx` | A assinatura: faixa hachurada + traço. Único componente de visualização de sinal. |
| `src/components/ui/Mark.tsx` | Marca do produto, recorte da faixa. Substitui `SignalMark`. |
| `src/components/TopBar.tsx` | Navegação global. Substitui a lateral de `AppShell`. |
| `src/hooks/useSelectedMachine.ts` | Escolha de computador persistida, com queda para a primeira ativa. |
| `src/lib/discoveries.ts` | Agrega os endpoints de insight num fluxo priorizado de descobertas. |
| `src/components/situacao/Verdict.tsx` | Bloco único: estado, resumo e ação. |
| `src/components/situacao/Indicators.tsx` | Os três indicadores em linha, sem card. |
| `src/components/situacao/MachineTabs.tsx` | Abas ou seletor de computador, conforme a escala. |
| `src/components/situacao/Discoveries.tsx` | Até duas descobertas no painel. |
| `src/pages/Situacao.tsx` | Substitui `Dashboard`. |
| `src/pages/Sistema.tsx` | Nível 3: as medidas em três grupos. |
| `src/pages/Historico.tsx` | Os gráficos. |
| `src/pages/Descobertas.tsx` | Todas as descobertas em fluxo único. |
| `src/pages/Instalacao.tsx` | Operação de frota: chaves em lote e comparação. |
| `src/pages/ContaSistema.tsx` | Superfícies de banca, reaproveitando `Research` e `Demo`. |

**Renomeados** (`git mv`, preservando histórico)

`pages/Anomalies.tsx` → `pages/Alertas.tsx` · `pages/AnomalyDetail.tsx` → `pages/AlertaDetalhe.tsx` · `pages/Machines.tsx` → `pages/Computadores.tsx` · `pages/Account.tsx` → `pages/Conta.tsx`

**Removidos** (só na Tarefa 13, depois que nada mais os importa)

`components/ui/VitalStrip.tsx` · `components/ui/SignalTrace.tsx` · `components/ui/SignalMark.tsx` · `components/Verdict.tsx` · `pages/Dashboard.tsx` · `pages/MachineDetail.tsx`

**Modificados**

`index.html` · `tailwind.config.js` · `src/index.css` · `src/App.tsx` · `src/components/AppShell.tsx` · `src/components/ui/Layout.tsx` · `src/components/ui/Button.tsx` · `src/lib/health.ts` · `src/pages/Login.tsx` · `src/components/machines/MachineCard.tsx` · `src/components/charts/MetricChart.tsx`

---

## Task 1: Fundação — fontes, tokens e escala

Introduz a paleta e a tipografia novas mantendo aliases dos nomes antigos, para que todo arquivo existente continue compilando. Os aliases saem na Tarefa 13.

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/tailwind.config.js`
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: nada.
- Produces: classes Tailwind `bg-paper` `bg-field` `border-rule` `text-mute` `text-ink` `text-ok` `text-warn` `text-crit`; famílias `font-display` `font-sans` `font-mono`; tamanhos `text-verdict` `text-title` `text-readout` `text-section` `text-body` `text-support` `text-channel` `text-micro`; raios `rounded-control` (4px) e `rounded-panel` (8px). Aliases temporários: `canvas`→paper, `surface`/`raised`/`sunken`→field, `hairline`/`edge`→rule, `fg`→ink, `fg-2`/`fg-3`→mute, `accent`→ink, `inverse`→ink, `inverse-fg`→paper.

- [ ] **Step 1: Trocar as fontes no `index.html`**

Substituir o `<link>` de Archivo/IBM Plex Mono por:

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Instrument+Sans:wght@400;500;600&family=Martian+Mono:wdth,wght@87.5,400;87.5,500&display=swap"
  rel="stylesheet"
/>
```

Manter o script de tema como está: `data-theme="dark"` continua sendo o padrão.

- [ ] **Step 2: Reescrever as variáveis de cor em `src/index.css`**

Substituir os dois blocos `:root, [data-theme="dark"]` e `[data-theme="light"]` por:

```css
:root,
[data-theme="dark"] {
  --paper: 14 21 24;
  --field: 21 28 32;
  --rule: 35 44 49;
  --mute: 138 149 155;
  --ink: 232 237 239;
  --ok: 78 158 122;
  --warn: 201 138 46;
  --crit: 212 90 86;
  /* No escuro a hachura é elemento estrutural, não separador:
     recebe mais contraste que o filete comum. */
  --hatch: 48 60 66;
  --hatch-opacity: 1;
}

[data-theme="light"] {
  --paper: 250 251 251;
  --field: 255 255 255;
  --rule: 227 231 233;
  --mute: 93 104 110;
  --ink: 16 22 26;
  --ok: 31 122 85;
  --warn: 138 90 8;
  --crit: 176 58 56;
  --hatch: 214 220 223;
  --hatch-opacity: 1;
}
```

- [ ] **Step 3: Reescrever `theme.extend` em `tailwind.config.js`**

```js
fontFamily: {
  // Display com restrição: só veredito e títulos de página.
  display: ['"Bricolage Grotesque"', "system-ui", "sans-serif"],
  sans: ['"Instrument Sans"', "system-ui", "-apple-system", "sans-serif"],
  // Regra do produto: TUDO que a máquina mediu é composto aqui.
  mono: ['"Martian Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
},
fontSize: {
  micro:    ["0.6875rem", { lineHeight: "1rem" }],
  channel:  ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.1em" }],
  support:  ["0.8125rem", { lineHeight: "1.25rem" }],
  body:     ["0.9375rem", { lineHeight: "1.55" }],
  section:  ["0.9375rem", { lineHeight: "1.4" }],
  title:    ["1.375rem",  { lineHeight: "1.2",  letterSpacing: "-0.015em" }],
  verdict:  ["2.125rem",  { lineHeight: "1.12", letterSpacing: "-0.02em" }],
  readout:  ["1.875rem",  { lineHeight: "1",    letterSpacing: "-0.01em" }],
},
colors: {
  paper: "rgb(var(--paper) / <alpha-value>)",
  field: "rgb(var(--field) / <alpha-value>)",
  rule:  "rgb(var(--rule) / <alpha-value>)",
  mute:  "rgb(var(--mute) / <alpha-value>)",
  ink:   "rgb(var(--ink) / <alpha-value>)",
  hatch: "rgb(var(--hatch) / <alpha-value>)",
  ok:    "rgb(var(--ok) / <alpha-value>)",
  warn:  "rgb(var(--warn) / <alpha-value>)",
  crit:  "rgb(var(--crit) / <alpha-value>)",

  // Aliases temporários — removidos na Tarefa 13. Existem só para que os
  // arquivos ainda não migrados continuem compilando.
  canvas:       "rgb(var(--paper) / <alpha-value>)",
  surface:      "rgb(var(--field) / <alpha-value>)",
  raised:       "rgb(var(--field) / <alpha-value>)",
  sunken:       "rgb(var(--field) / <alpha-value>)",
  hairline:     "rgb(var(--rule) / <alpha-value>)",
  edge:         "rgb(var(--rule) / <alpha-value>)",
  fg:           "rgb(var(--ink) / <alpha-value>)",
  "fg-2":       "rgb(var(--mute) / <alpha-value>)",
  "fg-3":       "rgb(var(--mute) / <alpha-value>)",
  accent:       "rgb(var(--ink) / <alpha-value>)",
  inverse:      "rgb(var(--ink) / <alpha-value>)",
  "inverse-fg": "rgb(var(--paper) / <alpha-value>)",
},
borderRadius: {
  DEFAULT: "4px",
  control: "4px",
  panel:   "8px",
},
boxShadow: {
  // Sombra só em sobreposição. Superfície plana usa filete.
  float: "0 12px 32px -10px rgb(0 0 0 / 0.5), 0 3px 8px -4px rgb(0 0 0 / 0.3)",
},
maxWidth: {
  prose: "68ch",
  measure: "760px",
  instrument: "1040px",
},
transitionTimingFunction: {
  signal: "cubic-bezier(0.22, 0.61, 0.36, 1)",
},
```

Remover de `theme.extend` as chaves `letterSpacing.channel` e o `fontSize` antigo (`xs`, `sm`, `base`, `md`, `lg`, `xl`, `readout-sm`). Manter `darkMode` e `content` como estão.

- [ ] **Step 4: Ajustar as classes base de `index.css`**

Trocar `@apply bg-canvas text-fg font-sans text-base` no `body` por `@apply bg-paper text-ink font-sans text-body`. Trocar o anel de foco de `ring-accent ring-offset-canvas` por `ring-ink ring-offset-paper`. Trocar `.field` para usar `border-rule bg-field text-ink placeholder:text-mute focus:border-ink`. Trocar `::selection` para `bg-ink/20`. Substituir a regra `.channel-label` por:

```css
.channel-label {
  @apply text-channel font-semibold uppercase text-mute;
}
```

- [ ] **Step 5: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Esperado: ambos passam. O `text-base`, `text-xs`, `text-sm`, `text-lg`, `text-xl` removidos do tema voltam a ser os padrões do Tailwind, então nada quebra — apenas muda de tamanho, o que é esperado nesta fase de transição.

- [ ] **Step 6: Confirmar que as fontes carregaram de verdade**

Uma URL malformada do Google Fonts falha em silêncio e o navegador cai no fallback sem erro no console. Com `npm run dev` aberto, no console do navegador:

```js
document.fonts.check('16px "Bricolage Grotesque"')
document.fonts.check('16px "Instrument Sans"')
document.fonts.check('16px "Martian Mono"')
```

Esperado: `true` nos três. Se algum for `false`, corrigir a URL antes de seguir — todas as tarefas seguintes dependem disto.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/tailwind.config.js frontend/src/index.css
git commit -m "Design: paleta e tipografia novas, com aliases de transicao"
```

---

## Task 2: A assinatura — `NormalBand`

O objeto pelo qual o produto será lembrado. Faixa hachurada do normal aprendido, com o traço do sinal por dentro; ao sair, a hachura para e o traço ganha cor.

**Files:**
- Create: `frontend/src/components/ui/NormalBand.tsx`
- Create: `frontend/src/components/ui/Mark.tsx`

**Interfaces:**
- Consumes: `Level` de `src/lib/health.ts`.
- Produces:

```ts
export interface NormalBandProps {
  /** Leituras em ordem cronológica, a mais recente por último. */
  values: number[];
  /** Teto do eixo. 100 para percentuais. */
  max?: number;
  /** A faixa do normal aprendido, na unidade da medida. */
  band?: { from: number; to: number } | null;
  /** Rótulo humano: "normal daqui às 14h: até 61%". */
  bandLabel?: string;
  /** Cor do trecho fora da faixa. Sem isto o desvio é neutro. */
  breachTone?: "warn" | "crit";
  /** Altura em px. 120 na Situação, 72 no detalhe do alerta. */
  height?: number;
  /** Instante da detecção, de 0 a 1 ao longo do eixo. */
  eventAt?: number | null;
  fromLabel?: string;
  toLabel?: string;
  /** Desenha o traço na montagem. Respeita prefers-reduced-motion. */
  animate?: boolean;
  className?: string;
  /** Descrição para leitor de tela. Obrigatória. */
  label: string;
}
export function NormalBand(props: NormalBandProps): JSX.Element;
```

`Mark.tsx` produz `export function Mark({ className }: { className?: string })` e `export function Wordmark({ className }: { className?: string })`, substituindo `SignalMark`/`Wordmark`.

- [ ] **Step 1: Escrever `NormalBand.tsx`**

```tsx
import { useId } from "react";
import { clsx } from "clsx";

export interface NormalBandProps {
  values: number[];
  max?: number;
  band?: { from: number; to: number } | null;
  bandLabel?: string;
  breachTone?: "warn" | "crit";
  height?: number;
  eventAt?: number | null;
  fromLabel?: string;
  toLabel?: string;
  animate?: boolean;
  className?: string;
  label: string;
}

/**
 * A faixa do normal aprendido, com o sinal correndo por dentro.
 *
 * É a assinatura do AnomalyDetect e a única visualização de sinal do produto.
 *
 * A ideia vem do sistema: ele aprende o que é normal para aquela máquina
 * naquela hora e percebe quando o sinal sai disso. A faixa é desenhada como
 * campo HACHURADO, não como tinta colorida — hachura evoca a região levantada
 * de um desenho de engenharia, e deixa a cor inteiramente livre para
 * significar estado.
 *
 * Ao sair da faixa acontecem duas coisas ao mesmo tempo: o traço ganha cor E a
 * hachura para, porque aquela região deixou de ser normal conhecido. A ausência
 * da hachura comunica tanto quanto a cor — o que mantém o desvio legível para
 * quem não distingue matizes.
 */
export function NormalBand({
  values,
  max = 100,
  band,
  bandLabel,
  breachTone,
  height = 120,
  eventAt = null,
  fromLabel,
  toLabel,
  animate = true,
  className,
  label,
}: NormalBandProps) {
  const uid = useId().replace(/:/g, "");
  const points = values.filter((v) => typeof v === "number" && Number.isFinite(v));

  const W = 1000;
  const H = 300;
  const y = (v: number) => H - (Math.min(Math.max(v, 0), max) / max) * H;
  const x = (i: number) => (points.length <= 1 ? 0 : (i / (points.length - 1)) * W);

  // Topo da faixa em coordenada de desenho. Sem faixa, a hachura cobre tudo.
  const bandTop = band ? y(band.to) : 0;
  const bandBottom = band ? y(band.from) : H;

  const path = points.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");

  // Índice a partir do qual o sinal está fora da faixa, para colorir só o
  // trecho que saiu — e não o histórico inteiro.
  const breachFrom = band
    ? points.findIndex((v) => v > band.to || v < band.from)
    : -1;
  const outside = breachFrom >= 0 && breachTone;
  const breachPath =
    outside
      ? points
          .slice(breachFrom)
          .map((v, i) => `${i === 0 ? "M" : "L"}${x(i + breachFrom).toFixed(1)},${y(v).toFixed(1)}`)
          .join(" ")
      : "";

  const strokeClass = breachTone === "crit" ? "stroke-crit" : "stroke-warn";

  return (
    <figure className={clsx("m-0", className)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ height }}
        className="block w-full"
        role="img"
        aria-label={label}
      >
        <defs>
          <pattern
            id={`hatch-${uid}`}
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line x1="0" y1="0" x2="0" y2="6" className="stroke-hatch" strokeWidth="1" />
          </pattern>
          {/* A hachura vale só até o ponto em que o sinal saiu da faixa. */}
          <clipPath id={`known-${uid}`}>
            <rect
              x="0"
              y="0"
              width={outside ? Math.max(x(breachFrom), 0) : W}
              height={H}
            />
          </clipPath>
        </defs>

        <rect
          x="0"
          y={bandTop}
          width={W}
          height={Math.max(bandBottom - bandTop, 1)}
          fill={`url(#hatch-${uid})`}
          clipPath={`url(#known-${uid})`}
        />
        <line
          x1="0"
          y1={bandTop}
          x2={outside ? Math.max(x(breachFrom), 0) : W}
          y2={bandTop}
          className="stroke-rule"
          strokeWidth="1"
          vectorEffect="non-scaling-stroke"
        />

        {points.length > 1 && (
          <>
            <path
              d={path}
              fill="none"
              className={clsx("stroke-mute", animate && "band-draw")}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
            {outside && (
              <path
                d={breachPath}
                fill="none"
                className={clsx(strokeClass, animate && "band-draw")}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            )}
          </>
        )}

        {eventAt !== null && eventAt >= 0 && eventAt <= 1 && (
          <line
            x1={eventAt * W}
            y1="0"
            x2={eventAt * W}
            y2={H}
            className="stroke-mute"
            strokeWidth="1"
            strokeDasharray="4 4"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>

      {(fromLabel || toLabel || bandLabel) && (
        <figcaption className="mt-2 flex items-baseline justify-between gap-4 text-micro text-mute">
          <span className="tnum font-mono">{fromLabel}</span>
          {bandLabel && <span className="truncate text-center">{bandLabel}</span>}
          <span className="tnum font-mono">{toLabel}</span>
        </figcaption>
      )}
    </figure>
  );
}
```

- [ ] **Step 2: Adicionar a animação do traço em `src/index.css`**

Dentro de `@layer components`:

```css
/* O único momento animado do produto: o traço se desenhando uma vez.
   A regra global de prefers-reduced-motion já zera a duração. */
.band-draw {
  stroke-dasharray: 2200;
  stroke-dashoffset: 2200;
  animation: band-draw 700ms cubic-bezier(0.22, 0.61, 0.36, 1) forwards;
}

@keyframes band-draw {
  to {
    stroke-dashoffset: 0;
  }
}
```

- [ ] **Step 3: Escrever `Mark.tsx`**

```tsx
import { clsx } from "clsx";

/**
 * A marca do AnomalyDetect: um recorte da faixa do normal, com o sinal
 * saindo dela. É o produto inteiro em vinte e quatro pixels, e fala a mesma
 * língua que a interface.
 */
export function Mark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 14" className={clsx("h-3.5 w-6 flex-shrink-0", className)} fill="none" aria-hidden="true">
      <pattern id="mark-hatch" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="4" stroke="currentColor" strokeWidth="0.75" opacity="0.42" />
      </pattern>
      <rect x="0" y="5" width="14" height="7" fill="url(#mark-hatch)" />
      <line x1="0" y1="5" x2="14" y2="5" stroke="currentColor" strokeWidth="0.75" opacity="0.42" />
      <path
        d="M0 9h9l3-7 3 11"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Assinatura completa: marca mais nome. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={clsx("flex items-center gap-2.5", className)}>
      <Mark className="text-ink" />
      <span className="font-display text-[0.9375rem] font-600 tracking-tight text-ink">AnomalyDetect</span>
    </span>
  );
}
```

- [ ] **Step 4: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Esperado: ambos passam.

- [ ] **Step 5: Verificação visual isolada**

Renderizar temporariamente na Dashboard, no topo, três casos e conferir cada um a olho:

```tsx
<NormalBand label="teste dentro" values={[40,42,39,44,41,43,40]} band={{from:0,to:61}} height={120}
  fromLabel="há 3 horas" toLabel="agora" bandLabel="normal daqui às 14h: até 61%" />
<NormalBand label="teste fora" values={[40,42,39,58,72,88,93]} band={{from:0,to:61}} breachTone="warn" height={120}
  fromLabel="há 3 horas" toLabel="agora" />
<NormalBand label="teste sem dados" values={[]} band={null} height={120} />
```

Conferir, nos temas escuro e claro: (a) no primeiro, nenhuma cor na tela e a hachura cobrindo toda a extensão; (b) no segundo, a hachura **parando** no ponto em que o traço sai e o trecho de saída em âmbar; (c) no terceiro, nada quebra e a área fica vazia sem erro; (d) o traço se desenha uma vez ao recarregar; (e) com `prefers-reduced-motion: reduce` ligado no SO, o traço aparece já completo. Remover o trecho de teste depois.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ui/NormalBand.tsx frontend/src/components/ui/Mark.tsx frontend/src/index.css
git commit -m "Design: faixa do normal como elemento-assinatura"
```

---

## Task 3: Barra superior e shell

**Files:**
- Create: `frontend/src/components/TopBar.tsx`
- Modify: `frontend/src/components/AppShell.tsx`

**Interfaces:**
- Consumes: `Wordmark` (Tarefa 2), `useAuth`, `useStatus`, `useTheme`, `anomaliesApi`, `usePolling`, `NotificationsBell`.
- Produces: `export function TopBar({ machineCount }: { machineCount: number })`. `AppShell` continua exportando `export function AppShell({ children }: { children: ReactNode })`.

- [ ] **Step 1: Escrever `TopBar.tsx`**

Requisitos exatos, sem margem de interpretação:

- Barra de 56px, `bg-paper`, filete inferior `border-rule`, `sticky top-0 z-30`.
- Conteúdo centrado em `max-w-instrument`, com `px-4 sm:px-8`.
- À esquerda: `<Wordmark />`, que é link para `/`.
- Ao centro-esquerda, `<nav aria-label="Seções">` com três links: `Situação` (`/`), `Alertas` (`/alertas`), `Perguntar` (`/perguntar`). Um quarto link `Computadores` (`/computadores`) só quando `machineCount >= 2`.
- Item ativo: `text-ink font-medium` mais um filete de 2px em `bg-ink` colado na borda inferior da barra. Inativo: `text-mute`, hover `text-ink`. `aria-current="page"` no ativo.
- Alertas em aberto: contagem em `font-mono text-micro text-mute` ao lado do rótulo, oculta quando zero. Buscar com `anomaliesApi.list({ hours: 168, unresolved_only: true })` em `usePolling(fetch, 45000)`, exatamente como o `AppShell` atual faz.
- À direita: `<NotificationsBell />`, botão de tema (`Sun`/`Moon`, `aria-label` alternando entre "Usar o tema claro" e "Usar o tema escuro") e link para `/conta` com a inicial do usuário num círculo de 28px.
- Quando `reachable === false`, uma linha abaixo da barra, largura total, `bg-warn/10 text-warn`, com ponto e o texto "Servidor fora de contato".
- Abaixo de `lg`: os links viram gaveta. Botão de menu (`Menu`, `aria-label="Abrir o menu"`, `aria-expanded`), gaveta `role="dialog" aria-modal="true"` deslizando da esquerda, fechando com `Escape`, com clique no fundo e ao mudar de rota. Reaproveitar a lógica de gaveta que já existe em `AppShell.tsx:47-56`.
- Todo alvo clicável com no mínimo 44px de altura efetiva.

- [ ] **Step 2: Reescrever `AppShell.tsx`**

Fica reduzido a: link "Ir para o conteúdo" (mantido como está), `<TopBar machineCount={...} />` e `<main id="conteudo">` com `mx-auto max-w-measure px-4 py-8 sm:px-8`. A `<aside>` lateral e todo o bloco `nav` saem.

`machineCount` vem de `machinesApi.list()` em `usePolling(fetch, 60000)`, guardado no próprio `AppShell`.

Adicionar a classe utilitária de rompimento em `index.css`, dentro de `@layer utilities`:

```css
/* A faixa rompe a coluna de leitura. Usada só pela NormalBand em página. */
.breakout {
  width: min(1040px, calc(100vw - 2rem));
  margin-left: 50%;
  transform: translateX(-50%);
}
```

- [ ] **Step 3: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 4: Verificação visual**

Com `npm run dev`: (a) a lateral sumiu e a barra superior aparece em todas as páginas logadas; (b) o item ativo muda ao navegar; (c) com uma máquina só, "Computadores" não aparece; (d) em 375px de largura a gaveta abre, fecha com `Escape`, fecha ao navegar; (e) `Tab` percorre todos os controles da barra com foco visível; (f) desligando o backend, a faixa "Servidor fora de contato" aparece.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/TopBar.tsx frontend/src/components/AppShell.tsx frontend/src/index.css
git commit -m "Frontend: barra superior no lugar da navegacao lateral"
```

---

## Task 4: Escolha de computador persistida

**Files:**
- Create: `frontend/src/hooks/useSelectedMachine.ts`
- Create: `frontend/src/components/situacao/MachineTabs.tsx`

**Interfaces:**
- Consumes: `Machine` de `src/types`.
- Produces:

```ts
export function useSelectedMachine(machines: Machine[]): {
  selected: Machine | null;
  selectedId: number | null;
  select: (id: number) => void;
};
export function MachineTabs(props: {
  machines: Machine[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  /** Alertas em aberto por id de computador. */
  openByMachine: Record<number, number>;
  /** Nível de estado por id de computador. */
  levelByMachine: Record<number, "ok" | "warn" | "crit" | "unknown">;
}): JSX.Element | null;
```

- [ ] **Step 1: Escrever `useSelectedMachine.ts`**

```ts
import { useCallback, useEffect, useState } from "react";
import { Machine } from "../types";

const KEY = "computador-selecionado";

/**
 * Qual computador a Situação está mostrando.
 *
 * Persiste entre sessões, porque quem tem mais de um quase sempre volta ao
 * mesmo. Se o computador guardado sumiu da lista — foi removido em outro
 * dispositivo — cai para a primeira máquina acompanhando, e só então para a
 * primeira da lista.
 */
export function useSelectedMachine(machines: Machine[]) {
  const [selectedId, setSelectedId] = useState<number | null>(() => {
    try {
      const raw = localStorage.getItem(KEY);
      return raw ? Number(raw) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (machines.length === 0) return;
    const stillThere = selectedId !== null && machines.some((m) => m.id === selectedId);
    if (stillThere) return;
    const fallback = machines.find((m) => m.is_active) ?? machines[0];
    setSelectedId(fallback.id);
  }, [machines, selectedId]);

  const select = useCallback((id: number) => {
    setSelectedId(id);
    try {
      localStorage.setItem(KEY, String(id));
    } catch {
      // Navegação privativa pode recusar a escrita; vale para a sessão.
    }
  }, []);

  const selected = machines.find((m) => m.id === selectedId) ?? null;
  return { selected, selectedId, select };
}
```

- [ ] **Step 2: Escrever `MachineTabs.tsx`**

Requisitos exatos:

- Com `machines.length <= 1`: retorna `null`. A pessoa com um computador nunca vê seletor.
- Com 2 a 5: `<div role="tablist">` com um botão por computador. Cada aba mostra ponto de estado (`ok`/`warn`/`crit`/`idle`), nome, e a contagem de alertas em aberto em `font-mono text-micro` quando maior que zero. Ativa: `text-ink font-medium` com filete de 2px `bg-ink` embaixo. Inativa: `text-mute`. `role="tab"`, `aria-selected`, navegação por setas esquerda/direita.
- Com 6 ou mais: um `<select>` rotulado "Computador" com a mesma informação em texto (`nome — N alertas`), mais uma linha acima, `text-support text-mute`, com o resumo da frota: `"{n} de {total} precisam de atenção"` quando houver algum fora de `ok`, ou `"Todos os {total} computadores estão normais"` quando não houver.
- O ponto de estado nunca é o único portador de significado: o `aria-label` de cada aba inclui a palavra do estado ("normal", "atenção", "problema", "sem leituras").

- [ ] **Step 3: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 4: Verificação visual**

Ainda não há tela que consuma — verificar na Tarefa 5. Aqui basta o build passar.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSelectedMachine.ts frontend/src/components/situacao/MachineTabs.tsx
git commit -m "Frontend: escolha de computador persistida e adaptativa"
```

---

## Task 5: Descobertas

**Files:**
- Create: `frontend/src/lib/discoveries.ts`
- Create: `frontend/src/components/situacao/Discoveries.tsx`
- Create: `frontend/src/pages/Descobertas.tsx`

**Interfaces:**
- Consumes: `insightsApi`, `reportsApi` de `src/services/api`.
- Produces:

```ts
export interface Discovery {
  key: string;
  sentence: string;
  tone?: "warn" | "crit";
  /** Menor é mais importante. */
  priority: number;
}
export function loadDiscoveries(machineId: number): Promise<Discovery[]>;
export function Discoveries(props: { items: Discovery[]; onSeeAll: () => void }): JSX.Element | null;
```

- [ ] **Step 1: Escrever `lib/discoveries.ts`**

Regras exatas, na ordem de prioridade da spec. Toda chamada usa `.catch(() => null)` — uma análise indisponível nunca derruba as outras. As frases vêm prontas do backend no campo `sentence`; o frontend **não** compõe texto a partir de números crus.

```ts
import { insightsApi, reportsApi } from "../services/api";

export interface Discovery {
  key: string;
  sentence: string;
  tone?: "warn" | "crit";
  priority: number;
}

/**
 * As análises que o sistema tem a dizer sobre um computador, num fluxo só.
 *
 * Antes viviam atrás de sete abas planas — inclusive as abas que não tinham
 * nada a dizer, que apareciam vazias. Aqui uma análise sem conteúdo
 * simplesmente não vira descoberta.
 */
export async function loadDiscoveries(machineId: number): Promise<Discovery[]> {
  const [forecast, upgrade, changes, energy, reports] = await Promise.all([
    insightsApi.forecast(machineId).then((r) => r.data).catch(() => null),
    insightsApi.upgrade(machineId).then((r) => r.data).catch(() => null),
    insightsApi.changes(machineId, 7).then((r) => r.data).catch(() => null),
    insightsApi.energy(machineId, 30).then((r) => r.data).catch(() => null),
    reportsApi.list(machineId).then((r) => r.data).catch(() => null),
  ]);

  const out: Discovery[] = [];

  if (forecast?.disk?.eta_days != null && forecast.disk.sentence) {
    out.push({
      key: "disco",
      sentence: forecast.disk.sentence,
      tone: forecast.disk.eta_days <= 7 ? "warn" : undefined,
      priority: 1,
    });
  }
  if (forecast?.battery?.health_now != null && forecast.battery.health_now < 80 && forecast.battery.sentence) {
    out.push({ key: "bateria", sentence: forecast.battery.sentence, tone: "warn", priority: 2 });
  }
  for (const leak of forecast?.leaks ?? []) {
    if (leak.sentence) {
      out.push({ key: `vazamento-${leak.process}`, sentence: leak.sentence, tone: "crit", priority: 3 });
    }
  }
  if (upgrade?.ready) {
    for (const rec of upgrade.recommendations ?? []) {
      if (rec.sentence) out.push({ key: `upgrade-${rec.component}`, sentence: rec.sentence, priority: 4 });
    }
  }
  for (const ch of changes?.changes ?? []) {
    if (ch.sentence && ch.effect) {
      out.push({ key: `mudanca-${ch.id ?? ch.sentence}`, sentence: ch.sentence, priority: 5 });
    }
  }
  if (energy?.waste?.sentence) {
    out.push({ key: "energia", sentence: energy.waste.sentence, tone: "warn", priority: 6 });
  }
  const unread = (reports ?? []).find((r: any) => !r.read_at);
  if (unread?.summary) {
    out.push({ key: `diario-${unread.id}`, sentence: unread.summary, priority: 7 });
  }

  return out.sort((a, b) => a.priority - b.priority);
}
```

- [ ] **Step 2: Escrever `Discoveries.tsx`**

Requisitos exatos:

- `items.length === 0` retorna `null`. Nunca renderiza seção vazia, nunca escreve "nenhuma descoberta ainda".
- Renderiza no máximo os **dois** primeiros itens.
- Cabeçalho: `<h2>` com o texto `Vale saber`, na classe `channel-label`.
- Cada item é uma linha de texto, **sem card e sem borda**: um marcador `·` em `text-mute` e a frase em `text-body text-ink`. Item com `tone` recebe a cor correspondente só no marcador, e a palavra do estado no `aria-label` da linha.
- Havendo mais de dois, um `ver todas ({items.length}) →` que chama `onSeeAll`.

- [ ] **Step 3: Escrever `pages/Descobertas.tsx`**

Página em `/descobertas`. Usa `useSelectedMachine`, chama `loadDiscoveries`, lista **todas** em fluxo único, sem abas e sem agrupamento. Cabeçalho com `PageHeader` título "Descobertas" e descrição "O que o sistema notou sobre este computador ao longo do tempo." Estado vazio via `EmptyState`, título "Nada a relatar ainda", corpo "O sistema precisa de alguns dias de uso para notar tendências. Volte depois."

- [ ] **Step 4: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 5: Verificação visual**

A rota ainda não está registrada — será na Tarefa 12. Verificar aqui apenas que o build passa e que `loadDiscoveries` não lança com backend desligado (chamar no console e conferir que resolve com `[]`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/discoveries.ts frontend/src/components/situacao/Discoveries.tsx frontend/src/pages/Descobertas.tsx
git commit -m "Frontend: analises promovidas a descobertas"
```

---

## Task 6: Veredito e indicadores

**Files:**
- Create: `frontend/src/components/situacao/Verdict.tsx`
- Create: `frontend/src/components/situacao/Indicators.tsx`

**Interfaces:**
- Consumes: `Level`, `Reading` de `src/lib/health`; `Anomaly`, `ANOMALY_TYPE_LABELS` de `src/types`; `NormalBand` da Tarefa 2; `timeAgo` de `src/lib/format`.
- Produces:

```ts
export function Verdict(props: {
  level: Level;
  openAlerts: Anomaly[];
  learning?: { collected: number; needed: number; ml_ready: boolean } | null;
  /** Qual medida está puxando o estado. */
  driver?: { label: string; value: string; expected?: string } | null;
  /** Dados da faixa, já resolvidos pela página. */
  bandProps: import("../ui/NormalBand").NormalBandProps | null;
  lastReadingAt?: string | null;
  paused?: boolean;
  onOpenAlert: (id: number) => void;
  onSeeAll: () => void;
}): JSX.Element;

export interface IndicatorItem {
  label: string;
  term: string;
  value: string;
  unit: string;
  reading: Reading;
}
export function Indicators({ items }: { items: IndicatorItem[] }): JSX.Element;
```

- [ ] **Step 1: Escrever `Verdict.tsx`**

Estrutura exata, nesta ordem, num bloco só — **nunca três blocos separados**:

1. Manchete em `font-display text-verdict`, com um símbolo antes quando não é normal (`▲` para atenção, `●` para crítico — nunca só cor). Cor: `text-ink` em normal, `text-warn` em atenção, `text-crit` em problema.
2. Havendo alerta aberto, uma linha `text-support text-mute` com o início: `Começou às HH:MM, {timeAgo}`.
3. Frase de apoio em `text-body text-mute`, largura máxima `max-w-prose`.
4. Um único botão, `Entender o problema`, quando há alerta aberto. Sem alerta aberto, nenhum botão.
5. Havendo mais de um alerta aberto, uma linha discreta: `e mais {n} alertas · ver todos`, em `text-support`, chamando `onSeeAll`.
6. `<NormalBand {...bandProps} className="breakout mt-8" />` quando `bandProps` não é nulo.
7. Abaixo da faixa, em `text-micro text-mute`: `Última leitura {timeAgo}` — ou `Coleta pausada` quando `paused`.
8. Quando `learning && !learning.ml_ready`, uma linha `text-micro text-mute`: `Aprendendo o normal deste computador — {collected} de {needed} leituras`, com o número em `font-mono`.

Manchetes, reaproveitando a lógica de severidade do `components/Verdict.tsx` atual (linhas 62-90) mas com o vocabulário novo:

| Condição | Manchete |
|---|---|
| algum alerta `critical` | `Precisa da sua atenção agora` |
| algum alerta `high` | `Precisa de atenção hoje` |
| há alerta aberto | `Há algo para olhar quando puder` |
| `level === "crit"` | `No limite da capacidade` |
| `level === "warn"` | `Sob pressão` |
| `level === "unknown"` | `Sem leituras ainda` |
| resto | `Tudo normal` |

Frase de apoio quando há `driver` e nenhum alerta aberto: `A {driver.label} está em {driver.value}` mais, quando `driver.expected` existe, `, acima do normal deste computador a esta hora ({driver.expected}).` Sem driver e sem alerta: `Nenhum alerta em aberto neste computador.`

A escala de três zonas do componente atual **não** é portada: a manchete já diz o estado, e a escala repetia a mesma informação numa segunda leitura.

- [ ] **Step 2: Escrever `Indicators.tsx`**

Requisitos exatos:

- Três itens, em `grid grid-cols-3 gap-6`. Sem card, sem borda, sem fundo.
- Por item: rótulo em `channel-label`; valor em `font-mono text-readout tnum` seguido da unidade em `text-support text-mute`; abaixo, a palavra do estado em `text-support` na cor do nível (`text-mute` quando `ok`, `text-warn`, `text-crit`).
- A cor nunca é o único portador: a palavra do estado está sempre escrita.
- Cada item tem `<Explain term={term} />` ao lado do rótulo.
- Abaixo de 480px, `grid-cols-1` com os itens em linha (rótulo à esquerda, valor à direita).

- [ ] **Step 3: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/situacao/Verdict.tsx frontend/src/components/situacao/Indicators.tsx
git commit -m "Frontend: veredito como bloco unico e indicadores sem card"
```

---

## Task 7: A tela Situação

Substitui `Dashboard`. Esta é a tarefa que entrega o critério central do redesign.

**Files:**
- Create: `frontend/src/pages/Situacao.tsx`
- Modify: `frontend/src/App.tsx` (só a rota `/`)

**Interfaces:**
- Consumes: `useSelectedMachine`, `MachineTabs`, `Verdict`, `Indicators`, `Discoveries`, `loadDiscoveries`, `NormalBand`, `health`, `worstLevel`, `THRESHOLDS`, `bandFor`, `usePolling`, `useWebSocket`, `machinesApi`, `metricsApi`, `anomaliesApi`.
- Produces: `export function Situacao(): JSX.Element`.

- [ ] **Step 1: Escrever `Situacao.tsx`**

A busca de dados é portada de `pages/Dashboard.tsx:41-97` sem alteração de comportamento: `usePolling(fetchAll, 60000)` para máquinas e alertas; ao trocar de computador, `Promise.all` de `metricsApi.list(id, 3)`, `latest`, `learning`, `baseline`; `useWebSocket` empurrando métrica nova e recarregando alertas. Manter o esqueleto durante a troca.

Adicionalmente, ao trocar de computador, chamar `loadDiscoveries(id)` e guardar em estado.

A estrutura renderizada é **exatamente** esta, nesta ordem, e nada mais:

```
<MachineTabs …/>                    (null com 1 computador)
<Verdict …/>                        (inclui a faixa e o carimbo de leitura)
<Indicators items={…}/>             (processador, memória, disco)
<Discoveries …/>                    (null quando não há)
<Link to=".../sistema">Ver informações do sistema →</Link>
```

Regras que a página deve cumprir:

- **Três indicadores, sempre os mesmos**: processador, memória, disco. A quarta medida de hoje (temperatura ou memória virtual) não aparece aqui.
- **Nenhum gráfico** além da faixa do veredito.
- **Nenhuma seção de alertas recentes.** O veredito já nomeia o alerta aberto.
- **Um único botão** no corpo da página (o `Entender o problema` do veredito). `Ver informações do sistema` é link textual, não botão. `Diagnosticar` e `Modo foco` não existem nesta tela.
- `StaleBanner` continua no topo, como hoje.
- Estado sem computador: `EmptyState` título "Nenhum computador conectado", corpo "Conecte o primeiro para começar a acompanhar. Leva cerca de dois minutos e não exige conhecimento técnico.", ação "Conectar um computador" para `/welcome`.
- Estado com computador e sem leitura: `EmptyState` título "Este computador ainda não enviou leituras", corpo "Confira se ele está ligado, com internet, e se o agente foi instalado. A primeira leitura chega em até 30 segundos depois disso."

A faixa passada ao veredito é montada assim, portando `bandOf` de `Dashboard.tsx:130-147`: usa o normal aprendido de `baseline.metrics[key].now` quando existe e não é `fallback`, com teto `min(max(p95, p50 + 3, 3), 100)`; senão usa `bandFor(metric)`. A métrica escolhida para a faixa é **a que está puxando o estado** — a pior entre processador, memória e disco; estando tudo normal, a memória.

`breachTone` só é passado quando a leitura também ultrapassa o limite de saúde. Sair do normal aprendido não é o mesmo que perigo: 60% de processador pode ser muito para aquela máquina às 3h e continuar saudável.

- [ ] **Step 2: Trocar a rota `/` em `App.tsx`**

Trocar o import de `Dashboard` por `Situacao` e o elemento da rota `/`. Não mexer nas outras rotas ainda.

- [ ] **Step 3: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 4: Verificação visual e contagem**

Com `npm run dev` e um computador saudável conectado, **contar na tela** e registrar os números:

- Unidades de informação (um valor, rótulo ou frase distinta; um indicador conta 3): deve ser **no máximo 16**.
- Controles no corpo, excluindo a barra superior e o seletor de computador: deve ser **no máximo 3**.
- Gráficos: **zero**, fora a faixa do veredito.
- Caixas com borda aninhadas: profundidade **no máximo 1**.

Conferir também: (a) em 375px a ordem é estado → alertas → ação → indicadores → detalhes; (b) `Tab` alcança tudo com foco visível; (c) com dois computadores as abas aparecem e trocam; (d) recarregando, o computador escolhido é lembrado.

Se qualquer contagem estourar, **cortar antes de commitar** — o número é o critério de aceitação, não uma meta.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Situacao.tsx frontend/src/App.tsx
git commit -m "Frontend: tela Situacao com revelacao progressiva"
```

---

## Task 8: Informações do sistema e histórico

**Files:**
- Create: `frontend/src/pages/Sistema.tsx`
- Create: `frontend/src/pages/Historico.tsx`
- Modify: `frontend/src/components/charts/MetricChart.tsx`

**Interfaces:**
- Consumes: `metricsApi`, `reputationApi`, `actionsApi`, `health`, `Layout` (`Section`, `DataList`, `DataRow`, `PanelLabel`), `DiagnoseButton`.
- Produces: `export function Sistema(): JSX.Element` e `export function Historico(): JSX.Element`, ambas lendo `:id` de `useParams`.

- [ ] **Step 1: Escrever `Sistema.tsx`**

Rota `/computadores/:id/sistema`. Três grupos, nesta ordem, cada um um `Section` com título em `channel-label` — **sem `Panel` em volta**, porque agrupamento não é objeto:

**MEDIDAS AGORA** — processador (com núcleos e frequência em `note`), memória (com `mem_used / mem_total`), disco (com livres), memória virtual, temperatura quando o sensor existir, GPU quando existir (uso, memória de vídeo, temperatura, modelo), bateria quando existir (carga, uso restante, saúde, ciclos), partições quando houver mais de uma.

**O QUE ESTÁ RODANDO** — programas rodando (`process_count`), fila do processador (`load_avg_1`, com a palavra de `health.loadAvg`), conexões abertas, ligado há (`uptime_seconds`). Mais a lista de programas de `reputationApi.programs(machineId)`, que é o conteúdo da antiga aba "Programas".

**REDE E DISCO** — enviando, recebendo, lendo do disco, gravando no disco.

No fim: link `Ver histórico das últimas horas →` para `/computadores/:id/sistema/historico`, e o `<DiagnoseButton />`, que vem do painel atual.

Toda linha usa `DataRow`, que já compõe o valor em mono e aceita `hint={<Explain term="…" />}`. Manter os `Explain` que hoje existem no painel para `uptime`, `processos`, `load`, `conexoes`, `swap`, `vram`, `particoes`, `saude_bateria`, `ciclos`.

- [ ] **Step 2: Escrever `Historico.tsx`**

Rota `/computadores/:id/sistema/historico`. Busca `metricsApi.list(id, 24)`. Renderiza **três** `MetricChart`: processador, memória e disco. O gráfico de "conexões de rede" que existe hoje **não** é portado — não sustenta decisão.

Cabeçalho com contagem de leituras e horário da última, como o painel faz hoje.

- [ ] **Step 3: Ajustar `MetricChart.tsx` aos tokens novos**

Trocar as referências de cor a `accent`, `fg-3`, `hairline`, `surface` pelas novas (`ink`, `mute`, `rule`, `field`). A linha de limite usa `crit`. Não alterar a API do componente.

- [ ] **Step 4: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 5: Verificação visual**

Rotas ainda não registradas (Tarefa 12) — navegar direto pela URL. Conferir: (a) os três grupos aparecem e nenhum tem caixa em volta; (b) toda medida está em mono; (c) nenhuma caixa aninhada além de profundidade 1; (d) o histórico tem três gráficos e nenhum de conexões; (e) os dois temas legíveis.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Sistema.tsx frontend/src/pages/Historico.tsx frontend/src/components/charts/MetricChart.tsx
git commit -m "Frontend: informacoes do sistema e historico em rotas proprias"
```

---

## Task 9: Alertas

**Files:**
- Rename: `frontend/src/pages/Anomalies.tsx` → `frontend/src/pages/Alertas.tsx`
- Modify: `frontend/src/components/AnomalyEvent.tsx`

**Interfaces:**
- Consumes: `anomaliesApi`, `machinesApi`, `Severity`, `usePolling`.
- Produces: `export function Alertas(): JSX.Element`.

- [ ] **Step 1: Renomear preservando histórico**

```bash
cd frontend && git mv src/pages/Anomalies.tsx src/pages/Alertas.tsx
```

- [ ] **Step 2: Recolher os filtros**

Renomear a função exportada para `Alertas`. A barra com os cinco controles (busca, período, severidade, computador, só em aberto) passa a viver dentro de um `<details>` cujo `<summary>` é `Filtrar`, alinhado à direita, fechado por padrão.

Regra: quando qualquer filtro estiver diferente do padrão, o `<details>` abre por conta própria (`open` controlado) e as fichas de filtro ativo removíveis — que já existem em `Anomalies.tsx:90-108` — continuam visíveis **fora** do `<details>`, para que um filtro esquecido nunca produza uma lista vazia que pareça "o sistema não está detectando nada".

Nenhum controle antes da primeira informação: a ordem da página é título, contagem, lista, e só então `Filtrar`.

- [ ] **Step 3: Aplicar o vocabulário**

Em toda a página, "aviso" vira "alerta". Título "Alertas". Descrição com alertas em aberto: `{n} alertas em aberto no período selecionado.` Sem nenhum: `Tudo que o sistema detectou fora do normal. Nada em aberto no momento.` Mensagens de toast: "Alerta resolvido." / "Alerta reaberto."

Os resolvidos ficam num `<details>` próprio, rotulado `Resolvidos ({n})`, fechado por padrão.

- [ ] **Step 4: Ajustar `AnomalyEvent.tsx`**

Cada linha de alerta: símbolo de severidade mais palavra (já feito por `Severity`), título traduzido por `ANOMALY_TYPE_LABELS`, nome do computador, tempo relativo, e à direita o link `Entender →` para `/alertas/{id}`. A linha inteira é clicável e focável, com `aria-label` completo.

Trocar tokens antigos pelos novos neste arquivo.

- [ ] **Step 5: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 6: Verificação visual**

Conferir: (a) zero controles antes da primeira informação — contar; (b) `Filtrar` abre e fecha; (c) aplicando um filtro e recarregando a seção, as fichas continuam à vista; (d) a palavra "aviso" não aparece em lugar nenhum (`grep -rn "aviso" src/pages/Alertas.tsx` deve voltar vazio); (e) severidade legível sem depender de cor.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src/pages frontend/src/components/AnomalyEvent.tsx
git commit -m "Frontend: Alertas sem filtros na frente da informacao"
```

---

## Task 10: Entender o problema

O centro do TCC. Reordena e recolhe; não remove nada.

**Files:**
- Rename: `frontend/src/pages/AnomalyDetail.tsx` → `frontend/src/pages/AlertaDetalhe.tsx`

**Interfaces:**
- Consumes: tudo que `AnomalyDetail` já consome, mais `NormalBand` e `metricsApi.baseline`.
- Produces: `export function AlertaDetalhe(): JSX.Element`.

- [ ] **Step 1: Renomear preservando histórico**

```bash
cd frontend && git mv src/pages/AnomalyDetail.tsx src/pages/AlertaDetalhe.tsx
```

- [ ] **Step 2: Reordenar em cinco blocos**

A ordem passa a ser exatamente esta, e a função exportada vira `AlertaDetalhe`:

1. **Cabeçalho** — voltar para `/alertas`; à direita, o seletor de nível de linguagem. Abaixo: símbolo de severidade, título traduzido, `{computador} · começou às HH:MM, {timeAgo}`.
2. **O QUE MUDOU** — um `NormalBand` com `height={72}`, alimentado por `context` (as métricas em volta do evento, já buscadas hoje) e pela faixa vinda de `metricsApi.baseline(machine_id)` para a métrica do alerta, com `eventAt` na posição da detecção e `breachTone` pela severidade. Abaixo, duas leituras em mono: `Normal a esta hora: até X` e `Agora: Y`. **Um gráfico só** — os `MetricChart` de hoje saem desta posição.
3. **POR QUE ISSO ESTÁ ACONTECENDO** — `explanation.summary` e as causas de `RankedCauses`.
4. **O QUE VOCÊ PODE FAZER** — `AdaptiveSteps` com os passos e o `Feedback` ("Isso resolveu?").
5. **`▸ Dados técnicos`** — um `Disclosure` fechado por padrão, com nota `score, modelo, evidências e histórico`. Dentro dele, **tudo** o que hoje está solto na página: `anomaly_score` e `model_used`, `evidence`, `VerificationBadge`, `DestinationTag`, `CounterfactualCard`, `provider_attempts`, `judge_scores`, `IncidentChain`, `Replay`, `AnomalyActions`, `ShareButton`, `RatingButtons`, e o botão de regerar explicação.

Nada é removido. Tudo que hoje aparece na página continua existindo — desce um nível.

- [ ] **Step 3: Ligar o seletor de nível de linguagem**

O seletor no cabeçalho oferece `Simples` e `Técnica`, mapeados para `leigo` e `tecnico` de `LANGUAGE_LEVEL_LABELS`. Ao trocar, chama `explanationsApi.variant(id, level)` e passa a renderizar `variant` no lugar de `explanation` nos blocos 3 e 4. A opção `intermediario` não é oferecida: dois níveis são uma escolha, três são um formulário.

Enquanto a variante carrega, manter o texto atual visível com `aria-busy`, nunca esvaziar a tela.

- [ ] **Step 4: Aplicar o vocabulário**

"aviso" vira "alerta" em toda a página, incluindo toasts.

- [ ] **Step 5: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 6: Verificação visual**

Com um alerta real ou gerado pela demonstração: (a) os cinco blocos na ordem certa; (b) um gráfico só acima de "Dados técnicos"; (c) `Dados técnicos` fechado ao abrir a página e contendo todos os itens listados no Step 2 — conferir um a um; (d) trocar Simples/Técnica muda o texto sem piscar; (e) `grep -rn "aviso" src/pages/AlertaDetalhe.tsx` volta vazio.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src/pages
git commit -m "Frontend: alerta em cinco blocos com dados tecnicos recolhidos"
```

---

## Task 11: Computadores, instalação, conta e sistema

**Files:**
- Rename: `frontend/src/pages/Machines.tsx` → `frontend/src/pages/Computadores.tsx`
- Rename: `frontend/src/pages/Account.tsx` → `frontend/src/pages/Conta.tsx`
- Create: `frontend/src/pages/Instalacao.tsx`
- Create: `frontend/src/pages/ContaSistema.tsx`
- Modify: `frontend/src/components/machines/MachineCard.tsx`

**Interfaces:**
- Produces: `export function Computadores()`, `export function Conta()`, `export function Instalacao()`, `export function ContaSistema()`.

- [ ] **Step 1: Renomear preservando histórico**

```bash
cd frontend && git mv src/pages/Machines.tsx src/pages/Computadores.tsx && git mv src/pages/Account.tsx src/pages/Conta.tsx
```

- [ ] **Step 2: Enxugar `Computadores.tsx`**

Renomear a função para `Computadores`. Remover `<FleetCompare />` e `<BulkEnrollPanel />` da página. Adicionar, ao fim, um link textual `Instalar em vários computadores →` para `/computadores/instalacao`.

Em `MachineCard.tsx`: a linha mostra nome, `hostname · os_type`, estado (ponto **mais palavra**), último contato, e a contagem de alertas em aberto quando houver. O bloco expansível de instalação/desinstalação continua como está — é conteúdo secundário já bem colocado. Trocar os tokens antigos pelos novos e o vocabulário ("acompanhando" / "pausado").

- [ ] **Step 3: Escrever `Instalacao.tsx`**

Rota `/computadores/instalacao`. Hospeda `<BulkEnrollPanel />` e `<FleetCompare />`, cada um numa `Section`. `PageHeader` título "Instalar em vários computadores", descrição "Chaves de instalação em lote e comparação entre os computadores conectados."

- [ ] **Step 4: Escrever `ContaSistema.tsx`**

Rota `/conta/sistema`. `PageHeader` título "Sistema", descrição "Medidas sobre o próprio AnomalyDetect e o modo demonstração." Duas `Section`: "Qualidade das explicações", com o corpo de `pages/Research.tsx`, e "Demonstração", com o corpo de `pages/Demo.tsx`.

Reaproveitar os componentes existentes em vez de reescrever: importar e renderizar `Research` e `Demo` sem seus próprios `PageHeader`. Para isso, extrair de cada um o corpo para um componente exportado (`ResearchBody`, `DemoBody`) e deixar as páginas antigas usando esse corpo — as páginas antigas serão substituídas por redirecionamento na Tarefa 12.

- [ ] **Step 5: Ajustar `Conta.tsx`**

Renomear a função para `Conta`. Acrescentar às seções existentes: **Modo foco** (vindo do painel, usando `FocusModeControl` por computador) e um link `Sistema →` para `/conta/sistema` no fim da página. Aplicar o vocabulário e os tokens novos.

- [ ] **Step 6: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 7: Verificação visual**

Conferir: (a) a lista de computadores não mostra nenhuma métrica; (b) o estado tem ponto e palavra; (c) `/computadores/instalacao` mostra chaves em lote e comparação; (d) `/conta/sistema` mostra as duas seções funcionando, incluindo iniciar um cenário de demonstração; (e) `Modo foco` funciona a partir da conta.

- [ ] **Step 8: Commit**

```bash
git add -A frontend/src
git commit -m "Frontend: computadores enxuto, instalacao e area de sistema"
```

---

## Task 12: Login e roteamento completo

**Files:**
- Modify: `frontend/src/pages/Login.tsx`
- Modify: `frontend/src/pages/Register.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces: rotas novas e redirecionamentos das antigas.

- [ ] **Step 1: Reescrever o layout do `Login.tsx`**

Duas partes no desktop (`lg:grid lg:grid-cols-[1.1fr_1fr]`), empilhado abaixo disso. Nenhuma mudança na lógica de autenticação, no Google Sign-In ou nas mensagens de `conta=criada` e `sessao=expirada`.

**Painel esquerdo** (`bg-field`, `border-r border-rule`, escondido abaixo de `lg`): `<Wordmark />` no topo; abaixo, centrado verticalmente, uma frase em `font-display text-title`: `O sistema aprende o que é normal no seu computador e avisa quando algo sai disso.`; sob ela, um `<NormalBand />` em repouso — valores estáveis dentro da faixa, `animate`, sem rótulos de eixo — como demonstração silenciosa do produto. Nenhum outro conteúdo: nada de lista de recursos, nada de estatística.

**Painel direito**: o formulário, largura máxima `24rem`, centrado. `<h1>` "Entrar" em `font-display text-title`. Campos com altura mínima de 44px.

Remover a largura fixa de 320px do botão do Google: passar `width: undefined` e deixar o contêiner controlar, com `className="w-full [&>div]:!w-full"` no `googleBtnRef`.

Aplicar o mesmo layout em `Register.tsx`, com a frase e o título próprios ("Criar conta").

- [ ] **Step 2: Reescrever as rotas em `App.tsx`**

Rotas privadas:

```
/                                          Situacao
/descobertas                               Descobertas
/alertas                                   Alertas
/alertas/:id                               AlertaDetalhe
/perguntar                                 Chat
/computadores                              Computadores
/computadores/instalacao                   Instalacao
/computadores/:id/sistema                  Sistema
/computadores/:id/sistema/historico        Historico
/conta                                     Conta
/conta/sistema                             ContaSistema
/welcome                                   Welcome
*                                          NotFound
```

Rotas públicas inalteradas: `/login`, `/register`, `/compartilhado/:token`.

Redirecionamentos, todos com `<Navigate replace />`:

```
/machines            → /computadores
/machines/:id        → /computadores/:id/sistema
/anomalies           → /alertas
/anomalies/:id       → /alertas/:id
/pergunte            → /perguntar
/pesquisa            → /conta/sistema
/demonstracao        → /conta/sistema
/account             → /conta
/sistema             → /computadores/{primeira máquina}/sistema
```

O último precisa de um componente pequeno que busca `machinesApi.list()` e redireciona para a primeira ativa; sem nenhuma, vai para `/`.

- [ ] **Step 3: Aplicar o vocabulário no `Chat.tsx`**

Título "Perguntar". Descrição: "Pergunte em português sobre o histórico deste computador — por que ficou lento, o que mudou, o que consome mais." Trocar tokens antigos pelos novos.

- [ ] **Step 4: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

- [ ] **Step 5: Verificação visual**

Abrir **cada uma** das nove rotas antigas e confirmar que redireciona para a nova. Abrir cada uma das treze rotas novas e confirmar que renderiza. No login: conferir em 1440px, 768px e 375px; conferir que o botão do Google acompanha a largura do formulário; conferir `Tab` e foco visível.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Login.tsx frontend/src/pages/Register.tsx frontend/src/pages/Chat.tsx frontend/src/App.tsx
git commit -m "Frontend: login em duas partes e roteamento novo com redirecionamentos"
```

---

## Task 13: Remover a andaimaria e auditar (FASE 7)

**Files:**
- Modify: `frontend/tailwind.config.js`
- Delete: `frontend/src/components/ui/VitalStrip.tsx`, `SignalTrace.tsx`, `SignalMark.tsx`, `frontend/src/components/Verdict.tsx`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/pages/MachineDetail.tsx`
- Create: `docs/superpowers/notes/2026-09-12-auditoria-antes-depois.md`

- [ ] **Step 1: Confirmar que nada importa os arquivos a remover**

```bash
cd frontend/src && grep -rn "VitalStrip\|SignalTrace\|SignalMark\|from \"./Verdict\"\|pages/Dashboard\|MachineDetail" . || echo "nenhuma referencia"
```

Esperado: `nenhuma referencia`. Havendo alguma, corrigir a importação antes de apagar.

`FreshnessTag.tsx` importa `LiveDot` de `SignalTrace` — mover `LiveDot` para dentro de `FreshnessTag.tsx`, que é o único consumidor.

- [ ] **Step 2: Apagar os arquivos**

```bash
cd frontend && git rm src/components/ui/VitalStrip.tsx src/components/ui/SignalTrace.tsx \
  src/components/ui/SignalMark.tsx src/components/Verdict.tsx \
  src/pages/Dashboard.tsx src/pages/MachineDetail.tsx
```

- [ ] **Step 3: Remover os aliases de token**

Apagar de `tailwind.config.js` as nove entradas marcadas como "Aliases temporários": `canvas`, `surface`, `raised`, `sunken`, `hairline`, `edge`, `fg`, `fg-2`, `fg-3`, `accent`, `inverse`, `inverse-fg`.

- [ ] **Step 4: Encontrar e corrigir todo uso remanescente**

```bash
cd frontend/src && grep -rnE "\b(bg|text|border|stroke|fill|ring|divide)-(canvas|surface|raised|sunken|hairline|edge|fg|fg-2|fg-3|accent|inverse|inverse-fg)\b" . || echo "limpo"
```

Corrigir cada ocorrência pela equivalência da Tarefa 1. Repetir até imprimir `limpo`.

- [ ] **Step 5: Verificar tipo e build**

```bash
cd frontend && npx tsc --noEmit && npm run build
```

Esperado: ambos passam. Se o build passar mas a tela ficar sem estilo, é sinal de classe inexistente — voltar ao Step 4.

- [ ] **Step 6: Auditoria comparativa**

Percorrer o app inteiro nos dois temas e em 1440px, 768px e 375px. Escrever `docs/superpowers/notes/2026-09-12-auditoria-antes-depois.md` com a tabela de cada critério de aceitação da spec, coluna ANTES (números da auditoria original: ~60 unidades, 12 controles, 5 itens de menu, 5 filtros à frente, 4 gráficos) e coluna DEPOIS medida de fato, mais o veredito de cada linha.

Registrar honestamente qualquer critério não atingido, com o motivo — um número inventado destrói o valor da auditoria.

Incluir o teste do usuário leigo: pedir a alguém que nunca viu o sistema para abrir e responder, sem ajuda, "o computador está bem?", "há algum problema?" e "onde vejo mais detalhes?". Anotar onde a pessoa hesitou.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Frontend: remover componentes aposentados e aliases de transicao"
```

---

## Self-review

**Cobertura da spec.** Menu de 3 itens → T3. Adaptação por escala → T4, T7. Situação → T6, T7. Informações do sistema → T8. Histórico → T8. Alertas → T9. Entender o problema → T10. Computadores → T11. Instalação → T11. Conta e Sistema → T11. Login → T12. Descobertas → T5. Tabela de destino das superfícies → T8 (Programas), T11 (Privacidade, Energia), T5 (Previsões, Diário, Mudanças, Upgrade), T12 (Pesquisa, Demonstração). Paleta e tipografia → T1. Faixa do normal → T2. Movimento → T2. Vocabulário → T9, T10, T11, T12. Redirecionamentos → T12. Critérios de aceitação → T7 (contagem da Situação), T13 (auditoria completa). Sem lacunas.

**Consistência de tipos.** `NormalBandProps` definida em T2 e consumida em T6, T7, T10, T12 com o mesmo nome. `Discovery` e `loadDiscoveries` definidas em T5, consumidas em T5 e T7. `useSelectedMachine` retorna `{ selected, selectedId, select }` em T4, usado assim em T5 e T7. `MachineTabs` recebe `openByMachine` e `levelByMachine` em T4, providos em T7. `IndicatorItem` definida em T6, construída em T7.

**Riscos conhecidos.** T1 muda a escala de tipo por baixo de todas as páginas ainda não migradas: entre T1 e T13 a interface fica visualmente inconsistente. É esperado e o build continua passando. T11 Step 4 exige extrair o corpo de `Research` e `Demo`; se esses arquivos resistirem à extração, a alternativa aceitável é montar `ContaSistema` como duas rotas filhas em vez de duas seções — decisão do executor, sem voltar ao plano.
