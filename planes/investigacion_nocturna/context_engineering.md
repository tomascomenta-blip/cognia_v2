# Investigacion: context engineering y gestion de ventana de contexto en agentes de coding

Queries ejecutadas (5): `context engineering agent`, `awesome context management agents`, `window context agent`, `coding agent alternatives`, `context handling agent`

## Resumen

Los resultados proporcionados muestran varios proyectos y modelos relacionados con la ingeniería de contexto y la gestión de la ventana de contexto en agentes de codificación. Entre ellos, `mksglu/context-mode` es un repositorio TypeScript que optimiza la ventana de contexto para agentes de codificación AI, reduciendo el uso de memoria de sesión y controlando el enrutamiento a través de 17 plataformas. Otro proyecto relevante es `vstorm-co/summarization-pydantic-ai`, que proporciona un procesador de gestión de contexto para agentes AI basados en Pydantic, con resumen impulsado por LLM o corte de ventana deslizante para manejar conversaciones largas sin desbordamiento de contexto.

Además, el artículo de investigación "LoCoBench-Agent: An Interactive Benchmark for LLM Agents in Long-Context Software Engineering" presenta un marco interactivo para evaluar la capacidad de los agentes de LLM en tareas de ingeniería de software con contexto largo. Otro artículo, "Scaling External Knowledge Input Beyond Context Windows of LLMs via Multi-Agent Collaboration", propone un enfoque de colaboración multi-agente para superar las limitaciones del contexto de los LLMs.

Estos proyectos y modelos son relevantes porque abordan directamente la optimización y gestión de la ventana de contexto en agentes de codificación AI, proporcionando soluciones y marcos para mejorar la eficiencia y la capacidad de estos agentes en tareas de codificación.

## Modelos (HuggingFace)

1. **alaatiger989/Self-improving_AI_agents-Agentic_Context_Engineering** (0 descargas) — https://huggingface.co/alaatiger989/Self-improving_AI_agents-Agentic_Context_Engineering
2. **contextboxai/Kokoro-Vietnamese** (21922 descargas) — https://huggingface.co/contextboxai/Kokoro-Vietnamese
  onnx, kokoro, vietnamese, text-to-speech, vi
3. **facebook/dragon-plus-context-encoder** (20464 descargas) — https://huggingface.co/facebook/dragon-plus-context-encoder
  BertForMaskedLM, 12 capas | ctx 512 | KV 36864 B/tok (4.50 GB @128k)
  transformers, pytorch, bert, fill-mask, feature-extraction, endpoints_compatible, deploy:azure
4. **perplexity-ai/pplx-embed-context-v1-0.6b** (7452 descargas) — https://huggingface.co/perplexity-ai/pplx-embed-context-v1-0.6b
  PPLXQwen3Model, GQA 16:8, 28 capas | ctx 32768 | KV 114688 B/tok (14.00 GB @128k)
  transformers, onnx, safetensors, bidirectional_pplx_qwen3, feature-extraction, sentence-similarity, conteb, contextual-embeddings, custom_code, multilingual
5. **nvidia/gpt-oss-120b-Eagle3-long-context** (7357 descargas) — https://huggingface.co/nvidia/gpt-oss-120b-Eagle3-long-context
  LlamaForCausalLMEagle3, GQA 64:8, 1 capas | ctx 131072 | KV 2048 B/tok (0.25 GB @128k)
  Model Optimizer, safetensors, llama, nvidia, ModelOpt, gpt-oss-120b, quantized, Eagle3, text-generation

## Evidencia (arXiv)

1. **LoCoBench-Agent: An Interactive Benchmark for LLM Agents in Long-Context Software Engineering** — https://arxiv.org/abs/2511.13998v1
  2025 | cs.SE
  As large language models (LLMs) evolve into sophisticated autonomous agents capable of complex software development tasks, evaluating their real-world capabilities becomes critical. While existing ben
2. **Beyond Turn Limits: Training Deep Search Agents with Dynamic Context Window** — https://arxiv.org/abs/2510.08276v1
  2025 | cs.CL
  While recent advances in reasoning models have demonstrated cognitive behaviors through reinforcement learning, existing approaches struggle to invoke deep reasoning capabilities in multi-turn agents 
3. **Scaling External Knowledge Input Beyond Context Windows of LLMs via Multi-Agent Collaboration** — https://arxiv.org/abs/2505.21471v2
  2025 | cs.CL
  With the rapid advancement of post-training techniques for reasoning and information seeking, large language models (LLMs) can incorporate a large quantity of retrieved knowledge to solve complex task
