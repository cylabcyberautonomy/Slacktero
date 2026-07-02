"""Run the bot.

    python main.py            # bare Python (needs deps + a reachable translation-server)
    docker compose up --build # the usual way (also runs the translation-server)
"""

from bot.app import main

if __name__ == "__main__":
    main()
