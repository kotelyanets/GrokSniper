#!/usr/bin/env python3
import os
import sys
import time
from dotenv import load_dotenv, set_key

def _is_enabled(value: str, default: str = "False") -> bool:
    return (value or default).strip().lower() in {"true", "1", "yes", "y", "on"}

def print_header(title):
    print("\n" + "=" * 50)
    print(f"🚀 {title.upper()}")
    print("=" * 50 + "\n")

def ask_confirm(prompt, default="n"):
    valid = {"y": True, "n": False}
    if default is None:
        prompt = prompt + " [y/n] "
    elif default == "y":
        prompt = prompt + " [Y/n] "
    elif default == "n":
        prompt = prompt + " [y/N] "
    else:
        raise ValueError(f"Invalid default answer: {default}")

    while True:
        sys.stdout.write(prompt)
        choice = input().lower().strip()
        if default is not None and choice == "":
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'y' or 'n'.\n")

def main():
    print_header("GrokSniper Live Trading Migration Utility")
    print("This interactive guide will help you safely transition from")
    print("Paper/Testnet trading to full LIVE execution.\n")
    
    if not ask_confirm("Ready to begin the migration check?", default="y"):
        print("Migration aborted.")
        sys.exit(0)

    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.getcwd(), ".env")

    if not os.path.exists(env_path):
        print(f"❌ Could not find .env file at {env_path}.")
        if ask_confirm("Do you want to continue without modifying .env?", default="n"):
            env_path = None
        else:
            sys.exit(1)
            
    if env_path:
        load_dotenv(env_path)
    
    # 1. API Keys Review
    print_header("1. API Key Assessment")
    binance_key = os.getenv("BINANCE_API_KEY", "")
    binance_secret = os.getenv("BINANCE_API_SECRET", "")
    
    if binance_key and binance_secret:
        print("✅ Binance API keys are present in environment.")
    else:
        print("❌ Binance API keys are MISSING.")
        print("You must add BINANCE_API_KEY and BINANCE_API_SECRET to your .env file.")
        
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        print("✅ Anthropic API key is present.")
    else:
        print("❌ Anthropic API key is MISSING.")
    
    time.sleep(1)

    # 2. Testnet configuration
    print_header("2. Binance Testnet Configuration")
    testnet = _is_enabled(os.getenv("BINANCE_TESTNET", "True"))
    print(f"Current BINANCE_TESTNET setting: {testnet}")
    
    if testnet:
        if ask_confirm("Turn OFF Binance Testnet (Connect to real mainnet)?", default="n"):
            if env_path:
                set_key(env_path, "BINANCE_TESTNET", "False")
                print("✅ Set BINANCE_TESTNET=False in .env")
            else:
                print("⚠️ Please manually set BINANCE_TESTNET=False in your .env")
    else:
        print("✅ Binance Testnet is already disabled.")
        
    time.sleep(1)

    # 3. Dry Run configuration
    print_header("3. Dry Run Configuration")
    dry_run = _is_enabled(os.getenv("DRY_RUN", "True"))
    print(f"Current DRY_RUN setting: {dry_run}")
    
    if dry_run:
        print("⚠️ DRY_RUN is enabled. The bot will ONLY simulate trades and will NOT send orders to the exchange.")
        if ask_confirm("Turn OFF Dry Run mode? (DANGER: Bot will place real orders)", default="n"):
            if ask_confirm("Are you absolutely sure?", default="n"):
                if env_path:
                    set_key(env_path, "DRY_RUN", "False")
                    print("✅ Set DRY_RUN=False in .env")
                else:
                    print("⚠️ Please manually set DRY_RUN=False in your .env")
            else:
                print("Keeping DRY_RUN=True.")
        else:
            print("Keeping DRY_RUN=True.")
    else:
        print("⚠️ DRY_RUN is already disabled. The bot is ready to place real orders.")

    time.sleep(1)

    # 4. Paper Trade configuration
    print_header("4. Paper Trade Configuration")
    paper_trade = _is_enabled(os.getenv("PAPER_TRADE", "True"))
    print(f"Current PAPER_TRADE setting: {paper_trade}")

    if paper_trade:
        print("⚠️ PAPER_TRADE is enabled. Some bot flows will still simulate trades.")
        if ask_confirm("Turn OFF Paper Trading mode? (DANGER: real money flow enabled)", default="n"):
            if ask_confirm("Are you absolutely sure?", default="n"):
                if env_path:
                    set_key(env_path, "PAPER_TRADE", "False")
                    print("✅ Set PAPER_TRADE=False in .env")
                else:
                    print("⚠️ Please manually set PAPER_TRADE=False in your .env")
            else:
                print("Keeping PAPER_TRADE=True.")
        else:
            print("Keeping PAPER_TRADE=True.")
    else:
        print("✅ PAPER_TRADE is already disabled.")

    # 5. Risk Limits
    print_header("5. Risk Limits Checklist")
    print("Before running live, please ensure:")
    print("  [ ] Your Binance account has enough USDT balance.")
    print("  [ ] Your API keys restrict withdrawals (IP-whitelisting recommended).")
    print("  [ ] Position sizes in .env (e.g., TRADE_AMOUNT) are within your risk tolerance.")
    
    ask_confirm("I have verified my risk limits and API restrictions.", default="y")
    
    print_header("Migration Complete")
    print("Please restart your backend server to apply any .env changes.")
    print("If you changed PAPER_TRADE, DRY_RUN, or BINANCE_TESTNET, the bot is now live.")
    print("Good luck and trade safe! 📈")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nMigration aborted by user.")
        sys.exit(0)
