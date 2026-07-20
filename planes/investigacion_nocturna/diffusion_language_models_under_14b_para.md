# Investigacion: diffusion language models under 14B parameters text generation

Queries ejecutadas (4): `diffusion language models`, `text generation under 14B`, `awesome language models`, `HuggingFace models 14B`

## Resumen

The search results provide information about diffusion language models under 14B parameters, focusing on their text generation capabilities. Specifically, the "A Cheaper and Better Diffusion Language Model with Soft-Masked Noise" paper introduces Masked-Diffuse LM, which uses soft-masking to add corruptions to text and directly predicts categorical distributions for better performance. Another relevant model is the "Latent Space Language Diffusion Model" from Hugging Face, which is a 201M parameter model that generates text by predicting all tokens in parallel, validated by an autoregressive oracle. Additionally, the "DiffusionBERT" paper combines diffusion models with pre-trained language models like BERT to improve text generation quality. These models demonstrate advancements in handling discrete data like languages and offer promising solutions for text generation tasks.

## Modelos (HuggingFace)

1. **brianschwabauer/latent-space-language-diffusion-model** (879 descargas) — https://huggingface.co/brianschwabauer/latent-space-language-diffusion-model
  MDLMBPEV3
  safetensors, mdlm, masked-diffusion, text-generation, parallel-decoding, diffusion, splatsdb, open-weights, reproducible, non-autoregressive
2. **LanguageMachines/stable-diffusion-2-1-base** (1403 descargas) — https://huggingface.co/LanguageMachines/stable-diffusion-2-1-base
  diffusers, safetensors, stable-diffusion, text-to-image, endpoints_compatible, diffusers:StableDiffusionPipeline
3. **LanguageMachines/stable-diffusion-2-1** (107 descargas) — https://huggingface.co/LanguageMachines/stable-diffusion-2-1
  diffusers, safetensors, stable-diffusion, text-to-image, endpoints_compatible, diffusers:StableDiffusionPipeline
4. **Pekkapuuma/diffusion_policy_libero_extended_language** (53 descargas) — https://huggingface.co/Pekkapuuma/diffusion_policy_libero_extended_language
  safetensors
5. **bzh666/Graphics2Code-Qwen3-VL-4B-Generation-and-Understanding** (16 descargas) — https://huggingface.co/bzh666/Graphics2Code-Qwen3-VL-4B-Generation-and-Understanding
  Qwen3VLForConditionalGeneration
  safetensors, qwen3_vl
6. **bzh666/Graphics2Code-Qwen3-VL-8B-Generation-and-Understanding** (14 descargas) — https://huggingface.co/bzh666/Graphics2Code-Qwen3-VL-8B-Generation-and-Understanding
  Qwen3VLForConditionalGeneration
  safetensors, qwen3_vl
7. **huggingfacehugsjess/ai-models** (2 descargas) — https://huggingface.co/huggingfacehugsjess/ai-models
  diffusers, flux, lora, replicate, text-to-image, en
8. **buse/huggingface-models-buse** (1 descargas) — https://huggingface.co/buse/huggingface-models-buse
  DistilBertForSequenceClassification | ctx 512
  transformers, safetensors, distilbert, text-classification, generated_from_trainer, text-embeddings-inference, endpoints_compatible
9. **LanguageSavvy/my_awesome_eli5_mlm_model** (3 descargas) — https://huggingface.co/LanguageSavvy/my_awesome_eli5_mlm_model
  RobertaForMaskedLM, 6 capas | ctx 514 | KV 18432 B/tok (2.25 GB @128k)
  transformers, tf, roberta, fill-mask, generated_from_keras_callback, endpoints_compatible
10. **mosesdaudu/my_awesome_language_model** (1 descargas) — https://huggingface.co/mosesdaudu/my_awesome_language_model
  Wav2Vec2ForSequenceClassification, 12 capas | KV 36864 B/tok (4.50 GB @128k)
  pytorch, wav2vec2
