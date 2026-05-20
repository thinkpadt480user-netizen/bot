#!/bin/sh

apt update

apt install -y python3 python3-pip

pip3 install aiohttp

python3 discord_username_checker_combined.py
