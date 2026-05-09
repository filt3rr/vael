# Security

## Token Storage

EVE SSO refresh tokens are stored encrypted using Fernet symmetric encryption (from the `cryptography` package). The encryption key is stored in your OS keyring:

- **Windows:** Windows Credential Manager (`eve-agent / token-encryption-key`)
- **macOS:** Keychain
- **Linux:** Secret Service (libsecret)

The encrypted token file (`data/tokens.json.enc`) cannot be decrypted without the keyring entry. Both must be compromised for token theft to occur.

## What the Agent Can Access

With the default read-only scopes, the agent can read:

- Wallet balance and journal
- Skill queue and training progress
- Asset locations and quantities
- Current location and ship
- Market orders
- Industry jobs
- Saved fittings
- Mail (subject lines only for notification)
- Contracts

The agent **cannot** in its default configuration:

- Place or cancel market orders
- Transfer ISK
- Send EVE mail
- Move ships or assets
- Change fleet or corporation settings
- Access other characters' data

## Credentials

- **EVE Client ID:** not a secret — it is sent in the OAuth authorization URL and visible in your browser's address bar
- **EVE Client Secret:** must be kept secret — it is stored only in your `.env` file (gitignored) and used server-side for token exchange
- **Discord Webhook URL:** treat as a secret — anyone with the URL can post to your channel

## What to Do If Your Secret Is Exposed

If your Client Secret appears in:
- A GitHub commit
- A chat message
- A screenshot shared publicly

**Immediately:**

1. Go to [developers.eveonline.com](https://developers.eveonline.com)
2. Click your application → Reset Secret Key
3. Update your `.env` file with the new secret
4. Old refresh tokens using the compromised secret will still work until you also revoke them — go to [eve.eveonline.com/settings/applications](https://eve.eveonline.com/settings/applications) to revoke third-party application access

## Reporting Security Issues

If you discover a security vulnerability in this project, please **do not open a public GitHub issue**. Instead:

1. Email `[your email here]` with the subject "VAEL Security Issue"
2. Describe the vulnerability and reproduction steps
3. Allow reasonable time for a fix before public disclosure

## Third-Party APIs

This project communicates with:

- **ESI (CCP Games)** — official EVE API. All communication is HTTPS. Credentials are sent only in the OAuth flow, not in API requests.
- **zKillboard** — public kill data API. No authentication required or sent.
- **Fuzzwork** — SDE mirror for initial download only. No ongoing communication.
- **Discord** — webhook only. No user credentials are sent.
- **Anthropic** — only via Claude Desktop's existing API connection. This project does not add any additional Anthropic API communication.

## CCP EULA Compliance

This project uses only the official ESI API with proper OAuth2 authentication. It does not:

- Inject into or modify the EVE client
- Automate gameplay actions
- Read memory from the EVE process
- Bypass any anti-cheat or rate limiting

It is fully compliant with CCP's [Developer License Agreement](https://developers.eveonline.com/resource/license-agreement) and [EULA](https://community.eveonline.com/support/policies/eve-online-end-user-license-agreement-en/).
