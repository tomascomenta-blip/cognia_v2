# Investigacion: tool permission approval and sandboxing policy in autonomous agents

Queries ejecutadas (4): `awesome autonomous agents`, `autonomous agent permission`, `agent tool approval`, `tool autonomous agents`

## Resumen

The search results provide insights into tool permission approval and sandboxing policies in autonomous agents, particularly focusing on repositories and research papers that address these issues. The Microsoft Agent Governance Toolkit (microsoft/agent-governance-toolkit) is a significant resource, offering policy enforcement, zero-trust identity, execution sandboxing, and reliability engineering for autonomous AI agents. This toolkit covers 10/10 OWASP Agentic Top 10, making it a comprehensive solution for managing permissions and ensuring secure execution environments. Additionally, the Janus project (arxiv.org/abs/2309.04744) introduces a playground for user-involved agentic permission management, exploring the role of users in managing permissions for AI agents that autonomously execute tool calls. These resources highlight the importance of robust permission management and sandboxing in ensuring the safe and effective operation of autonomous agents.

## Evidencia (arXiv)

1. **Self-Improvements in Modern Agentic Systems: A Survey** — https://arxiv.org/abs/2607.13104v1
  2026 | cs.AI
  Self-improving autonomous agents are moving from research prototypes to deployed systems. The primary goal is controllable evolution, or adaptation, from experience with minimal or even no human input
2. **Janus: a Playground for User-Involved Agentic Permission Management** — https://arxiv.org/abs/2607.01510v1
  2026 | cs.AI
  AI agents that autonomously execute tool calls on a user's behalf raise pressing questions about permission management: what role could users play, and what role should they play? Despite many propose
3. **SoK: Trust-Authorization Mismatch in LLM Agent Interactions** — https://arxiv.org/abs/2512.06914v2
  2025 | cs.CR
  Large Language Models (LLMs) are evolving into autonomous agents capable of executing complex workflows via standardized protocols (e.g., MCP). However, this paradigm shifts control from deterministic
4. **Agents: An Open-source Framework for Autonomous Language Agents** — https://arxiv.org/abs/2309.07870v3
  2023 | cs.CL
  Recent advances on large language models (LLMs) enable researchers and developers to build autonomous language agents that can automatically solve various tasks and interact with environments, humans,
5. **When Lower Privileges Suffice: Investigating Over-Privileged Tool Selection in LLM Agents** — https://arxiv.org/abs/2606.20023v2
  2026 | cs.SE
  As LLM agents increasingly select tools autonomously, their choices among tools with different privileges become safety-relevant. However, prior tool-selection studies focus on safety-agnostic metadat
6. **MCP-Zero: Active Tool Discovery for Autonomous LLM Agents** — https://arxiv.org/abs/2506.01056v4
  2025 | cs.AI
  True intelligence requires active capability acquisition, yet current LLM agents inject pre-defined tool schemas into prompts, reducing models to passive selectors and falling short of robust general-
7. **Phantom -- A RL-driven multi-agent framework to model complex systems** — https://arxiv.org/abs/2210.06012v3
  2022 | cs.AI
  Agent based modelling (ABM) is a computational approach to modelling complex systems by specifying the behaviour of autonomous decision-making components or agents in the system and allowing the syste
8. **A Survey of Data Agents: Emerging Paradigm or Overstated Hype?** — https://arxiv.org/abs/2510.23587v2
  2025 | cs.DB
  The rapid advancement of large language models (LLMs) has spurred the emergence of data agents, autonomous systems designed to orchestrate Data + AI ecosystems for tackling complex data-related tasks.
9. **The Path to Self-Evolving Clinical Systems: Scaling Medical Agents from Assistance to Autonomy** — https://arxiv.org/abs/2607.11175v1
  2026 | cs.AI
  The growing ability of large language models and vision language models to jointly interpret and reason over images and text is reshaping medical agents, moving them from task specific predictors towa
