# Investigacion: como los agentes de coding manejan memoria y contexto de repositorio

Queries ejecutadas (5): `agent memory management`, `agent context handling`, `repo context agent`, `awesome coding agents`, `memory context agent`

## Resumen

Los agentes de codificación manejan memoria y contexto de repositorio de diversas maneras, dependiendo del modelo o herramienta utilizada. Por ejemplo, el repositorio **mksglu/context-mode** optimiza la ventana de contexto para agentes de IA de codificación, reduciendo en un 98% el tamaño de la memoria de la sandbox y persistiendo la memoria de la sesión. Otro ejemplo es **volcengine/OpenViking**, que proporciona una base de datos de contexto autoevolutiva para agentes de IA, unificando la memoria del agente, el conocimiento RAG y las habilidades. Además, **deepset-ai/haystack** es un marco de orquestación de IA de código abierto que permite el diseño de pipelines y flujos de trabajo de agentes con control explícito sobre la recuperación, el enrutamiento, la memoria y la generación. Estos modelos y repositorios demuestran diversas estrategias para manejar la memoria y el contexto en el entorno de codificación de IA.

## Modelos (HuggingFace)

1. **omnaathg/contextvla_card_memory_v3** (4 descargas) — https://huggingface.co/omnaathg/contextvla_card_memory_v3
  safetensors
2. **omnaathg/contextvla_card_memory** (2 descargas) — https://huggingface.co/omnaathg/contextvla_card_memory
  safetensors
3. **omnaathg/contextvla_card_memory_v2** (2 descargas) — https://huggingface.co/omnaathg/contextvla_card_memory_v2
  safetensors
4. **espiusedwards/In_Context_Memory_Augmented** (0 descargas) — https://huggingface.co/espiusedwards/In_Context_Memory_Augmented
5. **agentmish/pplx-embed-context-v1-4b-mlx** (22 descargas) — https://huggingface.co/agentmish/pplx-embed-context-v1-4b-mlx
  PPLXQwen3Model, GQA 32:8, 36 capas | ctx 32768 | KV 147456 B/tok (18.00 GB @128k)
  mlx, safetensors, bidirectional_pplx_qwen3, apple-silicon, feature-extraction, sentence-similarity, contextual-embeddings, perplexity, qwen3, custom_code
6. **agentmish/pplx-embed-context-v1-0.6b-mlx** (19 descargas) — https://huggingface.co/agentmish/pplx-embed-context-v1-0.6b-mlx
  PPLXQwen3Model, GQA 16:8, 28 capas | ctx 32768 | KV 114688 B/tok (14.00 GB @128k)
  mlx, safetensors, bidirectional_pplx_qwen3, apple-silicon, feature-extraction, sentence-similarity, contextual-embeddings, perplexity, qwen3, custom_code
7. **xupy21/ContextRL_Qwen3_8B_Agentic** (5 descargas) — https://huggingface.co/xupy21/ContextRL_Qwen3_8B_Agentic
  Qwen3ForCausalLM, GQA 32:8, 36 capas | ctx 40960 | KV 147456 B/tok (18.00 GB @128k)
  transformers, safetensors, qwen3, text-generation, agentic, code, software-engineering, reinforcement-learning, grpo, context-aware
8. **xupy21/ContextRL_Klear_AgentForge_8B** (4 descargas) — https://huggingface.co/xupy21/ContextRL_Klear_AgentForge_8B
  Qwen3ForCausalLM, GQA 32:8, 36 capas | ctx 65536 | KV 147456 B/tok (18.00 GB @128k)
  transformers, safetensors, qwen3, text-generation, agentic, code, software-engineering, reinforcement-learning, grpo, context-aware
9. **coding-gen/my_awesome_opus_books_model** (1 descargas) — https://huggingface.co/coding-gen/my_awesome_opus_books_model
  T5ForConditionalGeneration | ctx 512
  transformers, pytorch, tensorboard, t5, text2text-generation, text-generation-inference, endpoints_compatible
10. **coding-gen/my_awesome_model** (0 descargas) — https://huggingface.co/coding-gen/my_awesome_model

## Evidencia (arXiv)

1. **Agent Memory Below the Prompt: Persistent Q4 KV Cache for Multi-Agent LLM Inference on Edge Devices** — https://arxiv.org/abs/2603.04428v1
  2026 | cs.LG
  Multi-agent LLM systems on edge devices face a memory management problem: device RAM is too small to hold every agent's KV cache simultaneously. On Apple M4 Pro with 10.2 GB of cache budget, only 3 ag
