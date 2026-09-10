# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import re


class Sym:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"Sym({self.name})"


class Kw:
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f":{self.name}"


class Reader:
    def __init__(self, text):
        self.s = text
        self.i = 0
        self.n = len(text)

    def peek(self):
        return self.s[self.i] if self.i < self.n else ""

    def skip_ws(self):
        while self.i < self.n:
            c = self.s[self.i]
            if c in " \t\r\n,":
                self.i += 1
            elif c == ";":
                while self.i < self.n and self.s[self.i] != "\n":
                    self.i += 1
            elif c == "#" and self.s[self.i:self.i + 2] == "#_":
                self.i += 2
                self.skip_ws()
                self.read()
            else:
                return

    def read_all(self):
        out = []
        while True:
            self.skip_ws()
            if self.i >= self.n:
                return out
            v = self.read()
            if v is not _SKIP:
                out.append(v)

    def read(self):
        self.skip_ws()
        if self.i >= self.n:
            return _SKIP
        c = self.s[self.i]
        if c == '"':
            return self.read_string()
        if c in "([{":
            return self.read_coll(c)
        if c in ")]}":
            self.i += 1
            return _SKIP
        if c == "#":
            nxt = self.s[self.i + 1:self.i + 2]
            if nxt == "{":
                self.i += 1
                v = self.read_coll("{")
                return {"__set__": v.get("__map__") if isinstance(v, dict) else v}
            if nxt == "(":
                self.i += 1
                v = self.read_coll("(")
                return {"__fn__": v}
            if nxt == '"':
                self.i += 1
                return {"__regex__": self.read_string()}
            if nxt == "'":
                self.i += 2
                return self.read()
            self.i += 1
            return self.read()
        if c in "'`~@^":
            if c == "~" and self.s[self.i + 1:self.i + 2] == "@":
                self.i += 2
            else:
                self.i += 1
            if c == "^":
                self.read()
                return self.read()
            return self.read()
        if c == "\\":
            self.i += 1
            m = re.match(r"[A-Za-z0-9]+|.", self.s[self.i:])
            self.i += len(m.group(0))
            return {"__char__": m.group(0)}
        return self.read_atom()

    def read_string(self):
        self.i += 1
        buf = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                nxt = self.s[self.i + 1]
                mapping = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
                if nxt == "u":
                    buf.append(chr(int(self.s[self.i + 2:self.i + 6], 16)))
                    self.i += 6
                    continue
                buf.append(mapping.get(nxt, nxt))
                self.i += 2
                continue
            if c == '"':
                self.i += 1
                return "".join(buf)
            buf.append(c)
            self.i += 1
        return "".join(buf)

    def read_coll(self, opener):
        closer = {"(": ")", "[": "]", "{": "}"}[opener]
        self.i += 1
        items = []
        while True:
            self.skip_ws()
            if self.i >= self.n:
                break
            if self.s[self.i] == closer:
                self.i += 1
                break
            if self.s[self.i] in ")]}":
                self.i += 1
                break
            v = self.read()
            if v is not _SKIP:
                items.append(v)
        if opener == "{":
            return {"__map__": items}
        return items

    def read_atom(self):
        m = re.match(r"[^\s()\[\]{}\"',;`~@^\\]+", self.s[self.i:])
        if not m:
            self.i += 1
            return _SKIP
        tok = m.group(0)
        self.i += len(tok)
        if tok.startswith(":"):
            return Kw(tok[1:])
        if tok in ("true", "false"):
            return tok == "true"
        if tok == "nil":
            return None
        try:
            return int(tok)
        except ValueError:
            pass
        try:
            return float(tok)
        except ValueError:
            pass
        return Sym(tok)


class _Skip:
    def __repr__(self):
        return "<skip>"


_SKIP = _Skip()


def read_all(text):
    return Reader(text).read_all()
