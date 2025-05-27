import atexit
import os
import time
from datetime import datetime

import selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class ParariusBot:
    def __init__(self, config, location, twilio_client):
        self.email = config["email"]
        self.password = config["password"]
        self.debug = config["debug"]
        self.time_between_requests = config["time_between_requests"]
        self.time_between_runs = config.get("time_between_runs", 0)

        self.location = location
        self.twilio_client = twilio_client

        options = webdriver.ChromeOptions()
        if not self.debug:
            options.add_argument("--headless")

        self.driver = webdriver.Chrome(options=options)
        atexit.register(self.cleanup)

    def run(self):
        counter = 0
        while True:
            self.process_listings()
            time.sleep(self.time_between_runs)

            counter += 1
            if counter % 25 == 0:
                print(f"Bot still searchin for listings in {self.location.name}...")

    def process_listings(self):
        self.driver.get(self.location.url)
        self.get_rid_of_cookie_consent()
        listings = self.driver.find_elements(By.CSS_SELECTOR, ".search-list__item--listing")  # search-list__item includes ads

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

        # Open the listing in a new tab to avoid losing the listings page
        self.driver.execute_script(f"window.open('{listing_url}', '_blank');")
        # Switch to the new tab and apply
        self.driver.switch_to.window(self.driver.window_handles[1])
        self.apply()

        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"Applied at {current_time}")
        if not self.debug:
            self.twilio_client.send_notification(
                listing_url, price, self.location.name
            )

        # Mark the listing as applied
        self.write_applied_listing(
            listing_url, self.location.applied_listings_file
        )

        self.driver.switch_to.window(self.driver.window_handles[0])

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
        # Open the listing in the same tab
        contact_link = self.driver.find_element(
            By.CSS_SELECTOR, ".listing-reaction-button"
        )  # Selects the anchor link in each listing
        contact_url = contact_link.get_attribute("href")
        self.driver.get(contact_url)

        # Check if you need to login
        if self.driver.current_url == "https://www.pararius.nl/inloggen":
            self.login()

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
        self.driver.close()

    def login(self):
        # Login via email by clicking the "Ga verder met Email" button
        email_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "account-access-options__button--email"))
        )
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

        # Click the "Inloggen" button
        login_button = WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".button--primary"))
        )
        login_button.click()

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
        # Write the URL of the listing to the file
        with open(applied_listings_file, "a") as file:
            file.write(url + "\n")

    @staticmethod
    def get_listing_prince(listing):
        price_element = listing.find_element(
            By.CSS_SELECTOR, ".listing-search-item__price"
        )  # Selects the price element in each listing
        price = price_element.text  # Get the text content (e.g., "€ 718 per maand")
        price = (
            price.replace("€", "")
            .replace("per maand", "")
            .replace(" ", "")
            .replace(".", "")
        )  # Remove unwanted characters
        try:
            price = int(price)
        except:
            price = 1000
        return price

    @staticmethod
    def get_listing_area(listing):
        area_element = listing.find_element(
            By.CSS_SELECTOR, ".illustrated-features__item--surface-area"
        )
        area = area_element.text
        area = area.replace("m²", "").replace(" ", "")
        area = int(area)

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
        self.driver.close()
