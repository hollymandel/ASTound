import ast
import logging

import astor
import jedi

jedi.settings.fast_parser = (
    False  # otherwise jedi will only maintain one script object!
)


class ForbiddenNodeType(BaseException):
    pass


class Source:
    """mutable wrapper around source text"""

    def __init__(self, name, path):
        self._name = name
        with open(path, "r") as file:
            self._text = file.read()
        self.jedi = jedi.Script(self._text)

    def text(self):
        return self._text

    def name(self):
        return self._name


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

        self._ast_node = ast_node
        self._text = ""

    def __repr__(self):
        if not self._ast_node:
            return self._text
        if isinstance(self._ast_node, ast.Constant):
            return "constant"
        if isinstance(self._ast_node, ast.Module):
            return f"Parent Module"
        if isinstance(self._ast_node, ast.Assign):
            return (
                "Assignment: ("
                + ", ".join(
                    [Node(target).__repr__() for target in self._ast_node.targets]
                )
                + ") = ("
                + Node(self._ast_node.value).__repr__()
                + ")"
            )
        if isinstance(self._ast_node, ast.Call):
            return (
                "Function Call: ("
                + Node(self._ast_node.func).__repr__()
                + ") with args ("
                + ", ".join([Node(arg).__repr__() for arg in self._ast_node.args])
                + ")"
            )
        if isinstance(self._ast_node, ast.BoolOp):
            return (
                "Boolean Op: ("
                + ", ".join([Node(value).__repr__() for value in self._ast_node.values])
                + ")"
            )
        if isinstance(self._ast_node, ast.If):
            return "If (" + self._ast_node.test.__repr__() + ")"

        # not all Ast types have a name, but all should have some sort of identifying data
        try:
            get_name = self._ast_node.name
        except AttributeError:
            if isinstance(self._ast_node, ast.Attribute):
                get_name = self._ast_node.attr
            elif isinstance(self._ast_node, ast.Name):
                get_name = self._ast_node.id
            else:
                raise ValueError from AttributeError

        return (
            f"{pretty_type(type(self._ast_node))} '{get_name}' "
            + f"at {(self._ast_node.lineno, self._ast_node.col_offset)}"
        )

    def assign_text(self, text):
        self._text = text

    def text(self):
        return self._text

    def print_children(self):
        for subnode in self._ast_node.body:
            try:
                print(Node(subnode).__repr__())
            except ForbiddenNodeType:
                continue


class SmartNode(Node):
    """methods for recursive summarization"""

    def __init__(self, ast_node=None, source: Source = None, parent=None):
        super().__init__(ast_node)
        self._source = source
        self._parent = parent
        self._children = {}
        self._summary = ""

        # to my knowledge, neither ast nor jedi is good at tracking down class inheritance,
        # so here we keep track of any base classes. This comes up if you see a call to "super()".
        # That being said, this functionality is limited to simple inheritance structures, because
        # we cannot use Python's import precedence resolution tool without executing
        self._inheritance = self.infer_inheritance()

    def __repr__(self):
        if self._summary:
            return self._summary
        else:
            return super().__repr__()

    def infer_inheritance(self):
        if not isinstance(self._ast_node, ast.ClassDef):
            if self._parent:
                return self._parent.infer_inheritance()
            else:
                return None
        if len(self._ast_node.bases) > 1:
            logging.warning(
                "ASTound cannot resolve multiple inheritance. Defaulting to first parent class."
            )
        return astor.to_source(self._ast_node.bases[0]).split("\n")[0]

    def get_text(self):
        if isinstance(self._ast_node, ast.Module):
            return self._source.text()

        if isinstance(self._ast_node, ast.Call):
            # assert False
            line, col = self._ast_node.lineno, self._ast_node.col_offset
            get_first_ref = self._source.jedi.infer(line, col)[0]

            if get_first_ref.full_name.__contains__("super"):
                return (
                    "Function call '"
                    + astor.to_source(self._ast_node)
                    + "' inherited from "
                    + self._inheritance
                )

            function_name = get_first_ref.full_name.split(".")[-1]

            visitor = ExtractFunctionSource(function_name, self._source)
            visitor.visit(ast.parse(self._source.text()))
            return visitor.function_def

        return self._source.text().split("\n")[
            self._ast_node.lineno - 1 : self._ast_node.end_lineno
        ]

    def get_child_by_loc(self, line, col):
        child_list = []
        if hasattr(self._ast_node, "body"):
            child_list += self._ast_node.body
        if hasattr(self._ast_node, "targets"):
            child_list += self._ast_node.targets
        if hasattr(self._ast_node, "value"):
            child_list += [self._ast_node.value]
        if hasattr(self._ast_node, "values"):
            child_list += self._ast_node.values

        for subnode in child_list:
            if subnode.lineno == line and subnode.col_offset == col:
                return subnode
        raise ValueError

    def attach_child(self, line, col):
        if (line, col) in self._children:
            raise ValueError("child already exists")

        self._children[(line, col)] = SmartNode(
            self.get_child_by_loc(line, col), source=self._source, parent=self
        )

    def link_child(self, line, col):
        parent_type = str(type(self._ast_node))
        child_type = str(type(self._children[line, col]))
        link_field = self._children[line, col]._link_field

        # TODO - CACHE LINKS!

        link_prompt = (
            "Please describe in one sentence the relationship between a python syntax parent node of type "
            + str(type(self._ast_node))
            + " and a child node of type "
            + str(type(self._children[line, col]))
            + f" from the {from_field} field of the parent."
        )

    def attach_manual(self, name, child):
        self._children[name] = child

    def summarize(self, client):
        if len(self._summary) > 0:
            return self._summary

        individual_prompt = INDIVIDUAL_SUMMARY_HEADER + "".join(self.get_text())

        individual_summary = (
            client.messages.create(
                **CLAUDE_KWARGS,
                messages=[{"role": "user", "content": individual_prompt}],
            )
            .content[0]
            .text
        )

        if len(self._children) == 0:
            self.summary = individual_summary
        else:
            joint_prompt = (
                JOINT_SUMMARY_HEADER
                + individual_summary
                + "\n".join(
                    [
                        f"{child_header(x)}{x.summarize(client)}"
                        for x in self._children.values()
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

            self._summary = joint_summary

        return self._summary
