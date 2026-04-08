# Related Work

## Prompt Injection

Greshake et al. (2023) demonstrated indirect prompt injection attacks where adversarial instructions are embedded in external data sources retrieved by LLM-integrated applications. Their taxonomy distinguishes direct injection (user-supplied) from indirect injection (third-party data), with the latter being more relevant to the MCP tool response channel. This work extends that taxonomy to the specific case of tool-mediated injection, where the adversarial content arrives through a protocol-defined response channel rather than arbitrary web content.

Perez and Ribeiro (2022) showed that LLMs can be manipulated through carefully crafted inputs that exploit the model's instruction-following behaviour. Their work on "ignore previous instructions" attacks is conceptually related to our social engineering and authority-framing injection variants.

## MCP Security

**Invariant Labs — Tool Pinning.** Invariant Labs demonstrated that MCP tool descriptions can be modified between sessions, allowing a previously-trusted server to inject new instructions through changed descriptions. Their tool-pinning proposal (hashing tool schemas and alerting on changes) directly addresses the H1 (description drift) vector. This existing work is why H1 was dropped from our experimental scope — the attack vector is already documented and a mitigation exists.

**CyberArk — ATPA (Agentic Tool Prompt Attacks).** CyberArk's research on prompt attacks through tool descriptions and responses informed the design of our injection variants. Their work focuses on attack feasibility; our contribution is systematic measurement of detection gaps on the client side.

## LLM Safety and Tool Use

Schick et al. (2023) introduced Toolformer, demonstrating that LLMs can learn to use tools through self-supervised learning. The safety implications of tool use — particularly when tool responses contain adversarial content — are underexplored relative to the capability research.

Anthropic's system prompt and tool use documentation acknowledges that tool responses are treated as trusted context, but does not provide mechanisms for clients to distinguish safe from adversarial content within the MCP protocol itself.

## Observability and Detection

The concept of "detection blindness" draws from security observability research where the gap between what happens and what operators can see determines incident response capability. Our transparent proxy approach is analogous to network taps in traditional security monitoring — a passive observer that captures ground truth without interfering with the system under test.

## Positioning of This Work

This research occupies a specific niche: **empirical measurement of the detection gap**, not attack development or defence proposal. Prior work has demonstrated that attacks are feasible (Greshake, CyberArk) and that specific mitigations exist for specific vectors (Invariant Labs). What has not been systematically measured is:

1. How do production MCP clients actually perform at surfacing security events to operators?
2. How do frontier LLMs respond to adversarial content arriving through the tool response channel specifically?
3. What is the quantitative gap between what a protocol-aware observer can detect and what standard clients expose?

These are the questions this experimental infrastructure is designed to answer.

## References

- Greshake, K., Abdelnabi, S., Mishra, S., Endres, C., Holz, T., & Fritz, M. (2023). Not what you've signed up for: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection. *arXiv:2302.12173*.
- Perez, F., & Ribeiro, I. (2022). Ignore This Title and HackAPrompt: Exposing Systemic Weaknesses of LLMs through a Global Scale Prompt Hacking Competition. *arXiv:2311.16119*.
- Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Hambro, E., ... & Scialom, T. (2023). Toolformer: Language Models Can Teach Themselves to Use Tools. *arXiv:2302.04761*.
- Invariant Labs. (2024). Tool Pinning for MCP Security. https://invariantlabs.ai
- CyberArk. (2025). Agentic Tool Prompt Attacks (ATPA). https://cyberark.com
