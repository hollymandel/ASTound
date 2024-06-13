import json
from types import MappingProxyType
from typing import Optional, Union
import logging

with open("data/prompts.json", "r", encoding="UTF-8") as f:
    PROMPTS = MappingProxyType(json.load(f))

MESSAGE_KWARGS = MappingProxyType(
    {
        "model": "claude-3-haiku-20240307",
        "max_tokens": 50,
        "temperature": 0.0,
        "system": PROMPTS["field_system_prompt"],
        # "api_key": YOUR_API_KEY
    }
)


def type_header(type):
    return (
        f"Which subfields of a python ast node of type {type} contain child nodes? " + 
        "Return only immediate subfields, i.e. 'subfield' is ok but 'subfield.subsubfield' is not."
    )


def parser_type_query(
    type: str,
    anthropic_client,
    sqlite_conn
):
    try:
        cursor = sqlite_conn.cursor()
    
        type_query = cursor.execute(
            'SELECT value FROM subfield_store WHERE key = ?', (type,)
        )
        result = cursor.fetchone()
    
        if result: 
            response = result[0]
        else:
            if anthropic_client is None:
                raise KeyError("unknown type and no anthropic client")
            else:
                prompt = type_header(type)
                
            response = (
                anthropic_client.messages.create(
                    **MESSAGE_KWARGS, messages=[{"role": "user", "content": prompt}]
                )
                .content[0]
                .text
            ).replace(" ","")
        
            logging.info(f"Generated link for type {type}:\n{response}") 
        
            cursor.execute(
                '''INSERT INTO subfield_store (key, value) VALUES (?, ?)'''
                , (type, response)
            )
    finally:
        cursor.close()

    return response
