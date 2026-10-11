"""
ChronoDB Query Layer — a small SQL dialect over the version engine

Supported statements (keywords are case-insensitive, statements end with ';'):

  SELECT <* | col [AS alias], ... | COUNT(*) | aggregate(col)> FROM <table>
        [AS OF COMMIT '<hash>' | AS OF BRANCH <name> | AS OF TAG <name>
         | AS OF TIMESTAMP '<ISO-8601 or epoch seconds>']
        [WHERE <expr>] [GROUP BY col] [ORDER BY col [ASC|DESC], ...]
        [LIMIT n [OFFSET m]]
  INSERT INTO <table> [(col, ...)] VALUES (v, ...)[, (v, ...)]
  UPDATE <table> SET col = expr[, ...] [WHERE <expr>]
  DELETE FROM <table> [WHERE <expr>]
  SHOW TABLES | SHOW BRANCHES | SHOW TAGS | SHOW LOG [LIMIT n]
  DESCRIBE <table>

Expressions: literals ('text', 12, 3.5, TRUE, FALSE, NULL), column names,
+ - * / %, =, != / <>, <, <=, >, >=, LIKE, NOT LIKE, IN (...), NOT IN (...),
BETWEEN a AND b, IS [NOT] NULL, AND, OR, NOT, parentheses.

Rows are schemaless JSON objects; `row_id` is the primary key. INSERT uses an
`id` or `row_id` column as the key when one is given and generates one
otherwise. All writes in a script are staged and committed together as one
commit on the target branch, so a multi-statement script is atomic.
"""

import datetime as _dt
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# ────────────────────────────────────────────────
# Tokenizer
# ────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+|--[^\n]*)
  | (?P<num>\d+\.\d*|\.\d+|\d+)
  | (?P<str>'(?:[^']|'')*')
  | (?P<qid>"(?:[^"]|"")*"|`[^`]*`)
  | (?P<op><=|>=|!=|<>|=|<|>|\+|-|\*|/|%|\(|\)|,|;|\.)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)

KEYWORDS = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "INSERT", "INTO", "VALUES", "UPDATE", "SET",
    "DELETE", "ORDER", "BY", "ASC", "DESC", "LIMIT", "OFFSET", "AS", "OF", "COMMIT", "BRANCH",
    "TAG", "TIMESTAMP", "LIKE", "IN", "IS", "NULL", "TRUE", "FALSE", "BETWEEN", "SHOW", "TABLES",
    "BRANCHES", "TAGS", "LOG", "DESCRIBE", "DESC", "COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP",
    "DISTINCT",
}


class SQLError(ValueError):
    pass


@dataclass
class Tok:
    kind: str   # num, str, id, kw, op, eof
    value: Any
    pos: int
    end: int = 0
    text: str = ""


def tokenize(sql: str) -> List[Tok]:
    out: List[Tok] = []
    pos = 0
    while pos < len(sql):
        m = _TOKEN_RE.match(sql, pos)
        if not m:
            raise SQLError(f"Unexpected character {sql[pos]!r} at position {pos}")
        kind = m.lastgroup
        text = m.group()
        end = m.end()
        if kind == "num":
            out.append(Tok("num", float(text) if "." in text else int(text), pos, end, text))
        elif kind == "str":
            out.append(Tok("str", text[1:-1].replace("''", "'"), pos, end, text))
        elif kind == "qid":
            out.append(Tok("id", text[1:-1], pos, end, text))
        elif kind == "op":
            out.append(Tok("op", text, pos, end, text))
        elif kind == "id":
            up = text.upper()
            out.append(Tok("kw", up, pos, end, text) if up in KEYWORDS else Tok("id", text, pos, end, text))
        pos = end
    out.append(Tok("eof", None, pos))
    return out


# ────────────────────────────────────────────────
# AST
# ────────────────────────────────────────────────

