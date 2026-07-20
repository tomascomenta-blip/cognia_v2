# Investigacion: como verifican los agentes de coding que su codigo funciona de verdad

Queries ejecutadas (5): `code verification agent`, `code analysis agent`, `agents coding`, `agents coding awesome list`, `agents coding cli tool`

## Resumen

Los agentes de codificación verifican que su código funciona de verdad a través de múltiples métodos y herramientas. Por ejemplo, el repositorio `FerroxLabs/agents-md` proporciona un archivo AGENTS.md que asegura que los agentes de codificación comporten como ingenieros senior en lugar de internos entusiastas, forzando bucles de verificación. Además, el repositorio `kodustech/awesome-agent-skills` ofrece una lista curada de habilidades para agentes de codificación como Claude Code, Codex y Cursor. También, el repositorio `moazbuilds/CodeMachine-CLI` es una herramienta abierta que orquesta a los agentes de codificación AI en flujos de trabajo repetibles y de larga duración. Estas herramientas y repositorios ayudan a garantizar que los agentes de codificación produzcan código de calidad y funcional.

## Modelos (HuggingFace)

1. **LordNeel/Agents-A1-GGUF** (36773 descargas) — https://huggingface.co/LordNeel/Agents-A1-GGUF
  GGUF
  llama.cpp, gguf, quantized, llama-cpp, qwen3.5-moe, mixture-of-experts, agents-a1, nvfp4, mtp, speculative-decoding
2. **felkf/Ornith-Agents-A1-3.7-35B-A3B-dare_ties_v4-oQ6-fp16** (68372 descargas) — https://huggingface.co/felkf/Ornith-Agents-A1-3.7-35B-A3B-dare_ties_v4-oQ6-fp16
  Qwen3_5MoeForConditionalGeneration
  mlx, safetensors, qwen3_5_moe, oq, quantized, 6-bit
3. **InternScience/Agents-A1-Q4_K_M-GGUF** (51675 descargas) — https://huggingface.co/InternScience/Agents-A1-Q4_K_M-GGUF
  GGUF
  gguf, quantized, moe, vlm, vision, agentic, text-generation, endpoints_compatible, conversational
4. **InternScience/Agents-A1** (35833 descargas) — https://huggingface.co/InternScience/Agents-A1
  Qwen3_5MoeForConditionalGeneration
  transformers, safetensors, qwen3_5_moe, image-text-to-text, moe, vlm, vision, agentic, text-generation, conversational

## Evidencia (arXiv)

1. **Your Code Agent Can Grow Alongside You with Structured Memory** — https://arxiv.org/abs/2603.13258v1
  2026 | cs.LG
  While "Intent-oriented programming" (or "Vibe Coding") redefines software engineering, existing code agents remain tethered to static code snapshots. Consequently, they struggle to model the critical 
2. **Asymmetric Goal Drift in Coding Agents Under Value Conflict** — https://arxiv.org/abs/2603.03456v2
  2026 | cs.AI
  Coding agents are increasingly deployed autonomously, at scale, and over long-context horizons. To be effective and safe, these agents must navigate complex trade-offs in deployment, balancing influen
3. **AutoSafeCoder: A Multi-Agent Framework for Securing LLM Code Generation through Static Analysis and Fuzz Testing** — https://arxiv.org/abs/2409.10737v2
  2024 | cs.SE
  Recent advancements in automatic code generation using large language models (LLMs) have brought us closer to fully automated secure software development. However, existing approaches often rely on a 
4. **Adoption and Impact of Command-Line AI Coding Agents: A Study of Microsoft's Early 2026 Rollout of Claude Code and GitHub Copilot CLI** — https://arxiv.org/abs/2607.01418v1
  2026 | cs.SE
  Organizations rolling out agentic command line tools like Anthropic's Claude Code and GitHub's Copilot CLI need to know who will try them, who will keep using them, and whether the tools produce enoug
5. **Steerability via constraints: a substrate for scalable oversight of coding agents** — https://arxiv.org/abs/2607.02389v1
  2026 | cs.AI
  Coding agents are capable; human oversight is the bottleneck. Unconstrained agents introduce security risks, erode codebase scalability, and make human review increasingly costly. We argue that the sa
6. **Lore: Repurposing Git Commit Messages as a Structured Knowledge Protocol for AI Coding Agents** — https://arxiv.org/abs/2603.15566v1
  2026 | cs.SE
  As AI coding agents become both primary producers and consumers of source code, the software industry faces an accelerating loss of institutional knowledge. Each commit captures a code diff but discar
7. **When Does Restricting a Coding Agent to execute_code Help? A Regime $\times$ Agent-Design Ablation** — https://arxiv.org/abs/2607.10569v1
  2026 | cs.SE
  Modern coding agents expose multiple tool surfaces -- IDE primitives, bash, and Model Context Protocol (MCP) code-execution -- and the field has shipped three contradictory claims about which one matt
