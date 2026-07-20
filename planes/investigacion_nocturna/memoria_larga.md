# Investigacion: memoria persistente de largo plazo para agentes de programacion open source

Queries ejecutadas (5): `awesome long-term memory agents`, `long-term memory agent alternative`, `open source programming agent`, `memory persistence agent`, `memory long agents`

## Resumen

Los resultados proporcionados muestran varios proyectos y repositorios de código abierto que ofrecen soluciones para la memoria persistente de largo plazo para agentes de programación. Entre ellos, **Cognee** (topoteretes/cognee) es una plataforma de memoria de IA de código abierto que permite a los agentes de IA tener una memoria persistente a largo plazo entre sesiones, utilizando un motor de conocimiento gráfico autoalojado. Otro proyecto relevante es **AitherOS** (alfadilmed/AitherOS), que es una plataforma de fuerza de trabajo de IA multi-agente autónoma con memoria a largo plazo y una integración de herramientas de gestión de proyectos. Además, **Resonant** (codependentai/resonant) es un marco de IA relacional de código abierto que incluye persistencia de identidad, memoria y una integración de MCP, permitiendo a los agentes de IA recordar, crecer y mantener continuidad. Finalmente, **Memvid** (memvid/memvid) es una capa de memoria para agentes de IA que reemplaza complejos pipelines RAG con una capa de memoria de un solo archivo y sin servidor, proporcionando a los agentes recuperación instantánea y memoria a largo plazo. Estos proyectos son relevantes porque ofrecen soluciones concretas y de código abierto para implementar la memoria persistente de largo plazo en agentes de IA.

## Modelos (HuggingFace)

1. **kayrahan35/HFP-O1-Memory-Model** (1925 descargas) — https://huggingface.co/kayrahan35/HFP-O1-Memory-Model
  HFPForCausalLM, 12 capas | ctx 4096 | KV 36864 B/tok (4.50 GB @128k)
  transformers, safetensors, hfp, text-generation, pytorch, causal-lm, linear-attention, long-context, recurrent-memory, o1-memory
2. **philomath-1209/programming-language-identification** (5455 descargas) — https://huggingface.co/philomath-1209/programming-language-identification
  RobertaForSequenceClassification, 6 capas | ctx 514 | KV 18432 B/tok (2.25 GB @128k)
  transformers, onnx, safetensors, roberta, text-classification, code, programming-language, code-classification, en, dataset:cakiki/rosetta-code
3. **BytedTsinghua-SIA/RL-MemoryAgent-14B** (3236 descargas) — https://huggingface.co/BytedTsinghua-SIA/RL-MemoryAgent-14B
  Qwen2ForCausalLM, GQA 40:8, ventana deslizante 131072, 48 capas | ctx 32768 | KV 196608 B/tok (24.00 GB @128k)
  safetensors, qwen2
4. **RichardErkhov/muscle-memory_-_llama_3_math-gguf** (736 descargas) — https://huggingface.co/RichardErkhov/muscle-memory_-_llama_3_math-gguf
  GGUF
  gguf, endpoints_compatible, conversational
5. **sennaLLMLearner/qwen2.5-7b-memory-distiller** (697 descargas) — https://huggingface.co/sennaLLMLearner/qwen2.5-7b-memory-distiller
  Qwen2ForCausalLM, GQA 28:4, 28 capas | ctx 32768 | KV 57344 B/tok (7.00 GB @128k) | GGUF
  transformers, safetensors, gguf, qwen2, text-generation, memory, distillation, orpo, merged, qwen2.5
6. **as-krn/quantum_programming_llama-3-8b-gguf** (417 descargas) — https://huggingface.co/as-krn/quantum_programming_llama-3-8b-gguf
  GGUF
  transformers, gguf, llama, text-generation-inference, unsloth, en, endpoints_compatible, conversational
7. **mengmeong/meng-programming-skill-finetune** (175 descargas) — https://huggingface.co/mengmeong/meng-programming-skill-finetune
  LlamaForCausalLM, GQA 9:3, 35 capas | ctx 2048 | KV 26880 B/tok (3.28 GB @128k) | GGUF
  safetensors, gguf, llama, text-generation, en, dataset:mengmeong/coding-skill-real-world-needs, endpoints_compatible
8. **BurakkTalha/programming-languages** (167 descargas) — https://huggingface.co/BurakkTalha/programming-languages
  GGUF
  gguf, llama, endpoints_compatible
