#!/usr/bin/env python3
"""
Build the Twin Rivers static site from _src/ (stdlib only).

    python3 _src/build.py            # build every page, the stubs and sitemap.xml
    python3 _src/build.py --check    # build into memory and report, write nothing
    python3 _src/build.py --only areas/chesterfield.html services/roof-repairs.html

Layout
    _src/site.json          owner facts, nav, redirects (one home per fact)
    _src/pages/<path>.html  one source per page: a <!--meta {json} --> block, the
                            hero copy, a <!--/hero--> marker, then the rest of <main>
    _src/partials/*.html    shared blocks pulled in with <!--include name-->

GitHub Pages runs Jekyll, which never publishes folders that start with "_",
so _src/ stays in the repo but off the live site. The built HTML has no front
matter, so Jekyll copies it untouched.

Template syntax inside page sources and partials
    {{phone}} {{phone_e164}} {{hours_text}} {{service_area_text}} {{name}}
    {{facts.warranty}}                     a value from site.json (null = build error)
    <!--if facts.warranty--> … <!--else--> … <!--endif-->
    <!--ifnot facts.warranty--> … <!--endif-->
    <!--include process-->                 _src/partials/process.html, or meta "process" steps
    <!--include other-areas-->             generated: every city page but this one
    <!--include area-links-->              generated: every city page
    <!--include service-links-->           generated: every service page
    <!--photos roof-decking roof-finished-->  photo grid from _src/photos.json (alt + caption live there)

Hero photo: meta "hero" names a photos.json key (default "hero-roofing").

The build fails on unfilled tokens, bracket placeholders ([PHONE], [WARRANTY] …),
duplicate titles, broken internal links and pages without exactly one lead form.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import sys
from html.parser import HTMLParser

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(SRC)
PAGES = os.path.join(SRC, "pages")
PARTIALS = os.path.join(SRC, "partials")
LASTMOD = os.path.join(SRC, "lastmod.json")

PLACEHOLDER = re.compile(r"\[[A-Z][A-Z :/_-]*\]")
SVG_PHONE = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 '
             '16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 '
             '19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 '
             '2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 '
             '12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>')


class BuildError(Exception):
    pass


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------
def load_site():
    with open(os.path.join(SRC, "site.json"), encoding="utf-8") as f:
        site = json.load(f)
    with open(os.path.join(SRC, "photos.json"), encoding="utf-8") as f:
        site["photos"] = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    return site


def img_html(site, key, sizes, hero=False):
    p = site["photos"].get(key)
    if p is None:
        raise BuildError(f"no photo '{key}' in photos.json")
    widths = p.get("widths", [800, 1200])
    srcs = [f"/assets/img/{p['name']}-{w}.webp" for w in widths]
    srcset = ", ".join(f"{u} {w}w" for u, w in zip(srcs, widths))
    w = widths[-1] if hero else widths[0]
    load = 'fetchpriority="high"' if hero else 'loading="lazy" decoding="async"'
    cls = ' class="hero-bg"' if hero else ""
    return (f'<img{cls} src="{srcs[widths.index(w)]}" srcset="{srcset}" sizes="{sizes}" '
            f'width="{w}" height="{w * 3 // 4}" alt="{esc(p["alt"])}" {load} />')


def photos_html(site, keys):
    figs = []
    for k in keys:
        cap = site["photos"].get(k, {}).get("caption")
        cap = f"<figcaption>{esc(cap)}</figcaption>" if cap else ""
        figs.append(f'      <figure class="photo">{img_html(site, k, "(max-width: 640px) 100vw, 400px")}{cap}</figure>')
    return '<div class="photo-grid">\n' + "\n".join(figs) + "\n    </div>"


def load_pages():
    pages = {}
    for dirpath, _, files in os.walk(PAGES):
        for fn in sorted(files):
            if not fn.endswith(".html"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, PAGES).replace(os.sep, "/")
            with open(full, encoding="utf-8") as f:
                raw = f.read()
            m = re.match(r"\s*<!--meta\s*(\{.*?\})\s*-->\s*", raw, re.S)
            if not m:
                raise BuildError(f"{rel}: missing <!--meta {{...}} --> block")
            try:
                meta = json.loads(m.group(1))
            except json.JSONDecodeError as e:
                raise BuildError(f"{rel}: bad meta JSON: {e}")
            body = raw[m.end():]
            meta["path"] = rel
            meta["url_path"] = url_path(rel)
            if "<!--/hero-->" in body:
                meta["hero_src"], meta["body_src"] = body.split("<!--/hero-->", 1)
            else:
                meta["hero_src"], meta["body_src"] = None, body
            pages[rel] = meta
    return pages


def url_path(rel):
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


# ---------------------------------------------------------------------------
# Template expansion
# ---------------------------------------------------------------------------
def lookup(site, key):
    cur = site
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise BuildError(f"unknown token {{{{{key}}}}}")
        cur = cur[part]
    return cur


def truthy(site, key):
    try:
        v = lookup(site, key)
    except BuildError:
        raise BuildError(f"unknown condition key '{key}'")
    return v not in (None, "", [], False)


# Innermost block first (its body holds no other <!--if), so conditions can nest.
_NO_IF = r"(?:(?!<!--if)(?!<!--else-->)(?!<!--endif-->).)*"
COND = re.compile(rf"<!--(if|ifnot) ([\w.]+)-->({_NO_IF})(?:<!--else-->({_NO_IF}))?<!--endif-->", re.S)


def expand(text, site, page, pages, depth=0):
    if depth > 4:
        raise BuildError("include nesting too deep")

    def inc(m):
        name = m.group(1)
        gen = GENERATED.get(name)
        if gen:
            return gen(site, page, pages)
        p = os.path.join(PARTIALS, name + ".html")
        if not os.path.exists(p):
            raise BuildError(f"{page['path']}: no partial '{name}'")
        with open(p, encoding="utf-8") as f:
            return expand(f.read(), site, page, pages, depth + 1)

    text = re.sub(r"<!--include ([\w-]+)-->", inc, text)
    text = re.sub(r"<!--photos ([\w -]+)-->", lambda m: photos_html(site, m.group(1).split()), text)

    def cond(m):
        kind, key, yes, no = m.group(1), m.group(2), m.group(3), m.group(4) or ""
        hit = truthy(site, key)
        if kind == "ifnot":
            hit = not hit
        return yes if hit else no

    while True:
        nxt = COND.sub(cond, text)
        if nxt == text:
            break
        text = nxt

    def tok(m):
        key = m.group(1)
        if key.startswith("page."):
            v = page.get(key[5:])
        else:
            v = lookup(site, key)
        if v in (None, ""):
            raise BuildError(f"{page['path']}: {{{{{key}}}}} is empty — wrap it in <!--if {key}-->")
        return str(v)

    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", tok, text)


def esc(s):
    return html.escape(s, quote=True)


# ---------------------------------------------------------------------------
# Generated blocks
# ---------------------------------------------------------------------------
def city_pages(pages):
    return sorted((p for p in pages.values() if p.get("type") == "city"),
                  key=lambda p: p.get("order", 99))


def service_pages(pages):
    return sorted((p for p in pages.values() if p.get("type") == "service"),
                  key=lambda p: p.get("order", 99))


def gen_other_areas(site, page, pages):
    items = [p for p in city_pages(pages) if p["path"] != page["path"]]
    lis = "\n".join(
        f'      <li><a href="{p["url_path"]}">{esc(p["city_label"])}</a>'
        f'<span>{esc(p.get("city_blurb", ""))}</span></li>' for p in items)
    return f"""<section class="section section-alt" data-structural>
  <div class="section-inner">
    <h2>Other areas we serve</h2>
    <ul class="link-list">
{lis}
      <li><a href="/areas/">All service areas</a><span>Every city and county we cover</span></li>
    </ul>
  </div>
