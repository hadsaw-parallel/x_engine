"""
Setup cookies for X/Twitter authentication.

Cloudflare blocks programmatic login, so we need browser cookies.

Steps:
  1. Log into https://x.com in your browser
  2. Open DevTools (F12) → Application → Cookies → https://x.com
  3. Copy the values for 'auth_token' and 'ct0'
  4. Run this script and paste them when prompted
"""

from twikit import Client

def main():
    print("=== X Engine — Cookie Setup ===\n")
    print("1. Log into https://x.com in your browser")
    print("2. Open DevTools (F12) → Application → Cookies → https://x.com")
    print("3. Copy the cookie values below:\n")

    auth_token = input("auth_token: ").strip()
    ct0 = input("ct0: ").strip()

    if not auth_token or not ct0:
        print("\nBoth values are required.")
        return

    client = Client("en-US")
    client.set_cookies({
        "auth_token": auth_token,
        "ct0": ct0,
    })
    client.save_cookies("cookies.json")

    print("\nCookies saved to cookies.json")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
