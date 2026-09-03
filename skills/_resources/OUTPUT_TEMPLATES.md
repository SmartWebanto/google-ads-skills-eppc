# Output templates

Skill bodies stay in English. The report is written in the client's `report_language` (`it` or `en`). Every report starts with the header block; every finding line names the skill that produced it. Never report the same entity and condition twice across related skills: the more specific skill wins.

## Header (both languages, always first)

```
## <Skill title> — <Account name>
Account <id> · currency <CUR> · data <date range> · snapshot <YYYY-MM-DD>
Library eppc-ads-skills@1.0.0 · skill <skill-id> (upstream <upstream_skill>@1.8.0) · profile <client slug or "defaults">
```

## Short — English (default)

```
<header>

### Critical (<n>)
- **<Entity>**: <issue> → <fix> · <skill-id>

### Warnings (<n>)
- **<Entity>**: <issue> → <fix> · <skill-id>

### Info (<n>)
- **<Entity>**: <note> · <skill-id>

### Recommendations
1. <priority action> (<estimated impact in CUR>)
2. <secondary action>
```

## Short — Italiano

```
<header>

### Critici (<n>)
- **<Entità>**: <problema> → <intervento> · <skill-id>

### Avvisi (<n>)
- **<Entità>**: <problema> → <intervento> · <skill-id>

### Informativi (<n>)
- **<Entità>**: <nota> · <skill-id>

### Raccomandazioni
1. <azione prioritaria> (<impatto stimato in CUR>)
2. <azione secondaria>
```

## Detailed — English

```
<header>

### What was checked
- <aspect>

### Critical issues (<n>)
1. **<Entity>**: <issue> · <skill-id>
   - Impact: <what it causes, in CUR where possible>
   - Evidence: <data, with the parameter values used, e.g. spend_significant = 120 EUR>
   - Fix: <specific action>

### Warnings (<n>)
1. **<Entity>**: <issue> · <skill-id>
   - Fix: <specific action>

### Summary
| Metric | Value |
|--------|-------|
| Entities analyzed | <n> |
| Issues found | <n> |
| Critical | <n> |
| Warnings | <n> |
| Insufficient sample (skipped) | <n> |

### Recommendations
1. **<priority action>** — <rationale>
```

## Detailed — Italiano

```
<header>

### Cosa è stato verificato
- <aspetto>

### Problemi critici (<n>)
1. **<Entità>**: <problema> · <skill-id>
   - Impatto: <cosa causa, in CUR dove possibile>
   - Evidenza: <dati, con i valori dei parametri usati, es. spend_significant = 120 EUR>
   - Intervento: <azione specifica>

### Avvisi (<n>)
1. **<Entità>**: <problema> · <skill-id>
   - Intervento: <azione specifica>

### Riepilogo
| Metrica | Valore |
|--------|-------|
| Entità analizzate | <n> |
| Problemi trovati | <n> |
| Critici | <n> |
| Avvisi | <n> |
| Campione insufficiente (saltati) | <n> |

### Raccomandazioni
1. **<azione prioritaria>** — <motivazione>
```

## No issues

English: `No issues found. <n> entities pass the audit criteria.` Italiano: `Nessun problema rilevato. <n> entità superano i criteri di audit.` The header block is still required.

## Rules

1. Never list passed entities individually.
2. Group by severity: Critical → Warnings → Info.
3. Name the exact entity (campaign, ad group, keyword, list).
4. Every issue carries a fix and the skill id.
5. Quantify impact in the account currency; state the parameter values used when a threshold was parametric.
6. Rate-based judgments below `{{min_clicks}}` / `{{min_conversions}}` go under "Insufficient sample", as Info.
7. No educational content.
