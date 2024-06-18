import ast

ALIASES = ("name", "id", "attr", "asname")

RICH_TYPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Call,  # special handling
    ast.Name,
)

SKIP_TYPES = ast_node_types = {
    ast.Expr: "value",
    ast.Return: "value",
    ast.Yield: "value",
    ast.Await: "value",
    ast.UnaryOp: "operand",
    ast.Not: "value",
    ast.Assert: "test",
    ast.Constant: None,
    ast.Load: None,
    ast.Eq: None,
    ast.List: None,
    ast.Tuple: None,
    ast.Dict: None
}


def skip_type(ast_node: ast.AST):
    """replace ast nodes in the SKIP_TYPES dictionary with either a
    single manually selected child or None to simplify tree structure."""
    for key, val in SKIP_TYPES.items():
        if isinstance(ast_node, key):
            if val is None:
                return None
            return getattr(ast_node, val)
    return ast_node


def get_ast_tuplestr(ast_node):
    return f"{ast_node.lineno}, {ast_node.col_offset}"


def tuplestr_to_tuple(tstr):
    keyls = tstr.split(",")
    return (int(x) for x in keyls)


def is_rich_type(ast_node):
    return any(isinstance(ast_node, rt) for rt in RICH_TYPES)


def pretty_type(t):
    return str(t).rsplit("ast.", maxsplit=1)[-1].split("'>")[0].split(" ")[0]


def extract_name(ast_node):
    """return namelike attribute"""
    if ast_node is None:
        return ""
    if isinstance(ast_node, ast.Call):
        return extract_name(ast_node.func)
    for alias in ALIASES:
        if hasattr(ast_node, alias):
            this_alias = getattr(ast_node, alias)
            if not this_alias:
                return ""
            assert isinstance(this_alias, str)
            return this_alias
    return ""
