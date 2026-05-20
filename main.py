import asyncio
import aiohttp
import random
import string
import time
import sys
import signal
from collections import deque
from datetime import datetime

# =========================================================
# CONFIG
# =========================================================

CONCURRENCY = 50
USERNAME_LENGTH = 4
USE_NUMBERS = True

# =========================================================
# WEBHOOKS
# =========================================================

STATS_WEBHOOK_URL = "https://discord.com/api/webhooks/1506778294983327774/Gs4U0KXsTVblV9LQIt5X340KsxiNZtwvRU_ipeCzm0LeU1Q5ASrCyzM-98bFwGYy0tX5"
DROPS_WEBHOOK_URL = "https://discord.com/api/webhooks/1506803035592986784/rtdrRvkPOzTQQCJOhi7zywWOIV7vrEMCAHzJA2EWk-uymDzEcU0cmfPxgzkQNGnd8hxJ"

SAVE_FILE = "found.txt"

API_URL = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"

MAX_RETRIES = 3
BASE_BACKOFF = 1

# =========================================================
# STATS TRACKER
# =========================================================

class StatsTracker:

    def __init__(self):
        self.checked = 0
        self.start_time = time.time()
        self.timestamps = deque(maxlen=500)

    def record_check(self):
        self.checked += 1
        self.timestamps.append(time.time())

    def checks_per_second(self):

        if len(self.timestamps) < 2:
            return 0.0

        elapsed = self.timestamps[-1] - self.timestamps[0]

        if elapsed <= 0:
            return 0.0

        return len(self.timestamps) / elapsed

    def elapsed_time(self):

        seconds = int(time.time() - self.start_time)

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"

        return f"{minutes:02d}:{secs:02d}"

# =========================================================
# MAIN CHECKER
# =========================================================

