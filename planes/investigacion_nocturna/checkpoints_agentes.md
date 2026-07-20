# Investigacion: checkpoints y rollback de estado en agentes autonomos de codigo

Queries ejecutadas (5): `agents code`, `agents code awesome list`, `agents code cli tool`, `agents code open source alternative`, `agents code comparison`

## Resumen

Los resultados proporcionados no contienen información específica sobre checkpoints y rollback de estado en agentes autónomos de código. Los proyectos mencionados se centran en diferentes aspectos de la generación de código, la gestión de tokens y costos, y la comparación de agentes de IA, pero no abordan los mecanismos de recuperación de estado o puntos de control. Para obtener información relevante, se necesitarían recursos que se centren específicamente en la gestión de estados y la recuperación de errores en agentes de IA que generan o manipulan código.

## Modelos (HuggingFace)

1. **llm-agents/tora-code-7b-v1.0** (114 descargas) — https://huggingface.co/llm-agents/tora-code-7b-v1.0
  LlamaForCausalLM, MHA, 32 capas | ctx 16384 | KV 524288 B/tok (64.00 GB @128k)
  transformers, pytorch, llama, text-generation, code, math, en, dataset:gsm8k, dataset:competition_math, text-generation-inference
2. **llm-agents/tora-code-13b-v1.0** (108 descargas) — https://huggingface.co/llm-agents/tora-code-13b-v1.0
  LlamaForCausalLM, MHA, 40 capas | ctx 16384 | KV 819200 B/tok (100.00 GB @128k)
  transformers, pytorch, llama, text-generation, code, math, en, dataset:gsm8k, dataset:competition_math, text-generation-inference
3. **llm-agents/tora-code-34b-v1.0** (99 descargas) — https://huggingface.co/llm-agents/tora-code-34b-v1.0
  LlamaForCausalLM, GQA 64:8, 48 capas | ctx 16384 | KV 196608 B/tok (24.00 GB @128k)
  transformers, pytorch, llama, text-generation, code, math, en, dataset:gsm8k, dataset:competition_math, text-generation-inference
4. **tensorblock/llm-agents_tora-code-7b-v1.0-GGUF** (13 descargas) — https://huggingface.co/tensorblock/llm-agents_tora-code-7b-v1.0-GGUF
  GGUF
  transformers, gguf, code, math, TensorBlock, GGUF, text-generation, en, dataset:gsm8k, dataset:competition_math

## Evidencia (arXiv)

1. **AutoSafeCoder: A Multi-Agent Framework for Securing LLM Code Generation through Static Analysis and Fuzz Testing** — https://arxiv.org/abs/2409.10737v2
  2024 | cs.SE
  Recent advancements in automatic code generation using large language models (LLMs) have brought us closer to fully automated secure software development. However, existing approaches often rely on a 
2. **Code as Agent Harness** — https://arxiv.org/abs/2605.18747v1
  2026 | cs.CL
  Recent large language models (LLMs) have demonstrated strong capabilities in understanding and generating code, from competitive programming to repository-level software engineering. In emerging agent
3. **Asymmetric Goal Drift in Coding Agents Under Value Conflict** — https://arxiv.org/abs/2603.03456v2
  2026 | cs.AI
  Coding agents are increasingly deployed autonomously, at scale, and over long-context horizons. To be effective and safe, these agents must navigate complex trade-offs in deployment, balancing influen
4. **A2P-Vis: an Analyzer-to-Presenter Agentic Pipeline for Visual Insights Generation and Reporting** — https://arxiv.org/abs/2512.22101v1
  2025 | cs.LG
  Automating end-to-end data science pipeline with AI agents still stalls on two gaps: generating insightful, diverse visual evidence and assembling it into a coherent, professional report. We present A
5. **Evaluating LLM-Based 0-to-1 Software Generation in End-to-End CLI Tool Scenarios** — https://arxiv.org/abs/2604.06742v2
  2026 | cs.SE
  The evolution of Large Language Models (LLMs) has catalyzed a paradigm shift towards intent-driven software development, where autonomous agents are expected to design and deliver complete, runnable s
6. **AgentMeter: Evaluating Model-CLI Matching for CLI-Based Local Task-Solving Agents** — https://arxiv.org/abs/2606.21140v1
  2026 | cs.SE
  LLM agents increasingly solve local tasks through command-line and CLI-based harness interfaces, including code editing, repository inspection, data analysis, and file workflows. Existing evaluations 
7. **Adoption and Impact of Command-Line AI Coding Agents: A Study of Microsoft's Early 2026 Rollout of Claude Code and GitHub Copilot CLI** — https://arxiv.org/abs/2607.01418v1
  2026 | cs.SE
  Organizations rolling out agentic command line tools like Anthropic's Claude Code and GitHub's Copilot CLI need to know who will try them, who will keep using them, and whether the tools produce enoug
