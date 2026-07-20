# Investigacion: skills y herramientas que usan los agentes de coding autonomos

Queries ejecutadas (5): `awesome coding agents`, `autonomous agent tools`, `coding agent libraries`, `coding agent frameworks`, `skills tools`

## Resumen

Los agentes de coding autónomos utilizan una variedad de habilidades y herramientas para mejorar su eficiencia y funcionalidad. Los repositorios más relevantes incluyen `hesreallyhim/awesome-claude-code` y `calesthio/OpenMontage`, que ofrecen colecciones de recursos y herramientas específicas para agentes de coding como Claude Code. Además, `google-labs-code/stitch-skills` proporciona una biblioteca de habilidades de agente diseñada para trabajar con servidores MCP, y `ref-tools/ref-tools-mcp` ayuda a los agentes de coding a evitar errores al trabajar con bibliotecas públicas o privadas. Los trabajos académicos como `SkillSmith` y `Dynamo` exploran la evolución dinámica de habilidades y herramientas para agentes autónomos, mejorando su capacidad para adaptarse y reparar errores.

## Modelos (HuggingFace)

1. **man-with-skills/gap-analysis-qwen3-merged** (1668 descargas) — https://huggingface.co/man-with-skills/gap-analysis-qwen3-merged
  Qwen3ForCausalLM, GQA 64:8, 64 capas | ctx 40960 | KV 262144 B/tok (32.00 GB @128k)
  transformers, safetensors, qwen3, text-generation, text-generation-inference, unsloth, conversational, en, endpoints_compatible
2. **AROY76/Embedding-gemma-300M-skills** (1009 descargas) — https://huggingface.co/AROY76/Embedding-gemma-300M-skills
  Gemma3TextModel, MQA, ventana deslizante 257, 24 capas | ctx 2048 | KV 24576 B/tok (3.00 GB @128k)
  sentence-transformers, safetensors, gemma3_text, sentence-similarity, feature-extraction, dense, generated_from_trainer, dataset_size:4992, loss:MultipleNegativesRankingLoss, text-embeddings-inference
3. **algiraldohe/lm-ner-linkedin-skills-recognition** (745 descargas) — https://huggingface.co/algiraldohe/lm-ner-linkedin-skills-recognition
  DistilBertForTokenClassification | ctx 512
  transformers, pytorch, tensorboard, distilbert, token-classification, generated_from_trainer, endpoints_compatible
4. **MB20261/job-skills_unsloth-tinyllama-bnb-4bit_v1_8k_gguf** (195 descargas) — https://huggingface.co/MB20261/job-skills_unsloth-tinyllama-bnb-4bit_v1_8k_gguf
  GGUF
  gguf, llama, endpoints_compatible
5. **coding-gen/my_awesome_opus_books_model** (1 descargas) — https://huggingface.co/coding-gen/my_awesome_opus_books_model
  T5ForConditionalGeneration | ctx 512
  transformers, pytorch, tensorboard, t5, text2text-generation, text-generation-inference, endpoints_compatible
6. **coding-gen/my_awesome_model** (0 descargas) — https://huggingface.co/coding-gen/my_awesome_model
7. **CREATUS/AutonomousAgents** (0 descargas) — https://huggingface.co/CREATUS/AutonomousAgents

## Evidencia (arXiv)

1. **SkillSmith: Co-Evolving Skills and Tools for Self-Improving Agent Systems** — https://arxiv.org/abs/2606.01314v1
  2026 | cs.AI
  Recent self-evolving agents have shown that skills can be discovered, refined, and accumulated through execution. However, existing skill-evolution frameworks typically assume a fixed tool layer and e
2. **Dynamo: Dynamic Skill-Tool Evolution for Vision-Language Agents** — https://arxiv.org/abs/2606.30185v1
  2026 | cs.AI
  Improving vision-language models (VLMs) on visual reasoning typically requires retraining or hand-designed prompts and tools. We present Dynamo, a training-free framework that adapts a frozen VLM with
3. **Advances and Frontiers of LLM-based Issue Resolution in Software Engineering: A Comprehensive Survey** — https://arxiv.org/abs/2601.11655v1
  2026 | cs.SE
  Issue resolution, a complex Software Engineering (SWE) task integral to real-world development, has emerged as a compelling challenge for artificial intelligence. The establishment of benchmarks like 
