import ast
from typing import Union

from astound import summarize
from astound.smartnode import Node, SmartNode, Source, pretty_type


class Cursor:
    def __init__(self, name: str, root: Union[Source, SmartNode]):
        if isinstance(root, Source):
            ast_node = ast.parse(root.text)
            self.root = SmartNode(ast_node, root)
        else:
            self.root = root

        self.current_location = self.root
        self.name = name
        self.depth = 0

    def __repr__(self):
        return (
            f"You are navigating '{self.name}'. "
            + f"You are {self.depth} edges down from the root.\n"
            + f"The current node has type {pretty_type(type(self.current_location.ast_node))}.\n\n"
            + f"The children of the current node are as follows:\n"
            + self.current_location.print_children()
        )

    def down(self, line, col):
        self.current_location.attach_child(line, col)
        self.current_location = self.current_location.children[line, col]
        self.depth += 1

        print(self)

    def up(self):
        self.current_location = self.current_location.parent
        self.depth -= 1

        print(self)
