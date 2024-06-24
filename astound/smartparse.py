import ast
import json
import logging
from types import MappingProxyType

from astound import claude_model
from astound.ast_node_utils import pretty_type

with open("data/prompts.json", "r", encoding="UTF-8") as f:
    PROMPTS = MappingProxyType(json.load(f))

MESSAGE_KWARGS = MappingProxyType(
    {
        "model": claude_model,
        "max_tokens": 50,
        "temperature": 0.0,
        "system": PROMPTS["field_system_prompt"],
    }
)


def type_header(t):
    return (
        f"Which subfields of a python ast node of type {t} contain child nodes? "
        "Omit fields that contain only strings. Strongly consider fields named 'value', 'func', or 'body'."
        "Return only immediate subfields, i.e. 'subfield' is ok but 'subfield.subsubfield' is not. "
    )


def validate_field(ast_node, field):
    if not hasattr(ast_node, field):
        logging.info(
            "Claude generated invalid field: node of type '%s' has no field '%s'",
            type(ast_node),
            field,
        )
        return False
    this_attr = getattr(ast_node, field)

    # ambiguous case - field could be valid but empty
    if not this_attr:
        return True

    if isinstance(this_attr, ast.AST):
        return True

    if isinstance(this_attr, list):
        if isinstance(this_attr[0], ast.AST):
            return True
        logging.info(
            "Claude generated invalid field: field '%s :: %s' is a list of objects that are not ast nodes",
            type(ast_node),
            field,
        )
        return False

    logging.info(
        "Claude generated invalid field: field '%s :: %s' is not an ast node or list of ast nodes",
        type(ast_node),
        field,
    )
    return False


def parser_type_query(
    ast_node: ast.AST,
    anthropic_client: "anthropic.Anthropic",
    sqlite_conn: "sqlite3.Connection",
):
    """
    Determines which attributes of an ast node of a given type contain
    child nodes by querying a language model. Avoids duplicate queries by maintaining
    a database of types already encountered.

    Inputs:
        ast_node: ast node of the desired type. Note that while the query only depends
            on the type of t, passing the entire node allows the parser to validate
            its response.
        anthropic_client: language model API client
        sqlite_conn: database connection

    Returns:
        response (str): text list of names of fields that are (1.) attributes of the type
        ast_node and (2.) contain None, a single ast node, or a list of ast_nodes.
    """
    try:
        cursor = sqlite_conn.cursor()

        t = pretty_type(type(ast_node))
        cursor.execute("SELECT value FROM subfield_store WHERE key = ?", (t,))
        result = cursor.fetchone()

        if result:
            logging.info("found in db:: %s:%s", t, result)
            return result[0]

        prompt = type_header(t)
        pre_list = (
            anthropic_client.messages.create(
                **MESSAGE_KWARGS, messages=[{"role": "user", "content": prompt}]
            )
            .content[0]
            .text
        )
        pre_list = pre_list.replace(" ", "").split(",")

        # remove stray characters and invalid types from list
        field_list = [field for field in pre_list if validate_field(ast_node, field)]
        field_list = ",".join(field_list)
        logging.info("generated:: %s:%s", t, field_list)

        # insert into database
        cursor.execute(
            """INSERT INTO subfield_store (key, value) VALUES (?, ?)""",
            (t, field_list),
        )
        logging.info("Generated list for type %s:\n%s", t, field_list)

        return field_list

    finally:
        cursor.close()