4. **AI for Auto-Research: Roadmap & User Guide** — https://arxiv.org/abs/2605.18661v1
  2026 | cs.AI
  AI-assisted research is crossing a threshold: fully automated systems can now generate research papers for as little as $15, while long-horizon agents can execute experiments, draft manuscripts, and s
5. **When Lower Privileges Suffice: Investigating Over-Privileged Tool Selection in LLM Agents** — https://arxiv.org/abs/2606.20023v2
  2026 | cs.SE
  As LLM agents increasingly select tools autonomously, their choices among tools with different privileges become safety-relevant. However, prior tool-selection studies focus on safety-agnostic metadat
6. **MCP-Zero: Active Tool Discovery for Autonomous LLM Agents** — https://arxiv.org/abs/2506.01056v4
  2025 | cs.AI
  True intelligence requires active capability acquisition, yet current LLM agents inject pre-defined tool schemas into prompts, reducing models to passive selectors and falling short of robust general-
7. **Beyond Static Sandboxing: Learned Capability Governance for Autonomous AI Agents** — https://arxiv.org/abs/2604.11839v2
  2026 | cs.CR
  Autonomous AI agents built on open-source runtimes such as OpenClaw expose every available tool to every session by default, regardless of the task. A summarization task receives the same shell execut
8. **CodeDistiller: Automatically Generating Code Libraries for Scientific Coding Agents** — https://arxiv.org/abs/2512.01089v2
  2025 | cs.AI
  Automated Scientific Discovery (ASD) systems can help automatically generate and run code-based experiments, but their capabilities are limited by the code they can reliably generate from parametric k
9. **pyhgf: A neural network library for predictive coding** — https://arxiv.org/abs/2410.09206v2
  2024 | cs.NE
  Bayesian models of cognition have gained considerable traction in computational neuroscience and psychiatry. Their scopes are now expected to expand rapidly to artificial intelligence, providing gener
10. **Act-Observe-Rewrite: Multimodal Coding Agents as In-Context Policy Learners for Robot Manipulation** — https://arxiv.org/abs/2603.04466v1
  2026 | cs.RO
  Can a multimodal language model learn to manipulate physical objects by reasoning about its own failures-without gradient updates, demonstrations, or reward engineering? We argue the answer is yes, un
11. **SciNav: A General Agent Framework for Scientific Coding Tasks** — https://arxiv.org/abs/2603.20256v1
  2026 | cs.CL
  Autonomous science agents built on large language models (LLMs) are increasingly used to generate hypotheses, design experiments, and produce reports. However, prior work mainly targets open-ended sci
12. **TaskWeaver: A Code-First Agent Framework** — https://arxiv.org/abs/2311.17541v3
  2023 | cs.AI
  Large Language Models (LLMs) have shown impressive abilities in natural language understanding and generation, leading to their widespread use in applications such as chatbots and virtual assistants. 
13. **Your Code Agent Can Grow Alongside You with Structured Memory** — https://arxiv.org/abs/2603.13258v1
  2026 | cs.LG
  While "Intent-oriented programming" (or "Vibe Coding") redefines software engineering, existing code agents remain tethered to static code snapshots. Consequently, they struggle to model the critical 
14. **DiffSkill: Skill Abstraction from Differentiable Physics for Deformable Object Manipulations with Tools** — https://arxiv.org/abs/2203.17275v1
  2022 | cs.LG
  We consider the problem of sequential robotic manipulation of deformable objects using tools. Previous works have shown that differentiable physics simulators provide gradients to the environment stat
15. **SearchSkill: Teaching LLMs to Use Search Tools with Evolving Skill Banks** — https://arxiv.org/abs/2605.09038v3
  2026 | cs.AI
  Teaching language models to use search tools is not only a question of whether they search, but also of whether they issue good queries. This is especially important in open-domain question answering,
16. **ESC-Eval: Evaluating Emotion Support Conversations in Large Language Models** — https://arxiv.org/abs/2406.14952v3
  2024 | cs.CL
  Emotion Support Conversation (ESC) is a crucial application, which aims to reduce human stress, offer emotional guidance, and ultimately enhance human mental and physical well-being. With the advancem
