import logging

from astound.cursor import Cursor, NonexistantChildError, display_tree
from astound.node import Source

logging.basicConfig(level=logging.ERROR)


class InvalidInput(Exception):
    pass


WELCOME_STR = "\nWelcome to Astound! Please enter your source path to begin:\n\n"
POST_WELCOME_STR = (
    "\nThanks! Now you will build the summary tree. Here's how to navigate:\n"
)
SHORT_MENU_STR = "\n\n[ C: Cursor, P: Print, D: Down, U: Up, L: Link, S: summarize, M: menu, Q: quit ]\n\n"
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
    " - Type 'M' for the full menu description."
    " - Type 'Q' to quit\n"
)


def clean_str(instr: str):
    return instr.replace(" ", "").replace('"', "").replace("'", "")


def parse_input(cursor, instr: str):
    instr = clean_str(instr)
    prefix = instr[0]
    post = instr[1:]
    if prefix == "A":
        keystr = post.split(",")
        if len(keystr) == 1:
            cursor.attach(pathstr=keystr[0])
            cursor.down(keystr[0])
        elif len(keystr) == 2:
            cursor.attach(line=int(keystr[0]), col=int(keystr[1]))
            cursor.down(f"{keystr[0]},{keystr[1]}")
        else:
            raise ValueError
        print(cursor)
        return True
    if prefix == "D":
        cursor.down(post)
        print(cursor)
        return True
    if prefix == "U":
        cursor.up()
        print(cursor)
        return True
    if prefix == "C":
        print(cursor)
        return True
    if prefix == "P":
        if post == "tree":
            display_tree(cursor.root)
            return True

        if post == "node":
            line_start = cursor.current.ast_node.lineno
            line_end = cursor.current.ast_node.end_lineno
        else:
            try:
                line_start, line_end = post.split(",")
            except ValueError as exc:
                raise InvalidInput from exc
            line_start, line_end = int(line_start), int(line_end)
        print(cursor.current.source.view_text(line_start, line_end))
        return True
    if prefix == "L":
        source = Source(post)
        cursor.link_source(post, source)
        print(cursor)
        return True
    if prefix == "S":
        cursor.summarize_down()
        return True
    if prefix == "M":
        print(LONG_MENU_STR)
        return True
    if prefix == "Q":
        return False
    raise InvalidInput("invalid input string")


if __name__ == "__main__":
    print(WELCOME_STR)
    source_path = input("enter source path: ")
    print(POST_WELCOME_STR)
    print(LONG_MENU_STR)

    src = Source(clean_str(source_path))
    cur = Cursor(root=src)
    print(cur)

    while True:
        user_input = input(SHORT_MENU_STR)
        print("\n")
        try:
            stat = parse_input(cur, user_input)
        except InvalidInput:
            print("invalid input, try again\n")
            continue
        except NonexistantChildError:
            print("No child at given key, try a different key or select another option\n")

        if not stat:
            break
