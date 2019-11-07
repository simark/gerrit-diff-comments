#!/usr/bin/env python3

import json
import requests
import sys
import urllib.parse
import textwrap
from collections import OrderedDict
from pprint import pprint


class Project:
    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    @classmethod
    def from_raw(cls, name, raw):
        return cls(name)

    def __str__(self):
        return "<Project {}>".format(self.name)

    def __repr__(self):
        return str(self)


class Change:
    @property
    def number(self):
        return self._number

    @property
    def subject(self):
        return self._subject

    @property
    def project(self):
        return self._project

    @classmethod
    def from_raw(cls, raw):
        change = cls()

        change._number = raw["_number"]
        change._subject = raw["subject"]
        change._project = raw["project"]

        return change

    def __str__(self):
        return "<Change {}>".format(self.number)

    def __repr__(self):
        return str(self)


class Account:
    @property
    def name(self):
        return self._name

    @property
    def id(self):
        return self._id

    @classmethod
    def from_raw(cls, raw):
        account = cls()

        account._name = raw["name"]
        account._id = raw["_account_id"]

        return account


class Message:
    @property
    def author(self):
        return self._author

    @property
    def date(self):
        return self._date

    @property
    def message(self):
        return self._message

    @classmethod
    def from_raw(cls, raw):
        message = cls()

        message._author = Account.from_raw(raw["author"])
        message._date = raw["date"]
        message._message = raw["message"]

        return message

    def __str__(self):
        return "<Message by {} at {}>".format(self.author.name, self.date)

    def __repr__(self):
        return str(self)


class Range:
    @property
    def start_line(self):
        return self._start_line

    @property
    def end_line(self):
        return self._end_line

    @classmethod
    def from_raw(cls, raw):
        rng = cls()

        rng._start_line = raw["start_line"]
        rng._end_line = raw["end_line"]

        return rng


class Comment:
    @property
    def author(self):
        return self._author

    @property
    def date(self):
        return self._date

    @property
    def message(self):
        return self._message

    @property
    def side(self):
        return self._side

    @property
    def line(self):
        return self._line

    @property
    def range(self):
        return self._range

    @property
    def path(self):
        return self._path

    @classmethod
    def from_raw(cls, raw, path=None):
        comment = cls()

        comment._author = Account.from_raw(raw["author"])
        comment._date = raw["updated"]
        comment._message = raw["message"]

        if path is not None:
            comment._path = path
        else:
            comment._path = raw["path"]

        comment._side = raw.get("side", "REVISION")

        comment._line = raw.get("line", None)

        if "range" in raw:
            comment._range = Range.from_raw(raw["range"])
        else:
            comment._range = None

        return comment

    def __str__(self):
        return "<Comment by {} at {}>".format(self.author.name, self.date)

    def __repr__(self):
        return str(self)


class Diff:
    @property
    def content(self):
        return self._content

    @property
    def path_a(self):
        return self._path_a

    @property
    def path_b(self):
        return self._path_b

    @classmethod
    def from_raw(cls, raw):
        diff = cls()

        diff._content = raw["content"]

        if "meta_a" in raw:
            diff._path_a = raw["meta_a"]["name"]
        else:
            diff._path_a = None

        if "meta_b" in raw:
            diff._path_b = raw["meta_b"]["name"]
        else:
            diff._path_b = None

        return diff