</section>"""


def gen_area_links(site, page, pages):
    lis = "\n".join(
        f'  <li><a href="{p["url_path"]}">{esc(p["city_label"])}</a>'
        f'<span>{esc(p.get("city_blurb", ""))}</span></li>' for p in city_pages(pages))
    return f'<ul class="link-list" data-structural>\n{lis}\n</ul>'


def gen_service_links(site, page, pages):
    lis = "\n".join(
        f'  <li><a href="{p["url_path"]}">{esc(p["nav_label"])}</a>'
        f'<span>{esc(p.get("blurb", ""))}</span></li>'
        for p in service_pages(pages) if p["path"] != page["path"])
    return f'<ul class="link-list" data-structural>\n{lis}\n</ul>'


def gen_process(site, page, pages):
    """Three-step block. A page can set meta "process": [[title, text], ...] to word
    the steps for its service; otherwise partials/process.html is used."""
    steps = page.get("process")
    if not steps:
        with open(os.path.join(PARTIALS, "process.html"), encoding="utf-8") as f:
            return expand(f.read(), site, page, pages, 1)
    lis = "\n".join(f"      <li><strong>{esc(t)}</strong>{esc(d)}</li>" for t, d in steps)
    return f"""<section class="section section-alt">
  <div class="section-inner">
    <h2>{esc(page.get("process_title", "How it works"))}</h2>
    <ol class="steps">
{lis}
    </ol>
  </div>
