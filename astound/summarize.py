import ast
from types import MappingProxyType
from typing import Optional

import anthropic
import smartnode

MESSAGE_KWARGS = MappingProxyType(
    {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 200,
        "temperature": 0.0,
        "system": SYSTEM_PROMPT,
        # "api_key": YOUR_API_KEY
    }
)

FORBIDDEN_TYPES = (ast.ImportFrom, ast.Import, ast.ListComp)

with open("prompts.json", "r") as f:
    PROMPTS = MappingProxyType(json.load(f))


def summarize(
    node: SmartNode, client, prompts: Optional[Union[MappingProxyType, Dict]] = None
):
    prompts = prompts or PROMPTS

    if len(node._summary) > 0:
        return node._summary

    individual_prompt = prompts["individual_header"] + "".join(node.get_text())

    individual_summary = (
        client.messages.create(
            **MESSAGE_KWARGS, messages=[{"role": "user", "content": individual_prompt}]
        )
        .content[0]
        .text
    )

    if len(node._children) == 0:
        node.summary = individual_summary
    else:
        joint_prompt = (
            prompts["joint_header"]
            + individual_summary
            + "\n".join(
                [
                    f"{child_header(x)}{x.summarize(client)}"
                    for x in node._children.values()
                ]
            )
        )

        joint_summary = (
            client.messages.create(
                **MESSAGE_KWARGS, messages=[{"role": "user", "content": joint_prompt}]
            )
            .content[0]
            .text
        )

        node._summary = joint_summary

    return node._summary