9. **ntc-ai/SDXL-LoRA-slider.in-the-style-of-the-painting-the-persistence-of-memory-by-Salvador-Dali** (4 descargas) — https://huggingface.co/ntc-ai/SDXL-LoRA-slider.in-the-style-of-the-painting-the-persistence-of-memory-by-Salvador-Dali
  diffusers, text-to-image, stable-diffusion-xl, lora, template:sd-lora, template:sdxl-lora, sdxl-sliders, ntcai.xyz-sliders, concept, en

## Evidencia (arXiv)

1. **OSS-UAgent: An Agent-based Usability Evaluation Framework for Open Source Software** — https://arxiv.org/abs/2505.23239v1
  2025 | cs.SE
  Usability evaluation is critical to the impact and adoption of open source software (OSS), yet traditional methods relying on human evaluators suffer from high costs and limited scalability. To addres
2. **Evaluating LLMs in Open-Source Games** — https://arxiv.org/abs/2512.00371v1
  2025 | cs.GT
  Large Language Models' (LLMs) programming capabilities enable their participation in open-source games: a game-theoretic setting in which players submit computer programs in lieu of actions. These pro
3. **Zombie Agents: Persistent Control of Self-Evolving LLM Agents via Self-Reinforcing Injections** — https://arxiv.org/abs/2602.15654v2
  2026 | cs.CR
  Self-evolving LLM agents update their internal state across sessions, often by writing and reusing long-term memory. This design improves performance on long-horizon tasks but creates a security risk:
4. **In Prospect and Retrospect: Reflective Memory Management for Long-term Personalized Dialogue Agents** — https://arxiv.org/abs/2503.08026v2
  2025 | cs.CL
  Large Language Models (LLMs) have made significant progress in open-ended dialogue, yet their inability to retain and retrieve relevant information from long-term interactions limits their effectivene
5. **Graph-based Agent Memory: Taxonomy, Techniques, and Applications** — https://arxiv.org/abs/2602.05665v1
  2026 | cs.AI
  Memory emerges as the core module in the Large Language Model (LLM)-based agents for long-horizon complex tasks (e.g., multi-turn dialogue, game playing, scientific discovery), where memory can enable
6. **Lifelong Learning of Large Language Model based Agents: A Roadmap** — https://arxiv.org/abs/2501.07278v2
  2025 | cs.AI
  Lifelong learning, also known as continual or incremental learning, is a crucial component for advancing Artificial General Intelligence (AGI) by enabling systems to continuously adapt in dynamic envi
7. **A Simple Yet Strong Baseline for Long-Term Conversational Memory of LLM Agents** — https://arxiv.org/abs/2511.17208v2
  2025 | cs.CL
  LLM-based conversational agents still struggle to maintain coherent, personalized interaction over many sessions: fixed context windows limit how much history can be kept in view, and most external me
8. **MAGE: Meta-Reinforcement Learning for Language Agents toward Strategic Exploration and Exploitation** — https://arxiv.org/abs/2603.03680v1
  2026 | cs.AI
  Large Language Model (LLM) agents have demonstrated remarkable proficiency in learned tasks, yet they often struggle to adapt to non-stationary environments with feedback. While In-Context Learning an
9. **Evolutionary Optimization of Deep Learning Agents for Sparrow Mahjong** — https://arxiv.org/abs/2508.07522v1
  2025 | cs.NE
  We present Evo-Sparrow, a deep learning-based agent for AI decision-making in Sparrow Mahjong, trained by optimizing Long Short-Term Memory (LSTM) networks using Covariance Matrix Adaptation Evolution
10. **Facing Off World Model Backbones: RNNs, Transformers, and S4** — https://arxiv.org/abs/2307.02064v2
  2023 | cs.LG
  World models are a fundamental component in model-based reinforcement learning (MBRL). To perform temporally extended and consistent simulations of the future in partially observable environments, wor
11. **Using Methods of Declarative Logic Programming for Intelligent Information Agents** — https://arxiv.org/abs/cs/0108008v1
  2001 | cs.MA
  The search for information on the web is faced with several problems, which arise on the one hand from the vast number of available sources, and on the other hand from their heterogeneity. A promising
12. **BuildBench: Benchmarking LLM Agents on Compiling Real-World Open-Source Software** — https://arxiv.org/abs/2509.25248v1
  2025 | cs.SE
  Automatically compiling open-source software (OSS) projects is a vital, labor-intensive, and complex task, which makes it a good challenge for LLM Agents. Existing methods rely on manually curated rul
