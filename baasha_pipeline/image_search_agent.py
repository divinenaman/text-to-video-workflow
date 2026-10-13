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


@errors.log_ctx_errors
def search(q, chatbot: Chatbot.ChatInterface):
    browser_manager = BrowserManager()
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
        browser_manager.stop()

    return src, val.get("color")


@errors.log_ctx_errors
def summarize_page(chatbot: Chatbot.ChatInterface, link, topic, word_limit=100):
    browser_manager = BrowserManager()
    page = browser_manager.get_page()

    try:
        page.goto(link)
        page.evaluate("window.scrollBy(0, 200);")

        img_bytes = page.screenshot()

        task = f"Give a topic: {topic}, create a summary around it using the below image, add only revelant information with dates, outcomes, results using max {word_limit} words. Format as a single paragraph and enclose it with ```summary"
        prompt = Chatbot.Img(_bytes=img_bytes, text=task)
        res = chatbot.fetch_text(prompt)

        try:
            return markdown_parser(res, lang="summary")
        except:
            return res

    except Exception as e:
        raise e
    finally:
        page.close()
        browser_manager.stop()


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