Expr = Tuple  # ("lit", v) | ("col", name) | ("bin", op, a, b) | ("not", e) | ("in", e, [..], neg)
              # ("like", e, pat, neg) | ("isnull", e, neg) | ("between", e, lo, hi, neg) | ("neg", e)


@dataclass
class SelectItem:
    kind: str                # "star" | "expr" | "agg"
    expr: Optional[Expr] = None
    func: Optional[str] = None
    alias: Optional[str] = None


@dataclass
class Select:
    table: str
    items: List[SelectItem]
    where: Optional[Expr] = None
    order: List[Tuple[str, bool]] = field(default_factory=list)
    limit: Optional[int] = None
    offset: int = 0
    as_of: Optional[Tuple[str, Any]] = None
    group_by: Optional[str] = None
    distinct: bool = False


@dataclass
class Insert:
    table: str
    columns: Optional[List[str]]
    rows: List[List[Expr]]


@dataclass
class Update:
    table: str
    sets: List[Tuple[str, Expr]]
    where: Optional[Expr]


@dataclass
class Delete:
    table: str
    where: Optional[Expr]


@dataclass
class Show:
    what: str
    limit: Optional[int] = None


@dataclass
class Describe:
    table: str


# ────────────────────────────────────────────────
# Parser
# ────────────────────────────────────────────────

