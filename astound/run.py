import logging

from astound.cursor import Cursor, display_tree
from astound.node import Source

logging.basicConfig(level=logging.ERROR)

MAX_LINES_PRINT = int(1e5)


class InvalidInput(Exception):
    pass


WELCOME_STR = "\nWelcome to Astound! Please enter your source path to begin:\n\n"
POST_WELCOME_STR = (
    "\nThanks! I have created a parent node based on your file and moved the cursor to this node.\n"
    "Now you can attach children, either from the AST of this file or from other files.\n\n"
    "Here's how to navigate:\n"
)
SHORT_MENU_STR = "\n\n[ A: Attach, U: Up, D: Down, C: Cursor, P: Print, S: summarize, M: menu, Q: quit ]\n\n"
LONG_MENU_STR = (
    " - Type 'A line,col' to link an ast subnode at (line,col) and navigate down to it\n"
    "        'A source.path' to create and link a child node based on the source in\n"
    "             filename source.path and navigate down to it\n"
    " - Type 'U' to navigate up to the parent node\n"
    " - Type 'D key' to navigate down to a child named 'key'\n"
    " - Type 'C' to print the cursor state.\n"
    " - Type 'P node' to print the current node source text\n"
    "        'P a,b' to print the source text from lines a to b\n"
    "        'P tree' to print a tree overview from root\n"
    " - Type 'S' to summarize down from the current node inclusive\n"
    " - Type 'M' for the full menu description.\n"
    " - Type 'Q' to quit\n"
)


def attach_command(cursor, post):
    """wraps cursor.attach"""
    keystr = post.split(",")
    if len(keystr) == 1:
        try:
            cursor.attach(pathstr=keystr[0])
        except FileNotFoundError as exc:
            raise InvalidInput("source file not found") from exc
        cursor.down(keystr[0])
    elif len(keystr) == 2:
        try:
            cursor.attach(line=int(keystr[0]), col=int(keystr[1]))
        except ValueError as exc:
            raise InvalidInput("line, col not found") from exc
        cursor.down(f"{keystr[0]},{keystr[1]}")
    print(cursor)
    return True


def down_command(cursor, post):
    """wraps cursor.down()"""
    try:
        cursor.down(post)
    except KeyError as exc:
        raise InvalidInput("child key not found") from exc
    print(cursor)
    return True


def up_command(cursor, post):
    """wraps cursor.up()"""
    cursor.up()
    print(cursor)
    return True


def cursor_command(cursor, post):
    """wraps cursor.__repr__()"""
    print(cursor)
    return True


def print_command(cursor, post):
    """if post is `node` or `a,b`, uses astor to print current source
    either of whole node or of node from a to b. If tree, calls print
    tree function."""

    if post == "tree":
        display_tree(cursor.root)
        return True

    if post == "node":
        line_start = getattr(cursor.current.ast_node, "lineno", 1)
        line_end = getattr(cursor.current.ast_node, "end_lineno", MAX_LINES_PRINT)
    else:
        try:
            line_start, line_end = post.split(",")
            line_start, line_end = int(line_start), int(line_end)
        except ValueError as exc:
            raise InvalidInput("invalid print spec") from exc
    print(cursor.current.source.view_text(line_start, line_end))
    return True


def summarize_command(cursor, post):
    """wraps cursor.summarize()"""
    cursor.summarize_down()
    return True


def menu_command(cursor, post):
    """print long menu string"""
    print(LONG_MENU_STR)
    return True


def quit_command(cursor, post):
    """exit loop"""
    return False


def clean_str(instr: str):
    """remove spaces and quotes."""
    return instr.replace(" ", "").replace('"', "").replace("'", "")


def parse_input(cursor, instr: str):
    """extract leading character to determine command type and then
    pass to appropriate command function. The goal is to only raise
    InvalidInput errors from here so that the user never errors out."""

    instr = clean_str(instr)
    prefix = instr[0]
    post = instr[1:]

    command_function = {
        "A": attach_command,
        "U": up_command,
        "D": down_command,
        "C": cursor_command,
        "P": print_command,
        "S": summarize_command,
        "M": menu_command,
        "Q": quit_command,
    }

    try:
        return command_function[prefix](cursor, post)
    except KeyError as exc:
        raise InvalidInput("Command not found") from exc


if __name__ == "__main__":
    print(WELCOME_STR)
    source_path = input("enter source path: ")
    print(POST_WELCOME_STR)
    print(LONG_MENU_STR)

    src = Source(clean_str(source_path))
    cur = Cursor(root=src)
    print("\n\nHere's the current cursor state:\n")
    print(cur)

    state = True
    while True:
        user_input = input(SHORT_MENU_STR)
        print("\n")
        try:
            state = parse_input(cur, user_input)
        except InvalidInput as reason:
            print(f"Your input was invalid: {reason}.\nPlease try again\n")
            continue

        if not state:
            break
