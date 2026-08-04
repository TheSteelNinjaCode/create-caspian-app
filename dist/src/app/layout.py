from casp.component_decorator import html


def layout():
    return html(r"""
<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="UTF-8" />
  <meta name="viewport"
        content="width=device-width, initial-scale=1.0" />
  <title>{{ metadata.title | default("Caspian App") }}</title>
  <meta name="description"
        content="{{ metadata.description | default('Powered by Caspian Framework') }}" />
  {#
    Everything a page put in `Metadata(extra={...})` -- robots, canonical,
    Open Graph, Twitter cards. The page pipeline already merges `extra` into
    this dict; without this loop it collected those values and dropped them,
    so `extra` silently did nothing. Open Graph is keyed by `property`, every
    other vocabulary by `name`.
  #}
  {% for meta_name, meta_content in (metadata | default({})).items()
     if meta_name not in ("title", "description") and meta_content %}
  {% if meta_name.startswith("og:") %}
  <meta property="{{ meta_name }}" content="{{ meta_content }}" />
  {% else %}
  <meta name="{{ meta_name }}" content="{{ meta_content }}" />
  {% endif %}
  {% endfor %}
  <link rel="icon"
        href="/favicon.ico"
        type="image/x-icon"
        sizes="16x16" />
</head>

<body style="
      opacity: 0;
      pointer-events: none;
      user-select: none;
      transition: opacity 0.18s ease-out;
    ">
  <slot />
</body>

</html>
""")