</section>"""


GENERATED = {
    "process": gen_process,
    "other-areas": gen_other_areas,
    "area-links": gen_area_links,
    "service-links": gen_service_links,
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def tel_schema(site):
    d = site["phone_e164"].lstrip("+")
    return f"+{d[0]}-{d[1:4]}-{d[4:7]}-{d[7:]}"


def place(a):
    return {"@type": a["type"], "name": a["name"],
            "containedInPlace": {"@type": "State", "name": "Missouri"}}


def provider_ref(site):
    b = site["base_url"]
    return {"@type": "RoofingContractor", "@id": f"{b}/#business", "name": site["name"],
            "telephone": tel_schema(site), "url": f"{b}/"}


def business(site, pages):
    b = site["base_url"]
    ent = {
        "@type": "RoofingContractor",
        "@id": f"{b}/#business",
        "name": site["name"],
        "description": pages["index.html"]["description"],
        "url": f"{b}/",
        "telephone": tel_schema(site),
        "logo": b + site["logo"],
        "image": b + site["og_image"],
        "priceRange": "$$",
        "areaServed": [place(a) for a in site["areas_served"]],
        "openingHoursSpecification": [
            {"@type": "OpeningHoursSpecification", "dayOfWeek": h["days"] if len(h["days"]) > 1 else h["days"][0],
             "opens": h["opens"], "closes": h["closes"]} for h in site["hours"]],
        "hasOfferCatalog": {
            "@type": "OfferCatalog", "name": "Roofing & exterior services",
            "itemListElement": [
                {"@type": "Offer", "itemOffered": {"@type": "Service", "name": p["schema_name"],
                                                   "url": b + p["url_path"]}}
                for p in service_pages(pages)]},
    }
    if site.get("email"):
        ent["email"] = site["email"]
    if site.get("same_as"):
        ent["sameAs"] = site["same_as"]
    return ent


def breadcrumbs(site, page, pages):
    b = site["base_url"]
    trail = [("Home", "/")]
    if page.get("type") == "city":
        trail.append(("Service Areas", "/areas/"))
    trail.append((page["breadcrumb"], page["url_path"]))
    return trail


def schema(site, page, pages):
    b = site["base_url"]
    url = b + page["url_path"]
    t = page["type"]
    graph = []
    if t == "home":
        graph.append(business(site, pages))
        graph.append({"@type": "WebSite", "@id": f"{b}/#website", "url": f"{b}/",
                      "name": site["name"], "publisher": {"@id": f"{b}/#business"}})
    elif t in ("service", "city"):
        svc = {"@type": "Service", "@id": f"{url}#service", "name": page["schema_name"],
               "serviceType": page.get("service_type", page["schema_name"]), "url": url,
               "description": page["description"], "provider": provider_ref(site)}
        if t == "city":
            svc["areaServed"] = [place(a) for a in page["area_served"]]
        else:
            svc["areaServed"] = [place(a) for a in site["areas_served"][:4]]
        graph.append(svc)
    elif t == "about":
        about = {"@type": "AboutPage", "@id": f"{url}#webpage", "url": url, "name": page["title"],
                 "about": provider_ref(site)}
        graph.append(about)
        owner = site["facts"].get("owner_name")
        if owner:
            graph.append({"@type": "Person", "name": owner, "worksFor": {"@id": f"{b}/#business"}})
    elif t == "contact":
        graph.append({"@type": "ContactPage", "@id": f"{url}#webpage", "url": url,
                      "name": page["title"], "about": provider_ref(site)})
    else:
        graph.append({"@type": "WebPage", "@id": f"{url}#webpage", "url": url, "name": page["title"]})
    if t != "home":
        graph.append({"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": b + u}
            for i, (n, u) in enumerate(breadcrumbs(site, page, pages))]})
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Page chrome
# ---------------------------------------------------------------------------
def head(site, page, pages, css_v):
    b = site["base_url"]
    url = b + page["url_path"]
    title, desc = esc(page["title"]), esc(page["description"])
    og_title = esc(page.get("og_title", page["title"]))
    noindex = '  <meta name="robots" content="noindex, follow" />\n' if page.get("noindex") else ""
    gsc = (f'  <meta name="google-site-verification" content="{esc(site["gsc_verification"])}" />\n'
           if site.get("gsc_verification") else "")
    ga = ""
    if site.get("ga4_id"):
        gid = esc(site["ga4_id"])
        ga = (f'  <script async src="https://www.googletagmanager.com/gtag/js?id={gid}"></script>\n'
              f'  <script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}'
              f'gtag("js",new Date());gtag("config","{gid}");</script>\n')
    return f"""<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title}</title>
  <meta name="description" content="{desc}" />
{noindex}  <link rel="canonical" href="{url}" />
  <meta property="og:type" content="website" />
  <meta property="og:url" content="{url}" />
  <meta property="og:title" content="{og_title}" />
  <meta property="og:description" content="{desc}" />
  <meta property="og:image" content="{b}{site['og_image']}" />
  <meta property="og:site_name" content="{esc(site['name'])}" />
  <meta property="og:locale" content="en_US" />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="theme-color" content="{site['theme_color']}" />
{gsc}  <link rel="icon" type="image/png" href="/favicon.png" />
  <link rel="stylesheet" href="/styles.css?v={css_v}" />
  <script type="application/ld+json">
{schema(site, page, pages)}
  </script>
{ga}</head>"""


def nav_html(site, page):
    items = []
    for group in site["nav"]:
        if "href" in group:
            cur = ' aria-current="page"' if group["href"] == page["url_path"] else ""
            items.append(f'        <li><a href="{group["href"]}"{cur}>{esc(group["label"])}</a></li>')
            continue
        sub_id = "sub-" + re.sub(r"[^a-z]+", "-", group["label"].lower()).strip("-")
        current = ' aria-current="page"'
        subs = "\n".join(
            f'            <li><a href="{h}"{current if h == page["url_path"] else ""}>{esc(l)}</a></li>'
            for h, l in group["items"])
        items.append(f"""        <li class="has-sub">
          <button type="button" class="nav-sub-toggle" aria-expanded="false" aria-controls="{sub_id}">{esc(group['label'])}</button>
          <ul class="nav-sub" id="{sub_id}">
{subs}
          </ul>
        </li>""")
    quote = "#quote" if page.get("hero_src") is not None else "/contact.html#quote"
    return f"""<header class="site-header">
  <div class="nav">
    <a href="/" class="logo">
      <img src="{site['logo']}" alt="{esc(site['name'])} logo" width="56" height="56" />
      <span>{esc(site['name'])}</span>
    </a>
    <nav class="main-nav" id="mainNav" aria-label="Main navigation">
      <ul class="nav-menu">
{chr(10).join(items)}
      </ul>
    </nav>
    <a href="tel:{site['phone_e164']}" class="nav-phone">{SVG_PHONE}<span>{site['phone']}</span></a>
    <a href="{quote}" class="nav-cta-btn">Free Inspection</a>
    <button type="button" class="hamburger" aria-label="Open menu" aria-expanded="false" aria-controls="mainNav">
      <span></span><span></span><span></span>
    </button>
  </div>