10. **LLM-Based Human-Agent Collaboration and Interaction Systems: A Survey** — https://arxiv.org/abs/2505.00753v5
  2025 | cs.CL
  Recent advances in large language models (LLMs) have sparked growing interest in building fully autonomous agents. However, fully autonomous LLM-based agents still face significant challenges, includi
11. **How Agents Ask for Permission: User Permissions for AI Agents, from Interfaces to Enforcement** — https://arxiv.org/abs/2607.13718v1
  2026 | cs.CR
  As AI agents gain prevalance, users are increasingly exposed to the risks such systems entail. Prompt injection attacks, as well as hallucination, can cause agents to leak private information to third
12. **Towards Automating Data Access Permissions in AI Agents** — https://arxiv.org/abs/2511.17959v1
  2025 | cs.CR
  As AI agents attempt to autonomously act on users' behalf, they raise transparency and control issues. We argue that permission-based access control is indispensable in providing meaningful control to
13. **Unicode TAG-Block Concealment of Tool-Metadata Payloads in the Model Context Protocol: An Approval-View Fidelity Gap Across Three Independent Server Implementations** — https://arxiv.org/abs/2607.05744v1
  2026 | cs.CR
  The Model Context Protocol (MCP) is the dominant way coding agents discover and invoke external tools. A server advertises each tool through a tools/list handshake that returns a name, a natural-langu
