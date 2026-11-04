from os.path import join
from playwright.sync_api import sync_playwright, Page, Locator, Playwright, Browser
from urllib.parse import urljoin, urlparse
import json
from . import chatbot as Chatbot
from .prompts.splitters import markdown_parse
from .logger import logging
from . import errors, text_embeddings
import time
import atexit
import threading
import os
import re
import shutil
import subprocess
from . import build_scraper

select_image_prompt = """Given a screenshot of an image search repository webpage, select the single best image most appropriate for the given search query.

CRITICAL SELECTION CRITERIA FOR WHAT IS 'BEST' FOR US:
1. **AUTHENTICITY & REALISM**: Choose clean, photographic portraits. Strictly avoid cartoon illustrations, drawings, fan-art, digital artwork, or CGI renders.
2. **CLEANLINESS (NO TEXT/UI)**: Do NOT select any image containing text overlays, subtitles, logos, branding, YouTube/Instagram UI elements (like play buttons), graphic borders, or visible watermarks. Avoid movie posters with titles/credits.
3. **NO COLLAGES OR GRIDS**: Absolutely avoid images that are collages, split-screens, before/after comparisons, or grids of any kind. Only pick a single contiguous image.
4. **SUBJECT ISOLATION & CLEAR VISIBILITY**: Prefer a single, clear subject/character in high focus (close-ups or medium portraits). Avoid multi-person group shots or chaotic backgrounds.
5. **FACIAL GEOMETRY & UNOBSCURED**: Avoid extreme camera angles that distort the face. Avoid heavy occlusions (face largely covered by hands, massive sunglasses, or objects) unless contextual.
6. **VISUAL FIDELITY**: Avoid heavily pixelated thumbnails, deep-fried memes, or extremely low-resolution images.
7. **RELEVANCY & LIKENESS**: Ensure the selected image accurately matches the character/subject likeness, age, and context of the query.

Output the two lines of text written below and outside the single selected image (used to identify it on the webpage) and a representative hex color code from the selected image to be used as a background.
Format your output as a JSON object enclosed in ```json with keys:
- "text1": The first line of text under/outside the selected image.
- "text2": The second line of text under/outside the selected image.
- "color": Hex color code of the image's background.

Search Query:
"""


LIGHTPANDA_CONTEXT_CHARS = 16000

_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def _extract_main_text(html: str):
    """Reader-mode style main-content extraction. Best-effort trafilatura."""
    if not html or len(html) < 200:
        return None
    try:
        import trafilatura

        return trafilatura.extract(html, include_comments=False)
    except Exception:
        logging.info("trafilatura extraction unavailable, using raw text")
    return None


def _clean_markdown(text: str):
    """Strip markdown link targets / images so nav chrome does not eat the
    context budget."""
    if not text:
        return ""
    text = _MD_IMG_RE.sub("", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


_lightpanda_bin_cache = None


def _lightpanda_bin():
    """Resolve the Lightpanda CLI binary (replaces screenshot->vision summaries)."""
    global _lightpanda_bin_cache
    if _lightpanda_bin_cache is not None:
        return _lightpanda_bin_cache
    bin_path = os.environ.get("LIGHTPANDA_BIN") or shutil.which("lightpanda")
    if bin_path and os.path.isfile(bin_path) and os.access(bin_path, os.X_OK):
        _lightpanda_bin_cache = bin_path
        return _lightpanda_bin_cache
    _lightpanda_bin_cache = ""

    return _lightpanda_bin_cache


def fetch_page_text(url, wait_ms=1500, timeout=25, obey_robots=False):
    """Fetch a page and extract its main text content.

    Chain: Lightpanda html dump -> trafilatura (reader-mode main content);
    then Lightpanda markdown dump (links stripped); finally plain requests+bs4.
    Returns a plain-text string; empty string on failure.
    """
    if not isinstance(url, str) or not url.startswith("http"):
        return ""

    def dump(mode):
        bin_path = _lightpanda_bin()
        if not bin_path:
            return None
        try:
            cmd = [bin_path, "fetch", "--dump", mode, "--wait-ms", str(wait_ms), url]
            if obey_robots:
                cmd.insert(1, "--obey-robots")
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=True,
            )
            return res.stdout.decode("utf-8", errors="replace").strip()
        except Exception as e:
            logging.info(f"lightpanda-{mode} dump: error for {url} : {e}")
            return None

    # 1) JS-rendered html -> main-content extraction
    text = _extract_main_text(dump("html") or "")

    # 2) markdown dump without link targets (chrome text still present)
    if not text:
        text = _clean_markdown(dump("markdown") or "")
        logging.info(f"fetch_page_text: trafilatura empty for {url}, using raw markdown")

    # 3) plain http fetch, no browser
    if not text:
        try:
            import requests

            res = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                    "Gecko/20100101 Firefox/130.0"
                },
                timeout=timeout,
            )
            text = _extract_main_text(res.text)
            if not text:
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(res.text, "html.parser")
                for tag in soup(["script", "style", "noscript", "head", "nav", "footer"]):
                    tag.decompose()
                text = " ".join(soup.stripped_strings)
        except Exception as e:
            logging.error(f"fetch_page_text: failed for {url} : {e}")

    return (text or "").strip()


