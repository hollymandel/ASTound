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

    def view_text(self, line_start, line_end):
        """Return the text of the current node with 1-start line numbers."""
        source_list = self.text.split("\n")[line_start - 1 : line_end]
        source_list = [
            f"[{line_start + i}]   {txt}" for i, txt in enumerate(source_list)
        ]
        return "\n".join(source_list)


class Node:
    """
    Node acts as a simplified wrapper for ast.AST to accommodate language model processing by
    reducing the complexity of the syntax tree. This class modifies the structure to streamline
    the interaction between code elements. Here's the implementation detail:

    1. Constructor (`self.__init__`):
       - It simplifies the tree by replacing certain node types, referred to as "skip types"
         (defined in `astound/ast_node_utils`), with either their single child node or None.
       - This replacement helps reduce navigation steps for users or minimizes clutter from
         self-explanatory or data-heavy node types.

    2. Child Access and Representation (`self.skip()`):
       - This method moderates how children of a Node are accessed and represented.
       - If `self.ast_node` is a "rich type" (as defined in `astound/ast_node_utils`), the
         method does nothing.
       - For other types, it identifies and returns a list of children based on the node's
         attributes, varying by the type of self.ast_node.
    """

    # TODO: replace with context managers external to this class. Can't come up with a good
    # solution consistent with jupyter notebook user interface...
    sqlite_conn = sqlite3.connect("data/subfield_store.db")
    anthropic_client = anthropic.Anthropic()  # requires ANTHROPIC_API_KEY env variable

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

        if not self.ast_node:
            return []
        if max_depth == 0:
            return [(self, tag + " truncated at")]

        components = []  # (ast node, relationship annotation)

        self_type = au.pretty_type(self.ast_node)
        field_list = parser_type_query(
            self.ast_node, self.anthropic_client, self.sqlite_conn
        ).split(",")
        field_list = [x for x in field_list if x]

        for field in field_list:
            this_attr = getattr(self.ast_node, field)
            if not isinstance(this_attr, list):
                this_attr = [this_attr]
            if this_attr and not isinstance(this_attr[0], ast.AST):
                logging.warning("Encountered non-AST field %s", field)
                continue

            for subnode in this_attr:
                if au.is_rich_type(self.ast_node):
                    use_depth = 0
                else:
                    use_depth = max_depth - 1
                components.extend(
                    Node(subnode).split(tag + f" {self_type}.{field} >>", use_depth)
                )

        return components

    def name(self):
        """many ast.AST types have a name-like field but where it is stored
        varies"""

        if self.ast_node is None:
            return "Null"
        if isinstance(self.ast_node, ast.Module):
            return self.source.path
        return au.extract_name(self)

    def infer_inheritance(self):
        """
        Tracks class inheritance when neither the 'ast' nor 'jedi' libraries can
        effectively determine it.

        This method maintains a record of any base classes associated with a given
        class. If 'self.ast_node' is an instance of 'ClassDef', it infers the parent
        class name directly from the source text. If 'self.ast_node' is not a
        'ClassDef', it recursively checks the inheritance chain to find any parent classes.

        Note:
            This method assumes there is only one parent class because it does not execute
            Python's import statements, thus bypassing the standard module and class
            resolution mechanisms that would be available at runtime.

        Returns:
            str: The name of the parent class if 'self.ast_node' is a 'ClassDef', or the
            nearest parent node that is a 'ClassDef'.
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

    def get_subnode(self, line: int, col: int):
        """
        Inputs:
            line (int): line number using ast conventions
            col (int): column number using ast conventions
        Returns:
            ast.AST: ast_node at that line, column
        """
        for subnode, _ in self.split():
            try:
                if (
                    subnode.ast_node.lineno == line
                    and subnode.ast_node.col_offset == col
                ):
                    return subnode.ast_node
            except AttributeError:
                logging.warning(
                    "Bypassing node of type %s, no location info",
                    au.pretty_type(type(subnode.ast_node)),
                )
        raise ValueError("(line, col) referenced invalid")

    def print_unattached_subnodes(self):
        out_str = ""

        if self.ast_node is None:
            return out_str

        for subnode, tag in self.split():
            try:
                if au.get_ast_tuplestr(subnode.ast_node) not in self.children:
                    out_str += f"{tag} {subnode}\n"
            except AttributeError:
                pass
        return out_str

    def attach_subnode(self, line: int, col: int):
        """add subnode to the children attribute at line, column"""

        if f"{line},{col}" in self.children:
            raise ValueError("child already exists")

        self.children[f"{line},{col}"] = Node(
            self.get_subnode(line, col), source=self.source, parent=self
        )

    def attach_manual(self, name: str, node):
        """add a node that is not part of the AST to the children attribute
        under `key`"""
        self.children[name] = node

    def print_children(self):
        if not self.children:
            return "   None"

        out_str = ""
        for key, value in self.children.items():
            out_str += f"{value} at key '{key}'"

        return out_str

    def core_text(self):
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
