# Investigacion: best small distilled draft models for speculative decoding with qwen coder 14b

Queries ejecutadas (4): `awesome small distilled models`, `speculative decoding techniques`, `qwen coder 14b`, `alternative decoding frameworks`

## Modelos (HuggingFace)

1. **Qwen/Qwen2.5-Coder-14B-Instruct** (2970330 descargas) — https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct
  Qwen2ForCausalLM, GQA 40:8, ventana deslizante 131072, 48 capas | ctx 32768 | KV 196608 B/tok (24.00 GB @128k)
  transformers, safetensors, qwen2, text-generation, code, codeqwen, chat, qwen, qwen-coder, conversational
2. **Qwen/Qwen2.5-Coder-14B-Instruct-AWQ** (726596 descargas) — https://huggingface.co/Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
  Qwen2ForCausalLM, GQA 40:8, ventana deslizante 131072, 48 capas | ctx 32768 | KV 196608 B/tok (24.00 GB @128k)
  transformers, safetensors, qwen2, text-generation, code, codeqwen, chat, qwen, qwen-coder, conversational
3. **lmstudio-community/Qwen2.5-Coder-14B-Instruct-MLX-4bit** (125722 descargas) — https://huggingface.co/lmstudio-community/Qwen2.5-Coder-14B-Instruct-MLX-4bit
  Qwen2ForCausalLM, GQA 40:8, ventana deslizante 131072, 48 capas | ctx 32768 | KV 196608 B/tok (24.00 GB @128k)
  mlx, safetensors, qwen2, code, codeqwen, chat, qwen, qwen-coder, text-generation, conversational
4. **lmstudio-community/Qwen2.5-Coder-14B-Instruct-MLX-8bit** (99567 descargas) — https://huggingface.co/lmstudio-community/Qwen2.5-Coder-14B-Instruct-MLX-8bit
  Qwen2ForCausalLM, GQA 40:8, ventana deslizante 131072, 48 capas | ctx 32768 | KV 196608 B/tok (24.00 GB @128k)
  mlx, safetensors, qwen2, code, codeqwen, chat, qwen, qwen-coder, text-generation, conversational
5. **ggml-org/Qwen2.5-Coder-1.5B-32B-speculative-GGUF** (108 descargas) — https://huggingface.co/ggml-org/Qwen2.5-Coder-1.5B-32B-speculative-GGUF
  GGUF
  gguf, code, codeqwen, chat, qwen, qwen-coder, text-generation, en, endpoints_compatible, conversational
6. **akhauriyash/DeepSeek-R1-Distill-Qwen-1.5B-SpeculativeReasoner** (77 descargas) — https://huggingface.co/akhauriyash/DeepSeek-R1-Distill-Qwen-1.5B-SpeculativeReasoner
  Qwen2ForCausalLM, GQA 12:2, ventana deslizante 4096, 28 capas | ctx 131072 | KV 28672 B/tok (3.50 GB @128k)
  transformers, safetensors, qwen2, text-generation, generated_from_trainer, open-r1, trl, sft, conversational, dataset:akhauriyash/OpenR1_Math_SpeculativeReasoning
7. **Contin2024/qwen3-0.6B-speculative-gguf-s** (23 descargas) — https://huggingface.co/Contin2024/qwen3-0.6B-speculative-gguf-s
  GGUF
  gguf, endpoints_compatible, conversational
8. **mradermacher/DeepSeek-R1-Distill-Qwen-1.5B-GRPO-SpeculativeReasoner-GGUF** (14 descargas) — https://huggingface.co/mradermacher/DeepSeek-R1-Distill-Qwen-1.5B-GRPO-SpeculativeReasoner-GGUF
  GGUF
  transformers, gguf, generated_from_trainer, open-r1, trl, grpo, en, dataset:akhauriyash/OpenR1_Math_SpecR_GRPO, endpoints_compatible, conversational
9. **Tech-Awesome-Hub/deepseek-distilled-qwen-1.5B** (5 descargas) — https://huggingface.co/Tech-Awesome-Hub/deepseek-distilled-qwen-1.5B
  Qwen2ForCausalLM, GQA 12:2, ventana deslizante 4096, 28 capas | ctx 131072 | KV 28672 B/tok (3.50 GB @128k)
  transformers, safetensors, qwen2, text-generation, conversational, text-generation-inference, endpoints_compatible
10. **Jefferzn/my-awesome-distilled-model** (2 descargas) — https://huggingface.co/Jefferzn/my-awesome-distilled-model
  MobileNetV2ForImageClassification
  safetensors, mobilenet_v2
11. **AwesomeCuber/gemma-4-26b-a4b-distilled-v1-merged** (1 descargas) — https://huggingface.co/AwesomeCuber/gemma-4-26b-a4b-distilled-v1-merged
  Gemma4ForConditionalGeneration
  safetensors, gemma4

