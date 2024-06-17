import ast
import logging
import sqlite3

import anthropic
import astor
import jedi

import astound.ast_node_utils as au
from astound.smartparse import parser_type_query


class ExtractFunctionSource(ast.NodeVisitor):
    """Node visitor to extract the text of a function definition
    given only the function name"""

    def __init__(self, target_function_name, source):
        self.target_function_name = target_function_name
        self.source = source
        self.function_def = None

    def visit_FunctionDef(self, node):
        if node.name == self.target_function_name:
            assert not self.function_def
            self.function_def = ast.get_source_segment(self.source.text, node)
        self.generic_visit(node)


class Source:
    """mutable wrapper around source text"""

    def __init__(self, path):
        with open(path, "r", encoding="utf-8") as file:
            self.text = file.read()
        self.path = path
        self.jedi = jedi.Script(self.text)


class Node:
    """Node is almost a wrapper around ast.AST, but it collapses much of the structure
    of the syntax tree because language models do not need so much rigor to understand
    the relationship between bits of code. Here is how the collapsing is implemented:

    1. The constructor (self.__init__) replaces certain types, called  "skip types"
        (see astound/ast_node_utils), with either a single child node or None. In the
        first case it is to save the user an extra navigation step. In the second case
        it is either because some types are self-explanatory or because certain
        data-heavy types create too much clutter for the cursor.
    2. Accessing and printing a Node's children is mediated by self.skip(). This method
        behaves different based on the type of self.ast_node. If self.ast_node is a
        "rich type" (see astound/ast_node_utils), split does nothing. Otherwise,
        split determines which attributes of self.ast_node contain children and returns
        a list containing all these children. Because the names of the relevant attributes
        vary by ast node type, astound asks the language model which fields to look at,
        and mantains these answers in a database. See astound/smartparse."""

    sqlite_conn = sqlite3.connect("data/subfield_store.db")
    anthropic_client = anthropic.Anthropic()

    def __init__(self, ast_node: ast.AST = None, source: Source = None, parent=None):
        self.ast_node = au.skip_type(ast_node)
        self.text = ""
        self.source = source
        self.parent = parent
        self.children = {}
        self.summary = ""
        self.inheritance = self.infer_inheritance()

    def __repr__(self):
        """If a node is not a rich type, display its components. Plus a bit of
        special handling."""

        if self.ast_node is None:
            return None
        if isinstance(self.ast_node, ast.Module):
            return f"{au.pretty_type(type(self.ast_node))} '{self.name()}'"
        return "\n".join(
            [
                f"{au.pretty_type(type(component.ast_node))} '{component.name()}' "
                + f"at key '{au.get_ast_tuplestr(self.ast_node)}'"
                for component, tag in self.split(max_depth=0)
            ]
        )

    def split(self, tag: str = " ", max_depth: int = 2):
        """
        Recursively simplifies AST nodes that are not "rich types" (as defined in
        astound/ast_node_utils). Breaks up nodes and returns a list of their
        relevant components.

        Args:
            tag (str): A string that is edited to display recursion performed at
                this step.
            max_depth (int): The limit to recursion depth. Non-rich type nodes
                will be returned if max_depth equals 0.

        Returns:
            List[tuple]: A list of tuples, each containing a Node and its
            corresponding tag, for each component simplified.
        """

        if au.is_rich_type(self.ast_node):
            return [(self, tag)]
        if max_depth == 0:
            if au.is_rich_type(self.ast_node):
                return [(self, tag)]
            return [(self, tag + " truncated at")]

        components = []  # (ast node, relationship annotation)

        self_type = au.pretty_type(self.ast_node)
        field_list = parser_type_query(
            self_type, self.anthropic_client, self.sqlite_conn
        )
        field_list = field_list.split(",")
        field_list = [x for x in field_list if x != " "]

        for field in field_list:
            try:
                this_attr = getattr(self.ast_node, field)
            except AttributeError:
                logging.warning(
                    "encountered key error: %s has no field %s", self_type, field
                )
                continue
            if isinstance(this_attr, list):
                for subnode in this_attr:
                    if isinstance(subnode, ast.AST):
                        components.extend(
                            Node(subnode).split(
                                tag + f" {self_type}.{field} >>", max_depth - 1
                            )
                        )
                    else:
                        logging.warning("omitting invalid field %s", field)
            elif isinstance(this_attr, ast.AST):
                components.extend(
                    Node(this_attr).split(
                        tag + f" {self_type}.{field} >>", max_depth - 1
                    )
                )
            else:
                logging.warning("omitting invalid field %s ", field)

        return components

    def body(self):
        """Applies split() to elements of the body attribute"""

        if not hasattr(self.ast_node, "body"):
            return []
        return [
            component
            for child in self.ast_node.body
            for component in Node(child).split()
            if component[0].ast_node is not None
        ]

    def name(self):
        """many ast.AST types have a name-like field but where it is stored
        varies"""

        if self.ast_node is None:
            return "Null"
        if isinstance(self.ast_node, ast.Module):
            return self.source.path
        return au.extract_name(self.ast_node)

    def infer_inheritance(self):
        """to my knowledge, neither ast nor jedi is good at tracking down class inheritance,
        so here we keep track of any base classes. If self.ast_node is a ClassDef,
        the parent class name is infered from the source text. Otherwise, we recursively
        check the inheritance of any parent class.

        Note that we assume a single parent class, because we cannot use Python's import
        precedence resolution tool without executing.

        Returns:
            string: name of parent class of self (if ClassDef) or parent node that is ClassDef
        """
        if not isinstance(self.ast_node, ast.ClassDef):
            if self.parent:
                return self.parent.infer_inheritance()
            return None
        if len(self.ast_node.bases) > 1:
            logging.warning(
                "astound cannot resolve multiple inheritance. Defaulting to first parent class."
            )
        if not self.ast_node.bases:
            return ""
        return astor.to_source(self.ast_node.bases[0]).split("\n", maxsplit=1)[0]

    def get_subnode(self, key):
        """
        Inputs:
            key (str): `line, column` using ast conventions
        Returns:
            ast.AST: ast_node at that line, column
        """
        line, col = au.tuplestr_to_tuple(key)
        for subnode, _ in self.body():
            if subnode.ast_node.lineno == line and subnode.ast_node.col_offset == col:
                return subnode.ast_node
        raise ValueError("(line, col) referenced invalid")

    def print_unattached_subnodes(self):
        out_str = ""

        if self.ast_node is not None:
            for subnode, tag in self.body():
                try:
                    if au.get_ast_tuplestr(subnode.ast_node) not in self.children:
                        out_str += f"{tag} {subnode}\n"
                except AttributeError:
                    pass
        return out_str

    def attach_subnode(self, key):
        """add subnode to the children attribute under `key`"""
        if key in self.children:
            raise ValueError("child already exists")

        self.children[key] = Node(
            self.get_subnode(key), source=self.source, parent=self
        )

    def attach_manual(self, name: str, node):
        """add a node that is not part of the AST to the children attribute
        under `key`"""
        self.children[name] = node

    def print_children(self):
        out_str = ""
        for key, value in self.children.items():
            out_str += f"{value} at key '{key}'"

        return out_str

    def get_text(self):
        """Return empty string for ast.Module nodes to avoid including text not selected
        by the user. For ast.Call nodes, use jedi to search for a function defintion and
        return source text of the function defintion. For all other nodes, return the
        source text of this node, indicated by ast_node.lineno and ast_node.end_lineno.
        """

        # inputing the whole module would destroy the emphasis created by the tree
        if isinstance(self.ast_node, ast.Module):
            return ""

        if isinstance(self.ast_node, ast.Call):
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

        return self.source.text.split("\n")[
            self.ast_node.lineno - 1 : self.ast_node.end_lineno
        ]
