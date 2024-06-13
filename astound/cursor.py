import ast
from typing import Union

from astound import summarize
from astound.smartnode import Node, Source, pretty_type

def display_tree(node, tag = ""):
    print(tag + f"{node}")
    for key, val in node.children.items():
        display_tree(val, tag + f">> ")

class Cursor:
    def __init__(self, root: Union[Source, Node]):
        if isinstance(root, Source):
            ast_node = ast.parse(root.text)
            self.root = Node(
                ast_node = ast_node, 
                source = root
            )
        else:
            self.root = root

        self.current = self.root
        self.depth = 0

    def __repr__(self):
        return (
            f"CURSOR :: You are {self.depth} edges down from the root.\n"
            + f"The current node has type {pretty_type(type(self.current.ast_node))}.\n\n"
            + f"The unattached subnodes of the current node are as follows:\n"
            + self.current.print_unattached_subnodes()
            + f"\nThe children of the current node are as follows:\n" 
            + self.current.print_children()
        )

    def down(self, key):
        try:
            self.current.attach_subnode(key)
        except ValueError:
            assert key in self.current.children
        self.current = self.current.children[key]
        self.depth += 1

        print(self)
        
    def up(self):
        self.current = self.current.parent
        self.depth -= 1

    def link_source(self, name: str, source):
        ast_node = ast.parse(source.text)
        self.current.attach_manual(name, Node(ast_node = ast_node, source = source, parent = self.current))
        self.depth += 1
        self.current = self.current.children[name]

    def link_node(self, name:str, node: Node):
        node = node.copy()
        node.parent = self.current
        self.current.attach_manual(name, node)
        self.depth += 1
        self.current = self.current.children[name]
                
    def summarize_down(self):
        return summarize.summarize(self.current)