</header>"""


def crumbs_html(site, page, pages):
    if page["type"] == "home":
        return ""
    trail = breadcrumbs(site, page, pages)
    parts = []
    for i, (n, u) in enumerate(trail):
        if i == len(trail) - 1:
            parts.append(f'<li aria-current="page">{esc(n)}</li>')
        else:
            parts.append(f'<li><a href="{u}">{esc(n)}</a></li>')
    return f'<nav class="breadcrumbs" aria-label="Breadcrumb"><ol>{"".join(parts)}</ol></nav>\n'


def form_html(site, page):
    pre = page.get("form_service", "")
    opts = ['<option value="">Choose one</option>'] + [
        f'<option value="{v}"{" selected" if v == pre else ""}>{esc(l)}</option>'
        for v, l in site["form_services"]]
    title = esc(page.get("form_title", "Book a free roof inspection"))
    benefits = "".join(f"<li>{esc(b)}</li>" for b in page.get("benefits", []))
    benefits = f'\n        <ul class="quote-benefits">{benefits}</ul>' if benefits else ""
    return f"""<form class="quote-card" id="quote" data-lead-form data-endpoint="{esc(site['webhook'])}" data-form-location="hero" novalidate>
        <p class="quote-title">{title}</p>
        <p class="quote-sub">Name and phone are all we need. We call you back to set a time.</p>{benefits}
        <div class="form-pair">
          <div class="form-row">
            <label for="q-name">Name</label>
            <input type="text" id="q-name" name="name" required autocomplete="name" />
          </div>
          <div class="form-row">
            <label for="q-phone">Phone</label>
            <input type="tel" id="q-phone" name="phone" required autocomplete="tel" inputmode="tel" />
          </div>
        </div>
        <div class="form-row">
          <label for="q-service">What do you need? <span class="opt">(optional)</span></label>
          <select id="q-service" name="service">{''.join(opts)}</select>
        </div>
        <details class="form-more">
          <summary>Add an email or details (optional)</summary>
          <div class="form-row">
            <label for="q-email">Email <span class="opt">(optional)</span></label>
            <input type="email" id="q-email" name="email" autocomplete="email" />
          </div>
          <div class="form-row">
            <label for="q-message">Anything we should know? <span class="opt">(optional)</span></label>
            <textarea id="q-message" name="description" rows="3"></textarea>
          </div>
        </details>
        <div class="hp" aria-hidden="true">
          <label for="q-company">Company website</label>
          <input type="text" id="q-company" name="company_website" tabindex="-1" autocomplete="off" />
        </div>
        <button type="submit" class="btn-primary btn-block">Get my free inspection</button>
        <p class="form-status" role="status" aria-live="polite"></p>
        <p class="form-legal">By submitting, you agree to our <a href="/privacy-policy.html">Privacy Policy</a> and <a href="/terms-of-service.html">Terms of Service</a>.</p>
        <p class="quote-call">Prefer to talk? Call <a href="tel:{site['phone_e164']}">{site['phone']}</a></p>
      </form>"""


def footer_html(site, pages):
    def col(title, items):
        lis = "".join(f'<li><a href="{h}">{esc(l)}</a></li>' for h, l in items)
        return f'<div class="footer-col"><p class="footer-head">{esc(title)}</p><ul>{lis}</ul></div>'
    groups = {g["label"]: g["items"] for g in site["nav"] if "items" in g}
    company = [("/about.html", "About"), ("/contact.html", "Contact"),
               ("/privacy-policy.html", "Privacy Policy"), ("/terms-of-service.html", "Terms of Service")]
    email = (f'<br /><a href="mailto:{esc(site["email"])}">{esc(site["email"])}</a>'
             if site.get("email") else "")
    return f"""<footer class="site-footer">
  <div class="footer-inner">
    <div class="footer-col footer-brand">
      <p class="footer-head">{esc(site['name'])}</p>
      <p><a href="tel:{site['phone_e164']}" class="footer-phone">{site['phone']}</a>{email}</p>
      <p>{esc(site['hours_short'])}</p>
      <p>Serving {esc(site['service_area_text'])}.</p>
    </div>
    {col("Roofing", groups["Roofing"])}
    {col("Exteriors", groups["Exteriors"])}
    {col("Service Areas", groups["Service Areas"])}
    {col("Company", company)}
  </div>
  <p class="footer-copy">&copy; <span data-year>{dt.date.today().year}</span> {esc(site['name'])}. All rights reserved.</p>
