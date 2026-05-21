#!/usr/bin/env python3

import asyncio
import aiohttp
import random
import string
import time
import signal
from collections import deque
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

CONCURRENCY = 100
USERNAME_LENGTH = 4
USE_NUMBERS = True

SAVE_FILE = "found.txt"

STATS_WEBHOOK_URL = "https://discord.com/api/webhooks/1506778294983327774/Gs4U0KXsTVblV9LQIt5X340KsxiNZtwvRU_ipeCzm0LeU1Q5ASrCyzM-98bFwGYy0tX5"

FOUND_WEBHOOK_URL = "https://discord.com/api/webhooks/1506803035592986784/rtdrRvkPOzTQQCJOhi7zywWOIV7vrEMCAHzJA2EWk-uymDzEcU0cmfPxgzkQNGnd8hxJ"

API_URL = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"

MAX_RETRIES = 5
BASE_BACKOFF = 0.3

# =========================================================
# GLOBALS
# =========================================================

running = True
checked_usernames = set()
stats_message_id = None

# =========================================================
# CHARACTER SET
# =========================================================

if USE_NUMBERS:
    CHARSET = string.ascii_lowercase + string.digits
else:
    CHARSET = string.ascii_lowercase

# =========================================================
# STATS
# =========================================================

class StatsTracker:

    def __init__(self):

        self.checked = 0
        self.start_time = time.time()
        self.timestamps = deque(maxlen=5000)

    def record(self):

        self.checked += 1
        self.timestamps.append(time.time())

    def cps(self):

        if len(self.timestamps) < 2:
            return 0.0

        elapsed = self.timestamps[-1] - self.timestamps[0]

        if elapsed <= 0:
            return 0.0

        return len(self.timestamps) / elapsed

    def uptime(self):

        secs = int(time.time() - self.start_time)

        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60

        return f"{h:02d}:{m:02d}:{s:02d}"

stats = StatsTracker()

# =========================================================
# USERNAME GENERATOR
# =========================================================

def generate_username():

    return ''.join(
        random.choices(
            CHARSET,
            k=USERNAME_LENGTH
        )
    )

# =========================================================
# BANNER
# =========================================================

def banner():

    total = len(CHARSET) ** USERNAME_LENGTH

    print(r"""
___.   .__                    .___ _____                
\_ |__ |  |   ____   ____   __| _// ____\__________  ___
 | __ \|  |  /  _ \ /  _ \ / __ |\   __\\___   /\  \/  /
 | \_\ \  |_(  <_> |  <_> ) /_/ | |  |   /    /  >    < 
 |___  /____/\____/ \____/\____ | |__|  /_____ \/__/\_ \
     \/                        \/             \/      \/
""")

    print(f"[ SYSTEM ] TOTAL TARGETS : {total:,}\n")

# =========================================================
# SAVE
# =========================================================

