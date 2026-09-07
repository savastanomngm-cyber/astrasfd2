import { Button } from '@/components/ui/button'
import { ArrowRight, BarChart3, FileSearch, GitBranch, PlayCircle } from 'lucide-react'

const features = [
  {
    icon: FileSearch,
    title: 'Import & Audit',
    description:
      'Ingest tick-level futures data. Automated integrity checks surface gaps, outliers, and session boundary anomalies before research begins.',
  },
  {
    icon: BarChart3,
    title: 'Gamma Analytics',
    description:
      'Pinpoint dealer strike exposure, gamma flip zones, and open-interest gravity wells. Visualise the option-driven flows that move ES & NQ.',
  },
  {
    icon: GitBranch,
    title: 'Walk-Forward Research',
    description:
      'Design signal hypotheses, run them across rolling windows, and measure out-of-sample stability — no peeking, no survivorship bias.',
  },
  {
    icon: PlayCircle,
    title: 'Causal Replay',
    description:
      'Step through historical sessions tick-by-tick. Observe how order-book pressure, absorption, and sweep events cascade into price discovery.',
  },
]

export default function Page() {
  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Ambient background glow */}
      <div className="pointer-events-none fixed inset-0 z-0">
        <div className="absolute -top-80 left-1/2 h-[600px] w-[600px] -translate-x-1/2 rounded-full bg-gamma/8 blur-[120px]" />
        <div className="absolute top-1/3 right-1/4 h-[400px] w-[400px] rounded-full bg-gamma/5 blur-[100px]" />
      </div>

      <main className="relative z-10 flex min-h-screen flex-col">
        {/* ───── Hero ───── */}
        <section className="flex flex-1 flex-col items-center justify-center px-4 pt-24 pb-16 text-center sm:px-8">
          {/* Badge */}
          <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-gamma/25 bg-gamma-subtle px-4 py-1.5 text-xs font-medium tracking-wider text-gamma-light uppercase">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-gamma-light/60 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-gamma-light" />
            </span>
            Research Terminal
          </div>

          {/* Heading */}
          <h1 className="max-w-3xl text-5xl font-bold tracking-tight sm:text-6xl lg:text-7xl">
            <span className="bg-gradient-to-b from-white to-white/60 bg-clip-text text-transparent">
              Γ
            </span>{' '}
            <span className="bg-gradient-to-b from-gamma-light via-gamma to-gamma-light/60 bg-clip-text text-transparent">
              Gamma Lab
            </span>
          </h1>

          <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground sm:text-xl">
            Order-flow research terminal for{' '}
            <span className="font-semibold text-foreground">ES</span> &amp;{' '}
            <span className="font-semibold text-foreground">NQ</span> futures
          </p>

          {/* CTA */}
          <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
            <a
              href="https://github.com/savastanomngm-cyber/astrasfd2"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button
                variant="default"
                size="lg"
                className="gap-2 bg-gamma px-6 text-sm font-medium shadow-lg shadow-gamma/20 transition-all hover:bg-gamma-light hover:shadow-gamma/30"
              >
                View on GitHub
                <ArrowRight className="size-4" />
              </Button>
            </a>
          </div>
        </section>

        {/* ───── Features ───── */}
        <section className="px-4 pb-24 sm:px-8">
          <div className="mx-auto max-w-5xl">
            <p className="mb-2 text-center text-xs font-medium tracking-widest text-muted-foreground uppercase">
              Capabilities
            </p>
            <div className="mt-8 grid gap-px overflow-hidden rounded-2xl border border-border bg-border/30 sm:grid-cols-2">
              {features.map(({ icon: Icon, title, description }) => (
                <div
                  key={title}
                  className="group relative bg-card p-6 transition-colors hover:bg-card/80 sm:p-8"
                >
                  <div className="mb-5 inline-flex rounded-xl border border-gamma/15 bg-gamma-subtle p-3 text-gamma-light transition-colors group-hover:border-gamma/30 group-hover:bg-gamma-subtle/80">
                    <Icon className="size-5" />
                  </div>
                  <h3 className="text-lg font-semibold text-foreground">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                    {description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ───── Disclaimer ───── */}
        <section className="border-t border-border/50 px-4 py-10 sm:px-8">
          <div className="mx-auto max-w-3xl text-center">
            <div className="inline-flex items-center gap-2 rounded-lg border border-border/40 bg-secondary/40 px-4 py-2.5 text-xs leading-relaxed text-muted-foreground">
              <span className="select-none text-gamma-light">ⓘ</span>
              Historical research only. No live feed. No order routing. Local-first.
            </div>
          </div>
        </section>

        {/* ───── Footer ───── */}
        <footer className="border-t border-border/50 px-4 py-8 sm:px-8">
          <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-4 text-sm text-muted-foreground sm:flex-row">
            <p>
              <span className="font-semibold text-foreground">Gamma Lab</span>{' '}
              &mdash; open-source order-flow research
            </p>
            <a
              href="https://github.com/savastanomngm-cyber/astrasfd2"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-muted-foreground transition-colors hover:text-gamma-light"
            >
              <svg className="size-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
                />
              </svg>
              GitHub
            </a>
          </div>
        </footer>
      </main>
    </div>
  )
}