17. **ParaView-MCP: An Autonomous Visualization Agent with Direct Tool Use** — https://arxiv.org/abs/2505.07064v1
  2025 | cs.HC
  While powerful and well-established, tools like ParaView present a steep learning curve that discourages many potential users. This work introduces ParaView-MCP, an autonomous agent that integrates mo
18. **Adaptive Self-improvement LLM Agentic System for ML Library Development** — https://arxiv.org/abs/2502.02534v2
  2025 | cs.CL
  ML libraries, often written in architecture-specific programming languages (ASPLs) that target domain-specific architectures, are key to efficient ML systems. However, writing these high-performance M
19. **Agent4cs: A Multi-agent System for Code Summarization in Large Hierarchical Codebases** — https://arxiv.org/abs/2607.01425v2
  2026 | cs.AI
  Understanding large, complex codebases, especially those with obfuscated structures and incomplete documentation, remains a significant challenge. Existing code summarization solutions often rely on a

## Codigo (GitHub)

1. **hesreallyhim/awesome-claude-code** (50444 estrellas) — https://github.com/hesreallyhim/awesome-claude-code
  Python
  A hand-picked collection of the finest of resources for the most awesome of agents, Claude Code, the undisputed champion of coding companions, from the unstoppable team at Anthropic PBC. A delectable 
2. **calesthio/OpenMontage** (40214 estrellas) — https://github.com/calesthio/OpenMontage
  Python
  World's first open-source, agentic video production system. 12 pipelines, 52 tools, 500+ agent skills. Turn your AI coding assistant into a full video production studio.
3. **google-labs-code/stitch-skills** (7704 estrellas) — https://github.com/google-labs-code/stitch-skills
  TypeScript
  A library of Agent Skills designed to work with the Stitch MCP server. Each skill follows the Agent Skills open standard, for compatibility with coding agents such as Antigravity, Gemini CLI, Claude C
4. **ref-tools/ref-tools-mcp** (1141 estrellas) — https://github.com/ref-tools/ref-tools-mcp
  TypeScript
  Helping coding agents never make mistakes working with public or private libraries without wasting the context window.
5. **VoltAgent/awesome-design-md** (103205 estrellas) — https://github.com/VoltAgent/awesome-design-md
  A collection of DESIGN.md files analysis by popular brand design systems. Drop one into your project and let coding agents generate a matching UI.
6. **ComposioHQ/awesome-claude-skills** (68126 estrellas) — https://github.com/ComposioHQ/awesome-claude-skills
  Python
  A curated list of awesome Claude Skills, resources, and tools for customizing Claude AI workflows
7. **headroomlabs-ai/headroom** (60425 estrellas) — https://github.com/headroomlabs-ai/headroom
  Python
  Compress tool outputs, logs, files, and RAG chunks before they reach the LLM. 20% fewer tokens for coding agents, 60-95% fewer tokens for JSON, same answers. Library, proxy, MCP server.
8. **zylon-ai/private-gpt** (57342 estrellas) — https://github.com/zylon-ai/private-gpt
  Python
  Complete API layer for private AI applications on local models: RAG, skills, tools, MCP, text-to-sql, and more. Works with any OpenAI-compatible inference server.
