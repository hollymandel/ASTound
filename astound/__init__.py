import json
import os

import jedi

def load_config():
    with open("astound/config.json", "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    return config


astound_config = load_config()
jedi.settings.fast_parser = astound_config["jedi"]["fast_parser"]
claude_model = astound_config["claude_model"]