</footer>"""


def render(site, page, pages, css_v):
    hero = ""
    if page["hero_src"] is not None:
        hero_copy = expand(page["hero_src"], site, page, pages).strip()
        hero = f"""  <section class="page-hero">
    {img_html(site, page.get("hero", "hero-roofing"), "100vw", hero=True)}
    <div class="page-hero-inner">
      <div class="page-hero-copy">
        <h1>{esc(page['h1'])}</h1>
        {hero_copy}
      </div>
      {form_html(site, page)}
    </div>
  </section>
"""
    body = expand(page["body_src"], site, page, pages).strip()
    return f"""<!DOCTYPE html>
<html lang="en">
{head(site, page, pages, css_v)}
<body class="page-{page['type']}">
<a href="#main-content" class="skip-link">Skip to main content</a>
{nav_html(site, page)}
{crumbs_html(site, page, pages)}<main id="main-content">
{hero}{body}
</main>
{footer_html(site, pages)}
<a href="tel:{site['phone_e164']}" class="call-now-mobile">{SVG_PHONE}Call {site['phone']}</a>
<script src="/assets/js/site.js" defer></script>
<script src="/assets/js/lead-form.js" defer></script>
</body>
</html>
"""


def stub(site, target):
    b = site["base_url"]
    canon = b + target.split("#")[0]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Moved | {esc(site['name'])}</title>
  <link rel="canonical" href="{canon}" />
  <meta http-equiv="refresh" content="0; url={target}" />
</head>
<body><p><a href="{target}">This page has moved.</a></p></body>
</html>
"""


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
class LinkScan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.ids = [], set()
        self.stack = []
        self.in_main = 0
        self.forms = 0
        self.tel = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "form" and "data-lead-form" in a:
            self.forms += 1
        structural = "data-structural" in a
        self.stack.append((tag, structural))
        if tag == "main":
            self.in_main += 1
        if tag == "a" and a.get("href"):
            href = a["href"]
            if href.startswith("tel:"):
                self.tel += 1
            ctx = self.in_main > 0 and not any(s for _, s in self.stack)
            self.links.append((href, ctx))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag == "main":
            self.in_main -= 1


