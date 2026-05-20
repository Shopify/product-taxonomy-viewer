#!/usr/bin/env python3
"""Generate the static taxonomy viewer under docs/.

The taxonomy source data lives in the private Shopify/product-taxonomy-internal
repo. This script expects a local checkout of that repo and reads:

    <source-dir>/dist/en/taxonomy.json     — compiled taxonomy
    <source-dir>/data/attributes.json      — base + extended attributes
    <source-dir>/VERSION                   — version string

…and writes:

    docs/
        index.html                             — landing page
        .nojekyll                              — disables Jekyll on GH Pages
        releases/unstable/
            index.html                         — categories view
            search_index.json                  — fetched by category_release.js
            attributes/index.html              — attributes view
            attribute_search_index.json        — fetched by attribute_release.js
            values/index.html                  — values view
            value_search_index.json            — fetched by value_release.js

Assets (docs/assets/styles.css, docs/assets/js/*.js) and docs/.nojekyll are
hand-written and unchanged by this script.

Source-dir resolution order:
    1. --source-dir CLI arg
    2. $INTERNAL_TAXONOMY_DIR env var
    3. ../product-taxonomy-internal/src/taxonomy/ (sibling checkout)

Usage:
    uv run python scripts/generate_docs_site.py
    uv run python scripts/generate_docs_site.py --source-dir /path/to/src/taxonomy
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
TEMPLATES = Path(__file__).resolve().parent / "site_templates"
DEFAULT_SOURCE_DIR = REPO_ROOT.parent / "product-taxonomy-internal" / "src" / "taxonomy"

RELEASE_TITLE = "unstable"
RELEASE_GITHUB_URL = "https://github.com/Shopify/product-taxonomy-internal/tree/main/src/taxonomy"


def _iter_categories(taxonomy: dict):
    for vertical in taxonomy["verticals"]:
        for category in vertical["categories"]:
            yield category


def build_sibling_groups(taxonomy: dict):
    """Return a list of (depth, [(parent_id, [category_view, ...]), ...]).

    The shape mirrors the public viewer's `sibling_groups.yml`: outer iteration
    by depth (insertion-ordered), inner by parent. We emit lists (not dicts) so
    Jinja2 iteration is predictable.
    """
    groups: dict[int, dict[str, list[dict]]] = {}
    flat: list[dict] = []
    for category in _iter_categories(taxonomy):
        level = category["level"]
        parent_id = category["parent_id"] or "root"
        ancestor_ids = ",".join(a["id"] for a in category["ancestors"])
        attribute_handles = ",".join(a["handle"] for a in category["attributes"])
        node_type = "root" if level == 0 else "leaf"
        entry = {
            "id": category["id"],
            "name": category["name"],
            "fully_qualified_type": category["full_name"],
            "depth": level,
            "parent_id": parent_id,
            "node_type": node_type,
            "ancestor_ids": ancestor_ids,
            "attribute_handles": attribute_handles,
        }
        groups.setdefault(level, {}).setdefault(parent_id, []).append(entry)
        flat.append(entry)

    by_depth = sorted(groups.items(), key=lambda kv: kv[0])
    nested = [(depth, list(parents.items())) for depth, parents in by_depth]
    return nested, flat


def _load_extended_index(source_attrs: Path) -> dict[str, list[dict]]:
    """Pair each extended attribute with its base via values_from -> friendly_id."""
    with source_attrs.open() as f:
        src = json.load(f)
    fid_to_handle = {b["friendly_id"]: b["handle"] for b in src["base_attributes"]}
    by_base: dict[str, list[dict]] = {}
    for ext in src["extended_attributes"]:
        base_handle = fid_to_handle.get(ext["values_from"])
        if base_handle is None:
            continue
        by_base.setdefault(base_handle, []).append(
            {"handle": ext["handle"], "name": ext["name"]}
        )
    return by_base


def build_attributes(taxonomy: dict, extended_by_base: dict[str, list[dict]]) -> list[dict]:
    """Flat list of attributes for the categories page (extended first, then base, per base)."""
    bases_sorted = sorted(taxonomy["attributes"], key=lambda a: a["name"])
    out: list[dict] = []
    for base in bases_sorted:
        base_values = [{"id": v["id"], "name": v["name"]} for v in base["values"]]
        for ext in sorted(extended_by_base.get(base["handle"], []), key=lambda e: e["name"]):
            out.append(
                {
                    "id": ext["handle"],
                    "name": base["name"],
                    "handle": ext["handle"],
                    "extended_name": ext["name"],
                    "values": base_values,
                }
            )
        out.append(
            {
                "id": base["id"],
                "name": base["name"],
                "handle": base["handle"],
                "extended_name": None,
                "values": base_values,
            }
        )
    return out


def build_reversed_attributes(
    taxonomy: dict, extended_by_base: dict[str, list[dict]]
) -> list[dict]:
    """Attribute -> [categories] index for the /attributes/ page."""
    attr_to_cats: dict[str, list[dict]] = {}
    for category in _iter_categories(taxonomy):
        for attr in category["attributes"]:
            attr_to_cats.setdefault(attr["handle"], []).append(
                {"id": category["id"], "full_name": category["full_name"]}
            )

    entries: list[tuple[dict, str | None, list[dict]]] = []
    for base in taxonomy["attributes"]:
        base_values = [{"id": v["id"], "name": v["name"]} for v in base["values"]]
        entries.append((base, None, base_values))
        for ext in extended_by_base.get(base["handle"], []):
            entries.append(
                (
                    {"id": ext["handle"], "name": ext["name"], "handle": ext["handle"]},
                    base["name"],
                    base_values,
                )
            )

    entries.sort(key=lambda t: t[0]["name"])

    return [
        {
            "id": attr["id"],
            "handle": attr["handle"],
            "name": attr["name"],
            "base_name": base_name,
            "categories": sorted(
                attr_to_cats.get(attr["handle"], []), key=lambda c: c["full_name"]
            ),
            "values": values,
        }
        for attr, base_name, values in entries
    ]


def build_values(taxonomy: dict) -> list[dict]:
    """Flat list of all attribute values for the /values/ page.

    Each value belongs to exactly one attribute (value handles are
    namespaced as ``<attribute_handle>__<value_slug>``). Sorted by value
    name to roughly match the public viewer's ordering.
    """
    out: list[dict] = []
    for attr in taxonomy["attributes"]:
        for value in attr["values"]:
            out.append(
                {
                    "id": value["id"],
                    "handle": value["handle"],
                    "name": value["name"],
                    "attribute_handle": attr["handle"],
                    "attribute_name": attr["name"],
                }
            )
    out.sort(key=lambda v: v["name"])
    return out


def build_value_search_index(values: list[dict]) -> list[dict]:
    return [
        {
            "searchIdentifier": v["handle"],
            "title": f"{v['name']} [{v['attribute_name']}]",
            "url": f"?valueHandle={urllib.parse.quote(v['handle'], safe='')}",
            "value": {
                "handle": v["handle"],
                "name": v["name"],
                "attribute_handle": v["attribute_handle"],
            },
        }
        for v in values
    ]


def build_category_search_index(taxonomy: dict) -> list[dict]:
    return [
        {
            "searchIdentifier": c["id"],
            "title": c["full_name"],
            "url": f"?categoryId={urllib.parse.quote(c['id'], safe='')}",
            "category": {
                "id": c["id"],
                "name": c["name"],
                "fully_qualified_type": c["full_name"],
                "depth": c["level"],
            },
        }
        for c in _iter_categories(taxonomy)
    ]


def build_attribute_search_index(
    taxonomy: dict, extended_by_base: dict[str, list[dict]]
) -> list[dict]:
    flat: list[dict] = []
    for base in taxonomy["attributes"]:
        flat.append({"handle": base["handle"], "name": base["name"]})
    for exts in extended_by_base.values():
        for ext in exts:
            flat.append({"handle": ext["handle"], "name": ext["name"]})
    flat.sort(key=lambda a: a["name"])
    return [
        {
            "searchIdentifier": a["handle"],
            "title": a["name"],
            "url": f"?attributeHandle={a['handle']}",
            "attribute": {"handle": a["handle"]},
        }
        for a in flat
    ]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")


def resolve_source_dir(cli_arg: str | None) -> Path:
    if cli_arg:
        return Path(cli_arg).expanduser().resolve()
    env = os.environ.get("INTERNAL_TAXONOMY_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SOURCE_DIR.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        help=(
            "Path to the internal repo's src/taxonomy/ directory. "
            "Defaults to $INTERNAL_TAXONOMY_DIR or "
            "../product-taxonomy-internal/src/taxonomy/."
        ),
    )
    args = parser.parse_args()

    source_dir = resolve_source_dir(args.source_dir)
    source = source_dir / "dist" / "en" / "taxonomy.json"
    source_attrs = source_dir / "data" / "attributes.json"
    version_file = source_dir / "VERSION"

    if not source.exists():
        sys.exit(
            f"error: taxonomy data not found at {source}.\n"
            f"Clone Shopify/product-taxonomy-internal as a sibling of this repo, "
            f"or pass --source-dir / set $INTERNAL_TAXONOMY_DIR.\n"
            f"  git clone git@github.com:Shopify/product-taxonomy-internal.git "
            f"{REPO_ROOT.parent / 'product-taxonomy-internal'}"
        )

    print(f"Reading {source}")
    with source.open() as f:
        taxonomy = json.load(f)
    version = version_file.read_text().strip()
    print(f"Internal taxonomy version: {version}")

    print("Loading source attributes for extended-attribute enrichment...")
    extended_by_base = _load_extended_index(source_attrs)
    ext_count = sum(len(v) for v in extended_by_base.values())
    print(f"  {ext_count} extended attributes across {len(extended_by_base)} bases")

    print("Building category and attribute structures...")
    sibling_groups, all_categories = build_sibling_groups(taxonomy)
    attributes = build_attributes(taxonomy, extended_by_base)
    reversed_attributes = build_reversed_attributes(taxonomy, extended_by_base)
    values = build_values(taxonomy)
    category_search = build_category_search_index(taxonomy)
    attribute_search = build_attribute_search_index(taxonomy, extended_by_base)
    value_search = build_value_search_index(values)

    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    print("Rendering index.html...")
    index_html = env.get_template("index.html.j2").render(
        title="Shopify Internal Product Taxonomy",
        assets_prefix="",
        releases=[
            {
                "title": RELEASE_TITLE,
                "path": f"releases/{RELEASE_TITLE}/",
                "github_url": RELEASE_GITHUB_URL,
            }
        ],
    )
    write(DOCS / "index.html", index_html)

    print(f"Rendering releases/{RELEASE_TITLE}/index.html (categories)...")
    categories_html = env.get_template("categories.html.j2").render(
        title=f"Shopify Internal Product Taxonomy ({RELEASE_TITLE})",
        release_title=RELEASE_TITLE,
        assets_prefix="../../",
        release_prefix="",
        sibling_groups=sibling_groups,
        all_categories=all_categories,
        attributes=attributes,
    )
    write(DOCS / "releases" / RELEASE_TITLE / "index.html", categories_html)

    print(f"Rendering releases/{RELEASE_TITLE}/attributes/index.html...")
    attributes_html = env.get_template("attributes.html.j2").render(
        title=f"Shopify Internal Product Taxonomy ({RELEASE_TITLE}) — Attributes",
        release_title=RELEASE_TITLE,
        assets_prefix="../../../",
        release_prefix="../",
        reversed_attributes=reversed_attributes,
    )
    write(
        DOCS / "releases" / RELEASE_TITLE / "attributes" / "index.html",
        attributes_html,
    )

    print(f"Rendering releases/{RELEASE_TITLE}/values/index.html...")
    values_html = env.get_template("values.html.j2").render(
        title=f"Shopify Internal Product Taxonomy ({RELEASE_TITLE}) — Values",
        release_title=RELEASE_TITLE,
        assets_prefix="../../../",
        release_prefix="../",
        values=values,
    )
    write(
        DOCS / "releases" / RELEASE_TITLE / "values" / "index.html",
        values_html,
    )

    print("Writing search indexes...")
    write_json(DOCS / "releases" / RELEASE_TITLE / "search_index.json", category_search)
    write_json(
        DOCS / "releases" / RELEASE_TITLE / "attribute_search_index.json",
        attribute_search,
    )
    write_json(
        DOCS / "releases" / RELEASE_TITLE / "value_search_index.json",
        value_search,
    )

    print(
        f"Done. Wrote {len(all_categories)} categories, {len(attributes)} attribute entries, "
        f"{len(values)} values, {len(attribute_search)} attribute-search entries, "
        f"{len(value_search)} value-search entries."
    )


if __name__ == "__main__":
    main()