class Server:
    def __init__(self, base_addr):
        self._base_addr = base_addr

    def _json_query(self, path):
        url = "{}/{}".format(self._base_addr, path)
        # print("Getting {}".format(url))
        text = requests.get(url).text
        text = text[5:]
        return json.loads(text)

    @property
    def base_addr(self):
        return self._base_addr

    def get_projects(self):
        raw = self._json_query("projects/")
        projects = []

        for (name, proj_raw) in raw.items():
            projects.append(Project.from_raw(name, proj_raw))

        return projects

    def get_change(self, change_number):
        raw = self._json_query("changes/?q=change:{}".format(change_number))
        if len(raw) == 0:
            return None

        return Change.from_raw(raw[0])

    def get_changes(self):
        raw = self._json_query("changes/")
        changes = []

        for change_raw in raw:
            changes.append(Change.from_raw(change_raw))

        return changes

    def get_change_messages(self, change):
        raw = self._json_query(
            "changes/{}~{}/messages".format(change.project, change.number,)
        )

        messages = []

        for message_raw in raw:
            messages.append(Message.from_raw(message_raw))

        return messages

    def get_change_message_comments(self, change, message_filter):
        raw = self._json_query(
            "changes/{}~{}/comments".format(change.project, change.number,)
        )

        # dict with revision as key -> dict with path as key -> list of comments on that rev/path.
        comments_by_revision = {}

        for (path, comment_raw_list) in raw.items():
            for comment_raw in comment_raw_list:
                if (
                    message_filter.author.id == comment_raw["author"]["_account_id"]
                    and message_filter.date == comment_raw["updated"]
                ):
                    rev = comment_raw["patch_set"]

                    if rev not in comments_by_revision:
                        comments_by_revision[rev] = OrderedDict()

                    comments_for_that_revision = comments_by_revision[rev]

                    if path not in comments_for_that_revision:
                        comments_for_that_revision[path] = []

                    comments_for_that_revision[path].append(
                        Comment.from_raw(comment_raw, path=path)
                    )

        return comments_by_revision

    def get_diff(self, change, revision, path):
        raw = self._json_query(
            "changes/{}~{}/revisions/{}/files/{}/diff?context=ALL&intraline&whitespace=IGNORE_NONE".format(
                change.project,
                change.number,
                revision,
                urllib.parse.quote(path, safe=""),
            )
        )

        return Diff.from_raw(raw)


def print_comment(comment, revision):
    if comment.line is None:
        print("PS{}:".format(revision))
    else:
        print("PS{}, Line {}:".format(revision, comment.line))

    print()

    comment_lines = comment.message.splitlines()

    for line in comment_lines:
        # Don't wrap lines that are quotes or code blocks (which start with a space)
        if line.startswith(">") or line.startswith(" "):
            print(line)
        else:
            print(textwrap.fill(line))


def is_interesting_line_c(line):
    if len(line) == 0:
        return False

    if line[0].isspace():
        return False

    if line in ("{", "}"):
        return False

    # Other ideas:
    #
    #   - skip things that look like labels, /^[a-zA-Z0-9_]+:$/
    #   - skip preprocessor directives
    return True


def render_diff(diff):
    diff_lines = []

    # Maps line numbers of files A/B (1-based) to the corresponding index
    # (0-based) in diff_lines.
    #
    # The index 0 in these list is unused (there is no line number 0), so set
    # it to -1 to ensure it's not used as an index.
    line_mapping_a_to_diff = [-1]
    line_mapping_b_to_diff = [-1]

    # Last line we've seen that is worthy of being used as context in range
    # headers.
    last_interesting_line = ""

    for chunk in diff.content:
        if "ab" in chunk:
            for line in chunk["ab"]:
                diff_lines.append(
                    {
                        "line": " {}".format(line),
                        "a": len(line_mapping_a_to_diff),
                        "b": len(line_mapping_b_to_diff),
                        # If a range were to start at this line, what would be
                        # the line number we would write in the header for each
                        # of the files.  And what would be the context line
                        # included in the header.
                        "line-num-a": len(line_mapping_a_to_diff),
                        "line-num-b": len(line_mapping_b_to_diff),
                        "context": last_interesting_line,
                    }
                )

                line_mapping_a_to_diff.append(len(diff_lines) - 1)
                line_mapping_b_to_diff.append(len(diff_lines) - 1)

                if is_interesting_line_c(line):
                    last_interesting_line = line

        if "a" in chunk:
            for line in chunk["a"]:
                diff_lines.append(
                    {
                        "line": "-{}".format(line),
                        "a": len(line_mapping_a_to_diff),
                        "line-num-a": len(line_mapping_a_to_diff),
                        "line-num-b": len(line_mapping_b_to_diff),
                        "context": last_interesting_line,
                    }
                )

                line_mapping_a_to_diff.append(len(diff_lines) - 1)

                if is_interesting_line_c(line):
                    last_interesting_line = line

        if "b" in chunk:
            for line in chunk["b"]:
                diff_lines.append(
                    {
                        "line": "+{}".format(line),
                        "b": len(line_mapping_b_to_diff),
                        "line-num-a": len(line_mapping_a_to_diff),
                        "line-num-b": len(line_mapping_b_to_diff),
                        "context": last_interesting_line,
                    }
                )

                line_mapping_b_to_diff.append(len(diff_lines) - 1)

                if is_interesting_line_c(line):
                    last_interesting_line = line

    return diff_lines, line_mapping_a_to_diff, line_mapping_b_to_diff