2. **Agentic Memory: Learning Unified Long-Term and Short-Term Memory Management for Large Language Model Agents** — https://arxiv.org/abs/2601.01885v2
  2026 | cs.CL
  Large language model (LLM) agents face fundamental limitations in long-horizon reasoning due to finite context windows, making effective memory management critical. Existing methods typically handle l
3. **Leveraging LLM Agents and Digital Twins for Fault Handling in Process Plants** — https://arxiv.org/abs/2505.02076v1
  2025 | cs.AI
  Advances in Automation and Artificial Intelligence continue to enhance the autonomy of process plants in handling various operational scenarios. However, certain tasks, such as fault handling, remain 
4. **Agent Context Protocols Enhance Collective Inference** — https://arxiv.org/abs/2505.14569v1
  2025 | cs.AI
  AI agents have become increasingly adept at complex tasks such as coding, reasoning, and multimodal understanding. However, building generalist systems requires moving beyond individual agents to coll
5. **Contract-Coding: Towards Repo-Level Generation via Structured Symbolic Paradigm** — https://arxiv.org/abs/2604.13100v1
  2026 | cs.SE
  The shift toward intent-driven software engineering (often termed "Vibe Coding") exposes a critical Context-Fidelity Trade-off: vague user intents overwhelm linear reasoning chains, leading to archite
6. **Less Context, More Accuracy: A Bi-Temporal Memory Engine for LLM Agents Where a Lean Retrieved Context Beats the Full History** — https://arxiv.org/abs/2606.09900v1
  2026 | cs.CL
  Long-term memory is the missing layer for LLM agents: across sessions they forget, and the common workaround -- replaying the whole history into the prompt -- is expensive, slow, and, as distractors a
7. **Agent Skills for Large Language Models: Architecture, Acquisition, Security, and the Path Forward** — https://arxiv.org/abs/2602.12430v4
  2026 | cs.MA
  The transition from monolithic language models to modular, skill-equipped agents marks a defining shift in how large language models (LLMs) are deployed in practice. Rather than encoding all procedura
8. **MemoryCD: Benchmarking Long-Context User Memory of LLM Agents for Lifelong Cross-Domain Personalization** — https://arxiv.org/abs/2603.25973v1
  2026 | cs.CL
  Recent advancements in Large Language Models (LLMs) have expanded context windows to million-token scales, yet benchmarks for evaluating memory remain limited to short-session synthetic dialogues. We 
9. **HELPER-X: A Unified Instructable Embodied Agent to Tackle Four Interactive Vision-Language Domains with Memory-Augmented Language Models** — https://arxiv.org/abs/2404.19065v1
  2024 | cs.AI
  Recent research on instructable agents has used memory-augmented Large Language Models (LLMs) as task planners, a technique that retrieves language-program examples relevant to the input instruction a
10. **Are We Ready For An Agent-Native Memory System?** — https://arxiv.org/abs/2606.24775v1
  2026 | cs.CL
  Memory for large language model (LLM) agents has rapidly evolved from simple retrieval-augmented mechanisms into a data management system that supports persistent information storage, retrieval, updat
11. **Memory Management in Resource-Bounded Agents** — https://arxiv.org/abs/1909.09454v1
  2019 | cs.AI
  In artificial intelligence, multi agent systems constitute an interesting typology of society modeling, and have in this regard vast fields of application, which extend to the human sciences. Logic is
12. **Interpretable Context Methodology: Folder Structure as Agentic Architecture** — https://arxiv.org/abs/2603.16021v2
  2026 | cs.AI
  Current approaches to AI agent orchestration typically involve building multi-agent frameworks that manage context passing, memory, error handling, and step coordination through code. These frameworks
13. **LLM Agents Improve Semantic Code Search** — https://arxiv.org/abs/2408.11058v1
  2024 | cs.SE
  Code Search is a key task that many programmers often have to perform while developing solutions to problems. Current methodologies suffer from an inability to perform accurately on prompts that conta
14. **Advances and Frontiers of LLM-based Issue Resolution in Software Engineering: A Comprehensive Survey** — https://arxiv.org/abs/2601.11655v1
  2026 | cs.SE
  Issue resolution, a complex Software Engineering (SWE) task integral to real-world development, has emerged as a compelling challenge for artificial intelligence. The establishment of benchmarks like 
