#!/usr/bin/env python3
import argparse
import calendar
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ActionChains
from selenium.webdriver import ChromeOptions
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


# HSK level by weekday (0 = Monday)
HSK_BY_DAY = {
    0: 2,
    1: 2,
    2: 1,
    3: 3,
    4: 4,
    5: 6,
    6: 5,
}

DEFAULT_OUTPUT_DIR = Path("public/daily_story")
DEFAULT_PROFILE_DIR = Path(".selenium-chatgpt-profile")
CHATGPT_URL = "https://chatgpt.com/"

COMPOSER_SELECTORS = [
    (By.CSS_SELECTOR, "#prompt-textarea"),
    (By.CSS_SELECTOR, "textarea"),
    (By.CSS_SELECTOR, "div[contenteditable='true'][id='prompt-textarea']"),
    (By.CSS_SELECTOR, "div[contenteditable='true'][data-testid='textbox']"),
    (By.CSS_SELECTOR, "div[contenteditable='true'][contenteditable='true']"),
]

ASSISTANT_MESSAGE_SELECTORS = [
    (By.CSS_SELECTOR, "[data-message-author-role='assistant']"),
    (By.CSS_SELECTOR, "article [data-message-author-role='assistant']"),
    (By.CSS_SELECTOR, "main article"),
]

SEND_BUTTON_SELECTORS = [
    (By.CSS_SELECTOR, "button[data-testid='send-button']"),
    (By.CSS_SELECTOR, "button[aria-label*='Send']"),
    (By.CSS_SELECTOR, "button[aria-label*='send']"),
    (By.CSS_SELECTOR, "form button[type='submit']"),
]


def generate_prompt(hsk_level: int) -> str:
    return f"""
Write a short story in simplified Chinese at HSK {hsk_level} level.
The story should be at least 5 sentences long but less than 15 sentences.
Avoid repeating the same character names across stories.
Use a mix of common Chinese names or nicknames for variety.
Make the story engaging.
Output a raw JSON object with exactly three keys:
- "chinese": the original text
- "pinyin": pinyin for the story
- "english": the English translation
Do not wrap the JSON in Markdown. Do not add any explanation before or after it.
""".strip()


def clean_response(text: str) -> str:
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)


def build_dates(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def month_end(d: date) -> date:
    end_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, end_day)


def parse_args():
    today = date.today()
    parser = argparse.ArgumentParser(
        description="Generate monthly Chinese stories through ChatGPT in Selenium."
    )
    parser.add_argument(
        "--start-date",
        default=today.isoformat(),
        help="Start date in YYYY-MM-DD format. Defaults to today.",
    )
    parser.add_argument(
        "--end-date",
        help="End date in YYYY-MM-DD format. Defaults to the last day of start-date's month.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for generated JSON files.",
    )
    parser.add_argument(
        "--model",
        default="gpt-5",
        help="Preferred ChatGPT model label to request. Example: gpt-5 or gpt-5.5.",
    )
    parser.add_argument(
        "--profile-dir",
        default=str(DEFAULT_PROFILE_DIR),
        help="Chrome user-data-dir to persist ChatGPT login.",
    )
    parser.add_argument(
        "--driver-path",
        help="Optional path to chromedriver if Selenium Manager is unavailable.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run Chrome headless. Not recommended for first-time login.",
    )
    parser.add_argument(
        "--manual-ready",
        action="store_true",
        help="Pause after opening ChatGPT so you can verify login/model before generation starts.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Seconds to wait for ChatGPT responses.",
    )
    return parser.parse_args()


def parse_iso_date(raw: str) -> date:
    return datetime.strptime(raw, "%Y-%m-%d").date()


def create_driver(profile_dir: Path, driver_path: Optional[str], headless: bool):
    options = ChromeOptions()
    options.add_argument(f"--user-data-dir={profile_dir.resolve()}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1440,1200")
    if headless:
        options.add_argument("--headless=new")

    service = Service(executable_path=driver_path) if driver_path else Service()
    return webdriver.Chrome(service=service, options=options)


def build_chat_url(model: str) -> str:
    if not model:
        return CHATGPT_URL
    return f"{CHATGPT_URL}?model={model}"


def wait_for_any(driver, selectors, timeout):
    wait = WebDriverWait(driver, timeout)
    last_error = None
    for by, selector in selectors:
        try:
            return wait.until(EC.presence_of_element_located((by, selector)))
        except TimeoutException as exc:
            last_error = exc
    raise last_error or TimeoutException("No matching element found.")


def find_visible_element(driver, selectors):
    for by, selector in selectors:
        for element in driver.find_elements(by, selector):
            if element.is_displayed() and element.is_enabled():
                return element
    return None


def wait_for_visible_element(driver, selectors, timeout):
    end_time = time.time() + timeout
    while time.time() < end_time:
        element = find_visible_element(driver, selectors)
        if element is not None:
            return element
        time.sleep(0.5)
    raise TimeoutException("No visible matching element found.")


