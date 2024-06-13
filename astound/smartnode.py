import ast
import logging

import astor
import jedi
import sqlite3
from astound.smartparse import parser_type_query
import anthropic

jedi.settings.fast_parser = (
    False  # otherwise jedi will only maintain one script object
)

ALIASES = (
    'name',
    'id',
    'attr',
    'asname'
)

RICH_TYPES = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
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
    ast.Eq: None
} # the llm can infer these skips from syntax

def get_ast_tuplestr(ast_node):
    return f'{ast_node.lineno}, {ast_node.col_offset}'
    
def tuplestr_to_tuple(tstr):
    keyls = tstr.split(",")
    return ( int(x) for x in keyls )
    
def is_rich_type(ast_node):
    return any(isinstance(ast_node, rt) for rt in RICH_TYPES)

def pretty_type(t):
    return str(t).rsplit("ast.", maxsplit=1)[-1].split("'>")[0].split(" ")[0]

class ExtractFunctionSource(ast.NodeVisitor):
    def __init__(self, target_function_name, source):
        self.target_function_name = target_function_name
        self.source = source
        self.function_def = None

    def visit_FunctionDef(self, node):
        if node.name == self.target_function_name:
            self.function_def = ast.get_source_segment(self.source.text, node)
        self.generic_visit(node)


class Source:
    """mutable wrapper around source text"""

    def __init__(self, path):
        with open(path, "r", encoding="utf-8") as file:
            self.text = file.read()
        self.jedi = jedi.Script(self.text)


class Node:
    """methods for recursive summarization"""
    sqlite_conn = sqlite3.connect('data/subfield_store.db')
    anthropic_client = anthropic.Anthropic()

    def __init__(self, ast_node=None, source: Source = None, parent=None):
        if not isinstance(ast_node, ast.AST):
            raise ValueError("ast_node type must inherit from ast.AST")

        for key, val in SKIP_TYPES.items():
            if isinstance(ast_node, key):
                if val is None:
                    ast_node = None
                else:
                    ast_node = getattr(ast_node, val)

        self.ast_node = ast_node
        self.text = ""
        self.source = source
        self.parent = parent
        self.children = {}
        self.summary = ""

        # to my knowledge, neither ast nor jedi is good at tracking down class inheritance,
        # so here we keep track of any base classes. This comes up if you see a call to "super()".
        # This functionality is limited to simple inheritance structures, because
        # we cannot use Python's import precedence resolution tool without executing
        self.inheritance = self.infer_inheritance()

    
    def name(self):
        if self.ast_node is None:
            return ""
        for alias in ALIASES:
            if hasattr(self.ast_node, alias):
                this_alias = getattr(self.ast_node, alias)
                if not this_alias:
                    return ""
                assert isinstance(this_alias, str)
                return this_alias
        return ""

    def split(self, tag=" ", max_depth = 2):
        """Recursive node simplification. Breaks up composite nodes like function calls
        and assigments and directly points to their relevant components, which should have
        all children contained in a single "body" field."""

        if is_rich_type(self.ast_node):
            return [ (self, tag) ]
        if max_depth == 0:
            if is_rich_type(self.ast_node):
                return [ (self, tag) ]
            else:
                return [ (self, tag + " truncated at" ) ]
                
        components = []  # (ast node, relationship annotation)

        self_type = pretty_type(self.ast_node)
        field_list = parser_type_query(
            self_type, 
            self.anthropic_client,
            self.sqlite_conn
        )
        field_list = field_list.split(",")
        field_list = [ x for x in field_list if x != " " ]

        for field in field_list:
            try:
                this_attr = getattr(self.ast_node, field)
            except:
                logging.warning(f"encountered key error: {self_type} has no field {field}")
                continue
            if isinstance(this_attr, list):
                for subnode in this_attr:
                    if isinstance(subnode, ast.AST):
                        components.extend(Node(subnode).split(tag + f" {self_type}.{field} >>", max_depth - 1))
                    else:
                        logging.warning(f"omitting invalid field {field}")
            else:
                if isinstance(this_attr, ast.AST):
                    components.extend(Node(this_attr).split(tag + f" {self_type}.{field} >>", max_depth - 1))
                else:
                    logging.warning(f"omitting invalid field {field}")
                    
        return components

    def body(self):
        if not hasattr(self.ast_node, "body"):
            return []
        return [
            component
            for child in self.ast_node.body
            for component in Node(child).split()
            if component[0].ast_node is not None
        ]

    def __repr__(self):
        """if a node is composite, display all its elements. Nontrivial case should rarely occur, since
        user should directly attach component nodes."""

        if self.ast_node is None:
            return None
        if isinstance(self.ast_node,ast.Module):
            return "Module"

        return "\n".join(
            [
                f"{pretty_type(type(component.ast_node))} '{component.name()}' "
                + f"at key '{get_ast_tuplestr(self.ast_node)}'"
                for component, tag in self.split(max_depth = 0)
            ]
        )

    def infer_inheritance(self):
        if not isinstance(self.ast_node, ast.ClassDef):
            if self.parent:
                return self.parent.infer_inheritance()
            return None
        if len(self.ast_node.bases) > 1:
            logging.warning(
                "ASTound cannot resolve multiple inheritance. Defaulting to first parent class."
            )
        if not self.ast_node.bases:
            return ""
        return astor.to_source(self.ast_node.bases[0]).split("\n", maxsplit=1)[0]

    def get_subnode(self, key):
        line, col = tuplestr_to_tuple(key)
        for subnode, _ in self.body():
            if subnode.ast_node.lineno == line and subnode.ast_node.col_offset == col:
                return subnode.ast_node
        raise ValueError("(line, col) referenced invalid")

    def print_unattached_subnodes(self):
        out_str = ""

        if self.ast_node is not None:
            for subnode, tag in self.body():
                try:
                    if get_ast_tuplestr(subnode.ast_node) not in self.children:
                        out_str += f"{tag} {subnode}\n"
                except AttributeError:
                    pass
        return out_str
        
    def attach_subnode(self, key):
        if key in self.children:
            raise ValueError("child already exists")

        self.children[key] = Node(
            self.get_subnode(key), source=self.source, parent=self
        )

    def attach_manual(self, name: str, node):
        self.children[name] = node

    def print_children(self):
        out_str = ""
        for key, value in self.children.items():
            out_str += f"{value} at key '{key}'"

        return out_str

    def get_text(self):
        if isinstance(self.ast_node, ast.Module):
            return self.source.text.split("\n")

        return self.source.text.split("\n")[
            self.ast_node.lineno - 1 : self.ast_node.end_lineno
        ]

    def get_function_def(self):
        line, col = self.ast_node.lineno, self.ast_node.col_offset
        try:
            get_first_ref = self.source.jedi.infer(line, col)[0]
        except IndexError:
            return "Function definition not found. Check imports and consider a manual link."

        if "super" in get_first_ref.full_name:
            return (
                "Function call '"
                + astor.to_source(self.ast_node)
                + "' inherited from "
                + self.inheritance
            )

        function_name = get_first_ref.full_name.split(".")[-1]

        visitor = ExtractFunctionSource(function_name, self.source)
        visitor.visit(ast.parse(self.source.text))
        return visitor.function_def
