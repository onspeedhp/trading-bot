# Solana Trading Bot

> ⚠️ **WARNING: TRADING RISKS AND LEGAL COMPLIANCE** ⚠️
>
> This trading bot involves significant financial risk. You can lose money rapidly, including the possibility of losing more than your initial investment. Cryptocurrency trading is highly volatile and speculative.
>
> **Before using this bot:**
>
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
   # Core installation (paper trading only)
   pip install -r requirements.txt

   # OR install with live trading support
   pip install ".[live]"
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
telegram_bot_token: 'your_bot_token_here' # Or set TELEGRAM_BOT_TOKEN env var
telegram_admin_ids: [123456789] # Your Telegram user ID
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

### Installing Live Trading Dependencies

**Before enabling live trading, install the optional dependencies:**

```bash
# Option 1: Install with live trading support (may have dependency conflicts)
pip install ".[live]"

# Option 2: Manual installation (recommended)
pip install solders==0.20.* solana==0.30.* base58==2.1.* pynacl==1.5.*

# Option 3: Use a separate environment for live trading
python -m venv live-trading-env
source live-trading-env/bin/activate
pip install -r requirements.txt
pip install solders==0.20.* solana==0.30.* base58==2.1.* pynacl==1.5.*
```

**⚠️ Dependency Conflict Warning:**
The Solana packages require `httpx<0.24.0`, but this project uses `httpx==0.27.*` for compatibility with `python-telegram-bot`. You may encounter installation conflicts. If this happens:

1. Use manual installation (Option 2)
2. Use a separate environment (Option 3)
3. Consider using an older version of `python-telegram-bot` that supports `httpx<0.24.0`

**This installs:**

- `solders==0.20.*` (Solana data structures)
- `solana==0.30.*` (Solana Python SDK)
- `base58==2.1.*` (Base58 encoding)
- `pynacl==1.5.*` (Cryptographic library)

### Enabling JupiterExecutor

1. **Install live trading dependencies** (see above)
2. **Set up Solana wallet and RPC access**
3. **Configure production settings:**

   ```yaml
   # In configs/prod.yaml
   dry_run: false # Enable live trading
   rpc_url: 'https://your-rpc-endpoint.com' # Use reliable RPC
   helius_api_key: 'your_helius_key' # Required for data
   birdeye_api_key: 'your_birdeye_key' # Required for data
   ```

4. **Set environment variables:**

   ```bash
   export HELIUS_API_KEY="your_helius_key"
   export BIRDEYE_API_KEY="your_birdeye_key"
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   ```

5. **Run in production mode:**
   ```bash
   solbot --config configs/prod.yaml --profile prod
   ```

### JupiterExecutor Requirements

The JupiterExecutor requires:

- **Live trading dependencies installed** (`pip install ".[live]"`)
- Solana wallet with SOL for transaction fees
- Jupiter API access (free tier available)
- Reliable RPC endpoint (Helius recommended)
- Proper slippage and fee configuration

### Live Trading Checklist

**⚠️ CRITICAL: Follow this checklist before enabling live trading ⚠️**

1. **🔐 Secure Key Management**

   - [ ] Use encrypted keypair file (`keypair_path_enc`) with `secret_vault.py`
   - [ ] Verify key is decrypted only in-memory, never written to disk
   - [ ] Confirm public key matches your expected wallet address
   - [ ] Test key loading with `python scripts/secret_vault.py show`

2. **🧪 Test Configuration**

   - [ ] Run paper trading mode first (`dry_run: true`)
   - [ ] Verify all data sources are working (Helius, Birdeye)
   - [ ] Test Telegram alerts are functioning
   - [ ] Confirm risk management settings are appropriate

3. **💰 Start Small**

   - [ ] Set `position_size_usd: 50` (or smaller) for initial testing
   - [ ] Ensure `daily_max_loss_usd` is reasonable (e.g., 200)
   - [ ] Use conservative `max_slippage_bps: 100` (1%)
   - [ ] Start with `jito_tip_lamports: 0` unless needed

4. **🔔 Enable Monitoring**

   - [ ] Configure Telegram bot token and admin IDs
   - [ ] Test alert delivery for trade executions
   - [ ] Verify status command works (`/status`)
   - [ ] Set up monitoring for bot uptime

5. **🛡️ Safety Checks**

   - [ ] Confirm `allow_devnet: false` (never true in production)
   - [ ] Verify `unsafe_allow_high_slippage: false`
   - [ ] Check RPC URL is mainnet, not localhost/devnet
   - [ ] Ensure `position_size_usd <= daily_max_loss_usd`

6. **🚀 Gradual Rollout**
   - [ ] Run with `dry_run: false` for first time
   - [ ] Monitor first few trades closely
   - [ ] Verify transaction signatures and execution
   - [ ] Gradually increase position size if performance is good

**Example Production Configuration:**

```yaml
# configs/prod.yaml
dry_run: false
rpc_url: 'https://your-helius-rpc.com'
position_size_usd: 50 # Start small
daily_max_loss_usd: 200
max_slippage_bps: 100
keypair_path_enc: './secrets/solana-main.enc'
telegram_bot_token: 'your_bot_token'
telegram_admin_ids: [123456789]
preflight_simulate: true
allow_devnet: false
unsafe_allow_high_slippage: false
```

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