def print_one_diff_line(diff, diff_line, num_width_a, num_width_b):
    # Keep this around because it's useful for debugging.
    print_line_number_prefix = False
    if print_line_number_prefix:
        if diff.path_a is None:
            # File added
            print(
                "{b:{num_width_b}} ".format(b=diff_line["b"], num_width_b=num_width_b),
                end="",
            )
        elif diff.path_b is None:
            # File removed
            print(
                "{a:{num_width_a}} ".format(a=diff_line["a"], num_width_a=num_width_a),
                end="",
            )
        else:
            # File modified
            print(
                "{a:{num_width_a}} {b:{num_width_b}} ".format(
                    a=diff_line.get("a", ""),
                    b=diff_line.get("b", ""),
                    num_width_a=num_width_a,
                    num_width_b=num_width_b,
                ),
                end="",
            )

    print("> {}".format(diff_line["line"]))


def print_comments_matching_diff_line(comments, diff_line, revision):
    for comment in comments:
        if (
            comment.side == "PARENT"
            and "a" in diff_line
            and diff_line["a"] == comment.line
        ):
            print()
            print_comment(comment, revision)
            print()

        if (
            comment.side == "REVISION"
            and "b" in diff_line
            and diff_line["b"] == comment.line
        ):
            print()
            print_comment(comment, revision)
            print()


def print_range_header(diff_slice):
    """Print a hunk-like header that indicates where the following
    lines come from in a and b versions of the file."""
    line_start_a = diff_slice[0]["line-num-a"]
    line_start_b = diff_slice[0]["line-num-b"]
    context = diff_slice[0]["context"]
    num_lines_a = 0
    num_lines_b = 0

    for diff_line in diff_slice:
        if "a" in diff_line:
            num_lines_a += 1

        if "b" in diff_line:
            num_lines_b += 1

    print(
        "> @@ -{},{} +{},{} @@ {}".format(
            line_start_a, num_lines_a, line_start_b, num_lines_b, context
        )
    )