8. **General Agent Evaluation** — https://arxiv.org/abs/2602.22953v2
  2026 | cs.AI
  General-purpose agents perform tasks in unfamiliar environments without domain-specific manual customization. Yet no study has systematically measured how agent architecture shapes performance across 
9. **When Bots Join the Team: Bot Adoption and the Institutional Fabric of Open-Source Software Projects** — https://arxiv.org/abs/2607.13679v1
  2026 | cs.AI
  AI agents are joining human teams, raising a basic question: when an automated agent becomes a regular participant, does group organization strengthen or weaken? We study this question in open-source 
10. **MedAgentGym: A Scalable Agentic Training Environment for Code-Centric Reasoning in Biomedical Data Science** — https://arxiv.org/abs/2506.04405v2
  2025 | cs.CL
  We introduce MedAgentGym, a scalable and interactive training environment designed to enhance coding-based biomedical reasoning capabilities in large language model (LLM) agents. MedAgentGym comprises
11. **SecureVibeBench: Benchmarking Secure Vibe Coding of AI Agents via Reconstructing Vulnerability-Introducing Scenarios** — https://arxiv.org/abs/2509.22097v5
  2025 | cs.SE
  Large language model-powered code agents are rapidly transforming software engineering, yet the security risks of their generated code have become a critical concern. Existing benchmarks have provided
12. **Read the Paper, Write the Code: Agentic Reproduction of Social-Science Results** — https://arxiv.org/abs/2604.21965v1
  2026 | cs.AI
  Recent work has used LLM agents to reproduce empirical social science results with access to both the data and code. We broaden this scope by asking: Can they reproduce results given only a paper's me
13. **When Does Restricting a Coding Agent to execute_code Help? A Regime $\times$ Agent-Design Ablation** — https://arxiv.org/abs/2607.10569v1
  2026 | cs.SE
  Modern coding agents expose multiple tool surfaces -- IDE primitives, bash, and Model Context Protocol (MCP) code-execution -- and the field has shipped three contradictory claims about which one matt
14. **AgentLens: Production-Assessed Trajectory Reviews for Coding Agent Evaluation** — https://arxiv.org/abs/2607.06624v2
  2026 | cs.AI
  We present AgentLens, a production-assessed benchmark for interactive code agents. Most code-agent benchmarks reduce a run to a single bit -- did the task pass? -- but the people who actually use thes
15. **DeepSWE: Measuring Frontier Coding Agents on Original, Long-Horizon Engineering Tasks** — https://arxiv.org/abs/2607.07946v1
  2026 | cs.SE
  DeepSWE is a benchmark of 113 original, long-horizon software engineering tasks for evaluating coding agents. Most public agentic coding benchmarks follow SWE-bench in mining merged fixes from public 
16. **ToolTweak: An Attack on Tool Selection in LLM-based Agents** — https://arxiv.org/abs/2510.02554v1
  2025 | cs.CR
  As LLMs increasingly power agents that interact with external tools, tool use has become an essential mechanism for extending their capabilities. These agents typically select tools from growing datab

## Codigo (GitHub)

1. **jarrodwatts/claude-hud** (26600 estrellas) — https://github.com/jarrodwatts/claude-hud
  JavaScript
  A Claude Code plugin that shows what's happening - context usage, active tools, running agents, and todo progress
2. **getagentseal/codeburn** (8762 estrellas) — https://github.com/getagentseal/codeburn
  TypeScript
  Free, local tool to track AI coding token usage and cost across 31 tools and agents (Claude Code, Cursor, Codex, Gemini and more), by model, project, and task. npx codeburn
3. **baserow/baserow** (5372 estrellas) — https://github.com/baserow/baserow
  Python
  Build databases, automations, apps & agents with AI — no code.  Open source platform available on cloud and self-hosted. GDPR, HIPAA, SOC 2 compliant. Best Airtable alternative.
4. **composio-community/awesome-claude-plugins** (1833 estrellas) — https://github.com/composio-community/awesome-claude-plugins
  JavaScript
  A curated list of Plugins that let you extend Claude Code with custom commands, agents, hooks, and MCP servers through the plugin system.
5. **Prat011/awesome-llm-skills** (1400 estrellas) — https://github.com/Prat011/awesome-llm-skills
  Python
  A curated list of awesome LLM and AI Agent Skills, resources and tools for customising AI Agent workflows - that works with Claude Code, Codex, Gemini CLI and your custom AI Agents
6. **murataslan1/ai-agent-benchmark** (27 estrellas) — https://github.com/murataslan1/ai-agent-benchmark
  AI coding agents comparison - 80+ agents, SWE-Bench leaderboard, pricing. Devin, Cursor, Claude Code, Copilot, and more. December 2025.
