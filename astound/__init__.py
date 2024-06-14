import json
import os

import jedi


class NoAnthropicAPIKey(Exception):
    pass


def load_config():
    with open("astound/config.json", "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    jedi.settings.fast_parser = config["jedi"]["fast_parser"]
    return config


astound_config = load_config()

api_key = os.getenv("ANTHROPIC_API_KEY", astound_config["api_key"])
if not api_key:
    raise NoAnthropicAPIKey(
        "An Anthropic API key must be supplied either as an environment variable (ANTHROPIC_API_KEY) or in astound/config.json"
    )

claude_model = astound_config["claude_model"]