## Codigo (GitHub)

1. **bunyaminergen/Qwen2.5-Coder-1.5B-Instruct-Reasoning** (9 estrellas) — https://github.com/bunyaminergen/Qwen2.5-Coder-1.5B-Instruct-Reasoning
  Python
  This repository provides everything you need to perform Supervised Fine-Tuning (SFT) of the Qwen2.5-Coder-1.5B-Instruct model—or any of its larger variants (7B, 14B, 32B)—on the Qwen Models, using the
2. **NVIDIA/Model-Optimizer** (3267 estrellas) — https://github.com/NVIDIA/Model-Optimizer
  Python
  A unified library of SOTA model optimization techniques like quantization, distillation, pruning, neural architecture search, speculative decoding, etc. It compresses deep learning models for downstre
3. **AGN000/foam-cfd-deploy** (4 estrellas) — https://github.com/AGN000/foam-cfd-deploy
  Python
  v2 — LLM-driven OpenFOAM agent: Qwen2.5-Coder-14B + 13 parametric gmsh templates + REPL. Full pipeline (LLM → CFDParams → polyMesh → OpenFOAM v2412 case → solver → score).
4. **findshan/qwen3-coder-distill** (1 estrellas) — https://github.com/findshan/qwen3-coder-distill
  Python
  Fully open, reproducible distillation of Claude's coding ability into a local Qwen3-14B (verifiable-reward SFT). Data pipeline, seeds, teacher prompts, configs & eval all public.
5. **peterzat/qwen-2.5-localreview** (1 estrellas) — https://github.com/peterzat/qwen-2.5-localreview
  Shell
  Local adversarial code reviewer using Qwen2.5-Coder-14B via vLLM offline inference
6. **lucidrains/speculative-decoding** (307 estrellas) — https://github.com/lucidrains/speculative-decoding
  Python
  Explorations into some recent techniques surrounding speculative decoding
7. **ccs96307/fast-llm-inference** (11 estrellas) — https://github.com/ccs96307/fast-llm-inference
  Python
  Accelerating LLM inference with techniques like speculative decoding, quantization, and kernel fusion, focusing on implementing state-of-the-art research papers.
8. **harsha-gouru/gpu-inference-playground** (5 estrellas) — https://github.com/harsha-gouru/gpu-inference-playground
  Python
  Benchmark LLM inference techniques on GPU — KV cache, quantization, FlashAttention, speculative decoding, continuous batching. Runs on H100/MI300X via Modal/RunPod.
9. **Panmax/awesome-nuwa** (229 estrellas) — https://github.com/Panmax/awesome-nuwa
  Awesome list of 女娲.skill — 用女娲蒸馏的人物思维框架合集 | Distilled human thinking frameworks for Claude Code
10. **slowernews/wisdom-tldr** (42 estrellas) — https://github.com/slowernews/wisdom-tldr
  Maxims distilled from awesome quotes. (WIP)
11. **TheMeinerLP/awesome** (3 estrellas) — https://github.com/TheMeinerLP/awesome
  Years of curating top-tier open source projects, distilled into a single, continuously updated list based on my starred repositories. Explore the best of the best! ⭐
12. **robinbraemer/awesome** (3 estrellas) — https://github.com/robinbraemer/awesome
  Years of curating top-tier open source projects, distilled into a single, continuously updated list based on my starred repositories. Explore the best of the best! ⭐

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **Step Guided Reasoning: Improving Mathematical Reasoning using Guidance Generation and Step Reasoning** — https://arxiv.org/abs/2410.19817v3
  contra: Qwen2.5-Coder-1.5B-Instruct-Reasoning
  Mathematical reasoning has been challenging for large language models (LLMs), and the introduction of step-by-step Chain-of-Thought (CoT) inference has significantly advanced the mathematical capabili
2. **GROK: From Quantitative Biomarkers to Qualitative Diagnosis via a Grounded MLLM with Knowledge-Guided Instruction** — https://arxiv.org/abs/2510.04281v1
  contra: Qwen2.5-Coder-1.5B-Instruct-Reasoning
  Multimodal large language models (MLLMs) hold promise for integrating diverse data modalities, but current medical adaptations such as LLaVA-Med often fail to fully exploit the synergy between color f
3. **Emotion-LLaMAv2 and MMEVerse: A New Framework and Benchmark for Multimodal Emotion Understanding** — https://arxiv.org/abs/2601.16449v2
  contra: Qwen2.5-Coder-14B-Instruct
  Understanding human emotions from multimodal signals poses a significant challenge in affective computing and human-robot interaction. While multimodal large language models (MLLMs) have excelled in g
