#!/bin/sh

apt update && apt install -y python3 python3-pip python3-venv

python3 -m venv venv

. venv/bin/activate

pip install aiohttp

python main.py
