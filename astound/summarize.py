import ast
import json
from types import MappingProxyType
from typing import Optional, Union, Dict

import anthropic
from astound.smartnode import SmartNode

with open("astound/prompts.json", "r") as f:
    PROMPTS = MappingProxyType(json.load(f))

MESSAGE_KWARGS = MappingProxyType(
    {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 200,
        "temperature": 0.0,
        "system": PROMPTS["system_prompt"],
        # "api_key": YOUR_API_KEY
    }
)

def summarize(
    node: SmartNode, client, prompts: Optional[Union[MappingProxyType, Dict]] = None
):
    prompts = prompts or PROMPTS

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
                [
                    f"{child_header(x)}{x.summarize(client)}"
                    for x in node.children.values()
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

        node.summary = joint_summary

    return node.summary