def render_diff_with_comments(server, diff, comments, revision):
    assert type(comments) is list

    if diff.path_a is not None:
        print("> --- {}".format(diff.path_a))
    else:
        print("> --- /dev/null")

    if diff.path_b is not None:
        print("> +++ {}".format(diff.path_b))
    else:
        print("> +++ /dev/null")

    diff_lines, line_mapping_a_to_diff, line_mapping_b_to_diff = render_diff(diff)

    def comment_to_diff_range_idx(comment):
        mapping = (
            line_mapping_a_to_diff
            if comment.side == "PARENT"
            else line_mapping_b_to_diff
        )

        if comment.range is not None:
            # Range comment.
            start = mapping[comment.range.start_line]
            end = mapping[comment.range.end_line]
            return start, end
        else:
            # Line comment.
            idx = mapping[comment.line]
            return idx, idx

    diff_line_ranges_to_print = []

    for comment in comments:
        if comment.line is None:
            # It's a file comment, doesn't matter for ranges.
            continue

        start_idx_in_diff, end_idx_in_diff = comment_to_diff_range_idx(comment)

        # We want to print at least from this point.
        low = max(0, start_idx_in_diff - 9)

        # And up to this point (exclusive).
        high = min(len(diff_lines) - 1, end_idx_in_diff + 10)

        if len(diff_line_ranges_to_print) == 0:
            # This is the first range we insert.
            diff_line_ranges_to_print.append((low, high))
        else:
            prev_range = diff_line_ranges_to_print[-1]
            if prev_range[1] >= low:
                # Overlap (or contiguous) with prev range, merge.
                diff_line_ranges_to_print[-1] = (prev_range[0], high)
            else:
                # Disjoint from prev range.
                diff_line_ranges_to_print.append((low, high))

    # First, print any file-level comments.
    for comment in comments:
        if comment.line is None:
            print_comment(comment, revision)
            print()
            continue

    # Print all diff ranges we want to print, with comments matching those lines.
    for i, (low, high) in enumerate(diff_line_ranges_to_print):
        diff_slice = diff_lines[low:high]

        print_range_header(diff_slice)

        # Figure out the maximal line number for a and b we'll need to display
        # in this range
        max_a_line = 0
        max_b_line = 0

        for diff_line in diff_slice:
            if "a" in diff_line:
                max_a_line = max(max_a_line, diff_line["a"])

            if "b" in diff_line:
                max_b_line = max(max_b_line, diff_line["b"])

        num_width_a = len(str(max_a_line))
        num_width_b = len(str(max_b_line))

        for diff_line in diff_slice:
            print_one_diff_line(diff, diff_line, num_width_a, num_width_b)
            print_comments_matching_diff_line(comments, diff_line, revision)

        if i != len(diff_line_ranges_to_print) - 1:
            print()
            print(" ...")
            print()


def read_int():
    while True:
        print("? ", end="")
        sys.stdout.flush()
        answer = sys.stdin.readline().strip()

        try:
            return int(answer)
        except ValueError:
            print("Can't parse {} as an integer.".format(answer))


def choose(items, key_func, render_func):
    by_key = {}

    for item in items:
        key = key_func(item)
        text = render_func(item)
        assert key not in by_key
        by_key[key] = item

        print("[{}] {}".format(key, text))

    while True:
        answer = read_int()
        if answer in by_key:
            return by_key[answer]
        else:
            print("Invalid choice.")


def main():
    if len(sys.argv) not in (3, 5):
        print("Invalid number of parameters.")
        print()
        print("Interactive usage: ./generate.py [server base address] [change number]")
        print(
            "Unattended usage:  ./generate.py [server base address] [change number] [author id] [comment timestamp]"
        )
        print()
        print("Examples:")
        print("  ./generate.py 'https://gnutoolchain-gerrit.osci.io/r' 483")
        print(
            "  ./generate.py 'https://gnutoolchain-gerrit.osci.io/r' 483 1000025 \"2019-11-05 23:52:21.000000000\""
        )
        sys.exit(1)

    interactive = len(sys.argv) == 3

    server_address = sys.argv[1]
    change_number = int(sys.argv[2])

    server = Server(server_address)

    change = server.get_change(change_number)
    if change is None:
        raise Exception("Change {} does not exist.".format(change_number))

    messages = server.get_change_messages(change)
    messages = sorted(messages, key=lambda m: m.date)

    if interactive:

        class Count:
            def __init__(self):
                self._n = 0

            def __call__(self, item):
                self._n += 1
                return self._n

        message = choose(
            messages,
            Count(),
            lambda m: "By {} ({}) at '{}'".format(m.author.name, m.author.id, m.date),
        )
    else:
        author_id = int(sys.argv[3])
        timestamp = sys.argv[4]

        for message in messages:
            if message.author.id == author_id and message.date == timestamp:
                break
        else:
            raise Exception(
                "Could not find message corresponding to author {} and timestamp {}".format(
                    author_id, timestamp
                )
            )

    # Look for code comments that were posted along this message.
    comments_by_revision = server.get_change_message_comments(change, message)

    for (revision, comments_by_path) in comments_by_revision.items():
        for (path, comment_for_path) in comments_by_path.items():
            diff_from_base_to_rev = server.get_diff(change, revision, path)
            render_diff_with_comments(
                server, diff_from_base_to_rev, comment_for_path, revision
            )


if __name__ == "__main__":
    main()
