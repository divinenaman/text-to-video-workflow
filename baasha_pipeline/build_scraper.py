from threading import ExceptHookArgs
from pydantic import errors
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.firefox.options import Options

from . import chatbot as Chatbot
from .logger import logging
from .prompts.splitters import markdown_parse
from . import errors
import requests
from bs4 import BeautifulSoup
import json
import time

# Initialize Selenium WebDriver (make sure you have the correct driver executable)
driver = None


def get_driver():
    global driver

    firefox_options = Options()
    firefox_options.add_argument("-headless")

    driver = webdriver.Firefox(options=firefox_options)
    # page load timeout 5 sec
    driver.set_page_load_timeout(5)


def generate_js_query(chatbot, link, html, task):
    """
    Generate JavaScript query using LLM.
    """

    build_scraper_prompt = """Given below is an HTML page from which data needs to be retrieved. Given a task which describes the content needed -- fetch it from the HTML or generate content after analyzing the page, to achieve this systematically create js code to perform following tasks: \nTask: \n1. create a function named `onloadComplete`, which checks the content to be scraped is ready and scrolls the page slowly to the end of the page to load all the content. \n2. create a function named `nextPage`, which clicks the next page button. \n2. create a function `fetchContent`, which fetches the content described and formats in the exact manner as described. Retrieve all the relevant content in the required format.\nFor reliability add null checks during for query selectors. Format the above 3 output as s single js file, in the global window variable add a new key named `scraperData` of type object with keys and values as `onloadComplete`, `nextPage` and `fetchContent`. Enclosed the output in ```javascript. \n\nContent to be scraped from HTML: """

    p = build_scraper_prompt + task + "\n\nHTML to be scraped: " + html
    retry = 3
    out = None
    result = None

    while retry > 0:
        logging.info("building-scraper")
        res = chatbot.fetch_text(p)
        out = markdown_parse(res, lang="javascript")
        result = None

        if out:
            logging.info("validating-scraper")
            result = run_scraper(link, out, pages=1)

        if result and len(result) > 0:
            return (out, result[0])

        logging.info("building-generic-scraper: retrying")
        retry -= 1

    return (out, None)


def fetch_and_clean_html(url, timeout=5):
    """
    Fetch HTML from a given URL and remove <head> and <script> tags.
    """

    if not driver:
        get_driver()

    driver.get(url)
    time.sleep(timeout)

    ele = driver.find_element(By.TAG_NAME, "body")
    html = ele.get_attribute("innerHTML")

    if len(html) > 5000:
        html = html[0:5000]

    return html


def run_scraper(url, scraper_script, pages):

    fetch_content = scraper_script + "\nreturn scraperData.fetchContent()"
    onload_content = scraper_script + "\nreturn scraperData.onloadComplete()"
    next_page = scraper_script + "\nreturn scraperData.nextPage()"

    if not driver:
        get_driver()

    driver.get(url)
    time.sleep(5)

    result = []

    for i in range(pages):
        if i > 0:
            driver.execute_script(next_page)
            time.sleep(10)
        loaded = driver.execute_script(onload_content)
        data = driver.execute_script(fetch_content)
        result.append(data)

    return result


@errors.log_ctx_errors
def scrape_page(chatbot, task, link):
    html = fetch_and_clean_html(link, timeout=20)
    out, scraped = generate_js_query(chatbot, link, html, task)

    if not out:
        return None

    return scraped


def build_and_run_generic_scraper(task, link, pages=3):
    chatbot = Chatbot.ChatInterface("gemini-2.0-flash")
    chatbot.new_conversation()

    html = fetch_and_clean_html(link)
    out, _ = generate_js_query(chatbot, link, html, task)

    if not out:
        logging.warn(f"scrape script not generared / empty")
        return None, None

    result = run_scraper(link, out, pages)

    return result, out


if __name__ == "__main__":

    # t = "fetch the video-link and descriptions of the displayed videos and format as JSON array with keys video_link and desp"

    chatbot = Chatbot.ChatInterface("gemini-1.5-flash")
    chatbot.new_conversation()

    # u = "https://www.istockphoto.com/videos/ai?page=1"

    # html = fetch_and_clean_html(u)
    # out = generate_js_query(chatbot, u, html, t)

    q = "What is the SCO submit ?"
    link = lambda x: f"https://duckduckgo.com/?q={x.replace(' ', '+')}&ia=web"
    summary = scrape_page(
        chatbot,
        "fetch summary text from top 5 links along with any summarized text / information about the search query and output as a single paragraph",
        link(q),
    )

    print(summary)

    # result = run_scraper(u, out)