13. **MemTrace: Probing What Final Accuracy Misses in Long-Term Memory** — https://arxiv.org/abs/2606.17328v1
  2026 | cs.AI
  LLM agents increasingly maintain long-term memory of user facts across sessions. Yet such memory is usually evaluated by aggregating accuracy over question rows or episodes. Because this approach scor
14. **Oracle Agent Memory as an Enterprise Memory Substrate for Long-Horizon AI Agents** — https://arxiv.org/abs/2607.13157v1
  2026 | cs.AI
  Agent memory is a systems problem for long-horizon agents. Practical deployments require retention of task state across extended conversations, recovery of user-specific facts and preferences across s
15. **Stateless Decision Memory for Enterprise AI Agents** — https://arxiv.org/abs/2604.20158v1
  2026 | cs.AI
  Enterprise deployment of long-horizon decision agents in regulated domains (underwriting, claims adjudication, tax examination) is dominated by retrieval-augmented pipelines despite a decade of increa
16. **Agent Memory Below the Prompt: Persistent Q4 KV Cache for Multi-Agent LLM Inference on Edge Devices** — https://arxiv.org/abs/2603.04428v1
  2026 | cs.LG
  Multi-agent LLM systems on edge devices face a memory management problem: device RAM is too small to hold every agent's KV cache simultaneously. On Apple M4 Pro with 10.2 GB of cache budget, only 3 ag
17. **Semantic Anchoring in Agentic Memory: Leveraging Linguistic Structures for Persistent Conversational Context** — https://arxiv.org/abs/2508.12630v1
  2025 | cs.CL
  Large Language Models (LLMs) have demonstrated impressive fluency and task competence in conversational settings. However, their effectiveness in multi-session and long-term interactions is hindered b
18. **Are We Ready For An Agent-Native Memory System?** — https://arxiv.org/abs/2606.24775v1
  2026 | cs.CL
  Memory for large language model (LLM) agents has rapidly evolved from simple retrieval-augmented mechanisms into a data management system that supports persistent information storage, retrieval, updat

## Codigo (GitHub)

1. **topoteretes/cognee** (28535 estrellas) — https://github.com/topoteretes/cognee
  Python
  Cognee is the open-source AI memory platform for agents. Give your AI agents persistent long-term memory across sessions with a self-hosted knowledge graph engine.
2. **alfadilmed/AitherOS** (1 estrellas) — https://github.com/alfadilmed/AitherOS
  Open-source multi-agent AI workforce platform. Autonomous agents that plan, discuss, and collaborate — with Kanban-driven task loops, long-term memory, and MCP tool integration. Self-hosted AutoGen/Cr
3. **jihoo-kim/awesome-context-engineering** (109 estrellas) — https://github.com/jihoo-kim/awesome-context-engineering
  A curated list of awesome open-source libraries for context engineering (Long-term memory, MCP: Model Context Protocol, Prompt/RAG Compression, Multi-Agent)
4. **codependentai/resonant** (48 estrellas) — https://github.com/codependentai/resonant
  TypeScript
  Open-source relational AI framework with identity persistence, memory, and MCP integration. Build relationship-aware AI agents that remember, grow, and maintain continuity. Built on Claude Agent SDK.
5. **caozhiyi/ai-programming-book** (37 estrellas) — https://github.com/caozhiyi/ai-programming-book
  "The First Principles of AI Programming" Open Source Book. Starting from the underlying physical constraints of large models, it deduces the operational mechanisms of agents and the engineering practi
6. **claw-dex/mewclaw** (0 estrellas) — https://github.com/claw-dex/mewclaw
  Shell
  MewClaw is a lightweight alternative to OpenClaw that runs in containers for security. Has long-term memory, scheduled jobs, credentials store, interactive Web UI Portal. Connects to Telegram, Gmail a
7. **memvid/memvid** (16009 estrellas) — https://github.com/memvid/memvid
  Rust
  Memory layer for AI Agents. Replace complex RAG pipelines with a serverless, single-file memory layer. Give your agents instant retrieval and long-term memory.
8. **TencentCloud/TencentDB-Agent-Memory** (9141 estrellas) — https://github.com/TencentCloud/TencentDB-Agent-Memory
  TypeScript
  TencentDB Agent Memory delivers fully local long-term memory for AI Agents via a 4-tier progressive pipeline, with zero external API dependencies.
