import json
from types import MappingProxyType
from typing import Optional, Union

from astound import api_key, claude_model
from astound.node import Node

with open("data/prompts.json", "r", encoding="UTF-8") as f:
    PROMPTS = MappingProxyType(json.load(f))

MESSAGE_KWARGS = MappingProxyType(
    {
        "model": claude_model,
        "max_tokens": 200,
        "temperature": 0.0,
        "system": PROMPTS["system_prompt"],
        "api_key": api_key,
    }
)


def child_header(child):
    if hasattr(child, "ast_node"):
        return f"Here is information about a child of type {type(child.ast_node)}.\n"
    return "Here is information about a child.\n"


def summarize(node: Node, prompts: Optional[Union[MappingProxyType, dict]] = None):
    """Recursive summarization via language model. Start at leaf nodes, summarize,
    then summarize parents using summaries of children and text of parent."""
    prompts = prompts or PROMPTS
    client = Node.anthropic_client

    if len(node.summary) > 0:
        return node.summary

    individual_prompt = prompts["individual_header"] + "".join(node.get_text())

    individual_summary = (
        client.messages.create(
            **MESSAGE_KWARGS, messages=[{"role": "user", "content": individual_prompt}]
        )
        .content[0]
        .text
    )

    if len(node.children) == 0:
        node.summary = individual_summary
    else:
        joint_prompt = (
            prompts["joint_header"]
            + individual_summary
            + "\n".join(
                [f"{child_header(x)}{summarize(x)}" for x in node.children.values()]
            )
        )

        joint_summary = (
            client.messages.create(
                **MESSAGE_KWARGS, messages=[{"role": "user", "content": joint_prompt}]
            )
            .content[0]
            .text
        )

        node.summary = joint_summary

    return node.summary
