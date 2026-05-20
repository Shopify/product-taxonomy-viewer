# Internal product-taxonomy viewer

Static site that lets people browse the *internal* (in-development) Shopify
product taxonomy. Mirrors the UX of the public viewer at
<https://shopify.github.io/product-taxonomy/releases/unstable/> but pre-renders
every page so GitHub Pages can serve it without Jekyll.

The taxonomy data itself lives in the private
[Shopify/product-taxonomy-internal](https://github.com/Shopify/product-taxonomy-internal)
repo — this repo only carries the viewer (generator, templates, hand-written
assets) and the rendered output that GH Pages serves.

Pure static HTML/JS — no Jekyll, no Ruby. `.nojekyll` tells GitHub Pages to
serve files as-is. Once the repo is public, configure under **Settings → Pages
→ Source: Deploy from a branch → `main` / `/docs`**.

## Regenerating

The generator reads from a local checkout of the internal repo (defaults to a
sibling directory):

```sh
# one-time: clone the internal repo next to this one
git clone git@github.com:Shopify/product-taxonomy-internal.git ../product-taxonomy-internal

# regenerate
uv run python scripts/generate_docs_site.py
git add docs
git commit -m "docs: regenerate viewer"
```

Point at a different location with `--source-dir` or `$INTERNAL_TAXONOMY_DIR`:

```sh
uv run python scripts/generate_docs_site.py --source-dir /path/to/product-taxonomy-internal/src/taxonomy
```

This regenerates:

- `docs/index.html` — landing page.
- `docs/releases/unstable/index.html` — categories view (pre-rendered, ~27MB).
- `docs/releases/unstable/attributes/index.html` — attributes view (~38MB).
- `docs/releases/unstable/values/index.html` — values view.
- `docs/releases/unstable/search_index.json` — fuse.js category index.
- `docs/releases/unstable/attribute_search_index.json` — fuse.js attribute index.
- `docs/releases/unstable/value_search_index.json` — fuse.js value index.

The Jinja2 templates live in [`scripts/site_templates/`](../scripts/site_templates/).
The shared assets (`docs/assets/styles.css`, `docs/assets/js/*.js`) are
hand-written and untouched by the generator.

## Local preview

```sh
cd docs
python3 -m http.server 8000
```

Open <http://localhost:8000/> and click "Explore unstable".

## Differences from the public viewer

- **No channel mappings column.** Internal taxonomy has no Google/Argo mappings yet.
- **Extended attributes use their handle as the ID badge** because the source data
  files don't assign GIDs to extended attributes. (The 318 extended attrs are joined
  to their bases via the `values_from` field.)
- **Pre-rendered, not Jekyll.** The page sizes are large because every category and
  every attribute is emitted inline (just like the public viewer's build does); JS
  toggles visibility. This works fine over GH Pages' gzipped transport.
