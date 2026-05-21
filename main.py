import asyncio
import aiohttp
import string
import time
import sys
import signal
from collections import deque
from datetime import datetime
from itertools import product

# =========================================================
# CONFIG
# =========================================================

CONCURRENCY = 80          # Increased (Discord tolerates ~ this with good backoff)
USERNAME_LENGTH = 4
USE_NUMBERS = True
SAVE_FILE = "found.txt"
PROGRESS_FILE = "progress.txt"  # For resuming

# Webhooks
STATS_WEBHOOK_URL = "https://discord.com/api/webhooks/1506778294983327774/Gs4U0KXsTVblV9LQIt5X340KsxiNZtwvRU_ipeCzm0LeU1Q5ASrCyzM-98bFwGYy0tX5"
DROPS_WEBHOOK_URL = "https://discord.com/api/webhooks/1506803035592986784/rtdrRvkPOzTQQCJOhi7zywWOIV7vrEMCAHzJA2EWk-uymDzEcU0cmfPxgzkQNGnd8hxJ"

API_URL = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"

MAX_RETRIES = 5
BASE_BACKOFF = 0.7

# =========================================================
# STATS TRACKER
# =========================================================

class StatsTracker:
    def __init__(self):
        self.checked = 0
        self.start_time = time.time()
        self.timestamps = deque(maxlen=1200)
        self.found = 0

    def record_check(self):
        self.checked += 1
        self.timestamps.append(time.time())

    def cps(self):
        if len(self.timestamps) < 15:
            return 0.0
        elapsed = self.timestamps[-1] - self.timestamps[0]
        return len(self.timestamps) / elapsed if elapsed > 0 else 0.0

    def elapsed(self):
        secs = int(time.time() - self.start_time)
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"


# =========================================================
# USERNAME CHECKER
# =========================================================

class UsernameChecker:
    def __init__(self):
        self.running = True
        self.stats = StatsTracker()
        self.webhook_message_id = None
        self.session = None

        self.charset = string.ascii_lowercase + (string.digits if USE_NUMBERS else "")
        print(f"Charset size: {len(self.charset)} | Total combinations: {len(self.charset) ** USERNAME_LENGTH:,}")

        self.generator = self.username_generator()
        self.tried = self.load_progress()

    def username_generator(self):
        """Systematic generation - zero duplicates"""
        for combo in product(self.charset, repeat=USERNAME_LENGTH):
            yield ''.join(combo)

    def load_progress(self):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return set(line.strip() for line in f if line.strip())
        except FileNotFoundError:
            return set()

    def save_progress(self, username):
        with open(PROGRESS_FILE, "a") as f:
            f.write(username + "\n")

    def setup_signals(self):
        def stop(*_):
            self.running = False
            print("\n\nStopping... Saving progress.")
        signal.signal(signal.SIGINT, stop)

    async def create_webhook_message(self):
        payload = {"content": "## 🚀 **DISCORD USERNAME SNIPER STARTED**"}
        try:
            async with self.session.post(STATS_WEBHOOK_URL + "?wait=true", json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.webhook_message_id = data.get("id")
                    print(f"Webhook message created: {self.webhook_message_id}")
        except Exception as e:
            print(f"Webhook creation failed: {e}")

    async def update_stats(self):
        while self.running:
            try:
                cps = self.stats.cps()
                msg = (
                    f"## 📊 **USERNAME SNIPER RUNNING**\n\n"
                    f"**Checked:** `{self.stats.checked:,}`\n"
                    f"**Speed:** `{cps:.1f}/s`\n"
                    f"**Runtime:** `{self.stats.elapsed()}`\n"
                    f"**Workers:** `{CONCURRENCY}` | **Length:** `{USERNAME_LENGTH}`"
                )

                # Console output
                print(f"\rChecked: {self.stats.checked:,} | Speed: {cps:.1f}/s | Runtime: {self.stats.elapsed()}", end="")

                # Update Discord webhook
                if self.webhook_message_id:
                    await self.session.patch(
                        f"{STATS_WEBHOOK_URL}/messages/{self.webhook_message_id}",
                        json={"content": msg}
                    )
            except:
                pass
            await asyncio.sleep(2.5)

    async def send_found(self, username):
        payload = {
            "content": f"""## ✅ **USERNAME FOUND!**

**@{username}**

**Checked:** `{self.stats.checked:,}`
**Speed:** `{self.stats.cps():.1f}/s`
**Time:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"""
        }
        try:
            await self.session.post(DROPS_WEBHOOK_URL, json=payload)
            print(f"\n\n✅ FOUND AND SENT: @{username}")
        except Exception as e:
            print(f"Failed to send found webhook: {e}")

    async def check_username(self, username: str):
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with self.session.post(
                    API_URL,
                    json={"username": username},
                    timeout=10
                ) as resp:
                    
                    self.stats.record_check()

                    if resp.status == 429:
                        try:
                            data = await resp.json()
                            retry_after = data.get("retry_after", 1.2)
                        except:
                            retry_after = 1.5
                        await asyncio.sleep(retry_after * 1.1)
                        continue

                    if resp.status != 200:
                        await asyncio.sleep(0.2)
                        continue

                    data = await resp.json()
                    return not data.get("taken", True)

            except asyncio.TimeoutError:
                await asyncio.sleep(0.4)
            except Exception:
                await asyncio.sleep(0.25 * (attempt + 1))

        return False

    async def worker(self):
        while self.running:
            try:
                username = next(self.generator)

                if username in self.tried:
                    continue

                self.tried.add(username)
                self.save_progress(username)

                if await self.check_username(username):
                    print(f"\n\n🔥 FOUND AVAILABLE USERNAME: @{username} 🔥\n")
                    with open(SAVE_FILE, "a") as f:
                        f.write(f"{username} | {datetime.now()}\n")

                    await self.send_found(username)
                    self.running = False
                    break

            except StopIteration:
                print("\n\nAll possible usernames checked!")
                self.running = False
                break
            except Exception:
                await asyncio.sleep(0.05)

    async def run(self):
        self.setup_signals()
        print("=" * 70)
        print("DISCORD USERNAME SNIPER v2.1 - OPTIMIZED")
        print("=" * 70)

        connector = aiohttp.TCPConnector(
            limit=CONCURRENCY * 3,
            ssl=False,
            ttl_dns_cache=300,
            keepalive_timeout=30
        )

        timeout = aiohttp.ClientTimeout(total=15, sock_connect=8)

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        ) as session:
            
            self.session = session
            await self.create_webhook_message()

            stats_task = asyncio.create_task(self.update_stats())

            workers = [asyncio.create_task(self.worker()) for _ in range(CONCURRENCY)]

            try:
                await asyncio.gather(*workers, stats_task, return_exceptions=True)
            finally:
                stats_task.cancel()

        print(f"\n\nFinished. Total checked: {self.stats.checked:,}")


async def main():
    checker = UsernameChecker()
    await checker.run()


if __name__ == "__main__":
    asyncio.run(main())