class BrowserManager:
    def __init__(self, headless=True):
        self.headless = True
        self.playwright: Playwright = None
        self.browser: Browser = None
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            if not self.browser:
                self.playwright = sync_playwright().start()
                self.browser = self.playwright.firefox.launch(headless=self.headless)

    def stop(self):
        with self._lock:
            if self.browser:
                self.browser.close()
                self.browser = None
            if self.playwright:
                self.playwright.stop()
                self.playwright = None

    def get_page(self):
        if not self.browser:
            self.start()
        return self.browser.new_page()


def get_area(element: Locator):
    try:
        box = element.bounding_box()
        if box:
            return box["width"] * box["height"]
    except Exception as e:
        logging.info(f"playwright-image-search : error in areas - {e}")
    return -1


def cmp_by_area(elements: list[Locator]):
    if not elements:
        return None
    if len(elements) == 1:
        return elements[0]

    max_element = elements[0]
    max_area = get_area(max_element)

    for e in elements[1:]:
        area = get_area(e)
        if area >= max_area:
            max_area = area
            max_element = e
    return max_element


def find_img_by_alt_text(
    page: Page, text: str, src_filter: str = None, pick_any: bool = False
):
    query_selector = f"//img[contains(@alt, '{text}')"
    if src_filter:
        query_selector += f" and contains(@src, '{src_filter}')"
    query_selector += "]"

    if pick_any:
        splits = text.split(" ")
        for i in range(1, len(splits)):
            try:
                t = " ".join(splits[0 : len(splits) - i + 1])
                t1 = t.replace('"', "").replace("'", "")
                query1 = f"//img[contains(@alt, '{t1}')"
                if src_filter:
                    query1 += f" and starts-with(@src, '{src_filter}')"
                query1 += "]"

                elements = page.locator(query1).all()

                if elements:
                    return cmp_by_area(elements)

            except Exception as e:
                logging.info(f"image-search-agent: sub-query error : {e}")
    return None