11. **SLAM5566/huggingface_models** (0 descargas) — https://huggingface.co/SLAM5566/huggingface_models
12. **HuggingFaceH4/pref_models_mistral-7b-dpo** (0 descargas) — https://huggingface.co/HuggingFaceH4/pref_models_mistral-7b-dpo

## Evidencia (arXiv)

1. **A Cheaper and Better Diffusion Language Model with Soft-Masked Noise** — https://arxiv.org/abs/2304.04746v1
  2023 | cs.CL
  Diffusion models that are based on iterative denoising have been recently proposed and leveraged in various generation tasks like image generation. Whereas, as a way inherently built for continuous da
2. **DiffusionBERT: Improving Generative Masked Language Models with Diffusion Models** — https://arxiv.org/abs/2211.15029v2
  2022 | cs.CL
  We present DiffusionBERT, a new generative masked language model based on discrete diffusion models. Diffusion models and many pre-trained language models have a shared training objective, i.e., denoi
3. **A Comprehensive Survey of Scientific Large Language Models and Their Applications in Scientific Discovery** — https://arxiv.org/abs/2406.10833v3
  2024 | cs.CL
  In many scientific fields, large language models (LLMs) have revolutionized the way text and other modalities of data (e.g., molecules and proteins) are handled, achieving superior performance in vari
4. **How Do Large Language Models Capture the Ever-changing World Knowledge? A Review of Recent Advances** — https://arxiv.org/abs/2310.07343v1
  2023 | cs.CL
  Although large language models (LLMs) are impressive in solving various tasks, they can quickly be outdated after deployment. Maintaining their up-to-date status is a pressing concern in the current e
5. **A Survey on Multimodal Large Language Models** — https://arxiv.org/abs/2306.13549v4
  2023 | cs.CV
  Recently, Multimodal Large Language Model (MLLM) represented by GPT-4V has been a new rising research hotspot, which uses powerful Large Language Models (LLMs) as a brain to perform multimodal tasks. 
6. **A Survey on Vision-Language-Action Models for Embodied AI** — https://arxiv.org/abs/2405.14093v8
  2024 | cs.RO
  Embodied AI is widely recognized as a cornerstone of artificial general intelligence (AGI) because it involves controlling embodied agents to perform tasks in the physical world. Building on the succe
7. **VARCO-VISION: Expanding Frontiers in Korean Vision-Language Models** — https://arxiv.org/abs/2411.19103v1
  2024 | cs.CV
  In this paper, we introduce an open-source Korean-English vision-language model (VLM), VARCO-VISION. We incorporate a step-by-step training strategy that allows a model learn both linguistic and visua
8. **Improving Variable-Length Generation in Diffusion Language Models via Length Regularization** — https://arxiv.org/abs/2602.07546v1
  2026 | cs.CL
  Diffusion Large Language Models (DLLMs) are inherently ill-suited for variable-length generation, as their inference is defined on a fixed-length canvas and implicitly assumes a known target length. W
9. **Signature filtering: a lightweight enhancement for statistical watermark detection in large language models** — https://arxiv.org/abs/2606.18430v2
  2026 | cs.LG
  Statistical watermarks help organizations attribute large language model (LLM) outputs, yet existing detectors often struggle when watermark signals are weak, texts are repetitive, or watermarks are e
10. **World Simulation with Video Foundation Models for Physical AI** — https://arxiv.org/abs/2511.00062v2
  2025 | cs.CV
  We introduce [Cosmos-Predict2.5], the latest generation of the Cosmos World Foundation Models for Physical AI. Built on a flow-based architecture, [Cosmos-Predict2.5] unifies Text2World, Image2World, 
11. **Language Control Diffusion: Efficiently Scaling through Space, Time, and Tasks** — https://arxiv.org/abs/2210.15629v4
  2022 | cs.LG
  Training generalist agents is difficult across several axes, requiring us to deal with high-dimensional inputs (space), long horizons (time), and generalization to novel tasks. Recent advances with ar