def ensure_chat_ready(driver, model: str, timeout: int, manual_ready: bool):
    driver.get(build_chat_url(model))
    wait_for_visible_element(driver, COMPOSER_SELECTORS, timeout)

    if manual_ready:
        print(
            f"Browser is open at ChatGPT. Confirm you're logged in and that the model is set to '{model}'."
        )
        input("Press Enter here when the page is ready to generate stories...")


def open_fresh_chat(driver, model: str, timeout: int):
    driver.get(build_chat_url(model))
    wait_for_visible_element(driver, COMPOSER_SELECTORS, timeout)


def set_prompt_text(driver, prompt: str, timeout: int):
    composer = wait_for_visible_element(driver, COMPOSER_SELECTORS, timeout)
    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center'});",
        composer,
    )
    time.sleep(0.5)

    tag_name = composer.tag_name.lower()
    if tag_name == "textarea":
        driver.execute_script("arguments[0].focus();", composer)
        composer.clear()
        composer.send_keys(prompt)
    else:
        driver.execute_script(
            """
            const el = arguments[0];
            const text = arguments[1];
            el.focus();
            el.textContent = '';
            el.dispatchEvent(new InputEvent('beforeinput', {
                bubbles: true,
                cancelable: true,
                inputType: 'insertText',
                data: text
            }));
            el.textContent = text;
            el.dispatchEvent(new InputEvent('input', {
                bubbles: true,
                inputType: 'insertText',
                data: text
            }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            """,
            composer,
            prompt,
        )
        ActionChains(driver).move_to_element(composer).click(composer).perform()

    try:
        composer.send_keys(Keys.ENTER)
        return
    except Exception:
        pass

    submit_prompt(driver, composer, timeout)


def submit_prompt(driver, composer, timeout: int):
    end_time = time.time() + timeout
    last_error = None

    while time.time() < end_time:
        send_button = find_visible_element(driver, SEND_BUTTON_SELECTORS)
        if send_button is not None:
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});",
                    send_button,
                )
                driver.execute_script("arguments[0].click();", send_button)
                return
            except Exception as exc:
                last_error = exc

        try:
            form = composer.find_element(By.XPATH, "./ancestor::form[1]")
            driver.execute_script("arguments[0].requestSubmit();", form)
            return
        except Exception as exc:
            last_error = exc

        time.sleep(0.5)

    raise last_error or TimeoutException("Could not submit prompt.")


def assistant_messages(driver):
    messages = []
    seen = set()
    for by, selector in ASSISTANT_MESSAGE_SELECTORS:
        for element in driver.find_elements(by, selector):
            text = element.text.strip()
            if text and text not in seen:
                seen.add(text)
                messages.append(element)
    return messages


def wait_for_response_text(driver, timeout: int) -> str:
    start = time.time()
    stable_for = 0
    last_text = ""

    while time.time() - start < timeout:
        messages = assistant_messages(driver)
        if messages:
            candidate = messages[-1].text.strip()
            if candidate:
                if candidate == last_text:
                    stable_for += 1
                else:
                    last_text = candidate
                    stable_for = 0

                # A few stable polling rounds is usually enough once streaming is done.
                if stable_for >= 6:
                    return candidate
        time.sleep(1)

    raise TimeoutException("Timed out waiting for ChatGPT response.")


def generate_story(driver, story_date: date, output_dir: Path, model: str, timeout: int):
    hsk_level = HSK_BY_DAY[story_date.weekday()]
    prompt = generate_prompt(hsk_level)

    open_fresh_chat(driver, model, timeout)
    set_prompt_text(driver, prompt, timeout)
    raw_response = wait_for_response_text(driver, timeout)

    try:
        story = json.loads(clean_response(raw_response))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse JSON for {story_date.isoformat()}. Raw response:\n{raw_response}"
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"{story_date.isoformat()}.json"
    with filename.open("w", encoding="utf-8") as handle:
        json.dump(story, handle, ensure_ascii=False, indent=2)

    print(f"Saved {filename}")


def main():
    args = parse_args()
    start_date = parse_iso_date(args.start_date)
    end_date = parse_iso_date(args.end_date) if args.end_date else month_end(start_date)
    output_dir = Path(args.output_dir)
    profile_dir = Path(args.profile_dir)

    driver = None
    try:
        driver = create_driver(profile_dir, args.driver_path, args.headless)
        ensure_chat_ready(driver, args.model, args.timeout, args.manual_ready)

        for story_date in build_dates(start_date, end_date):
            try:
                generate_story(driver, story_date, output_dir, args.model, args.timeout)
            except Exception as exc:
                print(f"Failed for {story_date.isoformat()}: {exc}", file=sys.stderr)
    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    main()