class Parser:
    def __init__(self, sql: str):
        self.toks = tokenize(sql)
        self.i = 0

    # helpers
    def peek(self, k: int = 0) -> Tok:
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def next(self) -> Tok:
        t = self.toks[self.i]
        self.i += 1
        return t

    def at_kw(self, *kws: str) -> bool:
        t = self.peek()
        return t.kind == "kw" and t.value in kws

    def at_op(self, *ops: str) -> bool:
        t = self.peek()
        return t.kind == "op" and t.value in ops

    def accept_kw(self, kw: str) -> bool:
        if self.at_kw(kw):
            self.i += 1
            return True
        return False

    def accept_op(self, op: str) -> bool:
        if self.at_op(op):
            self.i += 1
            return True
        return False

    def expect_kw(self, kw: str) -> None:
        if not self.accept_kw(kw):
            self.fail(f"expected {kw}")

    def expect_op(self, op: str) -> None:
        if not self.accept_op(op):
            self.fail(f"expected '{op}'")

    def fail(self, msg: str) -> None:
        t = self.peek()
        got = "end of input" if t.kind == "eof" else repr(t.value)
        raise SQLError(f"Syntax error at position {t.pos}: {msg}, got {got}")

    def ident(self) -> str:
        t = self.peek()
        if t.kind == "id":
            self.i += 1
            name = t.value
            # allow dotted names like table.col → keep last part
            while self.at_op(".") and self.peek(1).kind == "id":
                self.i += 1
                name = self.next().value
            return name
        if t.kind == "kw" and t.value not in ("FROM", "WHERE", "SET", "VALUES", "ORDER", "LIMIT", "AS"):
            # tolerate keywords used as column names (e.g. "log", "tag")
            self.i += 1
            return t.value.lower()
        self.fail("expected identifier")
        return ""

    # entry
    def parse_script(self) -> List[Any]:
        stmts = []
        while self.peek().kind != "eof":
            if self.accept_op(";"):
                continue
            stmts.append(self.statement())
            if not self.accept_op(";") and self.peek().kind != "eof":
                self.fail("expected ';'")
        if not stmts:
            raise SQLError("Empty query")
        return stmts

    def statement(self) -> Any:
        if self.accept_kw("SELECT"):
            return self.select()
        if self.accept_kw("INSERT"):
            return self.insert()
        if self.accept_kw("UPDATE"):
            return self.update()
        if self.accept_kw("DELETE"):
            self.expect_kw("FROM")
            table = self.ident()
            where = self.expr() if self.accept_kw("WHERE") else None
            return Delete(table, where)
        if self.accept_kw("SHOW"):
            t = self.next()
            what = str(t.value).upper()
            if what not in ("TABLES", "BRANCHES", "TAGS", "LOG"):
                raise SQLError("SHOW supports TABLES, BRANCHES, TAGS and LOG")
            limit = None
            if self.accept_kw("LIMIT"):
                limit = int(self.number())
            return Show(what, limit)
        if self.accept_kw("DESCRIBE") or self.accept_kw("DESC"):
            return Describe(self.ident())
        self.fail("expected SELECT, INSERT, UPDATE, DELETE, SHOW or DESCRIBE")

    def number(self) -> float:
        t = self.next()
        if t.kind != "num":
            self.i -= 1
            self.fail("expected a number")
        return t.value

    def select(self) -> Select:
        distinct = self.accept_kw("DISTINCT")
        items: List[SelectItem] = []
        while True:
            if self.accept_op("*"):
                items.append(SelectItem("star"))
            elif self.at_kw("COUNT", "SUM", "AVG", "MIN", "MAX") and self.peek(1).kind == "op" and self.peek(1).value == "(":
                func = self.next().value
                self.expect_op("(")
                if self.accept_op("*"):
                    arg = None
                else:
                    arg = self.expr()
                self.expect_op(")")
                alias = self.ident() if self.accept_kw("AS") else None
                items.append(SelectItem("agg", arg, func, alias or (f"{func.lower()}" if arg is None else f"{func.lower()}_{arg[1] if arg[0]=='col' else 'expr'}")))
            else:
                e = self.expr()
                alias = None
                if self.accept_kw("AS"):
                    alias = self.ident()
                elif self.peek().kind == "id":
                    alias = self.ident()
                items.append(SelectItem("expr", e, alias=alias or (e[1] if e[0] == "col" else None)))
            if not self.accept_op(","):
                break
        self.expect_kw("FROM")
        table = self.ident()
        q = Select(table, items, distinct=distinct)
        if self.at_kw("AS") and self.peek(1).kind == "kw" and self.peek(1).value == "OF":
            self.i += 2
            kind = self.next()
            kv = str(kind.value).upper()
            if kv == "COMMIT":
                q.as_of = ("commit", self.literal_or_ident())
            elif kv == "BRANCH":
                q.as_of = ("branch", self.literal_or_ident())
            elif kv == "TAG":
                q.as_of = ("tag", self.literal_or_ident())
            elif kv == "TIMESTAMP":
                q.as_of = ("timestamp", self.literal_or_ident())
            else:
                raise SQLError("AS OF expects COMMIT, BRANCH, TAG or TIMESTAMP")
        if self.accept_kw("WHERE"):
            q.where = self.expr()
        if self.accept_kw("GROUP"):
            self.expect_kw("BY")
            q.group_by = self.ident()
        if self.accept_kw("ORDER"):
            self.expect_kw("BY")
            while True:
                col = self.ident()
                desc = False
                if self.accept_kw("DESC"):
                    desc = True
                else:
                    self.accept_kw("ASC")
                q.order.append((col, desc))
                if not self.accept_op(","):
                    break
        if self.accept_kw("LIMIT"):
            q.limit = int(self.number())
            if self.accept_kw("OFFSET"):
                q.offset = int(self.number())
        return q

    def literal_or_ident(self) -> Any:
        t = self.next()
        if t.kind == "id" or (t.kind == "kw" and t.value not in ("WHERE", "ORDER", "GROUP", "LIMIT")):
            # Unquoted ref names may contain . - / (v1.0, feature/x-y): join
            # tokens that touch each other with no whitespace between them.
            name, end = t.text, t.end
            while self.peek().pos == end and self.peek().kind in ("id", "num", "kw", "op") \
                    and (self.peek().kind != "op" or self.peek().value in (".", "-", "/")):
                nt = self.next()
                name += nt.text
                end = nt.end
            return name
        if t.kind in ("str", "num"):
            return t.value
        self.i -= 1
        self.fail("expected a value")

    def insert(self) -> Insert:
        self.expect_kw("INTO")
        table = self.ident()
        cols = None
        if self.accept_op("("):
            cols = [self.ident()]
            while self.accept_op(","):
                cols.append(self.ident())
            self.expect_op(")")
        self.expect_kw("VALUES")
        rows = []
        while True:
            self.expect_op("(")
            vals = [self.expr()]
            while self.accept_op(","):
                vals.append(self.expr())
            self.expect_op(")")
            rows.append(vals)
            if not self.accept_op(","):
                break
        return Insert(table, cols, rows)

    def update(self) -> Update:
        table = self.ident()
        self.expect_kw("SET")
        sets = []
        while True:
            col = self.ident()
            self.expect_op("=")
            sets.append((col, self.expr()))
            if not self.accept_op(","):
                break
        where = self.expr() if self.accept_kw("WHERE") else None
        return Update(table, sets, where)

    # expressions (precedence climbing)
    def expr(self) -> Expr:
        return self.or_expr()

    def or_expr(self) -> Expr:
        e = self.and_expr()
        while self.accept_kw("OR"):
            e = ("bin", "OR", e, self.and_expr())
        return e

    def and_expr(self) -> Expr:
        e = self.not_expr()
        while self.accept_kw("AND"):
            e = ("bin", "AND", e, self.not_expr())
        return e

    def not_expr(self) -> Expr:
        if self.accept_kw("NOT"):
            return ("not", self.not_expr())
        return self.comparison()

    def comparison(self) -> Expr:
        e = self.additive()
        neg = False
        if self.at_kw("NOT") and self.peek(1).kind == "kw" and self.peek(1).value in ("LIKE", "IN", "BETWEEN"):
            self.i += 1
            neg = True
        if self.accept_kw("LIKE"):
            return ("like", e, self.additive(), neg)
        if self.accept_kw("IN"):
            self.expect_op("(")
            vals = [self.expr()]
            while self.accept_op(","):
                vals.append(self.expr())
            self.expect_op(")")
            return ("in", e, vals, neg)
        if self.accept_kw("BETWEEN"):
            lo = self.additive()
            self.expect_kw("AND")
            hi = self.additive()
            return ("between", e, lo, hi, neg)
        if self.accept_kw("IS"):
            n = self.accept_kw("NOT")
            self.expect_kw("NULL")
            return ("isnull", e, n)
        for op in ("<=", ">=", "!=", "<>", "=", "<", ">"):
            if self.accept_op(op):
                return ("bin", "!=" if op == "<>" else op, e, self.additive())
        return e

    def additive(self) -> Expr:
        e = self.term()
        while self.at_op("+", "-"):
            op = self.next().value
            e = ("bin", op, e, self.term())
        return e

    def term(self) -> Expr:
        e = self.unary()
        while self.at_op("*", "/", "%"):
            op = self.next().value
            e = ("bin", op, e, self.unary())
        return e

    def unary(self) -> Expr:
        if self.accept_op("-"):
            return ("neg", self.unary())
        return self.primary()

    def primary(self) -> Expr:
        t = self.peek()
        if t.kind in ("num", "str"):
            self.i += 1
            return ("lit", t.value)
        if t.kind == "kw" and t.value in ("TRUE", "FALSE", "NULL"):
            self.i += 1
            return ("lit", {"TRUE": True, "FALSE": False, "NULL": None}[t.value])
        if self.accept_op("("):
            e = self.expr()
            self.expect_op(")")
            return e
        return ("col", self.ident())


