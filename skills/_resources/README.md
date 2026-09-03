> Upstream document from TrueClicks google-ads@1.8.0, kept for reference. The commands under `commands/` call TrueClicks' hosted API (api.claudeppc.ai): use them only for a client with a signed DPA (see the root README).

# Google Ads Plugin for Claude Code

Free Google Ads account management plugin. Fetch account data, analyze and audit accounts, validate and execute changes - all from Claude Code.

## Setup

### Getting Started

1. Create a project folder for your Google Ads account
2. Run `/google-ads:start` to set up the project — it will create `config.json` and guide you through setup.
3. Run `/google-ads:get` to download your account data.