4. **Reasoner-Executor-Synthesizer: Scalable Agentic Architecture with Static O(1) Context Window** — https://arxiv.org/abs/2603.22367v1
  2026 | cs.IR
  Large Language Models (LLMs) deployed as autonomous agents commonly use Retrieval-Augmented Generation (RAG), feeding retrieved documents into the context window, which creates two problems: the risk 
5. **MemoryCD: Benchmarking Long-Context User Memory of LLM Agents for Lifelong Cross-Domain Personalization** — https://arxiv.org/abs/2603.25973v1
  2026 | cs.CL
  Recent advancements in Large Language Models (LLMs) have expanded context windows to million-token scales, yet benchmarks for evaluating memory remain limited to short-session synthetic dialogues. We 
6. **Position: Coding Benchmarks Are Misaligned with Agentic Software Engineering** — https://arxiv.org/abs/2606.17799v1
  2026 | cs.SE
  Coding agents have become a major mode of software engineering, but the benchmarks we use to compare them were designed in a pre-agent era: they collapse model, harness, and environment into a single 
7. **Lore: Repurposing Git Commit Messages as a Structured Knowledge Protocol for AI Coding Agents** — https://arxiv.org/abs/2603.15566v1
  2026 | cs.SE
  As AI coding agents become both primary producers and consumers of source code, the software industry faces an accelerating loss of institutional knowledge. Each commit captures a code diff but discar
8. **Agent Context Protocols Enhance Collective Inference** — https://arxiv.org/abs/2505.14569v1
  2025 | cs.AI
  AI agents have become increasingly adept at complex tasks such as coding, reasoning, and multimodal understanding. However, building generalist systems requires moving beyond individual agents to coll
9. **Context Engineering for Multi-Agent LLM Code Assistants Using Elicit, NotebookLM, ChatGPT, and Claude Code** — https://arxiv.org/abs/2508.08322v1
  2025 | cs.SE
  Large Language Models (LLMs) have shown promise in automating code generation and software engineering tasks, yet they often struggle with complex, multi-file projects due to context limitations and k
10. **SWEnergy: An Empirical Study on Energy Efficiency in Agentic Issue Resolution Frameworks with SLMs** — https://arxiv.org/abs/2512.09543v2
  2025 | cs.SE
  Context. LLM-based autonomous agents in software engineering rely on large, proprietary models, limiting local deployment. This has spurred interest in Small Language Models (SLMs), but their practica
11. **Leveraging LLM Agents and Digital Twins for Fault Handling in Process Plants** — https://arxiv.org/abs/2505.02076v1
  2025 | cs.AI
  Advances in Automation and Artificial Intelligence continue to enhance the autonomy of process plants in handling various operational scenarios. However, certain tasks, such as fault handling, remain 
12. **SWE-AGILE: A Software Agent Framework for Efficiently Managing Dynamic Reasoning Context** — https://arxiv.org/abs/2604.11716v1
  2026 | cs.AI
  Prior representative ReAct-style approaches in autonomous Software Engineering (SWE) typically lack the explicit System-2 reasoning required for deep analysis and handling complex edge cases. While re
13. **Meta Context Engineering via Agentic Skill Evolution** — https://arxiv.org/abs/2601.21557v2
  2026 | cs.AI
  The operational efficacy of large language models relies heavily on their inference-time context. This has established Context Engineering (CE) as a formal discipline for optimizing these inputs. Curr
14. **A Survey on Large Language Model Acceleration based on KV Cache Management** — https://arxiv.org/abs/2412.19442v3
  2024 | cs.AI
  Large Language Models (LLMs) have revolutionized a wide range of domains such as natural language processing, computer vision, and multi-modal tasks due to their ability to comprehend context and perf
15. **Can language agents be alternatives to PPO? A Preliminary Empirical Study On OpenAI Gym** — https://arxiv.org/abs/2312.03290v1
  2023 | cs.AI
  The formidable capacity for zero- or few-shot decision-making in language agents encourages us to pose a compelling question: Can language agents be alternatives to PPO agents in traditional sequentia
16. **Interpretable Context Methodology: Folder Structure as Agentic Architecture** — https://arxiv.org/abs/2603.16021v2
  2026 | cs.AI
  Current approaches to AI agent orchestration typically involve building multi-agent frameworks that manage context passing, memory, error handling, and step coordination through code. These frameworks

## Codigo (GitHub)

1. **mksglu/context-mode** (19108 estrellas) — https://github.com/mksglu/context-mode
  TypeScript
  Context window optimization for AI coding agents. Sandboxes tool output (98% reduction), persists session memory, and   enforces routing across 17 platforms via MCP + hooks.
2. **graykode/abtop** (3363 estrellas) — https://github.com/graykode/abtop
  Rust
  Like htop, but for AI coding agents. Monitor Claude    Code & Codex CLI sessions, tokens, context window,    rate limits, and ports in real-time.