def resolve(href, outputs):
    path = href.split("#")[0].split("?")[0]
    frag = href.split("#")[1] if "#" in href else None
    if path == "" or not path.startswith("/"):
        return None, frag
    rel = path.lstrip("/")
    if rel == "" or rel.endswith("/"):
        rel += "index.html"
    return rel, frag


def check(site, pages, outputs, allow_missing=False):
    errors, warnings = [], []
    titles, descs = {}, {}
    scans = {}
    for rel, page in pages.items():
        out = outputs[rel]
        for m in PLACEHOLDER.finditer(out):
            errors.append(f"{rel}: placeholder {m.group(0)} left in the page")
        if re.search(r"\{\{|<!--(if|ifnot|else|endif|include|photos)", out):
            errors.append(f"{rel}: unexpanded template syntax")
        for img in sorted(set(re.findall(r"/assets/img/[\w.-]+", out))):
            if not os.path.exists(os.path.join(OUT, img.lstrip("/"))):
                errors.append(f"{rel}: missing image {img} (run _src/photos.py)")
        t, d = page["title"], page["description"]
        if t in titles:
            errors.append(f"{rel}: title duplicates {titles[t]}")
        titles[t] = rel
        if d in descs:
            errors.append(f"{rel}: meta description duplicates {descs[d]}")
        descs[d] = rel
        if not page.get("noindex"):
            if not 45 <= len(t) <= 62:
                warnings.append(f"{rel}: title is {len(t)} chars (aim 50-60)")
            if len(d) > 158:
                warnings.append(f"{rel}: description is {len(d)} chars (aim <=155)")
        s = LinkScan()
        s.feed(out)
        scans[rel] = s
        want_form = 1 if page["hero_src"] is not None else 0
        if s.forms != want_form:
            errors.append(f"{rel}: {s.forms} lead forms (want {want_form})")
        if want_form and s.tel < 4:
            warnings.append(f"{rel}: phone appears {s.tel} times as tel: (want >=4)")

    inbound = {rel: set() for rel in pages}
    for rel, s in scans.items():
        for href, ctx in s.links:
            if href.startswith(("http://", "https://")):
                if href.startswith(site["base_url"]):
                    warnings.append(f"{rel}: absolute internal link {href} (use root-relative)")
                elif pages[rel]["type"] == "service":
                    warnings.append(f"{rel}: external link on a service page: {href}")
                continue
            target, frag = resolve(href, outputs)
            if target is None:
                continue
            if target not in outputs and not os.path.exists(os.path.join(OUT, target)):
                (warnings if allow_missing else errors).append(f"{rel}: broken link {href}")
                continue
            if frag and target in scans and frag not in scans[target].ids:
                errors.append(f"{rel}: link {href} points at a missing #{frag}")
            if ctx and target in inbound and target != rel:
                inbound[target].add(rel)
    return errors, warnings, inbound


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------
def sitemap(site, pages, outputs, lastmod):
    today = dt.date.today().isoformat()
    rows = []
    order = {"home": 0, "service": 1, "city": 2, "hub": 3, "about": 4, "contact": 5, "legal": 6}
    for rel, page in sorted(pages.items(), key=lambda kv: (order.get(kv[1]["type"], 9), kv[1].get("order", 99), kv[0])):
        if page.get("noindex"):
            continue
        h = hashlib.sha256(re.sub(r'<span data-year>\d+</span>', "", outputs[rel]).encode()).hexdigest()[:16]
        prev = lastmod.get(rel)
        if not prev or prev["hash"] != h:
            lastmod[rel] = {"hash": h, "date": today}
        pri = {"home": "1.0", "service": "0.8", "city": "0.8", "hub": "0.6"}.get(page["type"], "0.4")
        rows.append(f"""  <url>
    <loc>{site['base_url']}{page['url_path']}</loc>
    <lastmod>{lastmod[rel]['date']}</lastmod>
    <priority>{pri}</priority>
  </url>""")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="build in memory and report; write nothing")
    ap.add_argument("--only", nargs="+", metavar="PATH", help="write only these pages (no sitemap/stubs)")
    ap.add_argument("--links", action="store_true", help="print the inbound contextual-link table")
    ap.add_argument("--allow-missing", action="store_true",
                    help="treat links to pages that don't exist yet as warnings (drafting only)")
    args = ap.parse_args()

    try:
        site = load_site()
        pages = load_pages()
        with open(os.path.join(OUT, "styles.css"), "rb") as f:
            css_v = hashlib.sha256(f.read()).hexdigest()[:8]
        outputs = {rel: render(site, p, pages, css_v) for rel, p in pages.items()}
    except BuildError as e:
        print(f"BUILD ERROR: {e}", file=sys.stderr)
        return 2

    for rel in site["redirects"]:
        if rel in pages:
            print(f"BUILD ERROR: {rel} is both a page and a redirect", file=sys.stderr)
            return 2
    stubs = {rel: stub(site, target) for rel, target in site["redirects"].items()}
    errors, warnings, inbound = check(site, pages, {**outputs, **stubs}, args.allow_missing)

    for w in warnings:
        print(f"warn  {w}")
    for e in errors:
        print(f"ERROR {e}")

    if args.links or not args.only:
        print("\ninbound contextual links (from other pages' <main>, excluding nav/footer/link blocks):")
        for rel in sorted(inbound, key=lambda r: len(inbound[r])):
            if pages[rel]["type"] in ("legal",):
                continue
            n = len(inbound[rel])
            flag = "" if n >= 5 or pages[rel]["type"] in ("home", "contact") else "  <5"
            print(f"  {n:2d}  {rel}{flag}")

    if errors:
        print(f"\n{len(errors)} error(s); nothing written." if not args.check else f"\n{len(errors)} error(s).")
        return 1
    if args.check:
        print(f"\nOK: {len(outputs)} pages, {len(stubs)} stubs (check only, nothing written)")
        return 0

    targets = args.only or list(outputs)
    for rel in targets:
        if rel not in outputs:
            print(f"ERROR no page source for {rel}", file=sys.stderr)
            return 2
        dest = os.path.join(OUT, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            f.write(outputs[rel])
    if not args.only:
        for rel, text in stubs.items():
            with open(os.path.join(OUT, rel), "w", encoding="utf-8") as f:
                f.write(text)
        lastmod = {}
        if os.path.exists(LASTMOD):
            with open(LASTMOD, encoding="utf-8") as f:
                lastmod = json.load(f)
        sm = sitemap(site, pages, outputs, lastmod)
        with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as f:
            f.write(sm)
        with open(LASTMOD, "w", encoding="utf-8") as f:
            json.dump(lastmod, f, indent=1, sort_keys=True)
            f.write("\n")
    print(f"\nwrote {len(targets)} page(s)" + ("" if args.only else f", {len(stubs)} stub(s), sitemap.xml"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