12. **How Far Do On-Prem Open LLMs Get on Text-to-SQL? A Cross-Family Size x Technique Frontier on BIRD** — https://arxiv.org/abs/2606.29733v1
  2026 | cs.CL
  Organizations that cannot send data to a cloud API increasingly ask: how good is Text-to-SQL if the model must run on-premises on open weights, and which popular accuracy "recipes" are worth their com
13. **Motif-Video 2B: Technical Report** — https://arxiv.org/abs/2604.16503v2
  2026 | cs.CV
  Training strong video generation models usually requires massive datasets, large parameter counts, and substantial compute. In this work, we ask whether strong text-to-video quality is possible at a m
14. **Amadeus-Verbo Technical Report: The powerful Qwen2.5 family models trained in Portuguese** — https://arxiv.org/abs/2506.00019v1
  2025 | cs.CL
  This report introduces the experience of developing Amadeus Verbo, a family of large language models for Brazilian Portuguese. To handle diverse use cases, Amadeus Verbo includes base-tuned, merged, a

## Codigo (GitHub)

1. **ML-GSAI/LLaDA** (3902 estrellas) — https://github.com/ML-GSAI/LLaDA
  Python
  Official PyTorch implementation for "Large Language Diffusion Models"
2. **google-deepmind/proactive_t2i_agents** (76 estrellas) — https://github.com/google-deepmind/proactive_t2i_agents
  Python
  Code release for the paper, "Proactive Agents for Text-to-Image Generation under Uncertainty"
3. **Xiaofeng-Tan/MotionRFT** (32 estrellas) — https://github.com/Xiaofeng-Tan/MotionRFT
  Python
  [Under Review] This repository is the official implementation of "MotionRFT:  Unified Reinforcement Fine-Tuning for Text-to-Motion Generation"
4. **nikhil-dce/Learning-Disentangled-Representations-under-Supervision** (24 estrellas) — https://github.com/nikhil-dce/Learning-Disentangled-Representations-under-Supervision
  Python
  Controllable Text Generation using variational auto-encoder (VAE) and text CNN
5. **testzer0/AmbiQT** (11 estrellas) — https://github.com/testzer0/AmbiQT
  Python
  Code and Assets for "Benchmarking and Improving Text-to-SQL Generation Under Ambiguity" (EMNLP 2023)
6. **ogulcanaydogan/Turkish-LLM** (1 estrellas) — https://github.com/ogulcanaydogan/Turkish-LLM
  Python
  Turkey's first open-source family of Turkish language models (7B & 14B)
7. **sgl-project/sglang** (30546 estrellas) — https://github.com/sgl-project/sglang
  Python
  SGLang is a high-performance serving framework for large language models and multimodal models.
8. **BradyFU/Awesome-Multimodal-Large-Language-Models** (17953 estrellas) — https://github.com/BradyFU/Awesome-Multimodal-Large-Language-Models
  :sparkles::sparkles:Latest Advances on Multimodal Large Language Models
9. **luban-agi/Awesome-AIGC-Tutorials** (4520 estrellas) — https://github.com/luban-agi/Awesome-AIGC-Tutorials
  Curated tutorials and resources for Large Language Models, AI Painting, and more. 
10. **GT-RIPL/Awesome-LLM-Robotics** (4429 estrellas) — https://github.com/GT-RIPL/Awesome-LLM-Robotics
  A comprehensive list of papers using large language/multi-modal models for Robotics/RL, including papers, codes, and related websites
11. **ZHZisZZ/dllm** (2650 estrellas) — https://github.com/ZHZisZZ/dllm
  Python
  dLLM: Simple Diffusion Language Modeling