@errors.log_ctx_errors
def scrape_images_from_search_results(
    page: Page, chatbot: Chatbot.ChatInterface, query: str
):
    scraped_images = []
    try:
        page.goto(f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
        time.sleep(1)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        # page.wait_for_load_state("networkidle")

        # Get top 3 search results
        results = page.locator('a[data-testid="result-title-a"]').all()
        top_results = list(map(lambda x: x.get_attribute("href"), results[:2]))

        logging.info(f"top 2 search results : {top_results}")

        for url in top_results:
            if url:
                try:
                    images = build_scraper.scrape_page(
                        chatbot,
                        "fetch top 5 downloadable image links / src directly relevant to the webpage content, filter out irrelevant, generic images unrelated to the webpage topic or content. Create a description for each fetched image using the alt or the surrouding text. Format the output as a JSON array with each element having src and desp keys",
                        url,
                    )

                    if isinstance(images, str):
                        images = json.loads(images)

                    img_data = []
                    for img in images[: min(10, len(images))]:
                        src = img.get("src")
                        alt = img.get("desp")
                        if src:
                            absolute_src = urljoin(page.url, src)
                            img_data.append({"src": absolute_src, "alt": alt or ""})

                    if len(img_data) > 0:
                        out = choose_best_image(page, chatbot, img_data, query)

                        if out:
                            if out[2] > 0.7:
                                scraped_images.append(out[0])

                except Exception as e:
                    logging.error(f"Error scraping {url}: {e}")
    except Exception as e:
        logging.error(f"Error during web scraping: {e}")
    return scraped_images


@errors.raise_ctx_errors
def mk_image_grid_html(images, col=3):
    cell = (
        lambda x: f'<div style="border: solid 2px #000;"><p>Index: {x[0]}</p> <img src="{x[1]}" width="300px" /><p>Despcription: {x[2]}</p></div>'
    )
    row = lambda x: f'<div style="display: flex;">{x}</div>'
    create_html = (
        lambda x: f'<html> <head></head> <body> <div id="root" style="background-color: white; width: max-content;"> {x} </div> </body> </html>'
    )

    rows = []
    for idx in range(0, len(images), col):
        c1 = cell((idx, images[idx]["src"], images[idx]["alt"]))
        r = [c1]
        _idx = idx
        while _idx + 1 < min(idx + col, len(images)):
            _idx += 1
            c2 = cell((_idx, images[_idx]["src"], images[_idx]["alt"]))
            r.append(c2)

        rows.append(row("\n".join(r)))

    html = create_html("\n".join(rows))

    return html


@errors.log_ctx_errors
def make_collage(images, col=3):
    browser_manager = BrowserManager()
    page = browser_manager.get_page()
    try:
        html = mk_image_grid_html(
            list(map(lambda x: {"src": x, "alt": ""}, images)), col
        )

        page.set_content(html)
        time.sleep(2)

        elements = page.locator("//div[@id='root']").all()

        return elements[0].screenshot() if len(elements) > 0 else page.screenshot()
    finally:
        page.close()
        browser_manager.stop()


@errors.log_ctx_errors
def choose_best_image(page: Page, chatbot: Chatbot.ChatInterface, images, query):
    prompt_text = (
        f"Given the search query '{query}', choose the most appropriate character portrait image from the options.\n\n"
        f"CRITICAL RANKING CRITERIA FOR WHAT IS 'BEST' FOR US:\n"
        f"1. **AUTHENTICITY & REALISM**: Choose clean, photographic portraits. Strictly avoid cartoon illustrations, drawings, fan-art, digital artwork, or CGI renders.\n"
        f"2. **CLEANLINESS (NO TEXT/UI)**: Do NOT select any image containing text overlays, subtitles, logos, branding, YouTube/Instagram UI elements (like play buttons), graphic borders, or visible watermarks. Avoid movie posters with titles/credits.\n"
        f"3. **NO COLLAGES OR GRIDS**: Absolutely avoid images that are collages, split-screens, before/after comparisons, or grids of any kind. Only pick a single contiguous image.\n"
        f"4. **SUBJECT ISOLATION & CLEAR VISIBILITY**: Prefer a single, clear subject/character in high focus (close-ups or medium portraits). Avoid multi-person group shots or chaotic backgrounds.\n"
        f"5. **FACIAL GEOMETRY & UNOBSCURED**: Avoid extreme camera angles that distort the face. Avoid heavy occlusions (face largely covered by hands, massive sunglasses, or objects) unless contextual.\n"
        f"6. **VISUAL FIDELITY**: Avoid heavily pixelated thumbnails, deep-fried memes, or extremely low-resolution images.\n"
        f"7. **RELEVANCY & LIKENESS**: Ensure the selected image accurately matches the character/subject likeness, age, and context of the query.\n\n"
        f"Format your output as a JSON object enclosed in ```json markdown block with keys:\n"
        f'- "index": The integer index of the selected image.\n'
        f'- "color": A representative hex color code from the selected image that can be used as a premium visual background.\n'
        f'- "score": A strict relevancy score between 0.0 and 1.0 (only score above 0.7 if the image perfectly matches our criteria above).\n'
        f'If no image is suitable, return a JSON object with empty values: {{"index": null, "color": "#000000", "score": 0.0}}.'
    )

    html = mk_image_grid_html(images)

    page.set_content(html)
    time.sleep(2)
    # Use full_page=True to capture the entire scrollable grid height and prevent bottom row cut-offs
    img_bytes = page.screenshot(full_page=True)

    prompt = Chatbot.Img(_bytes=img_bytes, text=prompt_text)
    res = chatbot.fetch_text(prompt)
    out = json.loads(markdown_parse(res))

    logging.info(f"best image: {json.dumps(out)} in {len(images)} images")

    try:
        idx = out.get("index")
        if idx is not None and int(idx) < len(images):
            return images[int(idx)], out.get("color"), out.get("score")
    except Exception:
        pass

    return None, None, 0.0


@errors.log_ctx_errors
def find_image_focus_direction(images, chatbot: Chatbot.ChatInterface):
    browser_manager = BrowserManager()
    page = browser_manager.get_page()

    prompt_text = f"Given a set of images with a corresponding index, analyze all the images in detail and find the direction where the image should be focused to highlight the main content in an image. The direction can be any of the following - `top`, `bottom`, `left`, `right`, `top-left`, `top-right`, `bottom-left`, `bottom-right`, `middle` . Return a JSON with key as the index of the image and value as the one of the direction, enclose the JSON in ```json \n\n"

    output = [None] * len(images)
    i = 0
    while i <= len(images):
        html = mk_image_grid_html(
            list(
                map(
                    lambda x: {"src": x, "alt": None},
                    images[i : min(len(images), i + 4)],
                )
            ),
            col=4,
        )

        page.set_content(html)
        time.sleep(2)
        # Use full_page=True to capture the entire grid layout safely
        img_bytes = page.screenshot(full_page=True)

        prompt = Chatbot.Img(_bytes=img_bytes, text=prompt_text)
        res = chatbot.fetch_text(prompt)
        out = json.loads(markdown_parse(res))

        for j in range(i, min(len(images), i + 4)):
            output[j] = out.get(str(j - i))

        i += 4

    return output


_shared_browser_manager: BrowserManager = None
_shared_browser_lock = threading.Lock()


def get_shared_browser_manager():
    """Process-wide lazy browser so repeated visual calls skip the 2-5s
    Firefox relaunch. Closed via atexit."""
    global _shared_browser_manager
    with _shared_browser_lock:
        if _shared_browser_manager is None:
            _shared_browser_manager = BrowserManager()
            _shared_browser_manager.start()
            atexit.register(_shared_browser_manager.stop)
    return _shared_browser_manager


DDGS_MIN_WIDTH = 500
DDGS_MIN_HEIGHT = 300
DDGS_MAX_ASPECT = 2.3
DDGS_MAX_VETOES = 3


ddgs_image_pick_prompt = """Is this image a good visual reference for the query? Reject if it is a cartoon/drawing/CGI, contains text overlay/logo/watermark/UI, is a collage or grid, tiny thumbnail, group shot, or does not match the query subject.
Output a JSON object enclosed in ```json with keys: "ok": true/false, "reason": short.
Query:
"""


def _ddgs_rank_and_pick(query, results):
    """Filter + rank ddgs image metadata by semantic similarity to the query."""
    valid = []
    for r in results:
        try:
            w, h = int(r.get("width") or 0), int(r.get("height") or 0)
        except Exception:
            w, h = 0, 0
        if w < DDGS_MIN_WIDTH or h < DDGS_MIN_HEIGHT:
            continue
        if not (1 / DDGS_MAX_ASPECT <= w / h <= DDGS_MAX_ASPECT):
            continue
        if not r.get("image"):
            continue
        valid.append(r)

    if not valid:
        return []

    titles = [(r.get("title") or "") + " " + (r.get("source") or "") for r in valid]
    try:
        sims = text_embeddings.embedding_gemini_compare(query, titles)
    except Exception as e:
        logging.info(f"ddgs-image-search: embedding rank failed : {e}")
        sims = []

    for i, r in enumerate(valid):
        r["_score"] = (sims[i] if i < len(sims) else 0.0) + min(
            0.3, max(0, (int(r.get("width") or 0) - DDGS_MIN_WIDTH) / 4000)
        )

    valid.sort(key=lambda r: r["_score"], reverse=True)
    return valid


def ddgs_image_search(q, chatbot: Chatbot.ChatInterface = None):
    """Fallback image search using ddgs metadata (no browser). Rate-limited by
    DuckDuckGo, so only used when the visual browser path fails."""
    try:
        from ddgs import DDGS

        results = DDGS().images(q, max_results=15, safesearch="off")
        ranked = _ddgs_rank_and_pick(q, results)
        logging.info(f"ddgs-image-search: {len(ranked)} ranked results for {q}")

        veto_checks = 0
        for r in ranked:
            src = r.get("image")
            try:
                import requests as _requests

                img_res = _requests.get(
                    src,
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                        "Gecko/20100101 Firefox/130.0"
                    },
                    timeout=10,
                )
                if img_res.status_code != 200 or len(img_res.content) < 5000:
                    continue
                img_bytes = img_res.content
            except Exception as e:
                logging.info(f"ddgs-image-search: fetch failed {src} : {e}")
                continue

            veto = False
            if chatbot is not None and veto_checks < DDGS_MAX_VETOES:
                veto_checks += 1
                try:
                    check_cb = new_summarizer_chatbot(chatbot)
                    check_cb.new_conversation()
                    prompt = Chatbot.Img(
                        _bytes=img_bytes, text=ddgs_image_pick_prompt + q
                    )
                    out = markdown_parse(check_cb.fetch_text(prompt))
                    parsed = json.loads(out)
                    veto = parsed.get("ok") is False
                    logging.info(
                        f"ddgs-image-search: veto={veto} for {src} : {parsed.get('reason')}"
                    )
                except Exception as e:
                    logging.info(f"ddgs-image-search: vision veto error : {e}")

            if not veto:
                return src, None
    except Exception as e:
        logging.error(f"ddgs-image-search: {e}")
    return None, None


