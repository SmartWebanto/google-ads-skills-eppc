---
name: skill-093-pmax-video-asset-review
description: "Ensure Performance Max campaigns have custom video assets uploaded rather than relying on auto-generated videos."
allowed-tools: Read, Grep, Glob
metadata:
  library: eppc-ads-skills@1.0.0
  category: shopping_pmax
  kind: deterministic
  data_source: custom_query
  markets: all
  gaql_verified: null
  reviewed: 2026-09-03
---
# Skill 093: Performance Max Video Asset Review

## Purpose
Ensure Performance Max campaigns have custom video assets uploaded rather than relying on auto-generated videos. Custom videos improve brand control, ad quality, and performance on YouTube placements.

## Data Requirements

**Data Source:** Custom query required

**GAQL Query - Video Assets:**
```sql
SELECT
  campaign.name,
  asset_group.name,
  asset_group.id,
  asset_group.ad_strength,
  asset_group_asset.asset,
  asset_group_asset.field_type,
  asset_group_asset.status
FROM asset_group_asset
WHERE campaign.advertising_channel_type = 'PERFORMANCE_MAX'
  AND asset_group_asset.field_type IN ('YOUTUBE_VIDEO')
```

**GAQL Query - Video Asset Details:**
```sql
SELECT
  asset.id,
  asset.name,
  asset.type,
  asset.youtube_video_asset.youtube_video_id,
  asset.youtube_video_asset.youtube_video_title
FROM asset
WHERE asset.type = 'YOUTUBE_VIDEO'
```
Run the query through the Google Ads API, a UI custom report, or Google Ads Editor; save the result as `pmax_video_assets`.

**Export data:**
- **Campaigns** - Campaign settings

## Analysis Steps

1. **Inventory Video Assets:** Count custom videos per asset group; identify auto-generated vs. custom
2. **Evaluate Video Coverage:** Flag asset groups with 0 custom videos (auto-generated used)
3. **Assess Video Quality:** Check for multiple aspect ratios (16:9, 9:16, 1:1) and durations
4. **Review Performance:** Video view rates, completion rates, video-driven conversions

## Thresholds

| Condition | Severity |
|-----------|----------|
| No custom videos in any asset group | Critical |
| <3 custom videos per asset group | Warning |
| Missing portrait (9:16) format | Warning |
| Video completion rate <25% | Info |
| Ad strength affected by missing videos | Warning |

## Output

**Short (default):**
```
## PMax Video Asset Review
**Account:** [name] | **Asset Groups:** [count] | **With Custom Videos:** [count] | **Issues:** [count]

### Critical
- **[count] asset groups using auto-generated videos only** - Upload custom videos

### Warnings
- **[Asset Group]**: Only [count] videos - Add [count] more
- **[Asset Group]**: Missing portrait (9:16) format - Add vertical video

### Recommendations
1. Upload custom videos to [count] asset groups
2. Add portrait (9:16) videos for YouTube Shorts/Stories
3. Create 6-second bumper versions for broader reach
```

**Detailed adds:**
- Asset group video inventory table
- Video format coverage (landscape, portrait, square)
- Video duration coverage (6s, 15s, 30s+)
- YouTube performance metrics if available
