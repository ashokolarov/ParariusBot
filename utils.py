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


class TwilioClient(NotificationClient):
    def __init__(self, config):
        from twilio.rest import Client
        self.client = Client(config["account_sid"], config["auth_token"])
        self.sender = config["sender"]
        self.receivers = config["receivers"]

    def send_notification(self, url, price, location):
        for receiver in self.receivers.values():
            body = receiver["message"].format(url=url, price=price, location=location)
            receiver_number = receiver["phone_number"]
            self.client.messages.create(
                from_=self.sender, body=body, to=receiver_number
            )


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
    twilio_client = TwilioClient(config["twilio"])

    print(locations)
