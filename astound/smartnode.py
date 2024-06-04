import ast
import logging

import astor
import jedi

FORBIDDEN_TYPES = (
    ast.ImportFrom,
    ast.Import,
    ast.ListComp,
    ast.For,
    ast.Return,
    ast.Constant,
)

jedi.settings.fast_parser = (
    False  # otherwise jedi will only maintain one script object!
)


def pretty_type(type):
    return str(type).split("ast.")[-1].split("'>")[0]


class ForbiddenNodeType(BaseException):
    pass


class Source:
    """mutable wrapper around source text"""

    def __init__(self, name, path):
        self.name = name
        with open(path, "r") as file:
            self.text = file.read()
        self.jedi = jedi.Script(self.text)


class Node:
    """thin wrapper around AST for formatting and printing. Lots of special casing to
    convert python grammar into human- (and claude-) readable text"""

    def __init__(self, ast_node=None):
        if not isinstance(ast_node, ast.AST):
            raise ValueError("ast node must be a type of AST node")

        if any(
            isinstance(ast_node, forbidden_type) for forbidden_type in FORBIDDEN_TYPES
        ):
            self.ast_node = None
        else:
            self.ast_node = ast_node
        self.text = ""

    def name(self):
        if self.ast_node is None:
            return

        try:
            return self.ast_node.name
        except AttributeError:
            if isinstance(self.ast_node, ast.Attribute):
                return self.ast_node.attr
            if isinstance(self.ast_node, ast.Name):
                return self.ast_node.id
        raise ValueError

    def split(self, tag=""):
        """Recursive node simplification. Breaks up composite nodes like function calls
        and assigments and directly points to their relevant components, which should have
        all children contained in a single "body" field."""

        components = []  # (ast node, relationship annotation)

        if self.ast_node is None:
            return []
        if isinstance(self.ast_node, ast.Module):
            for subnode in self.ast_node.body:
                components.extend(Node(subnode).split(tag + "Module.body/"))
        elif isinstance(self.ast_node, ast.Expr):
            components.extend(
                Node(self.ast_node.value).split(tag + "Expression.value/")
            )
        elif isinstance(self.ast_node, ast.Assign):
            for subnode in self.ast_node.targets:
                components.extend(Node(subnode).split(tag + "Assign.target/"))
            components.extend(Node(self.ast_node.value).split(tag + "Assign.value/"))
        elif isinstance(self.ast_node, ast.Call):
            components.extend(Node(self.ast_node.func).split(tag + "Call.func/"))
            for subnode in self.ast_node.args:
                components.extend(Node(subnode).split(tag + "Call.arg/"))
        elif isinstance(self.ast_node, ast.BoolOp):
            for subnode in self.ast_node.args:
                components.extend(Node(subnode).split(tag + "BoolOp.arg/"))
        elif isinstance(self.ast_node, ast.If):
            components.extend(Node(self.ast_node.test).split(tag + "If.test/"))
        else:
            components.append((Node(self.ast_node), tag))

        return components

    def body(self):
        return [
            component
            for child in self.ast_node.body
            for component in Node(child).split()
        ]

    def __repr__(self):
        if self.ast_node is None:
            return ""

        return "\n".join(
            [
                (
                    f"{component[1]} >> "
                    + f"{pretty_type(type(component[0].ast_node))} '{component[0].name()}' "
                    + f"at {(component[0].ast_node.lineno, component[0].ast_node.col_offset)}"
                )
                for component in self.split()
            ]
        )

    def get_child_by_loc(self, line, col):
        for subnode, _ in self.body():
            if subnode.ast_node.lineno == line and subnode.ast_node.col_offset == col:
                return subnode.ast_node
        raise ValueError

    def print_children(self):
        out_str = ""

        if self.ast_node is not None:
            for subnode in self.body():
                try:
                    out_str += f"{subnode.__repr__()}\n"
                except ForbiddenNodeType:
                    continue
        return out_str


class SmartNode(Node):
    """methods for recursive summarization"""

    def __init__(self, ast_node=None, source: Source = None, parent=None):
        super().__init__(ast_node)
        self.source = source
        self.parent = parent
        self.children = {}
        self.summary = ""

        # to my knowledge, neither ast nor jedi is good at tracking down class inheritance,
        # so here we keep track of any base classes. This comes up if you see a call to "super()".
        # This functionality is limited to simple inheritance structures, because
        # we cannot use Python's import precedence resolution tool without executing
        self.inheritance = self.infer_inheritance()

    def __repr__(self):
        if self.summary:
            return self.summary
        else:
            return super().__repr__()

    def infer_inheritance(self):
        if not isinstance(self.ast_node, ast.ClassDef):
            if self.parent:
                return self.parent.infer_inheritance()
            else:
                return None
        if len(self.ast_node.bases) > 1:
            logging.warning(
                "ASTound cannot resolve multiple inheritance. Defaulting to first parent class."
            )
        return astor.to_source(self.ast_node.bases[0]).split("\n")[0]

    def get_text(self):
        if isinstance(self.ast_node, ast.Module):
            return self.source.text

        if isinstance(self.ast_node, ast.Call):
            # assert False
            line, col = self.ast_node.lineno, self.ast_node.col_offset
            get_first_ref = self.source.jedi.infer(line, col)[0]

            if get_first_ref.full_name.__contains__("super"):
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

    def attach_child(self, line, col):
        if (line, col) in self.children:
            raise ValueError("child already exists")

        self.children[(line, col)] = SmartNode(
            self.get_child_by_loc(line, col), source=self.source, parent=self
        )

    def attach_manual(self, name, child):
        self.children[name] = child
