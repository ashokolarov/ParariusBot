"""Find your Telegram chat id and send a test notification.

Usage:
    1. Open a chat with your bot in Telegram and send it any message
       (in a group, add the bot and send a message there).
    2. python telegram_setup.py          # prints every chat that messaged the bot
    3. python telegram_setup.py --test   # also sends a test message to TELEGRAM_CHAT_ID

Reads TELEGRAM_BOT_TOKEN (and TELEGRAM_CHAT_ID for --test) from .env, so it
works before config.yaml is filled in.
"""

import os
import sys

from utils import TelegramClient, load_dotenv


def describe(chat):
    # Groups have a title, private chats a first/last name and often a username.
    name = chat.get("title") or " ".join(
        part for part in (chat.get("first_name"), chat.get("last_name")) if part
    )
    username = f" (@{chat['username']})" if chat.get("username") else ""
    return f"{name}{username} [{chat.get('type')}]"


def main():
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("TELEGRAM_BOT_TOKEN is not set; add it to .env")

    client = TelegramClient({"bot_token": token, "receivers": {}})

    me = client.call("getMe", {})
    print(f"Bot: @{me['username']} ({me['first_name']})\n")

    updates = client.call("getUpdates", {})
    chats = {}
    for update in updates:
        # An update is one of many types (message, edited_message, channel_post,
        # ...); every one that carries a chat is a chat the bot can write to.
        for value in update.values():
            if isinstance(value, dict) and "chat" in value:
                chat = value["chat"]
                chats[chat["id"]] = chat

    if not chats:
        print(
            "No chats found. Send your bot a message in Telegram, then run this "
            "again. Note that Telegram only keeps updates for 24 hours, and that "
            "a running bot polling getUpdates consumes them."
        )
        return

    print("Chats that have messaged the bot:")
    for chat_id, chat in chats.items():
        print(f"  chat_id: {chat_id}  -  {describe(chat)}")
    print("\nPut the one you want in .env as TELEGRAM_CHAT_ID")

    if "--test" in sys.argv:
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not chat_id:
            sys.exit("\nTELEGRAM_CHAT_ID is not set; add it to .env first")
        client.receivers = {
            "test": {
                "chat_id": chat_id,
                "message": "ParariusBot test: applied to {url} for {price} in {location}",
            }
        }
        client.send_notification(
            "https://www.pararius.com/", 1200, "test-location"
        )
        print(f"\nTest message sent to {chat_id}")


if __name__ == "__main__":
    main()