9. **zhayujie/CowAgent** (46048 estrellas) — https://github.com/zhayujie/CowAgent
  Python
  Open-source super AI assistant & Agent Harness. Plans tasks, runs tools and skills, self-evolves with memory and knowledge. Multi-model, multi-channel. Lightweight, extensible, one-line install. (form
10. **mukul975/Anthropic-Cybersecurity-Skills** (26110 estrellas) — https://github.com/mukul975/Anthropic-Cybersecurity-Skills
  Python
  817 structured cybersecurity skills for AI agents · Mapped to 6 frameworks: MITRE ATT&CK, NIST CSF 2.0, MITRE ATLAS, D3FEND, NIST AI RMF & MITRE F3 (Fight Fraud) · agentskills.io standard · Works with
11. **0x4m4/hexstrike-ai** (10392 estrellas) — https://github.com/0x4m4/hexstrike-ai
  Python
  HexStrike AI MCP Agents is an advanced MCP server that lets AI agents (Claude, GPT, Copilot, etc.) autonomously run 150+ cybersecurity tools for automated pentesting, vulnerability discovery, bug boun
12. **deanpeters/Product-Manager-Skills** (5845 estrellas) — https://github.com/deanpeters/Product-Manager-Skills
  Shell
  Product Management skills framework built on battle-tested methods for Claude Code, Cowork, Codex, and AI agents.
13. **wesammustafa/Claude-Code-Everything-You-Need-to-Know** (2341 estrellas) — https://github.com/wesammustafa/Claude-Code-Everything-You-Need-to-Know
  Python
  A practical Claude Code guide with clear mental models and copy-paste examples — setup, prompt engineering, slash commands, skills, hooks, subagents, agent teams, and MCP servers. Beginner path to pow
14. **Armur-Ai/Pentest-Swarm-AI** (2081 estrellas) — https://github.com/Armur-Ai/Pentest-Swarm-AI
  Go
  Autonomous penetration testing using a swarm of AI agents. Orchestrates recon, classification, exploitation, and reporting specialists with ReAct reasoning — supports bug bounty, continuous monitoring
15. **study8677/awesome-architecture** (1875 estrellas) — https://github.com/study8677/awesome-architecture
  Vue
  🧭 Architecture-first system design: 26 bilingual tutorials, 25 architecture templates, and 6 end-to-end cases covering distributed systems, AI-native systems, RAG, coding Agents, and production trade-
16. **obra/superpowers** (257685 estrellas) — https://github.com/obra/superpowers
  Shell
  An agentic skills framework & software development methodology that works.
17. **omnigent-ai/omnigent** (7519 estrellas) — https://github.com/omnigent-ai/omnigent
  Python
  Omnigent is an open-source AI agent framework and meta-harness: orchestrate Claude Code, Codex, Cursor, Pi, and custom agents — swap harnesses without rewriting, enforce policies and sandboxing, and c
18. **gptme/gptme** (4361 estrellas) — https://github.com/gptme/gptme
  Python
  Your agent in your terminal, equipped with local tools: writes code, uses the terminal, browses the web. Make your own persistent autonomous agent on top!
19. **zarazhangrui/beautiful-html-templates** (3791 estrellas) — https://github.com/zarazhangrui/beautiful-html-templates
  HTML
  A library of HTML slide templates designed so any coding agent can pick the right one and produce a beautiful deck on the user's behalf, automatically.
20. **ascending-llc/jarvis-registry** (2318 estrellas) — https://github.com/ascending-llc/jarvis-registry
  Python
  Connect any AI copilot or autonomous agent to your enterprise tools — through a single, secure MCP/Agent gateway with built-in identity, access control, and full observability.

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **AWESOME: GPU Memory-constrained Long Document Summarization using Memory Mechanism and Global Salient Content** — https://arxiv.org/abs/2305.14806v2
  contra: awesome-claude-code
  Long document summarization systems are critical for domains with lengthy and jargonladen text, yet they present significant challenges to researchers and developers with limited computing resources. 
2. **Video Diffusion Models: A Survey** — https://arxiv.org/abs/2405.03150v2
  contra: awesome-claude-code
  Diffusion generative models have recently become a powerful technique for creating and modifying high-quality, coherent video content. This survey provides a comprehensive overview of the critical com
3. **SkillMimic-V2: Learning Robust and Generalizable Interaction Skills from Sparse and Noisy Demonstrations** — https://arxiv.org/abs/2505.02094v1
  contra: stitch-skills
  We address a fundamental challenge in Reinforcement Learning from Interaction Demonstration (RLID): demonstration noise and coverage limitations. While existing data collection approaches provide valu
4. **Stitching Sub-Trajectories with Conditional Diffusion Model for Goal-Conditioned Offline RL** — https://arxiv.org/abs/2402.07226v1
  contra: stitch-skills
  Offline Goal-Conditioned Reinforcement Learning (Offline GCRL) is an important problem in RL that focuses on acquiring diverse goal-oriented skills solely from pre-collected behavior datasets. In this
