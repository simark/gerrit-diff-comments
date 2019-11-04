import json
import requests
import sys
import urllib.parse
import textwrap
from collections import OrderedDict


class GerritProject:
    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name

    @classmethod
    def from_raw(cls, name, raw):
        return cls(name)

    def __str__(self):
        return "<GerritProject {}>".format(self.name)

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
        comment._range = raw.get("range", None)

        return comment

    def __str__(self):
        return "<Comment by {} at {}>".format(self.author.name, self.date)

    def __repr__(self):
        return str(self)


class Diff:
    @property
    def content(self):
        return self._content

    @classmethod
    def from_raw(cls, raw):
        diff = cls()

        diff._content = raw["content"]

        return diff


class GerritServer:
    def __init__(self, base_addr):
        self._base_addr = base_addr

    def _json_query(self, path):
        url = "{}/{}".format(self._base_addr, path)
        print("Getting {}".format(url))
        text = requests.get(url).text
        text = text[5:]
        return json.loads(text)

    def get_projects(self):
        raw = self._json_query("projects/")
        projects = []

        for (name, proj_raw) in raw.items():
            projects.append(GerritProject.from_raw(name, proj_raw))

        return projects

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


server = GerritServer("https://gnutoolchain-gerrit.osci.io/r")

changes = server.get_changes()

# Make it a dict index by change number
changes = {change.number: change for change in changes}

print("Enter a change number")
change_number = read_int()

if change_number not in changes:
    raise Exception("This change does not exist.")

change = changes[change_number]

messages = server.get_change_messages(change)


class Count:
    def __init__(self):
        self._n = 0

    def __call__(self, item):
        self._n += 1
        return self._n


messages = sorted(messages, key=lambda m: m.date)
message = choose(
    messages, Count(), lambda m: "By {} at {}".format(m.author.name, m.date)
)

# Look for code comments that were posted along this message.
comments_by_revision = server.get_change_message_comments(change, message)


def maybe_print_comment(line_number, comments):
    comment = comments.get(line_number, None)

    if comment is None:
        return

    print()
    # print("{} {}".format(where, comment.line))
    print(textwrap.fill(comment.message))
    print()


def render_diff_with_comments(diff, comments):
    assert type(comments) is list

    comments_on_base = {x.line: x for x in comments if x.side == "PARENT"}
    comments_on_rev = {x.line: x for x in comments if x.side == "REVISION"}

    line_number_a = 1
    line_number_b = 1

    for chunk in diff.content:
        if "ab" in chunk:
            for line in chunk["ab"]:
                print("  {:4} {:4} {}".format(line_number_a, line_number_b, line))

                maybe_print_comment(line_number_a, comments_on_base)
                maybe_print_comment(line_number_b, comments_on_rev)

                line_number_a += 1
                line_number_b += 1

        if "a" in chunk:
            for line in chunk["a"]:
                print("- {:4} {:4} {}".format(line_number_a, "", line))

                maybe_print_comment(line_number_a, comments_on_base)

                line_number_a += 1

        if "b" in chunk:
            for line in chunk["b"]:
                print("+ {:4} {:4} {}".format("", line_number_b, line))

                maybe_print_comment(line_number_b, comments_on_rev)

                line_number_b += 1


for (revision, comments_by_path) in comments_by_revision.items():
    for (path, comment_for_path) in comments_by_path.items():
        diff_from_base_to_rev = server.get_diff(change, revision, path)
        render_diff_with_comments(diff_from_base_to_rev, comment_for_path)