8. **Code as Agent Harness** — https://arxiv.org/abs/2605.18747v1
  2026 | cs.CL
  Recent large language models (LLMs) have demonstrated strong capabilities in understanding and generating code, from competitive programming to repository-level software engineering. In emerging agent
9. **CAVA: Canonical Action Verification and Attestation for Runtime Governance of Agentic AI Systems** — https://arxiv.org/abs/2607.13716v1
  2026 | cs.AI
  Agentic AI systems increasingly act through heterogeneous runtimes: local coding hooks, SDK tools, browser automation, managed-agent traces, API gateways, and workflow engines. A single operational ac
10. **Harnessing Code Agents for Automatic Software Verification** — https://arxiv.org/abs/2607.06341v1
  2026 | cs.FL
  Formal verification offers the strongest guarantee of software correctness, but it does not scale: the proofs demanded by interactive theorem provers such as Coq require enormous expert effort. Large 
11. **Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems** — https://arxiv.org/abs/2604.14228v2
  2026 | cs.SE
  Claude Code is an agentic coding tool that can run shell commands, edit files, and call external services on behalf of the user. This study describes its architecture by analyzing the publicly availab
12. **Executable Code Actions Elicit Better LLM Agents** — https://arxiv.org/abs/2402.01030v4
  2024 | cs.CL
  Large Language Model (LLM) agents, capable of performing a broad range of actions, such as invoking tools and controlling robots, show great potential in tackling real-world challenges. LLM agents are
13. **Virtual Agents in Live Coding: A Short Review** — https://arxiv.org/abs/2106.14835v1
  2021 | cs.HC
  AI and live coding has been little explored. This article contributes with a short review of different perspectives of using virtual agents in the practice of live coding looking at past and present a
14. **Agents: An Open-source Framework for Autonomous Language Agents** — https://arxiv.org/abs/2309.07870v3
  2023 | cs.CL
  Recent advances on large language models (LLMs) enable researchers and developers to build autonomous language agents that can automatically solve various tasks and interact with environments, humans,
15. **VoxelPrompt: A Vision Agent for End-to-End Medical Image Analysis** — https://arxiv.org/abs/2410.08397v2
  2024 | eess.IV
  We present VoxelPrompt, an end-to-end image analysis agent that tackles free-form radiological tasks. Given any number of volumetric medical images and a natural language prompt, VoxelPrompt integrate
16. **Foundations for Agentic AI Investigations from the Forensic Analysis of OpenClaw** — https://arxiv.org/abs/2604.05589v1
  2026 | cs.CR
  Agentic Al systems are increasingly deployed as personal assistants and are likely to become a common object of digital investigations. However, little is known about how their internal state and acti

## Codigo (GitHub)

1. **getagentseal/codeburn** (8763 estrellas) — https://github.com/getagentseal/codeburn
  TypeScript
  Free, local tool to track AI coding token usage and cost across 31 tools and agents (Claude Code, Cursor, Codex, Gemini and more), by model, project, and task. npx codeburn
2. **moazbuilds/CodeMachine-CLI** (2513 estrellas) — https://github.com/moazbuilds/CodeMachine-CLI
  TypeScript
  CodeMachine is an open-source tool that orchestrates AI coding agents into repeatable, long-running workflows. ⚡️
3. **FerroxLabs/agents-md** (630 estrellas) — https://github.com/FerroxLabs/agents-md
  Drop-in AGENTS.md that makes every coding agent behave like a senior engineer instead of an eager intern. Kills sycophancy, stops drive-by refactors, forces verification loops. Synthesizes Karpathy's 
4. **kodustech/awesome-agent-skills** (88 estrellas) — https://github.com/kodustech/awesome-agent-skills
  Curated list of Agent Skills for AI coding agents like Claude Code, Codex and Cursor.
5. **VoltAgent/awesome-design-md** (103219 estrellas) — https://github.com/VoltAgent/awesome-design-md
  A collection of DESIGN.md files analysis by popular brand design systems. Drop one into your project and let coding agents generate a matching UI.
6. **nexu-io/open-design** (79798 estrellas) — https://github.com/nexu-io/open-design
  TypeScript
  🎨 The open-source Claude Design alternative. 🖥️ Local-first desktop app. 🖼️ Your coding agent becomes the design engine: prototypes, landing pages, dashboards, slides, images & video — real files, HTM
7. **addyosmani/agent-skills** (79352 estrellas) — https://github.com/addyosmani/agent-skills
  JavaScript
  Production-grade engineering skills for AI coding agents.
8. **can1357/oh-my-pi** (18517 estrellas) — https://github.com/can1357/oh-my-pi
  TypeScript
  ⌥  AI Coding agent for the terminal — hash-anchored edits, optimized tool harness, LSP, Python, browser, subagents, and more
