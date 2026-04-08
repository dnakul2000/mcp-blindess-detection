# Responsible Disclosure Policy

## Principles

This research follows responsible disclosure practices. Findings are framed at the **protocol level**, not as vendor-specific criticism. The goal is to improve MCP ecosystem security, not to embarrass implementers.

## Disclosure Timeline

1. **Pre-experiment notification**: Before running experiments against production clients, notify each vendor's security team with:
   - Scope of testing (which clients, which attack vectors)
   - Expected timeline for findings
   - Contact information for coordination

2. **Findings report**: After analysis is complete, share detailed findings with all tested vendors under embargo. Report includes:
   - Per-client detection results (detection blindness scores)
   - Specific events missed by each client
   - Recommended mitigations

3. **Embargo period**: 90 days from findings report to public disclosure. Standard industry practice per Google Project Zero and CERT/CC guidelines.

4. **Publication**: After embargo expiration (or earlier with vendor agreement):
   - GitHub repository with full experimental infrastructure
   - arXiv preprint with methodology and results
   - Results webpage with interactive tables

## Vendor Contact List

| Vendor | Product | Security Contact | Status |
|--------|---------|-----------------|--------|
| Anthropic | Claude Desktop, Claude Code CLI | security@anthropic.com | Pending |
| Microsoft | VS Code + MCP Extension | security@microsoft.com | Pending |
| Cursor | Cursor IDE | security@cursor.com | Pending |

## What We Disclose

- Protocol-level detection gaps (e.g., "N/5 clients failed to surface schema mutations")
- Aggregate compliance data per model family (e.g., "Model family X showed full execution in M/N runs")
- Specific missing client features (e.g., "no client logged undeclared parameters")
- Recommended protocol extensions or client features

## What We Do Not Disclose

- Working exploit chains targeting specific users or deployments
- API keys, credentials, or internal infrastructure details
- Vendor-specific vulnerability details before the embargo period expires
- Comparisons framed as rankings or vendor quality scores

## Coordinated Disclosure Template

```
Subject: MCP Security Research — Detection Blindness Measurement

We are conducting empirical security research measuring observability
gaps in MCP client implementations. Our research tests whether
security-relevant events during MCP tool sessions (schema mutations,
undeclared parameters, response payload injections) are visible to
operators through your client's UI and logs.

We plan to test [CLIENT NAME] as part of a multi-client study. Our
methodology uses controlled adversarial MCP servers (no real data
exfiltration) with a transparent proxy to establish ground truth.

Expected timeline:
- Experiments: [DATE RANGE]
- Findings shared with you: [DATE]
- Embargo period: 90 days
- Target publication: [DATE]

We welcome coordination on timeline, scope, or mitigation priorities.

Contact: [RESEARCHER EMAIL]
```

## Mitigation Recommendations (to be included in disclosure)

Based on the experimental design, likely recommendations include:

1. **Schema validation**: Clients should validate `tools/call` arguments against declared `inputSchema` and log violations.
2. **Response content scanning**: Flag tool responses containing instruction-like patterns for operator review.
3. **Schema pinning**: Hash tool descriptions and alert operators on changes between `tools/list` calls.
4. **Observability**: Surface all MCP protocol events in client logs, not just final LLM responses.
5. **Content tagging**: Protocol-level mechanism to distinguish tool response data from instructions.
