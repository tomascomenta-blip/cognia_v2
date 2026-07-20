# Investigacion: servidores MCP gratuitos sin registro ni apikey para agentes de codigo

Queries ejecutadas (5): `free MCP servers`, `MCP agent alternatives`, `unregistered MCP services`, `MCP without API key`, `MCP for code agents`

## Resumen

Los resultados proporcionados no incluyen servidores MCP gratuitos sin registro ni API key específicamente para agentes de código. Sin embargo, se mencionan varios repositorios de GitHub que implementan servidores MCP de código abierto y gratuitos:

1. **LibreChat**: Un clon mejorado de ChatGPT que incluye soporte para agentes y MCP, entre otras características. Aunque no se especifica si requiere registro o API key, es una opción gratuita para integrar MCP en proyectos de chat.

2. **git-mcp**: Un servidor MCP remoto gratuito y de código abierto para proyectos de GitHub. Este repositorio es específico para integrar MCP con GitHub, lo que puede ser útil para agentes de código que trabajan con proyectos de desarrollo en este entorno.

3. **DevDocs**: Un servidor MCP privado y gratuito con interfaz de usuario basada en la web, diseñado para desarrolladores y codificadores. Permite la integración fácil con diversas aplicaciones como Cursor, Windsurf, Cline, Roo Code, Claude Desktop App, entre otras.

4. **meta-ads-mcp**: Un servidor MCP para Meta Ads (Facebook/Instagram) que es gratuito y hospedado de forma remota. No requiere autohospedaje y está disponible como parte de la familia de 5 plataformas de Pipeboard.

Estos repositorios ofrecen soluciones gratuitas para implementar MCP en diferentes entornos de desarrollo y pueden ser útiles para agentes de código que buscan integrar herramientas externas sin necesidad de pagar por servicios de hosting o registro.

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
5. **kyutai/pocket-tts-without-voice-cloning** (5810 descargas) — https://huggingface.co/kyutai/pocket-tts-without-voice-cloning
  pocket-tts, safetensors, en
6. **braindecode/signal-jepa_without-chans** (2577 descargas) — https://huggingface.co/braindecode/signal-jepa_without-chans
  braindecode, pytorch, safetensors, eeg, foundation-model, self-supervised, signal-jepa, feature-extraction
7. **yushengsu/sglang_lora_logprob_diff_without_tuning** (1688 descargas) — https://huggingface.co/yushengsu/sglang_lora_logprob_diff_without_tuning
  LlamaForCausalLM, MHA, 32 capas | ctx 4096 | KV 524288 B/tok (64.00 GB @128k)
  safetensors, llama
8. **veronoicc/VeroGPT-small-ServerSeeker** (4 descargas) — https://huggingface.co/veronoicc/VeroGPT-small-ServerSeeker
  GPT2LMHeadModel | ctx 1024 | KV 36864 B/tok (4.50 GB @128k)
  transformers, safetensors, gpt2, text-generation, not-for-all-audiences, en, text-generation-inference, endpoints_compatible
9. **veronoicc/DAMGPT-small-ServerSeeker** (4 descargas) — https://huggingface.co/veronoicc/DAMGPT-small-ServerSeeker
  GPT2LMHeadModel | ctx 1024 | KV 36864 B/tok (4.50 GB @128k)
  transformers, safetensors, gpt2, text-generation, conversational, en, de, text-generation-inference, endpoints_compatible
10. **arclabmit/mobile_xarm7_act_beavrsim_serverswap_model** (4 descargas) — https://huggingface.co/arclabmit/mobile_xarm7_act_beavrsim_serverswap_model
  lerobot, safetensors, robotics, act, dataset:arclabmit/mobile_xarm7_beavrsim_serverswap_dataset
11. **arclabmit/mobile_xarm7_diffusion_beavrsim_serverswap_model** (4 descargas) — https://huggingface.co/arclabmit/mobile_xarm7_diffusion_beavrsim_serverswap_model
  lerobot, safetensors, diffusion, robotics, dataset:arclabmit/mobile_xarm7_beavrsim_serverswap_dataset

