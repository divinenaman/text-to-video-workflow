import os
from playwright.sync_api import sync_playwright, Playwright, Browser
import json
from . import chatbot as Chatbot
from .prompts.splitters import markdown_parse
from .logger import logging
from . import errors, text_embeddings
import threading
import requests
import time


class BrowserManager:
    def __init__(self, headless=False):
        self.headless = headless
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


@errors.log_ctx_errors
def create_lottie_animation(
    chatbot: Chatbot.ChatInterface, query, image, image_width=None, image_height=None
):

    image_asset = {
        "id": "image_url",
        "w": image_width or 512,
        "h": "auto",
        "u": "",
        "p": "http://image.png",
        "e": 1,
    }

    prompt_text = f'Given a basic image description `{query}`and an image, create a motion graphics to show an image animated using lottie. Keep the lottie animation aesthetic, short, relevant, creative. Add the image in the lottie\'s assets block with config ${json.dumps(image_asset)}, to refer to the image use `refId` key with value as `image_url`. The animation should end with the image visible. It should be quick max 1-2 seconds long. Analyse the query and the image to create an animation that is relevant to the context. Animations can vary from gimble like zoom-in/zoom-out to important sections of an image, gimble like translation to create motion, adding artifacts relevant to image like shapes or confetti, intro animation to reveal the image or be creative sticking strictly to what suits the image and its descriptions. Pick colors from the image itself except black or white. Output a JSON with key lottie inclosed in markdown block ```json (Example: ```json {{ "lottie": "<lottie>" }}```) . \n\n Image - '

    res = requests.get(image, timeout=5000)
    res.raise_for_status()

    img_bytes = res.content
    prompt = Chatbot.Img(_bytes=img_bytes, text=prompt_text)

    sys_prompt = None
    with open(os.path.join(os.path.dirname(__file__), "lottie_spec_prompt.md")) as f:
        sys_prompt = f.read()

    retry = 2
    while retry > 0:
        try:
            res = chatbot.fetch_text(
                prompt,
                is_context=False,
                system_prompt=sys_prompt,
                custom_model="meta-llama/llama-4-maverick-17b-128e-instruct",
            )

            out = json.loads(markdown_parse(res))
            break
        except Exception as e:
            logging.error(f"motion-graphics-agent-error: {e}")

        retry -= 1

    logging.info(f"lottie animation: {json.dumps(out)}")

    lottie = out.get("lottie") or out.get("value") or out
    retry = 2

    try:
        browser = BrowserManager()
        while lottie and retry > 0:

            if lottie:
                if isinstance(lottie, dict):
                    lottie = json.dumps(lottie)

                lottie_patched = lottie.replace("http://image.png", image)
                is_ok, ss = test_lottie(chatbot, browser, lottie_patched)

                if is_ok:
                    return lottie_patched

                if not is_ok and not ss:
                    return None

                elif not is_ok and retry - 1 >= 0:
                    time.sleep(2)
                    retry -= 1

                    try:
                        feedback = Chatbot.Img(
                            _bytes=ss,
                            text=f"This is a lottie structure - {lottie}.\n\nThe lottie is not working as expected, it can be due to rendering a blank screen or image not being visible or animation is not playing or structure error. Think step by step and identify the issue then fix it reliably and output a JSON with key lottie and value as the fixed lottie structure enclosed in ```json block. The expectation is to create a motion graphic with the image creatively with the entirely when the animation finishes, this is of utmost importance.",
                        )
                        res = chatbot.fetch_text(
                            feedback.text,
                            system_prompt=sys_prompt,
                            custom_model="openai/gpt-oss-120b",
                        )
                        out = markdown_parse(res)
                        if out:
                            out = json.loads(out)
                            lottie = out.get("lottie") or out.get("value") or out

                    except Exception as e:
                        logging.error(e)
                        pass
                else:
                    return None
        return None
    finally:
        browser.stop()


@errors.log_ctx_errors
def test_lottie(chatbot, browser_manager, lottie):
    page = browser_manager.get_page()
    img_bytes = None
    try:
        html_content = (
            f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.13.0/lottie.min.js"></script>
        </head>
        <body>
            <div id="lottie-container" style="width: 512px; height: 512px;"></div>
            <script>
                var animationData = {lottie};
        """
            + """
                lottie.loadAnimation({
                    container: document.getElementById('lottie-container'),
                    renderer: 'svg',
                    loop: false,
                    autoplay: true,
                    animationData: animationData
                });
            </script>
        </body>
        </html>
        """
        )
        page.set_content(html_content)
        page.wait_for_load_state("networkidle", timeout=8000)
        img_bytes = page.screenshot()
        prompt = Chatbot.Img(
            _bytes=img_bytes,
            text="Is the below image visible or is it a blank screen / solid color ? Output yes or no enclosed in ```output",
        )
        res = chatbot.fetch_text(prompt)
        out: str = markdown_parse(res, lang="output")

        logging.info(f"lottie test result: {out}")

        if out and out.strip().lower() == "yes":
            return True, img_bytes

    finally:
        page.close()

    return False, img_bytes


if __name__ == "__main__":

    def main():
        chatbot = Chatbot.ChatInterface("groq")
        from . import object_storage
        a = create_lottie_animation(
            chatbot,
            "Confetti",
            object_storage.build_asset_url("images/349e2217-b0b1-4367-b9b8-aa2fd1205db7_ideogram_image.png"),
        )
        print(a)

    main()