15. **AI for Auto-Research: Roadmap & User Guide** — https://arxiv.org/abs/2605.18661v1
  2026 | cs.AI
  AI-assisted research is crossing a threshold: fully automated systems can now generate research papers for as little as $15, while long-horizon agents can execute experiments, draft manuscripts, and s
16. **Governed Memory: A Production Architecture for Multi-Agent Workflows** — https://arxiv.org/abs/2603.17787v1
  2026 | cs.AI
  Enterprise AI deploys dozens of autonomous agent nodes across workflows, each acting on the same entities with no shared memory and no common governance. We identify five structural challenges arising
17. **SWE-AGILE: A Software Agent Framework for Efficiently Managing Dynamic Reasoning Context** — https://arxiv.org/abs/2604.11716v1
  2026 | cs.AI
  Prior representative ReAct-style approaches in autonomous Software Engineering (SWE) typically lack the explicit System-2 reasoning required for deep analysis and handling complex edge cases. While re
18. **ESC-Eval: Evaluating Emotion Support Conversations in Large Language Models** — https://arxiv.org/abs/2406.14952v3
  2024 | cs.CL
  Emotion Support Conversation (ESC) is a crucial application, which aims to reduce human stress, offer emotional guidance, and ultimately enhance human mental and physical well-being. With the advancem

## Codigo (GitHub)

1. **mksglu/context-mode** (19107 estrellas) — https://github.com/mksglu/context-mode
  TypeScript
  Context window optimization for AI coding agents. Sandboxes tool output (98% reduction), persists session memory, and   enforces routing across 17 platforms via MCP + hooks.
2. **giraffe-tree/agent-base** (100 estrellas) — https://github.com/giraffe-tree/agent-base
  HTML
  Agent Base is a source-level research project on coding agents. It compares Codex CLI, OpenCode, Gemini CLI, Kimi CLI, and SWE-agent across agent loops, tools, MCP integration, context/memory handling
3. **volcengine/OpenViking** (26974 estrellas) — https://github.com/volcengine/OpenViking
  Python
  Self-evolving Context Database for AI Agents. Unify Agent Memory, Knowledge RAG and Skills.
4. **deepset-ai/haystack** (25949 estrellas) — https://github.com/deepset-ai/haystack
  MDX
  Open-source AI orchestration framework for building context-engineered, production-ready LLM applications. Design modular pipelines and agent workflows with explicit control over retrieval, routing, m
5. **repowise-dev/claude-code-prompts** (1166 estrellas) — https://github.com/repowise-dev/claude-code-prompts
  Independently authored prompt templates for AI coding agents — system prompts, tool prompts, agent delegation, memory management, and multi-agent coordination. Informed by studying Claude Code.
6. **repoprompt/repoprompt-ce** (818 estrellas) — https://github.com/repoprompt/repoprompt-ce
  Swift
  Community edition of RepoPrompt: a native macOS context engineering app for AI coding agents, with an MCP CLI.
7. **gmickel/flow-next** (662 estrellas) — https://github.com/gmickel/flow-next
  Python
  Repeatable agentic engineering. The workflow layer that turns AI coding agents into a disciplined factory: durable specs, fresh-context workers, adversarial cross-model reviews, receipts. Everything i
8. **0xranx/OpenContext** (660 estrellas) — https://github.com/0xranx/OpenContext
  JavaScript
  A personal context store for AI agents and assistants—reuse your existing coding agent CLI (Codex/Claude/OpenCode) with built‑in Skills/tools and a desktop GUI to capture, search, and reuse project kn
9. **YurunChen/repo-docs-skills** (400 estrellas) — https://github.com/YurunChen/repo-docs-skills
  Python
  Living project docs for coding agents: keep guides, progress logs, change maps, and handoff context updated as your repo evolves.
10. **VoltAgent/awesome-design-md** (103205 estrellas) — https://github.com/VoltAgent/awesome-design-md
  A collection of DESIGN.md files analysis by popular brand design systems. Drop one into your project and let coding agents generate a matching UI.
11. **hesreallyhim/awesome-claude-code** (50444 estrellas) — https://github.com/hesreallyhim/awesome-claude-code
  Python
  A hand-picked collection of the finest of resources for the most awesome of agents, Claude Code, the undisputed champion of coding companions, from the unstoppable team at Anthropic PBC. A delectable 