3. **mgechev/skills-best-practices** (2126 estrellas) — https://github.com/mgechev/skills-best-practices
  Python
  Write professional-grade skills for agents, validate them using LLMs, and maintain a lean context window.
4. **giraffe-tree/agent-base** (100 estrellas) — https://github.com/giraffe-tree/agent-base
  HTML
  Agent Base is a source-level research project on coding agents. It compares Codex CLI, OpenCode, Gemini CLI, Kimi CLI, and SWE-agent across agent loops, tools, MCP integration, context/memory handling
5. **vstorm-co/summarization-pydantic-ai** (67 estrellas) — https://github.com/vstorm-co/summarization-pydantic-ai
  Python
  Context Management processor for Pydantic AI agents, providing LLM-powered summarization or zero-cost sliding window trimming to handle infinite/long-running conversations without context overflow. Su
6. **dair-ai/Prompt-Engineering-Guide** (76754 estrellas) — https://github.com/dair-ai/Prompt-Engineering-Guide
  MDX
  🐙 Guides, papers, lessons, notebooks and resources for prompt engineering, context engineering, RAG, and AI Agents.
7. **gsd-build/gsd-2** (7752 estrellas) — https://github.com/gsd-build/gsd-2
  TypeScript
  A powerful meta-prompting, context engineering and spec-driven development system that enables agents to work for long periods of time autonomously without losing track of the big picture
8. **parcadei/Continuous-Claude-v3** (3870 estrellas) — https://github.com/parcadei/Continuous-Claude-v3
  Python
  Context management for Claude Code. Hooks maintain state via ledgers and handoffs. MCP execution without context pollution. Agent orchestration with isolated context windows.
9. **HyeokjaeLee/opencode-auto-fallback** (6 estrellas) — https://github.com/HyeokjaeLee/opencode-auto-fallback
  TypeScript
  ⚙️ Advanced fallback plugin for OpenCode agents — model switching, retry with backoff, and context overflow handling
10. **nexu-io/open-design** (79798 estrellas) — https://github.com/nexu-io/open-design
  TypeScript
  🎨 The open-source Claude Design alternative. 🖥️ Local-first desktop app. 🖼️ Your coding agent becomes the design engine: prototypes, landing pages, dashboards, slides, images & video — real files, HTM
11. **muratcankoylan/Agent-Skills-for-Context-Engineering** (17348 estrellas) — https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering
  Python
  A comprehensive collection of Agent Skills for context engineering, multi-agent architectures, and production agent systems. Use when building, optimizing, or debugging agent systems that require effe
12. **volcengine/MineContext** (5433 estrellas) — https://github.com/volcengine/MineContext
  Python
  MineContext is your proactive context-aware AI partner（Context-Engineering+ChatGPT Pulse）
13. **rivet-dev/agentos** (3943 estrellas) — https://github.com/rivet-dev/agentos
  Rust
  A faster, lighter, cheaper alternative to sandboxes. Run any coding agent inside an isolated Linux VM, with agent orchestration built in.
14. **krohling/bondai** (221 estrellas) — https://github.com/krohling/bondai
  Python
  BondAI is an open-source tool for developing AI Agent Systems. BondAI handles the implementation complexities including memory/context management, error handling, vector/semantic search and includes a
15. **aptratcn/awesome-agent-cost-optimization** (0 estrellas) — https://github.com/aptratcn/awesome-agent-cost-optimization
  🪙 Curated collection of tools and skills to reduce AI Agent API costs. Token optimization, model routing, context management.

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **Categorical Prior Lock-in: Why In-Context Learning Fails for Structured Data** — https://arxiv.org/abs/2606.11961v1
  contra: context-mode
  Large language models (LLMs) are increasingly used as conditional generators for structured data, relying on in-context learning (ICL) to adapt to new distributions without parameter updates. We inves
2. **Lost in the Maze: Overcoming Context Limitations in Long-Horizon Agentic Search** — https://arxiv.org/abs/2510.18939v2
  contra: context-mode
  Long-horizon agentic search requires iteratively exploring the web over long trajectories and synthesizing information across many sources, enabling powerful applications like deep research systems. I
3. **The Limitations of Stylometry for Detecting Machine-Generated Fake News** — https://arxiv.org/abs/1908.09805v2
  contra: abtop
  Recent developments in neural language models (LMs) have raised concerns about their potential misuse for automatically spreading misinformation. In light of these concerns, several studies have propo
4. **Transformers: "The End of History" for NLP?** — https://arxiv.org/abs/2105.00813v2
  contra: abtop
  Recent advances in neural architectures, such as the Transformer, coupled with the emergence of large-scale pre-trained models such as BERT, have revolutionized the field of Natural Language Processin
