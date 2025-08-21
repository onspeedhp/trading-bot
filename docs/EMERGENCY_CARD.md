# Emergency Response Card

> 🚨 **IMMEDIATE ACTIONS FOR LIVE TRADING INCIDENTS** 🚨

## Emergency Stop (Choose One)

```bash
# Option 1: Kill process
pkill -f "solbot.*prod"

# Option 2: Environment variable
export EMERGENCY_STOP=true

# Option 3: Telegram command (if implemented)
/emergency_stop
```

## Safe Mode Re-enable

```bash
# 1. Stop bot
pkill -f "solbot.*prod"

# 2. Switch to dry-run
sed -i 's/dry_run: false/dry_run: true/' configs/prod.yaml

# 3. Verify safe mode
grep "dry_run:" configs/prod.yaml

# 4. Restart safely
solbot --config configs/prod.yaml --profile prod
```

## Key Rotation (If Compromised)

```bash
# 1. Stop immediately
pkill -f "solbot.*prod"

# 2. Backup current key
mv ./secrets/solana-main.enc ./secrets/solana-main.enc.backup

# 3. Generate new keypair (Phantom/CLI)

# 4. Encrypt new key
python scripts/secret_vault.py encrypt \
  --in new-keypair.json \
  --out ./secrets/solana-main.enc \
  --key-from-env VAULT_KEY

# 5. Test with dry-run
solbot --config configs/prod.yaml --profile prod
```

## Quick Status Check

```bash
# Check bot status
curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
  -d "chat_id=<ADMIN_ID>&text=/status"

# View recent errors
tail -20 bot.log | grep -E "(ERROR|WARN|CRITICAL)"

# Check recent trades
sqlite3 prod_bot.sqlite "SELECT * FROM trades ORDER BY ts DESC LIMIT 5;"
```

## Common Issues

| Symptom | Action |
|---------|--------|
| High slippage | Stop trading, reduce position size |
| RPC errors | Check RPC health, switch endpoint |
| Failed simulations | Review transaction parameters |
| No quotes | Check Jupiter API status |

---

**Remember**: When in doubt, STOP TRADING and investigate.