@errors.log_ctx_errors
def search_visual(q, chatbot: Chatbot.ChatInterface):
    browser_manager = get_shared_browser_manager()
    page = browser_manager.get_page()
    src = None
    val = {}
    try:
        mk_url = (
            lambda q: f"https://duckduckgo.com/?q={q.replace(' ', '+')}&ia=images&iax=images"
        )
        page.goto(mk_url(q))
        time.sleep(2)
        # page.wait_for_load_state("networkidle", time)

        img_bytes = page.screenshot(full_page=True)

        element = None

        prompt = Chatbot.Img(_bytes=img_bytes, text=select_image_prompt + q)
        res = chatbot.fetch_text(prompt)

        out = markdown_parse(res)
        val = json.loads(out)
        logging.info(f"image-search-agent: LLM output {val}")

        text = val.get("text1")
        actual_alt = text

        if text:
            element = find_img_by_alt_text(page, text, pick_any=True)

            if element:
                actual_alt = element.get_attribute("alt")

                element.click()
                time.sleep(2)
                # page.wait_for_load_state("networkidle")

                expanded_image = find_img_by_alt_text(page, actual_alt, src_filter="//")

                if expanded_image:
                    element = expanded_image
                else:
                    logging.info("no expanded image")
            else:
                logging.info("no element found, getting the first image in page")
                element = page.locator("//img").first

        if element:
            src = element.get_attribute("src")
            if src:
                absolute_src = urljoin(page.url, src)
                logging.info(
                    f"playwright-image-search: src found for {q} using alt-text {val} : {absolute_src}"
                )
                src = absolute_src

        if not src:
            logging.info(f"playwright-image-search: src not found for {q}")

        image_options = []  # scrape_images_from_search_results(page, chatbot, q) or []

        if len(image_options) > 0:
            if src:
                image_options = [{"src": src, "alt": actual_alt}] + image_options

            image_selected = choose_best_image(page, chatbot, image_options, q)

            if image_selected:
                return image_selected[0].get("src"), image_selected[1]

    except Exception as e:
        logging.error(f"playwright-image-search: {e}")
    finally:
        page.close()

    return src, val.get("color")


