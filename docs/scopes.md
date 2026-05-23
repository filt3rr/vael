# EVE SSO Scopes

When registering your application at [developers.eveonline.com](https://developers.eveonline.com), enable these scopes under **esi-** categories:

## Required Scopes

| Scope | Category | What It Enables |
|-------|----------|-----------------|
| `esi-skills.read_skills.v1` | esi-skills | Total SP, trained skill levels |
| `esi-skills.read_skillqueue.v1` | esi-skills | Training queue + finish dates |
| `esi-wallet.read_character_wallet.v1` | esi-wallet | ISK balance + wallet journal |
| `esi-location.read_location.v1` | esi-location | Current solar system + station |
| `esi-location.read_ship_type.v1` | esi-location | Currently active ship type |
| `esi-location.read_online.v1` | esi-location | Online status + last login |
| `esi-assets.read_assets.v1` | esi-assets | All assets including fitted modules |
| `esi-markets.read_character_orders.v1` | esi-markets | Open buy + sell orders |
| `esi-industry.read_character_jobs.v1` | esi-industry | Active + completed industry jobs |
| `esi-fittings.read_fittings.v1` | esi-fittings | Saved ship fittings |
| `esi-contracts.read_character_contracts.v1` | esi-contracts | Contract status monitoring |
| `esi-mail.read_mail.v1` | esi-mail | New mail detection |
| `esi-characters.read_corporation_roles.v1` | esi-characters | Corp role access |
| `esi-characters.read_blueprints.v1` | esi-characters | Owned blueprints (BPOs/BPCs) |
| `esi-clones.read_clones.v1` | esi-clones | Jump clone locations + cooldown |
| `esi-clones.read_implants.v1` | esi-clones | Active clone implants |

## Optional Scopes (future features)

| Scope | What It Would Enable |
|-------|---------------------|
| `esi-markets.structure_markets.v1` | Prices inside player-owned structures |
| `esi-characters.read_contacts.v1` | Contact list and standings |
| `esi-corporations.read_corporation_membership.v1` | Corp member list |
| `esi-wallet.read_corporation_wallets.v1` | Corp wallet (requires director role) |

## Notes

- `publicData` is NOT required — it was removed after CCP deprecated it from the SSO flow
- All current scopes are **read-only** — the agent cannot modify your account
- You can add scopes later but must re-authenticate: `python -m eve_agent.auth --logout && python -m eve_agent.auth`

## Callback URL

Set exactly to:
```
http://localhost:8765/callback
```

No trailing slash. HTTP not HTTPS. Port 8765.
