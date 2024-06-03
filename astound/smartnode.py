import ast
import logging

import astor
import jedi

FORBIDDEN_TYPES = (ast.ImportFrom, ast.Import, ast.ListComp, ast.For, ast.If, ast.Return)

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
        if any(
            isinstance(ast_node, forbidden_type) for forbidden_type in FORBIDDEN_TYPES
        ):
            raise ForbiddenNodeType("import nodes excluded")
        if isinstance(ast_node, ast.Expr):
            ast_node = ast_node.value

        self.ast_node = ast_node
        self.text = ""

    def __repr__(self):
        if not self.ast_node:
            return self.text
        if isinstance(self.ast_node, ast.Constant):
            return "constant"
        if isinstance(self.ast_node, ast.Module):
            return f"Parent Module"
        if isinstance(self.ast_node, ast.Assign):
            return (
                "Assignment: ("
                + ", ".join(
                    [Node(target).__repr__() for target in self.ast_node.targets]
                )
                + ") = ("
                + Node(self.ast_node.value).__repr__()
                + ")"
            )
        if isinstance(self.ast_node, ast.Call):
            return (
                "Function Call: ("
                + Node(self.ast_node.func).__repr__()
                + ") with args ("
                + ", ".join([Node(arg).__repr__() for arg in self.ast_node.args])
                + ")"
            )
        if isinstance(self.ast_node, ast.BoolOp):
            return (
                "Boolean Op: ("
                + ", ".join([Node(value).__repr__() for value in self.ast_node.values])
                + ")"
            )
        if isinstance(self.ast_node, ast.If):
            return "If (" + self.ast_node.test.__repr__() + ")"

        # not all Ast types have a name, but all should have some sort of identifying data
        try:
            get_name = self.ast_node.name
        except AttributeError:
            if isinstance(self.ast_node, ast.Attribute):
                get_name = self.ast_node.attr
            elif isinstance(self.ast_node, ast.Name):
                get_name = self.ast_node.id
            else:
                raise ValueError from AttributeError

        return (
            f"{pretty_type(type(self.ast_node))} '{get_name}' "
            + f"at {(self.ast_node.lineno, self.ast_node.col_offset)}"
        )

    def print_children(self):
        out_str = ""
        for subnode in self.ast_node.body:
            try:
                out_str += f"{Node(subnode).__repr__()}\n"
                
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

        return self._source.text.split("\n")[
            self.ast_node.lineno - 1 : self.ast_node.end_lineno
        ]

    def get_child_by_loc(self, line, col):
        child_list = []
        if hasattr(self.ast_node, "targets"):
            child_list += self.ast_node.targets
        if hasattr(self.ast_node, "value"):
            child_list += [self.ast_node.value]
        if hasattr(self.ast_node, "values"):
            child_list += self.ast_node.values
        if hasattr(self.ast_node, "body"):
            child_list += self.ast_node.body

        for subnode in child_list:
            if subnode.lineno == line and subnode.col_offset == col:
                return subnode
        raise ValueError

    def attach_child(self, line, col):
        if (line, col) in self.children:
            raise ValueError("child already exists")

        self.children[(line, col)] = SmartNode(
            self.get_child_by_loc(line, col), source=self.source, parent=self
        )

    def link_child(self, line, col):
        parent_type = str(type(self.ast_node))
        child_type = str(type(self.children[line, col]))
        link_field = self.children[line, col].link_field

        # TODO - CACHE LINKS!

        link_prompt = (
            "Please describe in one sentence the relationship between a python syntax parent node of type "
            + str(type(self.ast_node))
            + " and a child node of type "
            + str(type(self.children[line, col]))
            + f" from the {from_field} field of the parent."
        )

    def attach_manual(self, name, child):
        self.children[name] = child

    def summarize(self, client):
        if len(self_summary) > 0:
            return self.summary

        individual_prompt = INDIVIDUAL_SUMMARY_HEADER + "".join(self.get_text())

        individual_summary = (
            client.messages.create(
                **CLAUDE_KWARGS,
                messages=[{"role": "user", "content": individual_prompt}],
            )
            .content[0]
            .text
        )

        if len(self.children) == 0:
            self.summary = individual_summary
        else:
            joint_prompt = (
                JOINT_SUMMARY_HEADER
                + individual_summary
                + "\n".join(
                    [
                        f"{child_header(x)}{x.summarize(client)}"
                        for x in self.children.values()
                    ]
                )
            )

            joint_summary = (
                client.messages.create(
                    **CLAUDE_KWARGS,
                    messages=[{"role": "user", "content": joint_prompt}],
                )
                .content[0]
                .text
            )

            self.summary = joint_summary

        return self.summary