SUMMARIZE_CHATBOT = os.environ.get(
    "SUMMARIZE_CHATBOT",
    "gemini_rest#gemini-3.5-flash-lite, groq",
)


def new_summarizer_chatbot(fallback: Chatbot.ChatInterface = None):
    """Dedicated cheap/fast chatbot for search-grounding summaries, independent
    of the primary chatbot chain. A fresh instance per call avoids shared state
    under concurrent summarization. Falls back to `fallback` if unavailable."""
    try:
        return Chatbot.ChatInterface(SUMMARIZE_CHATBOT)
    except Exception as e:
        logging.error(
            f"summarizer chatbot '{SUMMARIZE_CHATBOT}' init failed: {e}, "
            "falling back to caller chatbot"
        )
        return fallback


@errors.log_ctx_errors
def search(q, chatbot: Chatbot.ChatInterface):
    """Primary: browser-based visual search. Fallback: ddgs metadata search
    (keyless, no browser, but rate-limited)."""
    src, color = search_visual(q, chatbot)
    if src:
        return src, color

    logging.info(f"search: visual path failed for {q}, trying ddgs fallback")
    return ddgs_image_search(q, chatbot)


@errors.log_ctx_errors
def summarize_page(chatbot: Chatbot.ChatInterface, link, topic, word_limit=100):
    """Fetch a page's text (Lightpanda markdown dump, bs4 fallback) and summarize
    it with the dedicated summarizer chatbot. No browser screenshots / vision LLM
    needed for context."""
    try:
        text = fetch_page_text(link)
        if not text:
            logging.info(f"summarize_page: no text fetched for {link}")
            return ""

        text = text[:LIGHTPANDA_CONTEXT_CHARS]

        task = (
            f"Give a topic: {topic}, create a summary around it using the below page text, "
            f"add only relevant information with dates, outcomes, results using max {word_limit} words. "
            f"Ignore navigation menus, tables of contents and unrelated sections. "
            f"Output an empty summary only if the page text has nothing at all related to the topic. "
            f"Format as a single paragraph and enclose it with ```summary\n\nPage text:\n{text}"
        )
        sum_chatbot = new_summarizer_chatbot(chatbot)
        sum_chatbot.new_conversation()
        res = sum_chatbot.fetch_text(task)

        try:
            return markdown_parse(res, lang="summary")
        except Exception:
            return res
    except Exception as e:
        raise e


if __name__ == "__main__":

    def main():
        # chatbot = Chatbot.ChatInterface("gemini-2.0-flash")
        # l = "https://duckduckgo.com/?t=h_&q=grok+4+comparison+chart"
        # a = summarize_page(chatbot, l, "grok 4 comparison chart")

        from . import object_storage
        imgs = [
            object_storage.build_asset_url("images/349e2217-b0b1-4367-b9b8-aa2fd1205db7_ideogram_image.png"),
            object_storage.build_asset_url("images/00dc4f6f-59bb-49e2-8884-cb2bfd2fa0c4_ideogram_image.png"),
            # object_storage.build_asset_url("images/8f1f1bb7-96c9-435e-ae16-1634e9c2cb0f_ideogram_image.png"),
            # object_storage.build_asset_url("images/8f1f1bb7-96c9-435e-ae16-1634e9c2cb0f_ideogram_image.png"),
        ]
        # output = find_image_focus_direction(imgs, chatbot)
        im_bytes = make_collage(imgs)

        with open("im.png", "wb") as f:
            f.write(im_bytes)

        # print(output)

    main()
