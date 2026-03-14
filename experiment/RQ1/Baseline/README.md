# ReqElicitBench (ReqElicitGym)

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Gymnasium](https://img.shields.io/badge/gymnasium-0.26%2B-green.svg)](https://gymnasium.farama.org/)

**ReqElicitBench** is the official implementation and benchmark code for the paper:

**ReqElicitGym: An Evaluation Environment for Interview Competence in Conversational Requirements Elicitation**  
Dongming Jin, Zhi Jin*, Zheng Fang, Linyu Li, Xiaotian Yang, Yuanpeng He, Xiaohong Chen

**Language**: [English](README.md) | [中文](README_zh.md)

## 📖 Introduction

With rapidly improving LLM coding ability, a major bottleneck of LLM-based software development is shifting to **eliciting accurate and complete requirements**. ReqElicitGym provides an **interactive and automatic evaluation environment** to assess an agent/LLM’s **interview competence** in *conversational requirements elicitation*.

This repo includes:

- **Benchmark dataset** with **101** website requirements-elicitation scenarios spanning **10** application types (`ReqElicitGym/data/test.json`)
- An **oracle user** (LLM-based simulated stakeholder) grounded in predefined implicit requirements
- A **task evaluator (judge)** that classifies interviewer actions and tracks which implicit requirements are elicited turn-by-turn
- **Reproducible evaluation scripts** producing conversation logs and quantitative metrics

## 🚀 Quick Start

### Requirements

- Python 3.8+
- An **OpenAI-compatible** chat-completions API endpoint (set `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL`)

### Installation

```bash
pip install -r requirements.txt
```

### API Key Configuration

Set API credentials via environment variables:

```bash
export OPENAI_API_KEY="your-api-key"
# Optional: OpenAI-compatible gateway/proxy endpoint
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

Optional: configure judge/user separately (otherwise they reuse `OPENAI_API_KEY` and `OPENAI_BASE_URL`):

```bash
export JUDGE_API_KEY="your-judge-key"
export USER_API_KEY="your-user-key"
export JUDGE_BASE_URL="your-judge-base-url"
export USER_BASE_URL="your-user-base-url"
```

### Run Evaluation (all tasks)

```bash
bash run_reqelicitgym.sh
```

Or run the Python entry directly:

```bash
python3 run_reqelicitgym.py \
  --interviewer-model "Pro/deepseek-ai/DeepSeek-V3.2" \
  --gym-model "gpt-5.2" \
  --data-path "ReqElicitGym/data/test.json"
```

Enable “thinking” mode (used by some providers/models):

```bash
python3 run_reqelicitgym.py --use-thinking
```

Tip for debugging: create a smaller JSON file and pass it via `--data-path`.

## 📁 Project Structure

```text
ReqElicitBench/
├── ReqElicitGym/                     # Core environment package
│   ├── config.py                     # ReqElicitGymConfig
│   ├── interviewer.py                # Interviewer wrapper (model under evaluation)
│   ├── data/
│   │   └── test.json                 # 101 tasks (benchmark scenarios)
│   └── env/
│       ├── reqelicit_gym.py          # Gymnasium Env + metrics computation
│       ├── prompts.py                # Model calls (judge/user) + evaluation pipeline
│       ├── utils.py                  # Prompt templates + helpers
│       └── task_data.py              # Dataset loader
├── run_reqelicitgym.py               # Main evaluation runner (all tasks)
├── run_reqelicitgym.sh               # Shell wrapper
├── metrics_result/                   # Saved evaluation metrics (JSON)
├── conversation_result/              # Saved conversations (JSON)
└── ReqElicitGym.pdf                  # Paper PDF (for convenience)
```

## 🔧 Command Line Arguments

Run `python3 run_reqelicitgym.py --help` for the full list. Common options:

- `--api-key`: API key (or use `OPENAI_API_KEY`)
- `--base-url`: API base URL (or use `OPENAI_BASE_URL`)
- `--interviewer-model`: the **model under evaluation** (interviewer)
- `--gym-model`: the **gym model** used by **judge + oracle user** (default: `gpt-5.2`)
- `--use-thinking`: enable “thinking” mode for the interviewer (implementation uses an OpenAI-compatible `extra_body`)
- `--data-path`: path to task JSON (default: `ReqElicitGym/data/test.json`)
- `--verbose`: verbose logging

## 📦 Dataset Format

Each task in `ReqElicitGym/data/test.json` is a JSON object with:

- `name`: system name
- `application_type`: one of 10 application types
- `initial_requirements`: underspecified initial requirement statement (first user utterance)
- `Implicit Requirements`: a list of implicit requirements, each with:
  - `Aspect`: `Interaction` / `Content` / `Style`
  - `RequirementText`: the hidden requirement text
- `URL`: a “complete” user story list (reference target artifact)

## 📊 Metrics & Outputs

After running, two artifacts are produced:

- `metrics_result/<llm>_<thinking|no_thinking>_all.json`
  - `overall_evaluation`: overall metrics across all tasks, including:
    - **Elicitation Ratio (IRE)**: implicit requirement elicitation rate
    - **TKQR**: Turn-discounted Key Question Rate
    - **ORA**: Optimal Round Assessment
    - **action_type_effectiveness**: effectiveness by `probe/clarify/finish/...`
    - **aspect_type_elicitation**: elicitation ratio by `Interaction/Content/Style`
    - **application_type_statistics**: per application-type breakdown
  - `task_results`: per-task metrics

- `conversation_result/<llm>_<thinking|no_thinking>_all.json`
  - Per-task conversation turns with `action_type`, whether it hit an implicit requirement, and turn-level `elicitation_ratio`

## ⚠️ Notes

- **API compatibility**: The implementation uses the `openai` Python client with an **OpenAI-compatible** `chat.completions` endpoint. If your provider uses different “thinking” parameters, adjust `ReqElicitGym/env/prompts.py`.
- **Cost**: Running all 101 tasks calls LLMs for **interviewer + judge + oracle user**; expect non-trivial time/cost.

## 📝 Citation

If you use this repository in your research, please cite our paper.

## 📄 License

No license file is included in this snapshot. Please contact the authors if you need licensing/usage clarification.
