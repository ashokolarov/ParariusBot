import atexit
import os
import re
import time
from datetime import datetime

import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class SecurityCheckError(Exception):
    """Cloudflare served its bot-check interstitial instead of the page."""


class ParariusBot:
    # Titles Cloudflare uses for the "Performing security verification" page.
    SECURITY_CHECK_TITLES = ("just a moment", "even geduld")

    def __init__(self, config, location, notification_client):
        self.email = config["email"]
        self.password = config["password"]
        # debug is a dry run: browse and match listings, but never submit an
        # application or send a notification.
        self.debug = config["debug"]
        # headless is independent of debug, so you can watch a real run in a
        # visible window. Defaults to the old behaviour when unset.
        self.headless = config.get("headless", not self.debug)
        # With a visible window you can solve a challenge by hand, so wait
        # long enough for that to be possible.
        self.security_check_timeout = config.get(
            "security_check_timeout", 30 if self.headless else 120
        )
        self.time_between_requests = config["time_between_requests"]
        self.time_between_runs = config.get("time_between_runs", 0)

        self.location = location
        self.notification_client = notification_client

        options = webdriver.ChromeOptions()
        # ChromeDriver sets navigator.webdriver, which Cloudflare's checkbox
        # challenge reads. It verifies, re-runs its detection, sees the flag and
        # starts over, which is why the checkbox can loop forever. These turn
        # that signal off.
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        profile_dir = config.get("chrome_profile_dir")
        if profile_dir:
            # Reusing a profile keeps cookies (including Cloudflare's clearance
            # cookie), so a run does not start as a brand new visitor every
            # time. One directory per location: Chrome locks a profile to a
            # single running instance and the locations run in parallel.
            profile_path = os.path.abspath(
                os.path.join(profile_dir, self.location.name)
            )
            os.makedirs(profile_path, exist_ok=True)
            options.add_argument(f"--user-data-dir={profile_path}")

        if self.headless:
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1920,1080")

        self.driver = webdriver.Chrome(options=options)
        if self.headless:
            # Headless Chrome reports itself as "HeadlessChrome" in the user
            # agent, which Cloudflare blocks with a "Just a moment..." page, so
            # no listings are ever found. Reuse the real user agent with that
            # token removed instead of hardcoding a version that goes stale.
            user_agent = self.driver.execute_script(
                "return navigator.userAgent"
            ).replace("HeadlessChrome", "Chrome")
            self.driver.execute_cdp_cmd(
                "Network.setUserAgentOverride", {"userAgent": user_agent}
            )
        atexit.register(self.cleanup)

    def run(self):
        counter = 0
        while True:
            try:
                self.process_listings()
            except Exception as e:
                # Keep the bot alive; a failed cycle just retries next time.
                print(f"Run failed for {self.location.name}: {e}")
            time.sleep(self.time_between_runs)

            counter += 1
            if counter % 25 == 0:
                print(f"Bot still searchin for listings in {self.location.name}...")

    def process_listings(self):
        self.driver.get(self.location.url)
        time.sleep(self.time_between_requests)

        self.wait_for_security_check()
        self.get_rid_of_cookie_consent()
        listings = self.driver.find_elements(By.CSS_SELECTOR, ".search-list__item--listing")  # search-list__item includes ads
        print('Found ' + str(len(listings)) + ' listings in ' + self.location.name)

        applied_listings = self.read_applied_listings(
            self.location.applied_listings_file
        )
        for listing in listings:
            try:
                self.process_single_listing(listing, applied_listings)
            except Exception as e:
                print(e)

    def process_single_listing(self, listing, applied_listings):
        # Check the price
        price = self.get_listing_price(listing)

        if price < self.location.min_price or price > self.location.max_price:
            return

        if self.location.min_area is not None:
            area = self.get_listing_area(listing)
            if area < self.location.min_area:
                return

        if self.location.min_rooms is not None:
            rooms = self.get_listing_rooms(listing)
            if rooms < self.location.min_rooms:
                return

        # Open the listing link
        listing_link = listing.find_element(
            By.CSS_SELECTOR, "a"
        )  # Selects the anchor link in each listing
        listing_url = listing_link.get_attribute("href")

        # Check if already applied
        if listing_url in applied_listings:
            return

        current_time = datetime.now().strftime("%H:%M:%S")
        print(
            f"Found new listing {listing_url} with price {price} in {self.location.name} at {current_time}"
        )

        # Open the listing in a new tab to avoid losing the listings page.
        # Track handles by identity rather than by index: a restored profile
        # can start with several tabs, so window_handles[1] is not necessarily
        # the tab we just opened.
        search_handle = self.driver.current_window_handle
        previous_handles = set(self.driver.window_handles)
        self.driver.execute_script(f"window.open('{listing_url}', '_blank');")
        listing_handle = WebDriverWait(self.driver, 10).until(
            lambda driver: next(
                iter(set(driver.window_handles) - previous_handles), None
            )
        )
        self.driver.switch_to.window(listing_handle)
        try:
            self.apply()
        finally:
            # Always close the listing tab and go back to the results, even if
            # applying failed. Otherwise the driver is left sitting on the dead
            # tab and every later listing in this run fails too.
            if listing_handle in self.driver.window_handles:
                self.driver.switch_to.window(listing_handle)
                self.driver.close()
            self.driver.switch_to.window(search_handle)

        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"Applied at {current_time}")

        if self.debug:
            # A dry run must not leave the listing marked as applied, or the
            # next real run would skip it.
            print(f"Dry run, not recording {listing_url}")
            return

        # Record the application before notifying. Notifying first means a
        # Telegram error (bad token, wrong chat id, network blip) throws before
        # the listing is written, so it looks new again next run and gets
        # applied to a second time.
        self.write_applied_listing(
            listing_url, self.location.applied_listings_file
        )
        applied_listings.add(listing_url)

        try:
            self.notification_client.send_notification(
                listing_url, price, self.location.name
            )
        except Exception as e:
            # The application went through; a failed notification is not worth
            # failing the listing over.
            print(f"Applied, but the notification failed: {e}")

    def wait_for_page_load(self, timeout=30):
        # A newly opened tab starts on about:blank with an empty title, which
        # makes the security check below think it is looking at a clean page.
        # Wait for the real document before judging anything about it.
        WebDriverWait(self.driver, timeout).until(
            lambda driver: driver.current_url not in ("", "about:blank")
            and driver.execute_script("return document.readyState") == "complete"
        )

    def on_security_check_page(self):
        title = self.driver.title.lower()
        return any(check in title for check in self.SECURITY_CHECK_TITLES)

    def wait_for_security_check(self, timeout=None):
        # Cloudflare sometimes answers with its bot-check interstitial instead
        # of the real page. It often clears on its own, and in a visible window
        # you can solve it by hand, so wait it out rather than searching a page
        # that isn't there yet.
        timeout = self.security_check_timeout if timeout is None else timeout
        deadline = time.time() + timeout
        announced = False
        while time.time() < deadline:
            if not self.on_security_check_page():
                return
            if not announced and not self.headless:
                print(
                    f"Cloudflare check on {self.location.name}; solve it in the "
                    f"browser window if it does not clear by itself "
                    f"({timeout}s)"
                )
                announced = True
            time.sleep(1)
        raise SecurityCheckError(
            f"Cloudflare security check did not clear within {timeout}s for "
            f"{self.driver.current_url}"
        )

    def get_rid_of_cookie_consent(self):
        try:
            reject_cookies = self.driver.find_element(By.ID, 'onetrust-reject-all-handler')
        except selenium.common.exceptions.NoSuchElementException as e:
            # Button not found, no problem here
            pass
        else:
            WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(reject_cookies)
            )
            reject_cookies.click()

    def apply(self):
        # The tab was just opened, so wait for the page rather than assuming
        # it is already there.
        self.wait_for_page_load()
        self.wait_for_security_check()
        # .listing-reaction-button is a <wc-listing-reaction-button> web
        # component with no href of its own; the contact link is the anchor
        # inside it.
        contact_link = WebDriverWait(self.driver, 30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".listing-reaction-button a")
            )
        )
        contact_url = contact_link.get_attribute("href")
        self.driver.get(contact_url)
        self.wait_for_page_load()
        self.wait_for_security_check()

        # Check if you need to login. Match on the path so a redirect that
        # carries query parameters is still recognised.
        if "/inloggen" in self.driver.current_url:
            self.login()
            # Logging in does not always land back on the contact form.
            if "/contact/" not in self.driver.current_url:
                self.driver.get(contact_url)
                self.wait_for_page_load()
                self.wait_for_security_check()

        time.sleep(self.time_between_requests)
        if self.location.message:
            # Locate the text area and enter the message
            message_field = self.driver.find_element(By.XPATH, "//textarea")
            message_field.clear()
            message_field.send_keys(self.location.message)

        time.sleep(self.time_between_requests)
        # Click the "Verstuur" button
        submit_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".form__button--submit"))
        )
        if not self.debug:
            self.driver.execute_script("arguments[0].click();", submit_button)
        # The tab is closed by process_single_listing's finally block.

    def login(self):
        self.get_rid_of_cookie_consent()
        # Older layouts hid the form behind a "Ga verder met Email" button. The
        # current one puts the fields straight on the page, so only click it
        # when it is actually there.
        try:
            email_button = self.driver.find_element(
                By.CLASS_NAME, "account-access-options__button--email"
            )
        except selenium.common.exceptions.NoSuchElementException:
            pass
        else:
            email_button.click()

        # Wait for the email field and enter your email
        email_field = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//input[@type="email"]'))
        )
        email_field.clear()
        email_field.send_keys(self.email)

        time.sleep(self.time_between_requests)

        # Wait for the password field and enter your password
        password_field = WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.XPATH, '//input[@type="password"]'))
        )
        password_field.clear()
        password_field.send_keys(self.password)

        time.sleep(self.time_between_requests)

        # Click the "Inloggen" button. Scope it to the form's submit button:
        # .button--primary on its own also matches other buttons on the page.
        login_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[type='submit'].button--primary")
            )
        )
        login_button.click()
        self.wait_for_page_load()
        self.wait_for_security_check()
        if "/inloggen" in self.driver.current_url:
            raise RuntimeError(
                "Login did not go through; check the credentials in .env"
            )

    @staticmethod
    def read_applied_listings(applied_listings_file):
        # Create the file if it doesn't exist
        if not os.path.exists(applied_listings_file):
            return set()
        # Read the file and return the set of applied listings
        with open(applied_listings_file, "r") as file:
            return set(line.strip() for line in file)

    @staticmethod
    def write_applied_listing(url, applied_listings_file):
        # The configured folder is not guaranteed to exist; without this the
        # append raises and the listing is silently never recorded.
        directory = os.path.dirname(applied_listings_file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Write the URL of the listing to the file
        with open(applied_listings_file, "a") as file:
            file.write(url + "\n")

    @staticmethod
    def get_listing_price(listing):
        try:
            price_element = listing.find_element(
                By.CSS_SELECTOR, ".listing-search-item__price"
            )  # Selects the price element in each listing
        except selenium.common.exceptions.NoSuchElementException as e:
            print('No price found')
            raise
        price = price_element.get_attribute('innerHTML')  # Get the text content (e.g., "€ 718 per maand")

        # ^         start of string
        # [^0-9]*   non-numbers, optional
        # (         capture group
        # \d+       one or more digits
        # (?:       non-capture group
        # \.\d+     literal dot, followed by one or more digits
        # ?         optional
        price = re.match(r'^[^0-9]*(\d+(?:\.\d+)?)', price).group(1)
        price = price.replace(".", "")  # Remove unwanted characters
        try:
            price = int(price)
        except Exception as e:
            print(e)
            raise
        return price

    @staticmethod
    def get_listing_area(listing):
        area_element = listing.find_element(
            By.CSS_SELECTOR, ".illustrated-features__item--surface-area"
        )
        element_text = area_element.text
        area_str = element_text.replace("m²", "").replace(" ", "")
        try:
            area = int(area_str)
        except Exception as e:
            print(e)
            raise

        return area

    @staticmethod
    def get_listing_rooms(listing):
        rooms_element = listing.find_element(
            By.CSS_SELECTOR, ".illustrated-features__item--number-of-rooms"
        )  # Selects the price element in each listing
        rooms = rooms_element.text  # Get the text content (e.g., "€ 718 per maand")
        rooms = (
            rooms.replace("kamers", "")
            if "kamers" in rooms
            else rooms.replace("kamer", "")
        )
        rooms = rooms.replace(" ", "")
        rooms = int(rooms)

        return rooms

    def cleanup(self):
        print(f"Closing driver for {self.location.name}")
        try:
            # quit() ends the session; close() only closes one window and
            # leaves chromedriver running.
            self.driver.quit()
        except Exception:
            # Already gone; nothing useful to do while shutting down.
            pass
