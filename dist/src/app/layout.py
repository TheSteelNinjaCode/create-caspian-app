def layout():
    return r"""
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{{ metadata.title | default("Caspian App") }}</title>
    <meta
      name="description"
      content="{{ metadata.description | default('Powered by Caspian Framework') }}"
    />
    {% if metadata.robots %}
    <meta name="robots" content="{{ metadata.robots }}" />
    {% endif %}
    <link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="16x16" />
    <link href="/css/styles.css" rel="stylesheet" />
    <script type="module" src="/js/main.js"></script>
</head>

  <body
    style="
      opacity: 0;
      pointer-events: none;
      user-select: none;
      transition: opacity 0.18s ease-out;
    "
  >
    <slot />
  </body>
</html>
"""