7. **choxos/BiostatAgent** (8 estrellas) — https://github.com/choxos/BiostatAgent
  Python
  Claude Code plugin marketplace for biostatistics in R — 30 agents, 17 commands, and 45 skills spanning Bayesian modeling (Stan/PyMC/JAGS), indirect treatment comparisons (NMA/MAIC/STC/ML-NMR), tidy R 
8. **affaan-m/ECC** (231324 estrellas) — https://github.com/affaan-m/ECC
  JavaScript
  The agent harness performance optimization system. Skills, instincts, memory, security, and research-first development for Claude Code, Codex, Opencode, Cursor and beyond.
9. **thedotmack/claude-mem** (87901 estrellas) — https://github.com/thedotmack/claude-mem
  JavaScript
  Persistent Context Across Sessions for Every Agent –  Captures everything your agent does during sessions, compresses it with AI, and injects relevant context back into future sessions. Works with Cla
10. **DietrichGebert/ponytail** (86217 estrellas) — https://github.com/DietrichGebert/ponytail
  JavaScript
  Makes your AI agent think like the laziest senior dev in the room. The best code is the code you never wrote.
11. **nexu-io/open-design** (79798 estrellas) — https://github.com/nexu-io/open-design
  TypeScript
  🎨 The open-source Claude Design alternative. 🖥️ Local-first desktop app. 🖼️ Your coding agent becomes the design engine: prototypes, landing pages, dashboards, slides, images & video — real files, HTM
12. **cobusgreyling/loop-engineering** (8701 estrellas) — https://github.com/cobusgreyling/loop-engineering
  JavaScript
  Practical patterns, starters & CLI tools for loop engineering with AI coding agents. Design systems that prompt and orchestrate agents (inspired by Addy Osmani and Boris Cherny). Includes loop-audit, 
13. **gptme/gptme** (4361 estrellas) — https://github.com/gptme/gptme
  Python
  Your agent in your terminal, equipped with local tools: writes code, uses the terminal, browses the web. Make your own persistent autonomous agent on top!
14. **snwfdhmp/awesome-ralph** (913 estrellas) — https://github.com/snwfdhmp/awesome-ralph
  A curated list of resources about Ralph, the AI coding technique that runs AI coding agents in automated loops until specifications are fulfilled.
15. **swarmclawai/swarmclaw** (619 estrellas) — https://github.com/swarmclawai/swarmclaw
  TypeScript
  Open-source self-hosted AI agent runtime and multi-agent framework for autonomous agent swarms. Agent memory, MCP tools, schedules, delegation, and 23+ LLM providers (Claude, GPT, Gemini, OpenRouter, 
16. **swarmclawai/swarmvault** (618 estrellas) — https://github.com/swarmclawai/swarmvault
  TypeScript
  The local-first LLM Wiki: open-source knowledge graph builder, RAG knowledge base, and agent memory store. Built on Andrej Karpathy's pattern. An Obsidian alternative for personal knowledge management
17. **fcakyon/phd-skills** (335 estrellas) — https://github.com/fcakyon/phd-skills
  Shell
  PhD Research Skills for Claude Code: paper reproduction, experiment design, paper review, result comparison and more.
18. **carsteneu/ai-memory-comparison** (127 estrellas) — https://github.com/carsteneu/ai-memory-comparison
  HTML
  Source-backed feature comparison of memory systems for AI coding agents. No affiliation, no marketing — just facts from public docs.

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **The Dawn of GUI Agent: A Preliminary Case Study with Claude 3.5 Computer Use** — https://arxiv.org/abs/2411.10323v1
  contra: claude-hud
  The recently released model, Claude 3.5 Computer Use, stands out as the first frontier AI model to offer computer use in public beta as a graphical user interface (GUI) agent. As an early beta, its ca
2. **Capabilities of Large Language Models in Control Engineering: A Benchmark Study on GPT-4, Claude 3 Opus, and Gemini 1.0 Ultra** — https://arxiv.org/abs/2404.03647v1
  contra: claude-hud
  In this paper, we explore the capabilities of state-of-the-art large language models (LLMs) such as GPT-4, Claude 3 Opus, and Gemini 1.0 Ultra in solving undergraduate-level control problems. Controls
3. **The Limitations of Stylometry for Detecting Machine-Generated Fake News** — https://arxiv.org/abs/1908.09805v2
  contra: codeburn
  Recent developments in neural language models (LMs) have raised concerns about their potential misuse for automatically spreading misinformation. In light of these concerns, several studies have propo
4. **Transformers: "The End of History" for NLP?** — https://arxiv.org/abs/2105.00813v2
  contra: codeburn
  Recent advances in neural architectures, such as the Transformer, coupled with the emergence of large-scale pre-trained models such as BERT, have revolutionized the field of Natural Language Processin
