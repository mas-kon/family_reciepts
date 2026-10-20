"""Limit of parallel LLM jobs shared by the bot and the web app."""

import asyncio

# free LLM tiers are rate limited: do not hammer them when someone sends an album
llm_slots = asyncio.Semaphore(2)