## Evidencia (arXiv)

1. **Unicode TAG-Block Concealment of Tool-Metadata Payloads in the Model Context Protocol: An Approval-View Fidelity Gap Across Three Independent Server Implementations** — https://arxiv.org/abs/2607.05744v1
  2026 | cs.CR
  The Model Context Protocol (MCP) is the dominant way coding agents discover and invoke external tools. A server advertises each tool through a tools/list handshake that returns a name, a natural-langu
2. **From Tool Orchestration to Code Execution: A Study of MCP Design Choices** — https://arxiv.org/abs/2602.15945v1
  2026 | cs.CR
  Model Context Protocols (MCPs) provide a unified platform for agent systems to discover, select, and orchestrate tools across heterogeneous execution environments. As MCP-based systems scale to incorp
3. **Trivial Trojans: How Minimal MCP Servers Enable Cross-Tool Exfiltration of Sensitive Data** — https://arxiv.org/abs/2507.19880v1
  2025 | cs.CR
  The Model Context Protocol (MCP) represents a significant advancement in AI-tool integration, enabling seamless communication between AI agents and external services. However, this connectivity introd
4. **MPMA: Preference Manipulation Attack Against Model Context Protocol** — https://arxiv.org/abs/2505.11154v2
  2025 | cs.CR
  Model Context Protocol (MCP) standardizes interface mapping for large language models (LLMs) to access external data and tools, which revolutionizes the paradigm of tool selection and facilitates the 
5. **TheMCPCompany: Creating General-purpose Agents with Task-specific Tools** — https://arxiv.org/abs/2510.19286v2
  2025 | cs.CL
  Since the introduction of the Model Context Protocol (MCP), the number of available tools for Large Language Models (LLMs) has increased significantly. These task-specific tool sets offer an alternati
6. **Feedback-Normalized Developer Memory for Reinforcement-Learning Coding Agents: A Safety-Gated MCP Architecture** — https://arxiv.org/abs/2605.01567v1
  2026 | cs.SE
  Large language model (LLM) coding agents increasingly operate over repositories, terminals, tests, and execution traces across long software-engineering episodes. Persistent memory is useful, but stat
7. **Workflows vs Agents for Code Translation** — https://arxiv.org/abs/2512.14762v1
  2025 | cs.SE
  Translating algorithms from high-level languages like MATLAB to hardware description languages (HDLs) is a resource-intensive but necessary step for deployment on FPGAs and ASICs. While large language
8. **MCP-Atlas: A Large-Scale Benchmark for Tool-Use Competency with Real MCP Servers** — https://arxiv.org/abs/2602.00933v3
  2026 | cs.SE
  The Model Context Protocol (MCP) is emerging as a standard interface through which large language model (LLM) agents discover and invoke external tools. However, existing MCP evaluations fall short al
9. **LiveMCPBench: Can Agents Navigate an Ocean of MCP Tools?** — https://arxiv.org/abs/2508.01780v2
  2025 | cs.AI
  Model Context Protocol (MCP) has become a key infrastructure for connecting LLMs with external tools, scaling to 10,000+ MCP servers with diverse tools. Unfortunately, there is still a large gap betwe
10. **Firefly: Illuminating Large-Scale Verified Tool-Call Data Generation from Real APIs** — https://arxiv.org/abs/2605.17558v1
  2026 | cs.SE
  Training tool-calling agents requires large-scale trajectory data with verifiable labels, yet existing approaches either synthesize environments that diverge from real API behavior or generate tasks w
11. **General Agent Evaluation** — https://arxiv.org/abs/2602.22953v2
  2026 | cs.AI
  General-purpose agents perform tasks in unfamiliar environments without domain-specific manual customization. Yet no study has systematically measured how agent architecture shapes performance across 
