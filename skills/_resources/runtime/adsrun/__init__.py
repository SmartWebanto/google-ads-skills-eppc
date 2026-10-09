"""adsrun — Standard-library runtime for deterministic checks in eppc Google Ads skills.

exports: __version__ | cli | context | evidence | negatives | params | result | values | yamlish
used_by: skills/skill-*/scripts/check.py (via bootstrap), skills/_resources/scripts/build_app_skills.py (vendored)
rules:   Standard library only (Claude Team containers may have no network/PyPI).
         Read-only: never writes outside the --out folder, never calls the network or Google Ads.
agent:   claude-opus-5-5 | anthropic | 2026-09-25 | s_20260925_runtime | initial package
"""
__version__ = "1.0.0"
