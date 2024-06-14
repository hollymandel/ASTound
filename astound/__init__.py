import json

import jedi


def load_config():
    with open("astound/config.json", "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    jedi.settings.fast_parser = config["jedi"]["fast_parser"]


load_config()
