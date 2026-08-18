import concurrent.futures

from bot import ParariusBot
from utils import TelegramClient, PrintClient, generate_locations, parse_config


def main():
    config_file = "config.yaml"
    config = parse_config(config_file)

    if config.get("telegram") is not None:
        client = TelegramClient(config["telegram"])
    else:
        client = PrintClient()

    locations = generate_locations(config["locations"])
    bots = [
        ParariusBot(config["bot_settings"], location, client)
        for location in locations
    ]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(bot.run) for bot in bots]
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                print(f"Bot raised an exception: {e}")


if __name__ == "__main__":
    main()
