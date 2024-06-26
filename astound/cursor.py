import ast
from typing import Union

from astound import summarize
from astound.ast_node_utils import pretty_type
from astound.node import Node, Source


def display_tree(node, tag=""):
    print(tag + f"{node}")
    for val in node.children.values():
        display_tree(val, tag + ">> ")


class Cursor:
    """Wraps astound/Node type with utilities for building and navigating a syntax tree."""

    def __init__(self, root: Union[Source, Node]):
        if isinstance(root, Source):
            ast_node = ast.parse(root.text)
            self.root = Node(ast_node=ast_node, source=root)
        else:
            self.root = root

        self.current = self.root
        self.depth = 0

    def __repr__(self):
        return (
            f"CURSOR :: You are {self.depth} edges down from the root.\n"
            f"The current node '{self.current.name()}' has type "
            f"{pretty_type(type(self.current.ast_node))}.\n\n"
            "The unattached subnodes of the current node are as follows:\n"
            f"{self.current.print_unattached_subnodes()}"
            "\nThe children of the current node are as follows:\n"
            f"{self.current.print_children()}"
        )

    def down(self, key):
        """navigate to child node specified by 'key'"""
        self.current = self.current.children[key]
        self.depth += 1

    def up(self):
        """navigate to parent node"""
        if self.depth == 0:
            return
        self.current = self.current.parent
        self.depth -= 1

    def attach(self, pathstr: str = None, line: int = None, col: int = None):
        """If path is specified, attach a child node that is not part of the
        AST by creating a new Node based on source. This behavior wraps Node.attach_manual.

        If line and col are specified, attach a child node that is an ast
        subnode by line, column reference. This behavior wraps Node.attach_subnode."""
        if pathstr:
            source = Source(pathstr)
            ast_node = ast.parse(source.text)
            self.current.attach_manual(
                pathstr, Node(ast_node=ast_node, source=source, parent=self.current)
            )
        else:
            self.current.attach_subnode(line, col)

    def summarize_down(self):
        """Recursive summarization of the current node and its attached children."""
        self.current.summary = summarize.summarize(self.current)
        print(self.current.summary)
