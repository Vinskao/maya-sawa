import os
import argparse
import requests
from config import Config

def get_power_data(character_name):
    try:
        url = f"{Config.PUBLIC_API_BASE_URL}/tymb/weapons/owner/{character_name}"
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching power data: {e}")
        return None

def main():
    # 讀取測試角色名稱（預設 Chiaki，可由環境變數或參數覆蓋）
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", dest="name", default=os.getenv("TEST_CHARACTER_NAME", "Chiaki"), help="角色名稱")
    args, _ = parser.parse_known_args()
    character_name = args.name

    power_data = get_power_data(character_name)
    if power_data:
        print(f"Power data for {character_name}:")
        print(power_data)
    else:
 