9. **KKKKhazix/khazix-skills** (17419 estrellas) — https://github.com/KKKKhazix/khazix-skills
  Python
  数字生命卡兹克开源的 AI Skills 合集 | Agent Skills: neat-freak 洁癖 (docs/memory closeout), hv-analysis, khazix-writer & more — Claude Code, Codex & 40+ agents
10. **cobusgreyling/loop-engineering** (8701 estrellas) — https://github.com/cobusgreyling/loop-engineering
  JavaScript
  Practical patterns, starters & CLI tools for loop engineering with AI coding agents. Design systems that prompt and orchestrate agents (inspired by Addy Osmani and Boris Cherny). Includes loop-audit, 
11. **Ataraxy-Labs/sem** (3230 estrellas) — https://github.com/Ataraxy-Labs/sem
  Rust
  Semantic version control => entity-level diffs, blame, and impact analysis on top of git. 28 languages via tree-sitter. Built for coding agents.
12. **composio-community/awesome-claude-plugins** (1833 estrellas) — https://github.com/composio-community/awesome-claude-plugins
  JavaScript
  A curated list of Plugins that let you extend Claude Code with custom commands, agents, hooks, and MCP servers through the plugin system.
13. **Prat011/awesome-llm-skills** (1400 estrellas) — https://github.com/Prat011/awesome-llm-skills
  Python
  A curated list of awesome LLM and AI Agent Skills, resources and tools for customising AI Agent workflows - that works with Claude Code, Codex, Gemini CLI and your custom AI Agents
14. **snwfdhmp/awesome-ralph** (913 estrellas) — https://github.com/snwfdhmp/awesome-ralph
  A curated list of resources about Ralph, the AI coding technique that runs AI coding agents in automated loops until specifications are fulfilled.
15. **oliver-kriska/claude-elixir-phoenix** (492 estrellas) — https://github.com/oliver-kriska/claude-elixir-phoenix
  Python
  Claude Code plugin for Elixir/Phoenix/LiveView — 20 specialist agents, Iron Laws enforcement, and Tidewave MCP integration. Plan features with parallel research agents, execute with automatic verifica
16. **xbtlin/ai-berkshire** (13407 estrellas) — https://github.com/xbtlin/ai-berkshire
  Python
  AI 时代的伯克希尔：基于 Claude Code / Codex 的价值投资研究框架。巴菲特·芒格·段永平·李录四大师方法论 + 多Agent并行研究。| AI-era Berkshire: a value investing research framework built for Claude Code / Codex. 4 masters' methodologies + multi-ag
17. **wquguru/harness-books** (2681 estrellas) — https://github.com/wquguru/harness-books
  Python
  📚 Two books on harness engineering — the design philosophies behind Claude Code & Codex: constraints, query loops, context governance, multi-agent verification. harness-books.agentway.dev
18. **LoRexxar/Kunlun-M** (2402 estrellas) — https://github.com/LoRexxar/Kunlun-M
  Python
  KunLun-M — Open-source static code analysis for PHP, Nodejs/JavaScript, Python, Golang, Java and C/C++, with AST-based semantic scanning and one-click AI Agent integration (OpenClaw, Codex, Claude Cod
19. **larlarua/AutoCVE** (1285 estrellas) — https://github.com/larlarua/AutoCVE
  Python
  Agent-driven automated CVE discovery platform for source code auditing, vulnerability verification, and report generation.

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **The Limitations of Stylometry for Detecting Machine-Generated Fake News** — https://arxiv.org/abs/1908.09805v2
  contra: codeburn
  Recent developments in neural language models (LMs) have raised concerns about their potential misuse for automatically spreading misinformation. In light of these concerns, several studies have propo
2. **Transformers: "The End of History" for NLP?** — https://arxiv.org/abs/2105.00813v2
  contra: codeburn
  Recent advances in neural architectures, such as the Transformer, coupled with the emergence of large-scale pre-trained models such as BERT, have revolutionized the field of Natural Language Processin
3. **Enhancing Heterogeneous Multi-Agent Cooperation in Decentralized MARL via GNN-driven Intrinsic Rewards** — https://arxiv.org/abs/2408.06503v4
  contra: agents-md
  Multi-agent Reinforcement Learning (MARL) is emerging as a key framework for various sequential decision-making and control tasks. Unlike their single-agent counterparts, multi-agent systems necessita
4. **TimeWarp: Evaluating Web Agents by Revisiting the Past** — https://arxiv.org/abs/2603.04949v1
  contra: agents-md
  The improvement of web agents on current benchmarks raises the question: Do today's agents perform just as well when the web changes? We introduce TimeWarp, a benchmark that emulates the evolving web 