class UsernameChecker:

    def __init__(self):

        self.running = True

        self.stats = StatsTracker()

        self.checked_usernames = set()

        self.webhook_message_id = None

        if USE_NUMBERS:
            self.charset = string.ascii_lowercase + string.digits
        else:
            self.charset = string.ascii_lowercase

    # =====================================================
    # CTRL+C HANDLER
    # =====================================================

    def setup_signals(self):

        def stop(sig, frame):
            self.running = False
            print("\nStopping...")

        signal.signal(signal.SIGINT, stop)

    # =====================================================
    # GENERATE USERNAME
    # =====================================================

    def generate_username(self):

        return ''.join(
            random.choice(self.charset)
            for _ in range(USERNAME_LENGTH)
        )

    # =====================================================
    # CREATE WEBHOOK MESSAGE
    # =====================================================

    async def create_webhook_message(self, session):

        payload = {
            "content": "## 🚀 STARTING USERNAME CHECKER..."
        }

        try:

            async with session.post(
                STATS_WEBHOOK_URL + "?wait=true",
                json=payload
            ) as response:

                data = await response.json()

                self.webhook_message_id = data["id"]

                print(
                    f"\nCreated Webhook Message ID: "
                    f"{self.webhook_message_id}"
                )

        except Exception as e:

            print(f"\nCreate Webhook Error: {e}")

    # =====================================================
    # EDIT WEBHOOK MESSAGE
    # =====================================================

    async def edit_webhook_message(self, session, content):

        if not self.webhook_message_id:
            return

        try:

            async with session.patch(
                f"{STATS_WEBHOOK_URL}/messages/{self.webhook_message_id}",
                json={"content": content}
            ) as response:

                print(f"\nEdit Status: {response.status}")

        except Exception as e:

            print(f"\nEdit Error: {e}")

    # =====================================================
    # SEND FOUND USERNAME
    # =====================================================

    async def send_found_webhook(self, session, username):

        payload = {
            "content": (
                f"## ✅ USERNAME FOUND\n\n"
                f"**Username:** `{username}`\n"
                f"**Checked:** `{self.stats.checked:,}`\n"
                f"**Speed:** `{self.stats.checks_per_second():.2f}/sec`\n"
                f"**Runtime:** `{self.stats.elapsed_time()}`\n"
                f"**Length:** `{USERNAME_LENGTH}`\n"
                f"**Time Found:** `{datetime.now()}`"
            )
        }

        try:

            async with session.post(
                DROPS_WEBHOOK_URL,
                json=payload
            ) as response:

                print(
                    f"\nFound Webhook Status: "
                    f"{response.status}"
                )

        except Exception as e:

            print(f"\nFound Webhook Error: {e}")

    # =====================================================
    # CHECK USERNAME
    # =====================================================

    async def check_username(self, session, username):

        payload = {
            "username": username
        }

        retries = 0

        while retries <= MAX_RETRIES and self.running:

            try:

                async with session.post(
                    API_URL,
                    json=payload
                ) as response:

                    self.stats.record_check()

                    # CONSOLE STATS
                    print(
                        f"\rChecked: {self.stats.checked:,} | "
                        f"Status: {response.status} | "
                        f"Speed: "
                        f"{self.stats.checks_per_second():.2f}/sec | "
                        f"Runtime: "
                        f"{self.stats.elapsed_time()}",
                        end=""
                    )

                    # RATE LIMITED
                    if response.status == 429:

                        wait = BASE_BACKOFF * (2 ** retries)

                        retries += 1

                        await asyncio.sleep(wait)

                        continue

                    # BAD RESPONSE
                    if response.status != 200:
                        return False

                    data = await response.json()

                    taken = data.get("taken", True)

                    return not taken

            except Exception as e:

                print(f"\nRequest Error: {e}")

                self.stats.record_check()

                retries += 1

                await asyncio.sleep(
                    BASE_BACKOFF * (2 ** retries)
                )

        return False

    # =====================================================
    # WORKER
    # =====================================================

    async def worker(self, session):

        while self.running:

            username = self.generate_username()

            if username in self.checked_usernames:
                continue

            self.checked_usernames.add(username)

            available = await self.check_username(
                session,
                username
            )

            # =================================================
            # TESTING MODE
            # Uncomment this to fake-find usernames
            # =================================================

            # available = random.randint(1, 1000) == 1

            if available:

                print("\n" + "=" * 60)
                print(
                    f"FOUND AVAILABLE USERNAME: "
                    f"{username}"
                )
                print("=" * 60)

                with open(SAVE_FILE, "a") as f:

                    f.write(
                        f"{username} | "
                        f"{datetime.now()}\n"
                    )

                await self.send_found_webhook(
                    session,
                    username
                )

                self.running = False

                return

    # =====================================================
    # LIVE STATS LOOP
    # =====================================================

    async def stats_loop(self, session):

        await self.create_webhook_message(session)

        while self.running:

            cps = self.stats.checks_per_second()

            msg = (
                f"## 📊 USERNAME CHECKER RUNNING\n\n"
                f"**Checked:** `{self.stats.checked:,}`\n"
                f"**Speed:** `{cps:.2f}/sec`\n"
                f"**Runtime:** `{self.stats.elapsed_time()}`\n"
                f"**Workers:** `{CONCURRENCY}`\n"
                f"**Username Length:** `{USERNAME_LENGTH}`\n"
                f"**Charset:** `{'letters+numbers' if USE_NUMBERS else 'letters only'}`"
            )

            # CONSOLE
            console_msg = (
                f"\r"
                f"Checked: {self.stats.checked:,} | "
                f"Speed: {cps:.2f}/sec | "
                f"Runtime: {self.stats.elapsed_time()}"
            )

            sys.stdout.write(console_msg)
            sys.stdout.flush()

            # EDIT SAME WEBHOOK MESSAGE
            await self.edit_webhook_message(
                session,
                msg
            )

            await asyncio.sleep(2)

    # =====================================================
    # MAIN RUNNER
    # =====================================================

    async def run(self):

        self.setup_signals()

        print("=" * 60)
        print("Discord Username Checker")
        print("=" * 60)

        connector = aiohttp.TCPConnector(
            limit=CONCURRENCY,
            ssl=False
        )

        timeout = aiohttp.ClientTimeout(
            total=10
        )

        headers = {
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64)"
            )
        }

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers=headers
        ) as session:

            workers = [
                asyncio.create_task(
                    self.worker(session)
                )
                for _ in range(CONCURRENCY)
            ]

            stats_task = asyncio.create_task(
                self.stats_loop(session)
            )

            await asyncio.gather(
                *workers,
                stats_task,
                return_exceptions=True
            )

# =========================================================
# MAIN
# =========================================================

async def main():

    checker = UsernameChecker()

    await checker.run()

if __name__ == "__main__":

    asyncio.run(main())