12. **morningstarnasser/MORNINGSTAR-AI-MODEL** (0 estrellas) — https://github.com/morningstarnasser/MORNINGSTAR-AI-MODEL
  Python
  Elite Open-Source Coding AI — 3 Models: 14B, 32B, Vision. Built on Qwen2.5-Coder & LLaVA. 19/19 Benchmark Score. Ollama & GGUF ready. Apache 2.0.
13. **HuaizhengZhang/AI-Infra-from-Zero-to-Hero** (4210 estrellas) — https://github.com/HuaizhengZhang/AI-Infra-from-Zero-to-Hero
  🚀 Awesome System for Machine Learning ⚡️ AI System Papers and Industry Practice. ⚡️ System for Machine Learning, LLM (Large Language Model), GenAI (Generative AI). 🍻 OSDI, NSDI, SIGCOMM, SoCC, MLSys, 
14. **fetchwiki/deepcogito-cogito-v1-preview-qwen-14B** (1 estrellas) — https://github.com/fetchwiki/deepcogito-cogito-v1-preview-qwen-14B
  Mirror of deepcogito/cogito-v1-preview-qwen-14B from HuggingFace (model files excluded)
15. **fetchwiki/bartowski-deepcogito_cogito-v1-preview-qwen-14B-GGUF** (0 estrellas) — https://github.com/fetchwiki/bartowski-deepcogito_cogito-v1-preview-qwen-14B-GGUF
  Mirror of bartowski/deepcogito_cogito-v1-preview-qwen-14B-GGUF from HuggingFace (model files excluded)
16. **yl4579/StyleTTS2** (6312 estrellas) — https://github.com/yl4579/StyleTTS2
  Python
  StyleTTS 2: Towards Human-Level Text-to-Speech through Style Diffusion and Adversarial Training with Large Speech Language Models

## Contraevidencia

Fuentes que matizan o contradicen a los candidatos de arriba. NO son un veredicto: leelas y decidi vos.

1. **Language Generation as Optimal Control: Closed-Loop Diffusion in Latent Control Space** — https://arxiv.org/abs/2605.14531v3
  contra: latent-space-language-diffusion-model
  This work reformulates language generation as a stochastic optimal control problem, providing a unified theoretical perspective to analyze autoregressive and diffusion models and explain their limitat
2. **Cosmos: Compressed and Smooth Latent Space for Text Diffusion Modeling** — https://arxiv.org/abs/2506.21170v3
  contra: latent-space-language-diffusion-model
  Autoregressive language models dominate modern text generation, yet their sequential nature introduces fundamental limitations: decoding is slow, and maintaining global coherence remains challenging. 
3. **LLaDA-Rec: Discrete Diffusion for Parallel Semantic ID Generation in Generative Recommendation** — https://arxiv.org/abs/2511.06254v1
  contra: LLaDA
  Generative recommendation represents each item as a semantic ID, i.e., a sequence of discrete tokens, and generates the next item through autoregressive decoding. While effective, existing autoregress
4. **Arg-LLaDA: Argument Summarization via Large Language Diffusion Models and Sufficiency-Aware Refinement** — https://arxiv.org/abs/2507.19081v4
  contra: LLaDA
  Argument summarization aims to generate concise, structured representations of complex, multi-perspective debates. While recent work has advanced the identification and clustering of argumentative com
5. **A Cheaper and Better Diffusion Language Model with Soft-Masked Noise** — https://arxiv.org/abs/2304.04746v1
  contra: stable-diffusion-2-1-base
  Diffusion models that are based on iterative denoising have been recently proposed and leveraged in various generation tasks like image generation. Whereas, as a way inherently built for continuous da
6. **Stable Diffusion For Aerial Object Detection** — https://arxiv.org/abs/2311.12345v1
  contra: stable-diffusion-2-1-base
  Aerial object detection is a challenging task, in which one major obstacle lies in the limitations of large-scale data collection and the long-tail distribution of certain classes. Synthetic data offe
