# Solana Trading Bot

> ⚠️ **WARNING: TRADING RISKS AND LEGAL COMPLIANCE** ⚠️
> 
> This trading bot involves significant financial risk. You can lose money rapidly, including the possibility of losing more than your initial investment. Cryptocurrency trading is highly volatile and speculative.
> 
> **Before using this bot:**
> - Ensure you understand the risks involved in cryptocurrency trading
> - Only trade with money you can afford to lose
> - Verify that automated trading is legal in your jurisdiction
> - Consider consulting with a financial advisor or legal professional
> - This bot is for educational and research purposes only
> 
> The authors are not responsible for any financial losses incurred through the use of this software.

A production-ready Solana trading bot with paper trading capabilities, built with Python 3.13.

## Features

- Paper trading mode for safe testing
- Real-time data feeds from Helius, Birdeye, and DexScreener
- Configurable risk management
- Telegram alerts
- Prometheus metrics
- Modular architecture with type safety

## Quickstart

### Prerequisites

- Python 3.13
- pip

### Setup

1. **Clone and navigate to the project:**
   ```bash
   cd trading-bot
   ```

2. **Create and activate virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp configs/paper.yaml configs/local.yaml
   # Edit configs/local.yaml with your settings
   ```

5. **Run in paper trading mode:**
   ```bash
   make run-paper
   # Or use the dedicated script:
   python scripts/run_paper.py
   ```

## Telegram Bot Setup

### Creating a Telegram Bot

1. **Start a chat with @BotFather on Telegram**
2. **Send `/newbot` and follow the instructions**
3. **Save the bot token** (you'll need this for configuration)
4. **Optional: Set bot commands with `/setcommands`**
   ```
   status - Get bot status
   help - Show available commands
   ```

### Getting Your Admin User ID

1. **Start a chat with @userinfobot on Telegram**
2. **Send any message to get your user ID**
3. **Save this ID** (you'll need it for admin notifications)

### Configuration

Add your Telegram credentials to your configuration:

```yaml
# In your config file (paper.yaml, prod.yaml, etc.)
telegram_bot_token: "your_bot_token_here"  # Or set TELEGRAM_BOT_TOKEN env var
telegram_admin_ids: [123456789]  # Your Telegram user ID
```

### Testing Notifications

The bot will send notifications for:
- Trade executions
- Risk management events
- Error conditions
- Daily summaries

## Switching to Live Trading (JupiterExecutor)

### ⚠️ **IMPORTANT: Live Trading Risks** ⚠️

Live trading uses real money and can result in significant financial losses. Only proceed if you:
- Have thoroughly tested in paper trading mode
- Understand the risks involved
- Have proper risk management in place
- Are compliant with local regulations

### Enabling JupiterExecutor

1. **Set up Solana wallet and RPC access**
2. **Configure production settings:**
   ```yaml
   # In configs/prod.yaml
   dry_run: false  # Enable live trading
   rpc_url: "https://your-rpc-endpoint.com"  # Use reliable RPC
   helius_api_key: "your_helius_key"  # Required for data
   birdeye_api_key: "your_birdeye_key"  # Required for data
   ```

3. **Set environment variables:**
   ```bash
   export HELIUS_API_KEY="your_helius_key"
   export BIRDEYE_API_KEY="your_birdeye_key"
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   ```

4. **Run in production mode:**
   ```bash
   solbot --config configs/prod.yaml --profile prod
   ```

### JupiterExecutor Requirements

The JupiterExecutor requires:
- Solana wallet with SOL for transaction fees
- Jupiter API access (free tier available)
- Reliable RPC endpoint (Helius recommended)
- Proper slippage and fee configuration

### Feature Flag

The bot automatically switches between executors based on the `dry_run` setting:
- `dry_run: true` → Uses `PaperExecutor` (simulated trades)
- `dry_run: false` → Uses `JupiterExecutor` (live trades)

## Development

### Code Quality

```bash
make lint      # Run ruff linter
make format    # Format with black
make typecheck # Run mypy type checker
make test      # Run tests
```

### Project Structure

```
bot/
├── config/          # Configuration management
├── core/            # Core types and interfaces
├── data/            # Data providers (Helius, Birdeye, DexScreener)
├── filters/         # Trading filters and heuristics
├── risk/            # Risk management
├── exec/            # Execution engines (paper, Jupiter)
├── alerts/          # Alert systems (Telegram)
├── persist/         # Data persistence
└── runner/          # Main pipeline runner
```

## Configuration

The bot uses YAML configuration files:

- `configs/paper.yaml` - Paper trading configuration
- `configs/dev.yaml` - Development settings
- `configs/prod.yaml` - Production settings

### Environment Variables

Key environment variables:
- `HELIUS_API_KEY` - Helius API key for data feeds
- `BIRDEYE_API_KEY` - Birdeye API key for market data
- `TELEGRAM_BOT_TOKEN` - Telegram bot token for notifications

## Docker

Build and run with Docker:

```bash
docker build -t trading-bot .
docker run trading-bot
```

## License

MIT License