14. **Progressive Autonomy as Preference Learning: A Formalization of Trust Calibration for Agentic Tool Use** — https://arxiv.org/abs/2605.19151v1
  2026 | cs.AI
  We formalize trust calibration for agentic tool use (deciding when an automated agent's proposed action may execute autonomously versus require human approval) as a preference-learning problem. A poli
15. **From Tool Connection to Execution Control: Benchmarking Security Invariants in MCP-Style Agent Runtimes** — https://arxiv.org/abs/2606.29073v1
  2026 | cs.CR
  Model Context Protocol (MCP)-style ecosystems give language-model applications a practical connection layer for tools, resources, prompts, and transports. As agents move from connection to execution, 
16. **CAVA: Canonical Action Verification and Attestation for Runtime Governance of Agentic AI Systems** — https://arxiv.org/abs/2607.13716v1
  2026 | cs.AI
  Agentic AI systems increasingly act through heterogeneous runtimes: local coding hooks, SDK tools, browser automation, managed-agent traces, API gateways, and workflow engines. A single operational ac

## Codigo (GitHub)

1. **0x4m4/hexstrike-ai** (10396 estrellas) — https://github.com/0x4m4/hexstrike-ai
  Python
  HexStrike AI MCP Agents is an advanced MCP server that lets AI agents (Claude, GPT, Copilot, etc.) autonomously run 150+ cybersecurity tools for automated pentesting, vulnerability discovery, bug boun
2. **microsoft/agent-governance-toolkit** (4865 estrellas) — https://github.com/microsoft/agent-governance-toolkit
  Python
  AI Agent Governance Toolkit — Policy enforcement, zero-trust identity, execution sandboxing, and reliability engineering for autonomous AI agents. Covers 10/10 OWASP Agentic Top 10.
3. **Armur-Ai/Pentest-Swarm-AI** (2086 estrellas) — https://github.com/Armur-Ai/Pentest-Swarm-AI
  Go
  Autonomous penetration testing using a swarm of AI agents. Orchestrates recon, classification, exploitation, and reporting specialists with ReAct reasoning — supports bug bounty, continuous monitoring
4. **e2b-dev/awesome-ai-agents** (28949 estrellas) — https://github.com/e2b-dev/awesome-ai-agents
  A list of AI autonomous agents
5. **gptme/gptme** (4361 estrellas) — https://github.com/gptme/gptme
  Python
  Your agent in your terminal, equipped with local tools: writes code, uses the terminal, browses the web. Make your own persistent autonomous agent on top!
6. **webfuse-com/awesome-autoresearch** (2321 estrellas) — https://github.com/webfuse-com/awesome-autoresearch
  A curated list of autonomous improvement loops, research agents, and autoresearch-style systems inspired by Karpathy's autoresearch.
7. **cordum-io/cordum** (491 estrellas) — https://github.com/cordum-io/cordum
  Go
  The action firewall for AI agents. Enforce policy and human approval before risky tool calls, shell commands, workflows, and production changes, with auditable evidence.
8. **WORLD3-ai/world_ai_protocol** (257 estrellas) — https://github.com/WORLD3-ai/world_ai_protocol
  Move
  A chain-agnostic, secure delegation framework enabling AI Agents to perform autonomous, permissioned on-chain actions across Web3 ecosystems.
9. **DerekYRC/mini-claude-code** (149 estrellas) — https://github.com/DerekYRC/mini-claude-code
  Java
  mini-claude-code: a simplified Java Claude Code agent distilling core Agent Harness mechanisms. Features: Agent Loop, tools, permission control, Hooks, Todo, Subagent, Skill Loading, context compressi
10. **fu351/Doberman-Core** (112 estrellas) — https://github.com/fu351/Doberman-Core
  Python
  Doberman is an AI agent security framework for guardrails, prompt injection defense, runtime policy enforcement, tool-use permissions, agent monitoring, audit logs, LLM safety, autonomous workflow pro
11. **wxtsky/CodeIsland** (2149 estrellas) — https://github.com/wxtsky/CodeIsland
  Swift
  Real-time AI coding agent status panel in your MacBook notch — live status, approvals & replies for 13 AI tools, with iPhone & Apple Watch companions
12. **VoltAgent/awesome-ai-agent-papers** (1600 estrellas) — https://github.com/VoltAgent/awesome-ai-agent-papers
  A curated collection of AI agent research papers released in 2026, covering agent engineering, memory, evaluation, workflows, and autonomous systems.
13. **mkurman/zorai** (319 estrellas) — https://github.com/mkurman/zorai
  Rust
  Zorai is a persistent, multi-agent, auditable, learning execution platform where the daemon owns work, memory, approvals, tools, and long-running goals.
14. **bastani-inc/atomic** (289 estrellas) — https://github.com/bastani-inc/atomic
  TypeScript
  The verifiable coding agent runtime. Build your software factory with verification built in. Run verifiable engineering loops through explicit workflow graphs. Define the work as a graph of stages, ga
15. **aidrivencoder/Roo-Cline** (46 estrellas) — https://github.com/aidrivencoder/Roo-Cline
  TypeScript
  Autonomous coding agent right in your IDE, capable of creating/editing files, executing commands, using the browser, and more with your permission every step of the way.

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **Determinants and Limits of LLM Security-Tool Orchestration: A Study with HexStrike-AI** — https://arxiv.org/abs/2607.02873v1
  contra: hexstrike-ai
  Large language model agents driving security tool suites over the Model Context Protocol are increasingly common. Yet the factors that bound their capability remain poorly characterized: how much depe
2. **Risk Analysis Techniques for Governed LLM-based Multi-Agent Systems** — https://arxiv.org/abs/2508.05687v1
  contra: agent-governance-toolkit
  Organisations are starting to adopt LLM-based AI agents, with their deployments naturally evolving from single agents towards interconnected, multi-agent networks. Yet a collection of safe agents does
3. **Pentest-R1: Towards Autonomous Penetration Testing Reasoning Optimized via Two-Stage Reinforcement Learning** — https://arxiv.org/abs/2508.07382v2
  contra: Pentest-Swarm-AI
  Automating penetration testing is crucial for enhancing cybersecurity, yet current Large Language Models (LLMs) face significant limitations in this domain, including poor error handling, inefficient 
4. **Pen-Strategist: A Reasoning Framework for Penetration Testing Strategy Formation and Analysis** — https://arxiv.org/abs/2605.04499v1
  contra: Pentest-Swarm-AI
  Cyber threats are rapidly increasing, expanding their impact from large-scale enterprises to government services and individual users, making robust security systems increasingly essential. However, a
