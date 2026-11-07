# Mini AI Phase 1B — 30-day GPU MVP research

Research checked: **2026-11-07**. Pricing and quotas can change and depend on account eligibility, region and credit availability.

## Important distinction

No provider below guarantees a **free, dedicated GPU operating continuously 24/7 for an entire month**. Treat free offers as measured compute budgets, session quotas or startup credits, not as permanent GPU hosting. Keep the Linux VPS as the always-on app/auth/memory gateway and run GPU inference **on demand**.

## Ranked options for Mini AI

| Provider | Verified free allotment | Suitable for | Main limitation |
| --- | --- | --- | --- |
| **Modal Starter** | $30 of compute credit **per month** | Best fit for a serverless Mini inference endpoint that can scale to zero when idle | GPU + CPU + RAM are charged while running; usage over credits may be billed; cold starts |
| **Lightning AI Free** | 5 starter credits, plus 25 extra after card addition, up to ~80 GPU hours on some interruptible instance types | GPU debugging, Chatterbox voice tuning, latency benchmarks | 30 credits not guaranteed without adding card; free Studio restart rules, GPU capacity varies |
| **Kaggle Notebooks** | ~30 GPU hours per **week**, sometimes higher depending on availability | Free test sessions for Chatterbox and Whisper | Notebook sessions, not a production API; quota can vary |
| **Hugging Face ZeroGPU** | Up to 2 shared GPU Spaces for eligible verified accounts >30 days old; 5 daily GPU minutes per free user | Public queue-based speech demonstration | Gradio SDK only; supported PyTorch 2.8+ and Python versions may conflict with our current model code; not always-on |
| **Google Colab Free** | Dynamic GPU availability, no fixed monthly promise | Interactive experiments only | Managed runtimes explicitly restrict unrelated web services, remote proxies and free-tier SSH/background workers |
| **AWS Activate Founders** | $1,000 credits for eligible self-funded startups (approval required) | Longer-lived GPU MVP if GPU service quota approved | Not immediately guaranteed; GPU-instance quotas/account policies; costs after credits |
| **NVIDIA Inception** | Startup program is free; approved members can request offers including free cloud partner credits | Additional GPU runway and investor visibility | Startup criteria and grant availability; not an automatic GPU allocation |
| **Google Cloud Free Trial** | $300 for 90 days for eligible new users | Basic cloud resources, *not GPU before activation* | A free-trial billing account cannot attach GPUs; upgrade to paid billing to unlock, with billing risk |

## Economics (indicative only)

Modal's official listed GPU-only spot-equivalent list rates, excluding CPU/RAM, setup overhead and egress:

- T4: $0.000164/second (about $0.59/hour) → $30 covers at most about 50 GPU-only hours if entirely allocated to that GPU.
- L4: $0.000222/second (about $0.80/hour) → at most about 37 GPU-only hours before accompanying CPU/RAM costs.
- Use no always-warm container during the free-credit phase. Keep the worker at zero idle capacity, unless a scheduled investor demo needs prewarming.
- Set an explicit spending limit/budget and monitor remaining credits daily. Credits are **not** a zero-cost guarantee if automatic overage billing is enabled.

## Recommended Mini AI architecture

```text
Vercel → Mini frontend (mobile UI)
     ↓ HTTPS, authenticated user
Ubuntu VPS (2 vCPU / 8 GiB) → auth, sessions, profile, memory, quotas, small LLM experiment
     ↓ authenticated service request, no client-held GPU key
Modal (on-demand T4/L4) → Chatterbox reference-conditioned voice generation
     ↓ generated audio, not model weights
VPS / frontend → user hears Mini
```

For prototyping, use Lightning or Kaggle independently to test voice quality and loading time before packaging the inference container for Modal. Do not expose the user-supplied voice references or model weights on public GitHub or in a public Hugging Face Space.

For truly **continuous human-like duplex speech**, there is no verified no-cost 720-hour GPU offer here. Plan an investor demo window and collect actual cost-per-turn metrics rather than running a GPU 24/7.

## Four-week MVP path

**Week 1 — Get an audible prototype:** validate the two authorized voice references and run Chatterbox Nano/Turbo on a GPU notebook, compare Friend vs Mentor quality and record cold/warm latency, CPU/RAM/VRAM and real-time factor.

**Week 2 — Serve one secure voice turn:** move the best working TTS configuration into a Modal function (or approved GPU grant), authenticate from the existing Ubuntu API gateway, enforce per-user quotas, add cache and rate limits, and avoid persistent GPU idling.

**Week 3 — Pilot with invited testers:** profile/onboarding → speech recognition → real Mini reply → cloned voice; capture opt-in feedback, response latency, median cost per successful turn, crashes, and repeat use. Keep a fallback browser voice when GPU is exhausted.

**Week 4 — Fundraising evidence:** demonstrate live voice with two styles, publish honest latency figures (p50/p95), per-minute cost, user engagement, retention/return rates and a priced 100-user / 1,000-user roadmap. Pitch a measurable companion, not unverified AGI/24×7 claims.

## Confirmed primary sources

- Modal pricing and Starter $30/month: https://modal.com/pricing
- Lightning free trial terms: https://lightning.ai/pricing and https://support.lightning.ai/pricing/
- Kaggle free GPU-hours quota: https://www.kaggle.com/docs/efficient-gpu-usage
- Hugging Face ZeroGPU host eligibility, quotas and Gradio compatibility: https://huggingface.co/docs/hub/en/spaces-zerogpu
- Colab free GPU restrictions: https://research.google.com/colaboratory/faq.html
- AWS Activate (June 2026): https://aws.amazon.com/aws-startups/learn/applying-for-aws-activate-credits-a-step-by-step-guide/
- NVIDIA Inception: https://www.nvidia.com/en-us/startups/
- Google Cloud free-trial GPU restrictions: https://docs.cloud.google.com/free/docs/free-cloud-features

**Decision checkpoint:** start with Lightning + Kaggle for model experiments; use Modal Starter for on-demand, controlled investor demos. Apply for startup credits simultaneously if eligible. Do not modify the Vercel production app's provider routing until the chosen GPU provider and secure server adapter have been tested end to end.