12. **memvid/memvid** (16008 estrellas) — https://github.com/memvid/memvid
  Rust
  Memory layer for AI Agents. Replace complex RAG pipelines with a serverless, single-file memory layer. Give your agents instant retrieval and long-term memory.
13. **MemMachine/MemMachine** (3332 estrellas) — https://github.com/MemMachine/MemMachine
  Python
  Universal memory layer for AI Agents. It provides scalable, extensible, and interoperable memory storage and retrieval to streamline AI agent state management for next-generation autonomous systems.
14. **agentscope-ai/ReMe** (3202 estrellas) — https://github.com/agentscope-ai/ReMe
  Python
  ReMe: Memory Management Kit for Agents - Remember Me, Refine Me.
15. **study8677/awesome-architecture** (1875 estrellas) — https://github.com/study8677/awesome-architecture
  Vue
  🧭 Architecture-first system design: 26 bilingual tutorials, 25 architecture templates, and 6 end-to-end cases covering distributed systems, AI-native systems, RAG, coding Agents, and production trade-
16. **krohling/bondai** (221 estrellas) — https://github.com/krohling/bondai
  Python
  BondAI is an open-source tool for developing AI Agent Systems. BondAI handles the implementation complexities including memory/context management, error handling, vector/semantic search and includes a
17. **vstorm-co/summarization-pydantic-ai** (67 estrellas) — https://github.com/vstorm-co/summarization-pydantic-ai
  Python
  Context Management processor for Pydantic AI agents, providing LLM-powered summarization or zero-cost sliding window trimming to handle infinite/long-running conversations without context overflow. Su
18. **HyeokjaeLee/opencode-auto-fallback** (6 estrellas) — https://github.com/HyeokjaeLee/opencode-auto-fallback
  TypeScript
  ⚙️ Advanced fallback plugin for OpenCode agents — model switching, retry with backoff, and context overflow handling
19. **Josh-XT/AGiXT** (3204 estrellas) — https://github.com/Josh-XT/AGiXT
  Python
  AGiXT is a dynamic AI Agent Automation Platform that seamlessly orchestrates instruction management and complex task execution across diverse AI providers. Combining adaptive memory, smart features, a
20. **wesammustafa/Claude-Code-Everything-You-Need-to-Know** (2341 estrellas) — https://github.com/wesammustafa/Claude-Code-Everything-You-Need-to-Know
  Python
  A practical Claude Code guide with clear mental models and copy-paste examples — setup, prompt engineering, slash commands, skills, hooks, subagents, agent teams, and MCP servers. Beginner path to pow

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **Categorical Prior Lock-in: Why In-Context Learning Fails for Structured Data** — https://arxiv.org/abs/2606.11961v1
  contra: context-mode
  Large language models (LLMs) are increasingly used as conditional generators for structured data, relying on in-context learning (ICL) to adapt to new distributions without parameter updates. We inves
2. **Lost in the Maze: Overcoming Context Limitations in Long-Horizon Agentic Search** — https://arxiv.org/abs/2510.18939v2
  contra: context-mode
  Long-horizon agentic search requires iteratively exploring the web over long trajectories and synthesizing information across many sources, enabling powerful applications like deep research systems. I
3. **Foundation-Model-Based Agents in Industrial Automation: Purposes, Capabilities, and Open Challenges** — https://arxiv.org/abs/2605.02592v1
  contra: agent-base
  Foundation models, particularly large language models, are increasingly integrated into agent architectures for industrial tasks such as decision support, process monitoring, and engineering automatio
4. **LLM-Based Human-Agent Collaboration and Interaction Systems: A Survey** — https://arxiv.org/abs/2505.00753v5
  contra: agent-base
  Recent advances in large language models (LLMs) have sparked growing interest in building fully autonomous agents. However, fully autonomous LLM-based agents still face significant challenges, includi
5. **The Limitations of Stylometry for Detecting Machine-Generated Fake News** — https://arxiv.org/abs/1908.09805v2
  contra: OpenViking
  Recent developments in neural language models (LMs) have raised concerns about their potential misuse for automatically spreading misinformation. In light of these concerns, several studies have propo
6. **Transformers: "The End of History" for NLP?** — https://arxiv.org/abs/2105.00813v2
  contra: OpenViking
  Recent advances in neural architectures, such as the Transformer, coupled with the emergence of large-scale pre-trained models such as BERT, have revolutionized the field of Natural Language Processin