# ────────────────────────────────────────────────
# Evaluation
# ────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v) if any(c in v for c in ".eE") else int(v)
        except ValueError:
            return None
    return None


def _clean(x: Any) -> Any:
    """Trim binary floating-point noise (0.1 * 3 → 0.3)."""
    if isinstance(x, float):
        return float(f"{x:.12g}")
    return x


def _cmp_pair(a: Any, b: Any) -> Tuple[Any, Any]:
    """Coerce a pair for comparison: numeric if both look numeric, else text."""
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return na, nb
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).lower(), str(b).lower()
    return str(a), str(b)


def _like(value: Any, pattern: Any) -> bool:
    if value is None or pattern is None:
        return False
    rx = "^" + "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in str(pattern)) + "$"
    return re.match(rx, str(value), re.IGNORECASE | re.DOTALL) is not None


def evaluate(e: Expr, row: Dict[str, Any]) -> Any:
    k = e[0]
    if k == "lit":
        return e[1]
    if k == "col":
        name = e[1]
        if name in row:
            return row[name]
        if name == "id" and "row_id" in row:
            return row["row_id"]
        return None
    if k == "neg":
        v = _num(evaluate(e[1], row))
        return None if v is None else -v
    if k == "not":
        v = evaluate(e[1], row)
        return None if v is None else not bool(v)
    if k == "isnull":
        v = evaluate(e[1], row)
        return (v is not None) if e[2] else (v is None)
    if k == "like":
        r = _like(evaluate(e[1], row), evaluate(e[2], row))
        return not r if e[3] else r
    if k == "in":
        v = evaluate(e[1], row)
        hit = any(v is not None and x is not None and _cmp_pair(v, x)[0] == _cmp_pair(v, x)[1]
                  for x in (evaluate(i, row) for i in e[2]))
        return not hit if e[3] else hit
    if k == "between":
        v, lo, hi = evaluate(e[1], row), evaluate(e[2], row), evaluate(e[3], row)
        if v is None or lo is None or hi is None:
            return None
        a, l_ = _cmp_pair(v, lo)
        b, h = _cmp_pair(v, hi)
        try:
            r = l_ <= a and b <= h
        except TypeError:
            return None
        return not r if e[4] else r
    if k == "bin":
        op = e[1]
        if op == "AND":
            a = evaluate(e[2], row)
            if a is False:
                return False
            b = evaluate(e[3], row)
            if a is None or b is None:
                return None if (a is not False and b is not False) else False
            return bool(a) and bool(b)
        if op == "OR":
            a = evaluate(e[2], row)
            if a is True:
                return True
            b = evaluate(e[3], row)
            if a is None or b is None:
                return True if (a is True or b is True) else None
            return bool(a) or bool(b)
        a, b = evaluate(e[2], row), evaluate(e[3], row)
        if op in ("+", "-", "*", "/", "%"):
            if op == "+" and isinstance(a, str) and _num(a) is None:
                return None if b is None else f"{a}{b}"
            na, nb = _num(a), _num(b)
            if na is None or nb is None:
                return None
            if op == "+":
                return _clean(na + nb)
            if op == "-":
                return _clean(na - nb)
            if op == "*":
                return _clean(na * nb)
            if nb == 0:
                return None
            return _clean(na / nb if op == "/" else na % nb)
        if a is None or b is None:
            return None
        x, y = _cmp_pair(a, b)
        try:
            return {"=": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
        except TypeError:
            return None
    raise SQLError(f"Unsupported expression {k}")


def _truthy(e: Optional[Expr], row: Dict[str, Any]) -> bool:
    return True if e is None else evaluate(e, row) is True


def _sort_key(v: Any) -> Tuple[int, Any]:
    if v is None:
        return (2, "")
    n = _num(v)
    if n is not None:
        return (0, n)
    return (1, str(v).lower())


def parse_timestamp(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        d = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise SQLError(f"Cannot parse timestamp {s!r}; use ISO-8601 or epoch seconds")
    if d.tzinfo is None:
        d = d.astimezone()
    return d.timestamp()


# ────────────────────────────────────────────────
# Executor
# ────────────────────────────────────────────────

@dataclass
class StatementResult:
    kind: str                         # "rows" | "write" | "info"
    statement: str
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    affected: int = 0
    as_of: Optional[Dict[str, Any]] = None
    elapsed_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "statement": self.statement, "columns": self.columns,
                "rows": self.rows, "affected": self.affected, "as_of": self.as_of,
                "elapsed_ms": round(self.elapsed_ms, 3)}


class SQLExecutor:
    """Runs a SQL script against one branch of a VersionEngine."""

    def __init__(self, engine: Any, branch: str = "main"):
        self.engine = engine
        self.branch = branch
        # staged writes: (table, row_id) → data dict or None (deleted)
        self.staged: Dict[Tuple[str, str], Optional[Dict[str, Any]]] = {}

    # reading with staged writes applied
    def _base_rows(self, table: str, commit_id: int) -> Dict[str, Dict[str, Any]]:
        rows = {r["row_id"]: r for r in self.engine.read_table_at(table, commit_id)}
        return rows

    def _current_rows(self, table: str) -> List[Dict[str, Any]]:
        head = self.engine.catalog.get_branch(self.branch)["head_commit_id"]
        rows = self._base_rows(table, head)
        for (t, rid), data in self.staged.items():
            if t != table:
                continue
            if data is None:
                rows.pop(rid, None)
            else:
                rows[rid] = {"row_id": rid, **data}
        return list(rows.values())

    def _resolve_as_of(self, as_of: Tuple[str, Any]) -> Tuple[int, Dict[str, Any]]:
        kind, val = as_of
        cat = self.engine.catalog
        if kind == "commit":
            cid = self.engine._resolve_commit_id(str(val))
        elif kind == "branch":
            b = cat.get_branch(str(val))
            if b is None:
                raise SQLError(f"Branch '{val}' does not exist")
            cid = b["head_commit_id"]
        elif kind == "tag":
            t = cat.tags.get(str(val))
            if t is None:
                raise SQLError(f"Tag '{val}' does not exist")
            cid = t["commit_id"]
        else:
            cid = self.engine.commit_at_timestamp(parse_timestamp(val), self.branch)
        c = cat.get_commit(cid) or {}
        return cid, {"kind": kind, "value": val, "commit_hash": c.get("hash"),
                     "commit_message": c.get("message"), "timestamp": c.get("timestamp")}

    def run(self, sql: str) -> List[StatementResult]:
        stmts = Parser(sql).parse_script()
        results = []
        for st in stmts:
            t0 = time.perf_counter()
            res = self._exec(st)
            res.elapsed_ms = (time.perf_counter() - t0) * 1000.0
            results.append(res)
        return results

    def changes(self) -> List[Dict[str, Any]]:
        out = []
        for (t, rid), data in self.staged.items():
            if data is None:
                out.append({"action": "delete", "table_name": t, "row_id": rid})
            else:
                out.append({"action": "update", "table_name": t, "row_id": rid, "data": data})
        return out

    def _exec(self, st: Any) -> StatementResult:
        if isinstance(st, Select):
            return self._select(st)
        if isinstance(st, Insert):
            return self._insert(st)
        if isinstance(st, Update):
            return self._update(st)
        if isinstance(st, Delete):
            return self._delete(st)
        if isinstance(st, Show):
            return self._show(st)
        if isinstance(st, Describe):
            head = self.engine.catalog.get_branch(self.branch)["head_commit_id"]
            sch = self.engine.table_schema(st.table, head)
            rows = [{"column": c["name"], "type": c["type"], "nullable": c["nullable"]} for c in sch["columns"]]
            return StatementResult("rows", f"DESCRIBE {st.table}", ["column", "type", "nullable"], rows)
        raise SQLError("Unsupported statement")

    def _select(self, q: Select) -> StatementResult:
        as_of_info = None
        if q.as_of:
            cid, as_of_info = self._resolve_as_of(q.as_of)
            rows = list(self._base_rows(q.table, cid).values())
        else:
            rows = self._current_rows(q.table)
        rows = [r for r in rows if _truthy(q.where, r)]

        aggs = [i for i in q.items if i.kind == "agg"]
        if aggs or q.group_by:
            groups: Dict[Any, List[Dict[str, Any]]] = {}
            for r in rows:
                groups.setdefault(r.get(q.group_by) if q.group_by else None, []).append(r)
            if not q.group_by and not groups:
                groups[None] = []
            out = []
            for gk, grs in groups.items():
                o: Dict[str, Any] = {}
                for it in q.items:
                    if it.kind == "agg":
                        o[it.alias or it.func.lower()] = self._aggregate(it, grs)  # type: ignore[union-attr]
                    elif it.kind == "expr":
                        o[it.alias or "expr"] = evaluate(it.expr, grs[0]) if grs else None  # type: ignore[arg-type]
                if q.group_by and q.group_by not in o:
                    o = {q.group_by: gk, **o}
                out.append(o)
            rows_out = out
            columns = list(rows_out[0].keys()) if rows_out else [i.alias or "" for i in q.items]
        else:
            if q.order:
                for col, desc in reversed(q.order):
                    rows.sort(key=lambda r: _sort_key(r.get(col) if col != "id" else r.get("row_id")), reverse=desc)
            else:
                rows.sort(key=lambda r: _sort_key(r.get("row_id")))
            star = any(i.kind == "star" for i in q.items)
            columns: List[str] = []
            if star:
                seen = {"row_id": None}
                for r in rows:
                    for k in r:
                        seen.setdefault(k, None)
                columns = list(seen)
            rows_out = []
            for r in rows:
                o = {}
                for idx, it in enumerate(q.items):
                    if it.kind == "star":
                        for c in columns:
                            o[c] = r.get(c)
                    else:
                        name = it.alias or f"col{idx + 1}"
                        o[name] = evaluate(it.expr, r)  # type: ignore[arg-type]
                rows_out.append(o)
            for idx, it in enumerate(q.items):
                if it.kind != "star":
                    name = it.alias or f"col{idx + 1}"
                    if name not in columns:
                        columns.append(name)
            if q.distinct:
                seen_rows, uniq = set(), []
                for o in rows_out:
                    key = tuple((k, repr(v)) for k, v in o.items())
                    if key not in seen_rows:
                        seen_rows.add(key)
                        uniq.append(o)
                rows_out = uniq
        if q.order and (aggs or q.group_by):
            for col, desc in reversed(q.order):
                rows_out.sort(key=lambda r: _sort_key(r.get(col)), reverse=desc)
        if q.offset:
            rows_out = rows_out[q.offset:]
        if q.limit is not None:
            rows_out = rows_out[: q.limit]
        return StatementResult("rows", "SELECT", columns, rows_out, len(rows_out), as_of_info)

    @staticmethod
    def _aggregate(it: SelectItem, rows: List[Dict[str, Any]]) -> Any:
        if it.func == "COUNT":
            if it.expr is None:
                return len(rows)
            return sum(1 for r in rows if evaluate(it.expr, r) is not None)
        vals = [evaluate(it.expr, r) for r in rows]  # type: ignore[arg-type]
        nums = [n for n in (_num(v) for v in vals) if n is not None]
        if it.func in ("MIN", "MAX"):
            present = [v for v in vals if v is not None]
            if not present:
                return None
            pick = min if it.func == "MIN" else max
            return pick(present, key=_sort_key)
        if not nums:
            return None
        if it.func == "SUM":
            return _clean(sum(nums))
        return _clean(sum(nums) / len(nums))

    def _check_table(self, table: str) -> None:
        if not table or ":" in table:
            raise SQLError(f"Invalid table name {table!r}")

    def _insert(self, st: Insert) -> StatementResult:
        self._check_table(st.table)
        existing = {r["row_id"] for r in self._current_rows(st.table)}
        n = 0
        for vals in st.rows:
            cols = st.columns
            if cols is None:
                raise SQLError("INSERT needs a column list, e.g. INSERT INTO t (id, name) VALUES (...)")
            if len(cols) != len(vals):
                raise SQLError(f"INSERT has {len(cols)} columns but {len(vals)} values")
            data = {c: evaluate(v, {}) for c, v in zip(cols, vals)}
            rid = data.pop("row_id", None)
            if rid is None and "id" in data:
                rid = data["id"]
            if rid is None:
                rid = uuid.uuid4().hex[:8]
            rid = str(rid)
            if rid in existing:
                raise SQLError(f"Duplicate key: row '{rid}' already exists in {st.table}")
            existing.add(rid)
            self.staged[(st.table, rid)] = data
            n += 1
        return StatementResult("write", "INSERT", affected=n)

    def _update(self, st: Update) -> StatementResult:
        self._check_table(st.table)
        n = 0
        for r in self._current_rows(st.table):
            if not _truthy(st.where, r):
                continue
            new = {k: v for k, v in r.items() if k != "row_id"}
            for col, e in st.sets:
                if col == "row_id":
                    raise SQLError("row_id cannot be updated")
                new[col] = evaluate(e, r)
            self.staged[(st.table, r["row_id"])] = new
            n += 1
        return StatementResult("write", "UPDATE", affected=n)

    def _delete(self, st: Delete) -> StatementResult:
        self._check_table(st.table)
        n = 0
        for r in self._current_rows(st.table):
            if _truthy(st.where, r):
                self.staged[(st.table, r["row_id"])] = None
                n += 1
        return StatementResult("write", "DELETE", affected=n)

    def _show(self, st: Show) -> StatementResult:
        e = self.engine
        if st.what == "TABLES":
            head = e.catalog.get_branch(self.branch)["head_commit_id"]
            rows = [{"table": t, "rows": len(e.read_table_at(t, head))} for t in e.tables_at(head)]
            return StatementResult("rows", "SHOW TABLES", ["table", "rows"], rows)
        if st.what == "BRANCHES":
            rows = [{"branch": b["name"], "head": b.get("head_hash"), "ahead": b.get("ahead"),
                     "behind": b.get("behind"), "last_commit": b.get("head_message")}
                    for b in e.list_branches(detailed=True)]
            return StatementResult("rows", "SHOW BRANCHES", ["branch", "head", "ahead", "behind", "last_commit"], rows)
        if st.what == "TAGS":
            rows = [{"tag": t["name"], "commit": t.get("hash"), "message": t.get("message")} for t in e.list_tags()]
            return StatementResult("rows", "SHOW TAGS", ["tag", "commit", "message"], rows)
        log, _ = e.get_log(self.branch, limit=st.limit or 20)
        rows = [{"hash": c["hash"], "author": c["author"], "message": c["message"],
                 "time": _dt.datetime.fromtimestamp(c["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")} for c in log]
        return StatementResult("rows", "SHOW LOG", ["hash", "author", "message", "time"], rows)


def run_sql(engine: Any, sql: str, branch: str = "main", author: str = "sql",
            message: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Parse and run a script; commit staged writes as a single commit."""
    ex = SQLExecutor(engine, branch)
    if engine.catalog.get_branch(branch) is None:
        raise SQLError(f"Branch '{branch}' does not exist")
    results = ex.run(sql)
    changes = ex.changes()
    commit = None
    if changes and not dry_run:
        first = sql.strip().splitlines()[0][:120] if sql.strip() else "SQL"
        commit = engine.commit(branch, message or f"SQL: {first}", author, changes=changes)
    return {"results": [r.to_dict() for r in results], "commit": commit,
            "changes": len(changes), "dry_run": dry_run}