12. **Tool Preferences in Agentic LLMs are Unreliable** — https://arxiv.org/abs/2505.18135v2
  2025 | cs.AI
  Large language models (LLMs) can now access a wide range of external tools, thanks to the Model Context Protocol (MCP). This greatly expands their abilities as various agents. However, LLMs rely entir
13. **EE-MCP: Self-Evolving MCP-GUI Agents via Automated Environment Generation and Experience Learning** — https://arxiv.org/abs/2604.09815v1
  2026 | cs.AI
  Computer-use agents that combine GUI interaction with structured API calls via the Model Context Protocol (MCP) show promise for automating software tasks. However, existing approaches lack a principl
14. **Notation Matters: A Benchmark Study of Token-Optimized Formats in Agentic AI Systems** — https://arxiv.org/abs/2605.29676v2
  2026 | cs.AI
  Large language models in Agentic AI systems consume tool schemas and execution results and emit tool invocations as structured data. The default language for that exchange, JSON, was designed for appl
15. **Exploiting user-frequency information for mining regionalisms from Social Media texts** — https://arxiv.org/abs/1907.04492v1
  2019 | cs.CL
  The task of detecting regionalisms (expressions or words used in certain regions) has traditionally relied on the use of questionnaires and surveys, and has also heavily depended on the expertise and 

## Codigo (GitHub)

1. **danny-avila/LibreChat** (40956 estrellas) — https://github.com/danny-avila/LibreChat
  TypeScript
  Enhanced ChatGPT Clone: Features Agents, MCP, Skills, DeepSeek, Anthropic, AWS, OpenAI, Responses API, Azure, Groq, o1, GPT-5, Mistral, OpenRouter, Vertex AI, Gemini, Artifacts, AI model switching, me
2. **idosal/git-mcp** (8267 estrellas) — https://github.com/idosal/git-mcp
  TypeScript
  Put an end to code hallucinations! GitMCP is a free, open-source, remote MCP server for any GitHub project
3. **cyberagiinc/DevDocs** (2096 estrellas) — https://github.com/cyberagiinc/DevDocs
  TypeScript
  Completely free, private, UI based Tech Documentation MCP server. Designed for coders and software developers in mind. Easily integrate into Cursor, Windsurf, Cline, Roo Code, Claude Desktop App 
4. **pipeboard-co/meta-ads-mcp** (1090 estrellas) — https://github.com/pipeboard-co/meta-ads-mcp
  Python
  Meta Ads (Facebook/Instagram) MCP server for Claude, ChatGPT, Perplexity & Cursor — the Meta node of Pipeboard’s 5-platform family (+ Google, TikTok, Snap, Reddit). Hosted remote MCP, badged Meta Busi
5. **headroomlabs-ai/headroom** (60425 estrellas) — https://github.com/headroomlabs-ai/headroom
  Python
  Compress tool outputs, logs, files, and RAG chunks before they reach the LLM. 20% fewer tokens for coding agents, 60-95% fewer tokens for JSON, same answers. Library, proxy, MCP server.
6. **wshobson/agents** (38067 estrellas) — https://github.com/wshobson/agents
  Python
  Multi-harness agentic plugin marketplace for Claude Code, Codex CLI, Cursor, OpenCode, GitHub Copilot, and Gemini CLI
7. **sahibzada-allahyar/YC-Killer** (2780 estrellas) — https://github.com/sahibzada-allahyar/YC-Killer
  TypeScript
  A library of enterprise-grade AI agents designed to democratize artificial intelligence and provide free, open-source alternatives to overvalued Y Combinator startups. If you are excited about democra
8. **neka-nat/freecad-mcp** (1369 estrellas) — https://github.com/neka-nat/freecad-mcp
  Python
  FreeCAD MCP(Model Context Protocol) server
