# product-taxonomy-viewer

Static viewer for Shopify's internal (in-development) product taxonomy. Mirrors
the UX of the [public viewer](https://shopify.github.io/product-taxonomy/releases/unstable/)
but pre-renders every page so GitHub Pages can serve it without Jekyll.

The taxonomy data itself lives in the private
[Shopify/product-taxonomy-internal](https://github.com/Shopify/product-taxonomy-internal)
repo — this repo only carries the viewer (generator, templates, hand-written
assets) and the rendered output GH Pages serves.

## Regenerating

```sh
# one-time: clone the internal repo next to this one
git clone git@github.com:Shopify/product-taxonomy-internal.git ../product-taxonomy-internal

uv run python scripts/generate_docs_site.py
git add docs && git commit -m "docs: regenerate viewer"
```

See [docs/README.md](docs/README.md) for full details and the GitHub Pages
configuration steps.
