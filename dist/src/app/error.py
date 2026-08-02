from typing import Optional
from casp.component_decorator import html
from casp.layout import Metadata


metadata = Metadata(
    title="Application Error",
    description="An unexpected error occurred.",
    extra={"robots": "noindex, nofollow"},
)


def page(error_message: str, error_trace: Optional[str] = None):
    return html(r"""
<main class="container py-10">
  <div class="mx-auto max-w-2xl rounded bg-white p-6 shadow-sm">
    <div class="flex items-start gap-4">
      <svg class="h-10 w-10 text-red-600"
           viewBox="0 0 24 24"
           fill="none"
           xmlns="http://www.w3.org/2000/svg"
           aria-hidden="true">
        <path d="M11.001 2a1 1 0 0 1 .998 0L21 7v9a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V7l8.001-5z"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round" />
        <path d="M12 8v4"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round" />
        <path d="M12 16h.01"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round" />
      </svg>

      <div class="flex-1">
        <h1 class="text-2xl font-semibold text-red-600">Something went wrong</h1>
        <p class="mt-2 text-sm text-gray-600">
          We're sorry—an unexpected error occurred. Try reloading or return to
          the homepage.
        </p>
        <p class="mt-3 text-sm text-gray-700">{{ error_message }}</p>

        <div class="mt-4 flex flex-wrap gap-2">
          <a href="/"
             class="inline-block rounded border border-gray-200 bg-gray-100 px-3 py-1.5 text-sm text-gray-800 hover:bg-gray-200">
            Home
          </a>
          <button class="inline-block rounded bg-blue-600 px-3 py-1.5 text-sm text-white"
                  onclick="window.location.reload()">
            Reload
          </button>
          {% if error_trace %}
          <button class="inline-block rounded border border-gray-200 bg-transparent px-3 py-1.5 text-sm text-black"
                  onclick="setShowTrace(current => !current)">
            {showTrace ? "Hide details" : "Show details"}
          </button>
          {% endif %}
        </div>
      </div>
    </div>

    {% if error_trace %}
    <section class="mt-4" hidden="{!showTrace}">
      <div class="mb-2 flex items-center justify-between">
        <div class="text-xs text-gray-500">Error details (development only)</div>
        <div class="flex gap-2">
          <button class="rounded border bg-gray-100 px-2 py-1 text-xs text-black"
                  onclick="copyTrace()">
            {traceCopied ? "Copied" : "Copy"}
          </button>
          <button class="rounded border bg-gray-100 px-2 py-1 text-xs text-black"
                  onclick="downloadTrace()">
            Download
          </button>
        </div>
      </div>
      <pre pp-ref="{tracePre}"
           class="overflow-auto rounded bg-gray-100 p-4 text-xs text-black">{{ error_trace }}</pre>
    </section>
    {% endif %}

    <script>
      const [showTrace, setShowTrace] = pp.state(false);
      const [traceCopied, setTraceCopied] = pp.state(false);
      const tracePre = pp.ref(null);

      async function copyTrace() {
        if (!tracePre.current) return;
        await navigator.clipboard.writeText(tracePre.current.innerText);
        setTraceCopied(true);
        setTimeout(() => setTraceCopied(false), 2000);
      }

      function downloadTrace() {
        if (!tracePre.current) return;
        const blob = new Blob([tracePre.current.innerText], { type: "text/plain" });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = "error_trace.txt";
        link.click();
        URL.revokeObjectURL(url);
      }
    </script>
  </div>
</main>
""", error_message=error_message, error_trace=error_trace)
