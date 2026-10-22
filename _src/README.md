# Site sources

Every HTML page on the live site is generated from this folder. **Edit here, not the HTML at the repo root.** A hand edit to a built page is overwritten on the next build.

```bash
python3 _src/build.py            # rebuild every page, the redirect stubs and sitemap.xml
python3 _src/build.py --check    # build in memory and report problems; writes nothing
```

GitHub Pages runs Jekyll, which never publishes folders that start with `_`. So this folder lives in the repo but never appears on the site.

## Where things live

| File | What it holds |
|---|---|
| `site.json` | **Every owner fact:** phone, hours, email, warranty, prices and the rest; nav; lead-form options; redirects |
| `pages/<path>.html` | One source per page: a `<!--meta {json} -->` block, the hero intro, `<!--/hero-->`, then the rest of `<main>` |
| `partials/*.html` | Shared blocks: `process`, `cta`, `closing-cta` |
| `build.py` | The generator (stdlib Python 3), which also runs the checks |
| `lastmod.json` | Tracks when each page last changed, for `sitemap.xml` |
| `../assets/js/lead-form.js` | The one lead-form script (success only on a 2xx from the webhook) |
| `../assets/js/site.js` | Menu, dropdowns, footer year, GA4 `click_to_call` |

## Filling in owner facts

Every key under `facts` in `site.json` is `null` until the owner answers (BUILD-PLAN.md §2). A null fact hides the sentences that depend on it, through `<!--if facts.x--> … <!--else--> … <!--endif-->` blocks in the page sources, so pages read naturally without it.

To add a fact:
1. Set its value, written to slot into a sentence. For example, `"warranty": "a 10-year workmanship warranty"`.
2. Rebuild.
3. Re-score the pages that use it (`grep -rl facts.warranty _src/pages`).

Phone, hours and email work the same way: change them once in `site.json` and every page, the schema and the footer follow.

## Photos

Every photo is listed once, in `photos.json`: source file, crop, output name, alt text and caption.

- **Show photos on a page:** `<!--photos roof-decking roof-finished-->` renders a two-column grid with captions, lazy-loaded.
- **Pick a hero:** meta `"hero": "hero-exteriors"` swaps the hero background. The default is `hero-roofing`. Hero alt text is empty on purpose, because the photo sits behind a dark overlay as decoration.
- **Add or re-crop a photo:**
  1. Edit `photos.json`.
  2. Run `python3 _src/photos.py "<folder of originals>"`. It needs Pillow. It writes `assets/img/<name>-<width>.webp`, at 800 and 1200 px for content and 640 and 1280 px for heroes.
  3. Rebuild.
- **Writing alt text:** say what is actually in the photo. Use service words where they're true, and no city names unless the job location is known.
- **Originals:** the Twin Rivers Facebook photos in `~/Documents/Twin Rivers Photos` (2026-10-21).

## What the build refuses to ship

The build stops on:
- a bracket placeholder (`[PHONE]`, `[WARRANTY]` …) or unfilled `{{token}}`;
- a duplicate title or meta description;
- a broken internal link or `#anchor`;
- a page without exactly one lead form;
- a missing image file under `/assets/img/`.

It warns on:
- titles outside 45–62 characters;
- descriptions over 158 characters;
- fewer than 4 `tel:` links;
- absolute internal links;
- external links on service pages.

It also prints how many pages link to each page from inside their content (BUILD-PLAN §7.3 wants ≥5).

## Before publishing a page

Run the retrieval gate from this repo's root:

```bash
python3 ../tools/score_page.py page <file> --root . --query-map ../plan/query-map.json
```

The page's intro chunk must score ≥108 relevance and n-gram ≥ min(4, words in the query). The full checklist is BUILD-PLAN.md §8.