9. **masterofthechaos/ProxyPilot-public** (49 estrellas) — https://github.com/masterofthechaos/ProxyPilot-public
  Swift
  Run any AI model in Xcode Agent Mode. Change models without losing the thread. New: ProxyPilot Agent in Xcode 27. Use local models (Ollama and LM Studio) with no API key, or route to cloud routers and
10. **TheSethRose/Fetch-Browser** (24 estrellas) — https://github.com/TheSethRose/Fetch-Browser
  TypeScript
  A powerful headless browser MCP server that enables AI agents to fetch web content and perform Google searches without requiring any API keys. 
11. **MODSetter/SurfSense** (15282 estrellas) — https://github.com/MODSetter/SurfSense
  Python
  Open-source NotebookLM alternative. Research the open web with live data, through one platform, API or MCP server. Join our Discord: https://discord.gg/ejRNvftDp9
12. **wysh3/perplexity-mcp-zerver** (93 estrellas) — https://github.com/wysh3/perplexity-mcp-zerver
  TypeScript
  MCP web search using perplexity without any API KEYS 
13. **Jaspreet2110/SafeDepositBox** (0 estrellas) — https://github.com/Jaspreet2110/SafeDepositBox
  SafeDepositBox application is a Serverless Application developed by using services from AWS and GCP. This application allow maximum of three users to enter to the application. This application has fea
14. **affaan-m/ECC** (231304 estrellas) — https://github.com/affaan-m/ECC
  JavaScript
  The agent harness performance optimization system. Skills, instincts, memory, security, and research-first development for Claude Code, Codex, Opencode, Cursor and beyond.
15. **ZSeven-W/openpencil** (4170 estrellas) — https://github.com/ZSeven-W/openpencil
  Rust
  The world's first open-source AI-native vector design tool and the first to feature concurrent Agent Teams. Design-as-Code. Turn prompts into UI directly on the live canvas. A modern alternative to Pe
16. **mishamyrt/perplexity-web-api-mcp** (87 estrellas) — https://github.com/mishamyrt/perplexity-web-api-mcp
  Rust
  🔍 Perplexity AI MCP without API key
17. **pranshi112/Goods-Locator** (1 estrellas) — https://github.com/pranshi112/Goods-Locator
  PHP
  A web service to make the essentials available to the citizens by linking the registered/unregistered organizations or individuals.
18. **ravkishore27/Rate_Review** (0 estrellas) — https://github.com/ravkishore27/Rate_Review
  Java
  Admin, Registered User and Unregistered User services are implemented in Java using JDBC and MYSQL.
19. **sajiniPW/Online-booking-web-site** (0 estrellas) — https://github.com/sajiniPW/Online-booking-web-site
  HTML
  Online Salon Booking System This system supports registered and unregistered customers. Unregistered customers must register to log in, while registered customers can log in, make reservations, view a

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **The Limitations of Stylometry for Detecting Machine-Generated Fake News** — https://arxiv.org/abs/1908.09805v2
  contra: LibreChat
  Recent developments in neural language models (LMs) have raised concerns about their potential misuse for automatically spreading misinformation. In light of these concerns, several studies have propo
2. **Transformers: "The End of History" for NLP?** — https://arxiv.org/abs/2105.00813v2
  contra: LibreChat
  Recent advances in neural architectures, such as the Transformer, coupled with the emergence of large-scale pre-trained models such as BERT, have revolutionized the field of Natural Language Processin
3. **Agentic Hardware Design as Repository-Level Code Evolution** — https://arxiv.org/abs/2606.28279v1
  contra: git-mcp
  We present HORIZON, a self-evolving agent framework that treats hardware design as repository-level code evolution. A Markdown harness is compiled into a project pack containing domain knowledge, an e
4. **NanoVLMs: How small can we go and still make coherent Vision Language Models?** — https://arxiv.org/abs/2502.07838v2
  contra: git-mcp
  Vision-Language Models (VLMs), such as GPT-4V and Llama 3.2 vision, have garnered significant research attention for their ability to leverage Large Language Models (LLMs) in multimodal tasks. However
