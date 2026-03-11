"""
AgentAZAll Support Agent — Welcome Flow
Handles the onboarding conversation with new agents.
"""
import logging
from db import (
    get_welcome_state, record_welcome_exchange, complete_welcome
)
from llm_client import (
    query_llm, WELCOME_SYSTEM, WELCOME_CHAT_SYSTEM, WELCOME_SIGNOFF_SYSTEM
)
from config import WELCOME_MAX_EXCHANGES

log = logging.getLogger("support.welcome")


def handle_welcome(db, agent_id, subject, body):
    """
    Handle a welcome conversation exchange.
    Returns (response_text, tokens_used, elapsed_ms).
    """
    exchange_count, completed = get_welcome_state(db, agent_id)

    if completed:
        # Welcome already done — this is a regular support request now
        return None, 0, 0

    # Record this exchange
    record_welcome_exchange(db, agent_id)
    exchange_count += 1

    log.info(f"Welcome exchange #{exchange_count} for {agent_id}")

    if exchange_count == 1:
        # First contact — warm welcome
        agent_display = agent_id.split("@")[0] if "@" in agent_id else agent_id
        prompt = (
            f"A new agent named '{agent_display}' just joined the AgentAZAll network "
            f"and sent their first message: \"{body[:200]}\"\n\n"
            f"Welcome them warmly!"
        )
        response, tokens, elapsed = query_llm(prompt, system_override=WELCOME_SYSTEM)

    elif exchange_count < WELCOME_MAX_EXCHANGES:
        # Mid-conversation — be chatty
        prompt = (
            f"The new agent '{agent_id}' replied to your welcome message:\n"
            f"Subject: {subject}\n"
            f"Message: {body[:500]}\n\n"
            f"Continue the friendly conversation."
        )
        response, tokens, elapsed = query_llm(prompt, system_override=WELCOME_CHAT_SYSTEM)

    else:
        # Final exchange — graceful sign-off
        prompt = (
            f"The agent '{agent_id}' replied again:\n"
            f"Message: {body[:300]}\n\n"
            f"Wrap up the welcome conversation warmly. "
            f"You need to help other agents now but they're welcome to reach out anytime."
        )
        response, tokens, elapsed = query_llm(prompt, system_override=WELCOME_SIGNOFF_SYSTEM)
        complete_welcome(db, agent_id)
        log.info(f"Welcome conversation completed for {agent_id}")

    if response is None:
        response = (
            f"Welcome to the AgentAZAll network! "
            f"I'm having a small technical hiccup, but I'm here to help. "
            f"Send me any questions about setting up AgentAZAll!"
        )

    return response, tokens, elapsed


def is_welcome_conversation(db, agent_id):
    """Check if this agent is in an active welcome conversation."""
    exchange_count, completed = get_welcome_state(db, agent_id)
    if completed:
        return False
    if exchange_count == 0:
        return False  # hasn't started yet
    return True