def save_username(username):

    with open(
        SAVE_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(
            f"{username} | {datetime.now()}\n"
        )

# =========================================================
# WEBHOOKS
# =========================================================

async def create_stats_message(session):

    global stats_message_id

    if not STATS_WEBHOOK_URL:
        return

    payload = {
        "content": "# STARTING SESSION..."
    }

    try:

        async with session.post(
            STATS_WEBHOOK_URL + "?wait=true",
            json=payload
        ) as r:

            if r.status == 200:

                data = await r.json()

                stats_message_id = data["id"]

                print(
                    f"\n[ WEBHOOK ] CREATED MESSAGE "
                    f"{stats_message_id}"
                )

            else:

                text = await r.text()

                print(
                    f"\n[ WEBHOOK ERROR ] "
                    f"{r.status} | {text}"
                )

    except Exception as e:

        print(
            f"\n[ WEBHOOK ERROR ] {e}"
        )

async def update_stats_webhook(session):

    global stats_message_id

    while running:

        try:

            if not stats_message_id:
                await asyncio.sleep(1)
                continue

            payload = {
                "content":
                    f"# LIVE SESSION\n\n"
                    f"CHECKED : `{stats.checked:,}`\n"
                    f"SPEED : `{stats.cps():.1f}/s`\n"
                    f"UPTIME : `{stats.uptime()}`\n"
                    f"WORKERS : `{CONCURRENCY}`"
            }

            async with session.patch(
                f"{STATS_WEBHOOK_URL}/messages/{stats_message_id}",
                json=payload
            ) as r:

                if r.status not in [200, 204]:

                    text = await r.text()

                    print(
                        f"\n[ STATS UPDATE ERROR ] "
                        f"{r.status} | {text}"
                    )

        except Exception as e:

            print(
                f"\n[ STATS UPDATE ERROR ] {e}"
            )

        await asyncio.sleep(15)

async def send_found_webhook(session, username):

    if not FOUND_WEBHOOK_URL:
        return

    payload = {
        "content":
            f"# AVAILABLE USERNAME\n\n"
            f"`@{username}`\n\n"
            f"CHECKED : `{stats.checked:,}`"
    }

    try:

        await session.post(
            FOUND_WEBHOOK_URL,
            json=payload
        )

        print(
            f"\n[ DROPS ] SENT @{username}"
        )

    except Exception as e:

        print(
            f"\n[ FOUND WEBHOOK ERROR ] {e}"
        )

# =========================================================
# CHECKER
# =========================================================

async def check_username(session, username):

    payload = {
        "username": username
    }

    retries = 0

    while retries <= MAX_RETRIES and running:

        try:

            async with session.post(
                API_URL,
                json=payload
            ) as response:

                stats.record()

                if response.status == 429:

                    retry_after = BASE_BACKOFF * (
                        2 ** retries
                    )

                    await asyncio.sleep(retry_after)

                    retries += 1

                    continue

                if response.status != 200:
                    return False

                try:

                    data = await response.json()

                except Exception:

                    return False

                taken = data.get("taken")

                if taken is False:
                    return True

                return False

        except aiohttp.ClientError:

            retry_after = BASE_BACKOFF * (
                2 ** retries
            )

            await asyncio.sleep(retry_after)

            retries += 1

        except asyncio.CancelledError:

            return False

        except Exception:

            return False

    return False

# =========================================================
# WORKER
# =========================================================

async def worker(session, wid):

    global running

    while running:

        try:

            username = generate_username()

            if username in checked_usernames:
                continue

            checked_usernames.add(username)

            available = await check_username(
                session,
                username
            )

            if available:

                print(
                    f"\n"
                    f"========================================\n"
                    f"USERNAME AVAILABLE : @{username}\n"
                    f"========================================\n"
                )

                save_username(username)

                await send_found_webhook(
                    session,
                    username
                )

        except asyncio.CancelledError:

            return

        except Exception as e:

            print(
                f"[ WORKER {wid} ] {e}"
            )

# =========================================================
# LIVE STATS
# =========================================================

async def live_stats():

    while running:

        print(
            f"\r"
            f"[ LIVE ] "
            f"CHECKED : {stats.checked:,} | "
            f"SPEED : {stats.cps():.1f}/s | "
            f"UPTIME : {stats.uptime()} | "
            f"WORKERS : {CONCURRENCY}      ",
            end=""
        )

        await asyncio.sleep(1)

# =========================================================
# SIGNALS
# =========================================================

def setup_signals():

    global running

    def stop(*_):

        running = False

        print(
            "\n[ SYSTEM ] TERMINATING SESSION"
        )

    signal.signal(signal.SIGINT, stop)

# =========================================================
# MAIN
# =========================================================

async def main():

    global running

    setup_signals()

    banner()

    connector = aiohttp.TCPConnector(
        limit=0,
        limit_per_host=0,
        ssl=False,
        ttl_dns_cache=300,
        keepalive_timeout=120,
        enable_cleanup_closed=True
    )

    timeout = aiohttp.ClientTimeout(
        total=4,
        connect=2,
        sock_connect=2,
        sock_read=2
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/136.0.0.0 Safari/537.36"
        )
    }

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
        headers=headers
    ) as session:

        await create_stats_message(session)

        workers = [

            asyncio.create_task(
                worker(session, i)
            )

            for i in range(CONCURRENCY)

        ]

        stats_task = asyncio.create_task(
            live_stats()
        )

        webhook_stats_task = asyncio.create_task(
            update_stats_webhook(session)
        )

        try:

            await asyncio.gather(*workers)

        except KeyboardInterrupt:

            running = False

        finally:

            stats_task.cancel()
            webhook_stats_task.cancel()

            for task in workers:
                task.cancel()

            await asyncio.gather(
                *workers,
                return_exceptions=True
            )

    print(
        "\n[ SYSTEM ] SESSION CLOSED"
    )

# =========================================================
# ENTRY
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\n[ SYSTEM ] STOPPED BY USER"
        )