9. **AutoTrustAI/PaperGuru-Benchmark** (1313 estrellas) — https://github.com/AutoTrustAI/PaperGuru-Benchmark
  TeX
  Lifecycle-Aware Memory for long-horizon LLM agents — 66.05% on PaperBench, 94.66% on SurveyBench, 10 peer-reviewed acceptances at FSE/ICML/TOSEM/AEI/ICoGB
10. **IAAR-Shanghai/Awesome-AI-Memory** (1092 estrellas) — https://github.com/IAAR-Shanghai/Awesome-AI-Memory
  Python
  Awesome AI Memory | LLM Memory | A curated knowledge base on AI memory for LLMs and agents, covering long-term memory, reasoning, retrieval, and memory-native system design.  Awesome-AI-Memory 是一个 集中式
11. **timwuhaotian/the-pair** (344 estrellas) — https://github.com/timwuhaotian/the-pair
  TypeScript
  Open-source AI pair programming for desktop: a Mentor + Executor agent cross-check each other's code to catch AI hallucinations. Works with Claude Code, Codex, Gemini & opencode. macOS / Windows / Lin
12. **AlekseiUL/openclaw-memory-kit** (33 estrellas) — https://github.com/AlekseiUL/openclaw-memory-kit
  Shell
  Complete memory and context persistence system for OpenClaw AI agents
13. **Snseam/awesome-agent-memory** (6 estrellas) — https://github.com/Snseam/awesome-agent-memory
  Ruby
  Curated reading list & living survey on long-term memory for LLM agents — 989 papers, 529 archived PDFs, deep notes mapped to memory-kernel modules. Feeds the Ymem Research Radar.
14. **LikeACloud7/awesome-personalized-ai-benchmarks** (1 estrellas) — https://github.com/LikeACloud7/awesome-personalized-ai-benchmarks
  Python
  A living, evidence-based catalog of benchmarks for personalized LLMs and AI agents—covering preference alignment, long-term memory, tool use, safety, privacy, and multimodal adaptation.
15. **MiscellaneousStuff/anterion** (183 estrellas) — https://github.com/MiscellaneousStuff/anterion
  Python
  Open-source software engineer
16. **SpillwaveSolutions/mastering-langgraph-agent-skill** (37 estrellas) — https://github.com/SpillwaveSolutions/mastering-langgraph-agent-skill
  Build stateful AI agents and agentic workflows with LangGraph in Python. Covers tool-using agents, branching workflows, memory persistence, human-in-the-loop, multi-agent systems, and production deplo
17. **shd-git/fast-asdlc** (26 estrellas) — https://github.com/shd-git/fast-asdlc
  Fast-ASDLC: 5x TTM with AI-native Agentic SDLC. Local-LLM first, Human-in-the-loop, Spec-driven. Built on DDD, Hexagonal Architecture, C4 Model & MCP. Features Meta-agents for self-improvement, Memory
18. **complexus-tech/fortyone** (20 estrellas) — https://github.com/complexus-tech/fortyone
  TypeScript
  The Open Source Agentic Project Management Platform
19. **cloudwithax/crusty** (0 estrellas) — https://github.com/cloudwithax/crusty
  TypeScript
  a telegram ai agent with web browsing capabilities, long-term memory, and a modular personality system.

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **Optimizing the Interface Between Knowledge Graphs and LLMs for Complex Reasoning** — https://arxiv.org/abs/2505.24478v1
  contra: cognee
  Integrating Large Language Models (LLMs) with Knowledge Graphs (KGs) results in complex systems with numerous hyperparameters that directly affect performance. While such systems are increasingly comm
2. **The Limitations of Stylometry for Detecting Machine-Generated Fake News** — https://arxiv.org/abs/1908.09805v2
  contra: AitherOS
  Recent developments in neural language models (LMs) have raised concerns about their potential misuse for automatically spreading misinformation. In light of these concerns, several studies have propo
3. **Transformers: "The End of History" for NLP?** — https://arxiv.org/abs/2105.00813v2
  contra: AitherOS
  Recent advances in neural architectures, such as the Transformer, coupled with the emergence of large-scale pre-trained models such as BERT, have revolutionized the field of Natural Language Processin
4. **From Question Answering to Task Completion: A Survey on Agent System and Harness Design** — https://arxiv.org/abs/2606.20683v1
  contra: awesome-context-engineering
  LLM-based agents mark a shift from passive question answering to active task completion: they perceive environments, invoke tools, maintain state, and act over extended horizons. As agent systems have
