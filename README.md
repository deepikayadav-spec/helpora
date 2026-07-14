---
title: Helpora
emoji: 🤖
colorFrom: blue
colorTo: indigo
sdk: streamlit
sdk_version: 1.40.0
app_file: app.py
pinned: false
---

# Helpora 🤖

A payments & scholarship support agent · Agentic AI Workshop · NIAT

Helpora reads a student's records, decides what happened, and either answers
directly or files a task for a human. It handles two kinds of tickets:

- **Refunds** — e.g. "I was charged twice."
- **Scholarships / fee waivers** — e.g. "My waiver isn't on my invoice."

## Setup

Add your OpenRouter key as a **Secret** (Settings → Variables and secrets):

- Name: `OPENROUTER_KEY`
- Value: your OpenRouter API key
