from casp.component_decorator import html


def page():
    return html(r"""
<main class="flex min-h-screen flex-col justify-between gap-16 bg-background px-6 py-8 text-foreground md:px-12 md:py-12">
  <header class="flex items-center justify-between gap-4">
    <p class="border border-border px-4 py-2 font-mono text-xs text-muted-foreground">
      Get started by editing
      <code class="text-foreground">src/app/index.py</code>
    </p>

    <a class="flex items-center gap-2 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground transition-colors hover:text-foreground"
       href="https://github.com/TheSteelNinjaCode/create-caspian-app"
       target="_blank"
       rel="noreferrer">
      <span class="hidden sm:inline">Built with Caspian</span>

      <svg class="size-5"
           xmlns="http://www.w3.org/2000/svg"
           viewBox="0 0 24 24"
           fill="none"
           stroke="currentColor"
           stroke-width="2"
           stroke-linecap="round"
           stroke-linejoin="round"
           aria-hidden="true">
        <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.3 1.15-.3 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65-.17.6-.22 1.23-.15 1.85v4" />
        <path d="M9 18c-4.51 2-5-2-7-2" />
      </svg>
    </a>
  </header>

  <div class="flex flex-col items-center text-center">
    <img class="size-20 object-contain md:size-24"
         src="/favicon.ico"
         alt="Caspian" />

    <h1 class="mt-8 text-5xl font-bold tracking-[-0.04em] md:text-7xl">CASPIAN</h1>

    <p class="mt-5 max-w-md text-pretty text-muted-foreground">
      The native Python framework, with
      <span class="text-foreground">PulsePoint</span> reactivity.
    </p>
  </div>

  <nav class="grid gap-px border border-border bg-border sm:grid-cols-2 lg:grid-cols-4">
    <a class="group bg-background p-6 transition-colors hover:bg-muted/50"
       href="https://caspian.tsnc.tech/docs"
       target="_blank"
       rel="noreferrer">
      <h2 class="flex items-center gap-2 font-semibold">
        Docs
        <span class="transition-transform group-hover:translate-x-1 motion-reduce:transform-none">&rarr;</span>
      </h2>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
        Everything about routing, layouts, components and PulsePoint.
      </p>
    </a>

    <a class="group bg-background p-6 transition-colors hover:bg-muted/50"
       href="https://caspian.tsnc.tech/docs/rpc"
       target="_blank"
       rel="noreferrer">
      <h2 class="flex items-center gap-2 font-semibold">
        RPC
        <span class="transition-transform group-hover:translate-x-1 motion-reduce:transform-none">&rarr;</span>
      </h2>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
        Call a Python function straight from a click, no endpoint to write.
      </p>
    </a>

    <a class="group bg-background p-6 transition-colors hover:bg-muted/50"
       href="https://caspian.tsnc.tech/docs/database"
       target="_blank"
       rel="noreferrer">
      <h2 class="flex items-center gap-2 font-semibold">
        Schema
        <span class="transition-transform group-hover:translate-x-1 motion-reduce:transform-none">&rarr;</span>
      </h2>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">
        Define your models in <code class="font-mono text-xs">schema.prisma</code> and query them with types.
      </p>
    </a>

    <a class="group bg-background p-6 transition-colors hover:bg-muted/50"
       href="https://caspian.tsnc.tech/docs/deploy"
       target="_blank"
       rel="noreferrer">
      <h2 class="flex items-center gap-2 font-semibold">
        Deploy
        <span class="transition-transform group-hover:translate-x-1 motion-reduce:transform-none">&rarr;</span>
      </h2>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">Ship your Python app to Vercel, Railway or Docker.</p>
    </a>
  </nav>
</main>
""")
