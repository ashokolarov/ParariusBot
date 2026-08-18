import os
import re
from copy import deepcopy
from abc import ABC, abstractmethod

import yaml

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class NotificationClient(ABC):

    @abstractmethod
    def send_notification(self, url, price, location):
        pass


class PrintClient(NotificationClient):
    def send_notification(self, url, price, location):
        print(f"URL: {url}\nPrice: {price}\nLocation: {location}\n")


class TelegramClient(NotificationClient):
    API_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, config):
        self.token = config["bot_token"]
        self.receivers = config["receivers"]
        # Empty values expand fine, so catch them here rather than letting the
        # first application fail on a 401 hours into a run.
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN is empty; get one from @BotFather")
        for name, receiver in self.receivers.items():
            if not receiver.get("chat_id"):
                raise ValueError(
                    f"Telegram receiver '{name}' has no chat_id; run "
                    f"`python telegram_setup.py` to find it"
                )
        # Telegram's API is a plain HTTPS call, so there is no SDK to install.
        import requests

        self.requests = requests

    def send_notification(self, url, price, location):
        for receiver in self.receivers.values():
            text = receiver["message"].format(url=url, price=price, location=location)
            self.call(
                "sendMessage",
                {"chat_id": str(receiver["chat_id"]), "text": text},
            )

    def call(self, method, payload):
        response = self.requests.post(
            self.API_URL.format(token=self.token, method=method),
            json=payload,
            timeout=10,
        )
        body = response.json()
        if not body.get("ok"):
            # Telegram answers 4xx with a readable reason ("chat not found",
            # "Unauthorized"), which is far more useful than the status code.
            raise RuntimeError(
                f"Telegram {method} failed: "
                f"{body.get('description', response.text)}"
            )
        return body["result"]


class Location:
    def __init__(self, config):
        self.name = config["name"]
        self.url = config["url"]
        self.min_price = config["min_price"]
        self.max_price = config["max_price"]
        self.message = config["message"]
        self.applied_listings_file = config["applied_listings_file"]

        self.min_area = config.get("min_area", None)
        self.min_rooms = config.get("min_rooms", None)


def generate_locations(config):
    locations = []
    default_location_config = config["default"]
    for location_name, location_config in config.items():
        if location_name != "default":
            merged_config = deepcopy(default_location_config)
            if location_config is not None:
                merged_config.update(location_config)
            merged_config["name"] = location_name
            merged_config["url"] = default_location_config["url"] + "/" + location_name
            merged_config["applied_listings_file"] = (
                default_location_config["applied_listings_location"]
                + "/"
                + location_name
                + ".txt"
            )
            location = Location(merged_config)
            locations.append(location)
    return locations


def load_dotenv(dotenv_file=".env"):
    # Read KEY=value pairs from .env into the environment. Variables already
    # set in the real environment win, so you can override .env per run.
    if not os.path.exists(dotenv_file):
        return
    with open(dotenv_file, "r") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def expand_env_vars(config):
    # Replace every ${VAR} in the config with the environment variable's value.
    if isinstance(config, dict):
        return {key: expand_env_vars(value) for key, value in config.items()}
    if isinstance(config, list):
        return [expand_env_vars(value) for value in config]
    if isinstance(config, str):
        return ENV_VAR_PATTERN.sub(lookup_env_var, config)
    return config


def lookup_env_var(match):
    name = match.group(1)
    if name not in os.environ:
        raise KeyError(
            f"config.yaml references ${{{name}}}, but that environment "
            f"variable is not set. Set it in your shell or add it to .env"
        )
    return os.environ[name]


def parse_config(config_file):
    load_dotenv()
    with open(config_file, "r") as file:
        config = yaml.safe_load(file)
    return expand_env_vars(config)


if __name__ == "__main__":
    config_file = "config.yaml"
    config = parse_config(config_file)

    locations = generate_locations(config["locations"])

    print(locations)
