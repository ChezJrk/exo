# import ast as pyast
import functools
import inspect
import re

# import types
from dataclasses import dataclass
from typing import Any, List, Union, Tuple

from .API import Procedure
from .API_cursors import public_cursors as PC, ExprCursor
from .LoopIR import LoopIR, T  # , UAST, LoopIR_Do
import exo.LoopIR_scheduling as scheduling

from .LoopIR_unification import DoReplace, UnificationError
from .configs import Config
from .effectcheck import CheckEffects
from .memory import Memory
from .parse_fragment import parse_fragment
from .prelude import *
from . import internal_cursors as ic


def is_subclass_obj(x, cls):
    return isinstance(x, type) and issubclass(x, cls)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Generic Definitions: Atomic Scheduling Operations and Argument Processing


@dataclass
class ArgumentProcessor:
    i: int
    arg_name: str
    f_name: str

    def __init__(self):
        # see setdata below for setting of the above fields
        pass

    def err(self, message, Error=TypeError):
        raise Error(f"argument {self.i}, '{self.arg_name}' to {self.f_name}: {message}")

    def setdata(self, i, arg_name, f_name):
        self.i = i
        self.arg_name = arg_name
        self.f_name = f_name

    def __call__(self, arg, all_args):
        raise NotImplementedError("Must Sub-class and redefine __call__")


@dataclass
class AtomicSchedulingOp:
    sig: inspect.Signature
    arg_procs: List[ArgumentProcessor]
    func: Any

    def __str__(self):
        return f"<AtomicSchedulingOp-{self.__name__}>"

    def __call__(self, *args, **kwargs):
        # capture the arguments according to the provided signature
        bound_args = self.sig.bind(*args, **kwargs)

        # potentially need to patch in default values...
        bargs = bound_args.arguments
        if len(self.arg_procs) != len(bargs):
            for nm in self.sig.parameters:
                if nm not in bargs:
                    default_val = self.sig.parameters[nm].default
                    assert default_val != inspect.Parameter.empty
                    kwargs[nm] = default_val
            # now re-bind the arguments with the defaults having been added
            bound_args = self.sig.bind(*args, **kwargs)
            bargs = bound_args.arguments

        # convert the arguments using the provided argument processors
        assert len(self.arg_procs) == len(bargs)
        for nm, argp in zip(bargs, self.arg_procs):
            bargs[nm] = argp(bargs[nm], bargs)

        # invoke the scheduling function with the modified arguments
        return self.func(*bound_args.args, **bound_args.kwargs)


# decorator for building Atomic Scheduling Operations in the
# remainder of this file
def sched_op(arg_procs):
    def check_ArgP(argp):
        if is_subclass_obj(argp, ArgumentProcessor):
            return argp()
        else:
            assert isinstance(argp, ArgumentProcessor)
            return argp

    # note pre-pending of ProcA
    arg_procs = [check_ArgP(argp) for argp in ([ProcA] + arg_procs)]

    def build_sched_op(func):
        f_name = func.__name__
        sig = inspect.signature(func)
        assert len(arg_procs) == len(sig.parameters)

        # record extra implicit information in the argument processors
        for i, (param, arg_p) in enumerate(zip(sig.parameters, arg_procs)):
            arg_p.setdata(i, param, f_name)

        atomic_op = AtomicSchedulingOp(sig, arg_procs, func)
        return functools.wraps(func)(atomic_op)

    return build_sched_op


def is_atomic_scheduling_op(x):
    return isinstance(x, AtomicSchedulingOp)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Argument Processing


class IdA(ArgumentProcessor):
    def __call__(self, arg, all_args):
        return arg


class ProcA(ArgumentProcessor):
    def __call__(self, proc, all_args):
        if not isinstance(proc, Procedure):
            self.err("expected a Procedure object")
        return proc


class MemoryA(ArgumentProcessor):
    def __call__(self, mem, all_args):
        if not is_subclass_obj(mem, Memory):
            self.err("expected a Memory subclass")
        return mem


class ConfigA(ArgumentProcessor):
    def __call__(self, config, all_args):
        if not isinstance(config, Config):
            self.err("expected a Config object")
        return config


class ConfigFieldA(ArgumentProcessor):
    def __init__(self, config_arg_name="config"):
        self.cfg_arg = config_arg_name

    def __call__(self, field, all_args):
        config = all_args[self.cfg_arg]
        if not is_valid_name(field):
            self.err("expected a valid name string")
        elif not config.has_field(field):
            self.err(
                f"expected '{field}' to be a field of config '{config.name()}'",
                ValueError,
            )
        return field


class NameA(ArgumentProcessor):
    def __call__(self, name, all_args):
        if not is_valid_name(name):
            self.err("expected a valid name")
        return name


class PosIntA(ArgumentProcessor):
    def __call__(self, val, all_args):
        if not is_pos_int(val):
            self.err("expected a positive integer")
        return val


class IntA(ArgumentProcessor):
    def __call__(self, val, all_args):
        if not isinstance(val, int):
            self.err("expected an integer")
        return val


class BoolA(ArgumentProcessor):
    def __call__(self, bval, all_args):
        if not isinstance(bval, bool):
            self.err("expected a bool")
        return bval


class OptionalA(ArgumentProcessor):
    def __init__(self, arg_proc):
        if is_subclass_obj(arg_proc, ArgumentProcessor):
            arg_proc = arg_proc()
        self.arg_proc = arg_proc

    def setdata(self, i, arg_name, f_name):
        super().setdata(i, arg_name, f_name)
        self.arg_proc.setdata(i, arg_name, f_name)

    def __call__(self, opt_arg, all_args):
        if opt_arg is None:
            return opt_arg
        else:
            return self.arg_proc(opt_arg, all_args)


class ListA(ArgumentProcessor):
    def __init__(self, elem_arg_proc, list_only=False, length=None):
        if is_subclass_obj(elem_arg_proc, ArgumentProcessor):
            elem_arg_proc = elem_arg_proc()
        self.elem_arg_proc = elem_arg_proc
        self.list_only = list_only
        self.fixed_length = length

    def setdata(self, i, arg_name, f_name):
        super().setdata(i, arg_name, f_name)
        self.elem_arg_proc.setdata(i, arg_name, f_name)

    def __call__(self, xs, all_args):
        if self.list_only:
            if not isinstance(xs, list):
                self.err("expected a list")
        else:
            if not isinstance(xs, (list, tuple)):
                self.err("expected a list or tuple")
        if self.fixed_length:
            if len(xs) != self.fixed_length:
                self.err(f"expected a list of length {self.fixed_length}")
        # otherwise, check the entries
        xs = [self.elem_arg_proc(x, all_args) for x in xs]
        return xs


class ListOrElemA(ListA):
    def __call__(self, xs, all_args):
        arg_typ = list if self.list_only else (list, tuple)
        if isinstance(xs, arg_typ):
            return super().__call__(xs, all_args)
        else:
            return [self.elem_arg_proc(xs, all_args)]


class InstrStrA(ArgumentProcessor):
    def __call__(self, instr, all_args):
        if not isinstance(instr, str):
            self.err("expected an instruction macro " "(i.e. a string with {} escapes)")
        return instr


_name_count_re = r"^([a-zA-Z_]\w*)\s*(\#\s*([0-9]+))?$"


class NameCountA(ArgumentProcessor):
    def __call__(self, name_count, all_args):
        if not isinstance(name_count, str):
            self.err("expected a string")
        results = re.search(_name_count_re, name_count)
        if not results:
            self.err(
                "expected a name pattern of the form\n"
                "  <ident> [# <int>]?\n"
                "where <ident> is the name of a variable "
                "and <int> specifies which occurrence. "
                "(e.g. 'x #2' means 'the second occurence of x')",
                ValueError,
            )

        name = results[1]
        count = int(results[3]) if results[3] else None
        return (name, count)


class EnumA(ArgumentProcessor):
    def __init__(self, enum_vals):
        assert isinstance(enum_vals, list)
        self.enum_vals = enum_vals

    def __call__(self, arg, all_args):
        if arg not in self.enum_vals:
            vals_str = ", ".join([str(v) for v in self.enum_vals])
            self.err(f"expected one of the following values: {vals_str}", ValueError)
        return arg


class TypeAbbrevA(ArgumentProcessor):
    _shorthand = {
        "R": T.R,
        "f32": T.f32,
        "f64": T.f64,
        "i8": T.int8,
        "i32": T.int32,
    }

    def __call__(self, typ, all_args):
        if typ in TypeAbbrevA._shorthand:
            return TypeAbbrevA._shorthand[typ]
        else:
            precisions = ", ".join([t for t in TypeAbbrevA._shorthand])
            self.err(
                f"expected one of the following strings specifying "
                f"precision: {precisions}",
                ValueError,
            )


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Cursor Argument Processing


class ExprCursorA(ArgumentProcessor):
    def __init__(self, many=False):
        self.match_many = many

    def __call__(self, expr_pattern, all_args):
        if self.match_many:
            if isinstance(expr_pattern, list):
                if all(isinstance(ec, PC.ExprCursor) for ec in expr_pattern):
                    return expr_pattern
                else:
                    for ec in expr_pattern:
                        if not isinstance(ec, PC.ExprCursor):
                            self.err(
                                f"expected a list of ExprCursor, "
                                f"not {type(expr_pattern)}"
                            )
            elif not isinstance(expr_pattern, str):
                self.err("expected an ExprCursor or pattern string")
        else:
            if isinstance(expr_pattern, PC.ExprCursor):
                return expr_pattern
            elif isinstance(expr_pattern, PC.Cursor):
                self.err(f"expected an ExprCursor, not {type(expr_pattern)}")
            elif not isinstance(expr_pattern, str):
                self.err("expected an ExprCursor or pattern string")

        proc = all_args["proc"]
        # TODO: Remove all need for `call_depth`
        matches = proc.find(expr_pattern, many=self.match_many)

        if self.match_many:
            for m in matches:
                if not isinstance(m, PC.ExprCursor):
                    self.err(
                        f"expected pattern to match only ExprCursors, not {type(m)}"
                    )
            return matches
        else:
            match = matches
            if not isinstance(match, PC.ExprCursor):
                self.err(f"expected pattern to match an ExprCursor, not {type(match)}")
            return match


class StmtCursorA(ArgumentProcessor):
    def __init__(self, many=False):
        self.match_many = many

    def __call__(self, stmt_pattern, all_args):
        if isinstance(stmt_pattern, PC.StmtCursor):
            return stmt_pattern
        elif isinstance(stmt_pattern, PC.Cursor):
            self.err(f"expected an StmtCursor, not {type(stmt_pattern)}")
        elif not isinstance(stmt_pattern, str):
            self.err("expected a StmtCursor or pattern string")

        proc = all_args["proc"]
        # TODO: Remove all need for `call_depth`
        matches = proc.find(stmt_pattern, many=self.match_many)

        match = matches[0] if self.match_many else matches
        if not isinstance(match, PC.StmtCursor):
            self.err(f"expected pattern to match a StmtCursor, not {type(match)}")

        return match


class BlockCursorA(ArgumentProcessor):
    def __init__(self, many=False, block_size=None):
        self.match_many = many
        self.block_size = block_size

    def __call__(self, block_pattern, all_args):
        if isinstance(block_pattern, PC.BlockCursor):
            cursor = block_pattern
        elif isinstance(block_pattern, PC.StmtCursor):
            cursor = block_pattern.as_block()
        else:
            if isinstance(block_pattern, PC.Cursor):
                self.err(
                    f"expected a StmtCursor or BlockCursor, "
                    f"not {type(block_pattern)}"
                )
            elif not isinstance(block_pattern, str):
                self.err("expected a Cursor or pattern string")

            proc = all_args["proc"]
            # TODO: Remove all need for `call_depth`
            matches = proc.find(block_pattern, many=self.match_many)

            match = matches[0] if self.match_many else matches
            if isinstance(match, PC.StmtCursor):
                match = match.as_block()
            elif not isinstance(match, PC.BlockCursor):
                self.err(f"expected pattern to match a BlockCursor, not {type(match)}")
            cursor = match

        # regardless, check block size
        if self.block_size:
            if len(cursor) != self.block_size:
                self.err(
                    f"expected a block of size {self.block_size}, "
                    f"but got a block of size {len(cursor)}",
                    ValueError,
                )

        return cursor


class GapCursorA(ArgumentProcessor):
    def __call__(self, gap_cursor, all_args):
        if not isinstance(gap_cursor, PC.GapCursor):
            self.err("expected a GapCursor")
        return gap_cursor


class AllocCursorA(StmtCursorA):
    def __call__(self, alloc_pattern, all_args):
        try:
            name, count = NameCountA()(alloc_pattern, all_args)
            count = f" #{count}" if count is not None else ""
            alloc_pattern = f"{name} : _{count}"
        except:
            pass

        cursor = super().__call__(alloc_pattern, all_args)
        if not isinstance(cursor, PC.AllocCursor):
            self.err(f"expected an AllocCursor, not {type(cursor)}")
        return cursor


class WindowStmtCursorA(StmtCursorA):
    def __call__(self, alloc_pattern, all_args):
        cursor = super().__call__(alloc_pattern, all_args)
        if not isinstance(cursor, PC.WindowStmtCursor):
            self.err(f"expected a WindowStmtCursor, not {type(cursor)}")
        return cursor


class ForSeqOrIfCursorA(StmtCursorA):
    def __call__(self, cursor_pat, all_args):
        # TODO: eliminate this redundancy with the ForSeqCursorA code
        # allow for a special pattern short-hand, but otherwise
        # handle as expected for a normal statement cursor
        try:
            name, count = NameCountA()(cursor_pat, all_args)
            count = f"#{count}" if count is not None else ""
            cursor_pat = f"for {name} in _: _{count}"
        except:
            pass

        cursor = super().__call__(cursor_pat, all_args)
        if not isinstance(cursor, (PC.ForSeqCursor, PC.IfCursor)):
            self.err(f"expected a ForSeqCursor or IfCursor, not {type(cursor)}")
        return cursor


class ForSeqCursorA(StmtCursorA):
    def __call__(self, loop_pattern, all_args):
        # allow for a special pattern short-hand, but otherwise
        # handle as expected for a normal statement cursor
        try:
            name, count = NameCountA()(loop_pattern, all_args)
            count = f"#{count}" if count is not None else ""
            loop_pattern = f"for {name} in _: _{count}"
        except:
            pass

        cursor = super().__call__(loop_pattern, all_args)
        if not isinstance(cursor, PC.ForSeqCursor):
            self.err(f"expected a ForSeqCursor, not {type(cursor)}")
        return cursor


class IfCursorA(StmtCursorA):
    def __call__(self, if_pattern, all_args):
        cursor = super().__call__(if_pattern, all_args)
        if not isinstance(cursor, PC.IfCursor):
            self.err(f"expected an IfCursor, not {type(cursor)}")
        return cursor


_name_name_count_re = r"^([a-zA-Z_]\w*)\s*([a-zA-Z_]\w*)\s*(\#\s*([0-9]+))?$"


class NestedForSeqCursorA(StmtCursorA):
    def __call__(self, loops_pattern, all_args):

        if isinstance(loops_pattern, PC.ForSeqCursor):
            if len(loops_pattern.body()) != 1 or not isinstance(
                loops_pattern.body()[0], PC.ForSeqCursor
            ):
                self.err(
                    f"expected the body of the outer loop "
                    f"to be a single loop, but it was a "
                    f"{loops_pattern.body()[0]}",
                    ValueError,
                )
            cursor = loops_pattern
        elif isinstance(loops_pattern, PC.Cursor):
            self.err(f"expected a ForSeqCursor, not {type(loops_pattern)}")
        elif isinstance(loops_pattern, str) and (
            match_result := re.search(_name_name_count_re, loops_pattern)
        ):
            pass
            out_name = match_result[1]
            in_name = match_result[2]
            count = f" #{match_result[3]}" if match_result[3] else ""
            pattern = f"for {out_name} in _:\n  for {in_name} in _: _{count}"
            cursor = super().__call__(pattern, all_args)
        else:
            self.err(
                "expected a ForSeqCursor, pattern match string, "
                "or 'outer_loop inner_loop' shorthand"
            )

        return cursor


class AssignOrReduceCursorA(StmtCursorA):
    def __call__(self, stmt_pattern, all_args):
        cursor = super().__call__(stmt_pattern, all_args)
        if not isinstance(cursor, (PC.AssignCursor, PC.ReduceCursor)):
            self.err(f"expected an AssignCursor or ReduceCursor, not {type(cursor)}")
        return cursor


class CallCursorA(StmtCursorA):
    def __call__(self, call_pattern, all_args):
        # allow for special pattern short-hands, but otherwise
        # handle as expected for a normal statement cursor
        if isinstance(call_pattern, Procedure):
            call_pattern = f"{call_pattern.name()}(_)"
        try:
            name, count = NameCountA()(call_pattern, all_args)
            count = f"#{count}" if count is not None else ""
            call_pattern = f"{name}(_)"
        except:
            pass

        cursor = super().__call__(call_pattern, all_args)
        if not isinstance(cursor, PC.CallCursor):
            self.err(f"expected a CallCursor, not {type(cursor)}")
        return cursor


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# New Code Fragment Argument Processing


@dataclass
class FormattedExprStr:
    """
    Allows the user to provide a string with holes in it along with
    `ExprCursor`s to fill the holes. The object is designed as a wrapper to
    allow the user to give those inputs as an argument to scheduling
    operations. The object does not evaluate the expression, but merely
    holds the string and AST nodes the cursors point to until they are
    passed to the scheduling operation where they are extracted
    and evaluated to a new expression.
    """

    _expr_str: str
    _expr_holes: Tuple[LoopIR.expr]

    def __init__(self, expr_str: str, *expr_holes) -> None:
        if not isinstance(expr_str, str):
            raise TypeError("expr_str must be a string")
        self._expr_str = expr_str
        for cursor in expr_holes:
            if not isinstance(cursor, ExprCursor):
                raise TypeError("Cursor provided to fill a hole must be a ExprCursor")
        self._expr_holes = tuple(cursor._impl._node for cursor in expr_holes)


class NewExprA(ArgumentProcessor):
    def __init__(self, cursor_arg, before=True):
        self.cursor_arg = cursor_arg
        self.before = before

    def _get_ctxt_stmt(self, all_args):
        proc = all_args["proc"]
        cursor = all_args[self.cursor_arg]

        # if we don't have a gap cursor, convert to a gap cursor
        if not isinstance(cursor, PC.GapCursor):
            cursor = cursor.before() if self.before else cursor.after()

        # resolve gaps down to statements in a somewhat silly way
        # TODO: improve parse_fragment to just take gaps
        if not (stmtc := cursor.after()):
            assert (stmtc := cursor.before())
        ctxt_stmt = stmtc._impl._node

        return ctxt_stmt

    def __call__(self, expr_str, all_args):
        expr_holes = None
        if isinstance(expr_str, int):
            return LoopIR.Const(expr_str, T.int, null_srcinfo())
        elif isinstance(expr_str, float):
            return LoopIR.Const(expr_str, T.R, null_srcinfo())
        elif isinstance(expr_str, bool):
            return LoopIR.Const(expr_str, T.bool, null_srcinfo())
        elif isinstance(expr_str, FormattedExprStr):
            expr_str, expr_holes = expr_str._expr_str, expr_str._expr_holes
        elif not isinstance(expr_str, str):
            self.err("expected a string")

        proc = all_args["proc"]
        ctxt_stmt = self._get_ctxt_stmt(all_args)

        expr = parse_fragment(
            proc._loopir_proc, expr_str, ctxt_stmt, expr_holes=expr_holes
        )
        return expr


# This is implemented as a workaround because the
# current PAST parser and PAST IR don't support windowing
# expressions.
class CustomWindowExprA(NewExprA):
    def __call__(self, expr_str, all_args):
        proc = all_args["proc"]
        ctxt_stmt = self._get_ctxt_stmt(all_args)

        # degenerate case of a scalar value
        if is_valid_name(expr_str):
            return expr_str, []

        # otherwise, we have multiple dimensions
        match = re.match(r"(\w+)\[([^\]]+)\]", expr_str)
        if not match:
            raise ValueError(
                f"expected windowing string of the form "
                f"'name[args]', but got '{expr_str}'"
            )
        buf_name, args = match.groups()
        if not is_valid_name(buf_name):
            raise ValueError(f"'{buf_name}' is not a valid name")

        loopir = proc._loopir_proc

        def parse_arg(a):
            match = re.match(r"\s*([^:]+)\s*:\s*([^:]+)\s*", a)
            if not match:
                # a.strip() to remove whitespace
                pt = parse_fragment(loopir, a.strip(), ctxt_stmt)
                return pt
            else:
                lo, hi = match.groups()
                lo = parse_fragment(loopir, lo, ctxt_stmt)
                hi = parse_fragment(loopir, hi, ctxt_stmt)
                return (lo, hi)

        args = [parse_arg(a) for a in args.split(",")]

        return buf_name, args


# --------------------------------------------------------------------------- #
#  - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * -
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#                       Atomic Scheduling Operations
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
#  - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * - * -
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Basic Operations


@sched_op([])
def simplify(proc):
    """
    Simplify the code in the procedure body. Tries to reduce expressions
    to constants and eliminate dead branches and loops. Uses branch
    conditions to simplify expressions inside the branches.
    """
    proc_c = ic.Cursor.create(proc)
    return scheduling.DoSimplify(proc_c).result()


@sched_op([NameA])
def rename(proc, name):
    """
    Rename the procedure. Affects generated symbol names.

    args:
        name    - string
    """
    p = proc._loopir_proc
    p = p.update(name=name)
    return Procedure(p, _provenance_eq_Procedure=proc)


@sched_op([InstrStrA])
def make_instr(proc, instr):
    """
    Turn this procedure into an "instruction" using the provided macro-string

    args:
        name    - string representing an instruction macro
    """
    p = proc._loopir_proc
    p = p.update(instr=instr)
    return Procedure(p, _provenance_eq_Procedure=proc)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# General Statement and Expression Operations


@sched_op([GapCursorA])
def insert_pass(proc, gap_cursor):
    """
    Insert a `pass` statement at the indicated position.

    args:
        gap_cursor  - where to insert the new `pass` statement

    rewrite:
        `s1 ; s2` <--- gap_cursor pointed at the semi-colon
        -->
        `s1 ; pass ; s2`
    """
    ir, _fwd = scheduling.DoInsertPass(gap_cursor._impl)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([])
def delete_pass(proc):
    """
    DEPRECATED (to be replaced by a more general operation)

    Delete all `pass` statements in the procedure.
    """
    proc_c = ic.Cursor.create(proc)
    return scheduling.DoDeletePass(proc_c).result()


@sched_op([BlockCursorA(block_size=2)])
def reorder_stmts(proc, block_cursor):
    """
    swap the order of two statements within a block.

    args:
        block_cursor    - a cursor to a two statement block to reorder

    rewrite:
        `s1 ; s2`  <-- block_cursor
        -->
        `s2 ; s1`
    """
    s1 = block_cursor[0]._impl
    s2 = block_cursor[1]._impl

    ir, _fwd = scheduling.DoReorderStmt(s1, s2)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([ExprCursorA(many=True)])
def commute_expr(proc, expr_cursors):
    """
    commute the binary operation of '+' and '*'.

    args:
        expr_cursors - a list of cursors to the binary operation

    rewrite:
        `a * b` <-- expr_cursor
        -->
        `b * a`

        or

        `a + b` <-- expr_cursor
        -->
        `b + a`
    """

    exprs = [ec._impl for ec in expr_cursors]
    for e in exprs:
        if not isinstance(e._node, LoopIR.BinOp) or (
            e._node.op != "+" and e._node.op != "*"
        ):
            raise TypeError(f"only '+' or '*' can commute, got {e._node.op}")
    if any(not e._node.type.is_numeric() for e in exprs):
        raise TypeError(
            "only numeric (not index or size) expressions "
            "can commute by commute_expr()"
        )

    ir, _fwd = scheduling.DoCommuteExpr(exprs)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([ExprCursorA(many=True), NameA, BoolA])
def bind_expr(proc, expr_cursors, new_name, cse=False):
    """
    Bind some numeric/data-value type expression into a new intermediate,
    scalar-sized buffer.  If `cse=True` and more than one expression is
    pointed to, then this operation will attempt to perform
    common sub-expression elimination while binding. It will stop upon
    encountering a read of any buffer that the expression depends on.

    args:
        expr_cursors    - a list of cursors to multiple instances of the
                          same expression
        new_name        - a string to name the new buffer
        cse             - (bool) use common sub-expression elimination?

    rewrite:
        bind_expr(..., '32.0 * x[i]', 'b')
        `a = 32.0 * x[i] + 4.0`
        -->
        `b : R`
        `b = 32.0 * x[i]`
        `a = b + 4.0`
    """
    exprs = [ec._impl for ec in expr_cursors]
    if any(not e._node.type.is_numeric() for e in exprs):
        raise TypeError(
            "only numeric (not index or size) expressions "
            "can be bound by bind_expr()"
        )

    proc_c = ic.Cursor.create(proc)
    return scheduling.DoBindExpr(proc_c, new_name, exprs, cse).result()


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Sub-procedure Operations


@sched_op([NameA, StmtCursorA])
def extract_subproc(proc, subproc_name, body_stmt):
    """
    Documentation TODO
    """
    proc_c = ic.Cursor.create(proc)
    stmt = body_stmt._impl
    passobj = scheduling.DoExtractMethod(proc_c, subproc_name, stmt)
    return (passobj.result(), passobj.subproc())


@sched_op([CallCursorA])
def inline(proc, call_cursor):
    """
    Inline a sub-procedure call.

    args:
        call_cursor     - Cursor or pattern pointing to a Call statement
                          whose body we want to inline
    """
    ir, _fwd = scheduling.DoInline(call_cursor._impl)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([BlockCursorA, ProcA, BoolA])
def replace(proc, block_cursor, subproc, quiet=False):
    """
    Attempt to match the supplied `subproc` against the supplied
    statement block.  If the two can be unified, then replace the block
    of statements with a call to `subproc`.

    args:
        block_cursor    - Cursor or pattern pointing to block of statements
        subproc         - Procedure object to replace this block with a
                          call to
        quiet           - (bool) control how much this operation prints
                          out debug info
    """
    stmts = [sc._impl._node for sc in block_cursor]
    try:
        p = DoReplace(subproc._loopir_proc, stmts).apply_proc(proc._loopir_proc)
        return Procedure(p, _provenance_eq_Procedure=proc)
    except UnificationError:
        if quiet:
            raise
        print(f"Failed to unify the following:\nSubproc:\n{subproc}Statements:\n")
        [print(s) for s in stmts]
        raise


@sched_op([CallCursorA, ProcA])
def call_eqv(proc, call_cursor, eqv_proc):
    """
    Swap out the indicated call with a call to `eqv_proc` instead.
    This operation can only be performed if the current procedures being
    called and `eqv_proc` are equivalent due to being scheduled
    from the same procedure (or one scheduled from the other).

    args:
        call_cursor     - Cursor or pattern pointing to a Call statement
        eqv_proc        - Procedure object for the procedure to be
                          substituted in

    rewrite:
        `orig_proc(...)`    ->    `eqv_proc(...)`
    """
    call_stmt = call_cursor._impl
    new_loopir = eqv_proc._loopir_proc

    proc_c = ic.Cursor.create(proc)
    rewrite_pass = scheduling.DoCallSwap(proc_c, call_stmt, new_loopir)
    mod_config = rewrite_pass.mod_eq()
    return rewrite_pass.result(mod_config=mod_config)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Precision, Memory and Window Setting Operations


@sched_op([NameCountA, TypeAbbrevA])
def set_precision(proc, name, typ):
    """
    Set the precision annotation on a given buffer to the provided
    base-type precision.

    args:
        name    - string w/ optional count, e.g. "x" or "x #3"
        typ     - string representing base data type

    rewrite:
        `name : _[...]    ->    name : typ[...]`
    """
    name, count = name
    proc_c = ic.Cursor.create(proc)
    return scheduling.DoSetTypAndMem(proc_c, name, count, basetyp=typ).result()


@sched_op([NameCountA, BoolA])
def set_window(proc, name, is_window=True):
    """
    Set the annotation on a given buffer to indicate that it should be
    a window (True) or should not be a window (False)

    args:
        name        - string w/ optional count, e.g. "x" or "x #3"
        is_window   - boolean representing whether a buffer is a window

    rewrite when is_window = True:
        `name : R[...]    ->    name : [R][...]`
    """
    name, count = name
    proc_c = ic.Cursor.create(proc)
    return scheduling.DoSetTypAndMem(proc_c, name, count, win=is_window).result()


@sched_op([NameCountA, MemoryA])
def set_memory(proc, name, memory_type):
    """
    Set the memory annotation on a given buffer to the provided memory.

    args:
        name    - string w/ optional count, e.g. "x" or "x #3"
        mem     - new Memory object

    rewrite:
        `name : _ @ _    ->    name : _ @ mem`
    """
    name, count = name
    proc_c = ic.Cursor.create(proc)
    return scheduling.DoSetTypAndMem(proc_c, name, count, mem=memory_type).result()


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Configuration Modifying Operations


@sched_op([ExprCursorA, ConfigA, ConfigFieldA])
def bind_config(proc, var_cursor, config, field):
    """
    extract a control-value expression and write it into some
    designated field of a config

    args:
        var_cursor  - cursor or pattern pointing at the expression to
                      be bound
        config      - config object to be written into
        field       - (string) the field of `config` to be written to

    rewrite:
        Let `s[ e ]` mean a statement with control expression `e` occurring
        within it.  Then,
        `s[ e ]    ->    config.field = e ; s[ config.field ]`
    """
    e = var_cursor._impl._node
    cfg_f_type = config.lookup(field)[1]
    if not isinstance(e, LoopIR.Read):
        raise ValueError("expected a cursor to a single variable Read")
    elif e.type != cfg_f_type:
        raise ValueError(
            f"expected type of expression to bind ({e.type}) "
            f"to match type of Config variable ({cfg_f_type})"
        )

    ir, _fwd, cfg = scheduling.DoBindConfig(config, field, var_cursor._impl)
    return Procedure(ir, _provenance_eq_Procedure=proc, _mod_config=cfg)


@sched_op([StmtCursorA])
def delete_config(proc, stmt_cursor):
    """
    delete a statement that writes to some config.field

    args:
        stmt_cursor - cursor or pattern pointing at the statement to
                      be deleted

    rewrite:
        `s1 ; config.field = _ ; s3    ->    s1 ; s3`
    """
    (ir, cfg), _fwd = scheduling.DoDeleteConfig(
        ic.Cursor.create(proc), stmt_cursor._impl
    )
    return Procedure(ir, _provenance_eq_Procedure=proc, _mod_config=cfg)


@sched_op([GapCursorA, ConfigA, ConfigFieldA, NewExprA("gap_cursor")])
def write_config(proc, gap_cursor, config, field, rhs):
    """
    insert a statement that writes a desired value to some config.field

    args:
        gap_cursor  - cursor pointing to where the new write statement
                      should be inserted
        config      - config object to be written into
        field       - (string) the field of `config` to be written to
        rhs         - (string) the expression to write into the field

    rewrite:
        `s1 ; s3    ->    s1 ; config.field = new_expr ; s3`
    """

    # TODO: just have scheduling pass take a gap cursor directly
    before = True
    if not (stmtc := gap_cursor.after()):
        assert (stmtc := gap_cursor.before())
        before = False
    stmt = stmtc._impl

    proc_c = ic.Cursor.create(proc)
    rewrite_pass = scheduling.DoConfigWrite(
        proc_c, stmt, config, field, rhs, before=before
    )
    mod_config = rewrite_pass.mod_eq()
    return rewrite_pass.result(mod_config=mod_config)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Memory and Windowing-oriented Operations


@sched_op([AllocCursorA, NewExprA("buf_cursor"), NewExprA("buf_cursor"), BoolA])
def expand_dim(proc, buf_cursor, alloc_dim, indexing_expr, unsafe_disable_checks=False):
    """
    expand the number of dimensions of a buffer variable (`buf_cursor`).
    After expansion, the existing code will initially only use particular
    entries of the new dimension, chosen by the provided `indexing_expr`

    args:
        buf_cursor      - cursor pointing to the Alloc to expand
        alloc_dim       - (string) an expression for the size
                          of the new buffer dimension.
        indexing_expr   - (string) an expression to index the newly
                          created dimension with.

    rewrite:
        `x : T[...] ; s`
          ->
        `x : T[alloc_dim, ...] ; s[ x[...] -> x[indexing_expr, ...] ]`
    checks:
        The provided dimension size is checked for positivity and the
        provided indexing expression is checked to make sure it is in-bounds
    """
    stmt_c = buf_cursor._impl
    ir, _fwd = scheduling.DoExpandDim(stmt_c, alloc_dim, indexing_expr)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([AllocCursorA, ListA(IntA)])
def rearrange_dim(proc, buf_cursor, permute_vector):
    """
    Rearranges the dimensions of the indicated buffer allocation according
    to the supplied permutation (`permute_vector`).

    args:
        buf_cursor      - cursor pointing to an Alloc statement
                          for an N-dimensional array
        permute_vector  - a permutation of the integers (0,1,...,N-1)

    rewrite:
        (with permute_vector = [2,0,1])
        `x : T[N,M,K]` -> `x : T[K,N,M]`
    """
    proc_c = ic.Cursor.create(proc)
    stmt = buf_cursor._impl
    # extra sanity check
    N = len(stmt._node.type.hi)
    if set(range(0, N)) != set(permute_vector):
        raise ValueError(
            f"permute_vector argument ({permute_vector}) "
            f"was not a permutation of {set(range(0, N))}"
        )
    return scheduling.DoRearrangeDim(proc_c, stmt, permute_vector).result()


@sched_op([AllocCursorA, ListA(OptionalA(NewExprA("buf_cursor"))), BoolA])
def bound_alloc(proc, buf_cursor, new_bounds, unsafe_disable_checks=False):
    """
    NOTE: TODO: This name needs to be changed
    change the dimensional extents of an allocation, but leave the number
    and order of dimensions the same.

    args:
        buf_cursor      - cursor pointing to the Alloc to change bounds of
        new_bounds      - (list of strings/ints) expressions for the
                          new sizes of each buffer dimension.
                          Pass `None` for any dimensions you do not want
                          to change the extent/bound of.

    rewrite:
        bound_alloc(p, 'x : _', ['N+1',None])
        `x : T[N,M]` -> `x : T[N+1,M]`

    checks:
        The new bounds are checked to make sure they don't cause any
        out-of-bounds memory accesses
    """
    proc_c = ic.Cursor.create(proc)
    stmt = buf_cursor._impl
    if len(stmt._node.type.hi) != len(new_bounds):
        raise ValueError(
            f"buffer has {len(stmt._node.type.hi)} dimensions, "
            f"but only {len(new_bounds)} bounds were supplied"
        )
    new_proc_c = scheduling.DoBoundAlloc(proc_c, stmt, new_bounds).result()

    if not unsafe_disable_checks:
        CheckEffects(new_proc_c._node)

    return new_proc_c


@sched_op([AllocCursorA, IntA, PosIntA])
def divide_dim(proc, alloc_cursor, dim_idx, quotient):
    """
    Divide the `dim_idx`-th buffer dimension into a higher-order
    and lower-order dimensions, where the lower-order dimension is given
    by the constant integer `quotient`.

    This limited implementation of `divide_dim` requires that the dimension
    being divided is constant itself.

    args:
        alloc_cursor    - cursor to the allocation to divide a dimension of
        dim_idx         - the index of the dimension to divide
        quotient        - (positive int) the factor to divide by

    rewrite:
        divide_dim(..., 1, 4)
        `x : R[n, 12, m]`
        `x[i, j, k] = ...`
        ->
        `x : R[n, 3, 4, m]`
        `x[i, j / 4, j % 4, k] = ...`
    """
    if quotient == 1:
        raise ValueError("why are you trying to divide by 1?")
    proc_c = ic.Cursor.create(proc)
    stmt = alloc_cursor._impl
    if not (0 <= dim_idx < len(stmt._node.type.shape())):
        raise ValueError(f"Cannot divide out-of-bounds dimension index {dim_idx}")

    return scheduling.DoDivideDim(proc_c, stmt, dim_idx, quotient).result()


@sched_op([AllocCursorA, IntA, IntA])
def mult_dim(proc, alloc_cursor, hi_dim_idx, lo_dim_idx):
    """
    Mutiply the `hi_dim_idx`-th buffer dimension by the `low_dim_idx`-th
    buffer dimension to create a single buffer dimension.  This operation
    is only permitted when the `lo_dim_idx`-th dimension is a constant
    integer value.

    args:
        alloc_cursor    - cursor to the allocation to divide a dimension of
        hi_dim_idx      - the index of the higher order dimension to multiply
        lo_dim_idx      - the index of the lower order dimension to multiply

    rewrite:
        mult_dim(..., 0, 2)
        `x : R[n, m, 4]`
        `x[i, j, k] = ...`
        ->
        `x : R[4*n, m]`
        `x[4*i + k, j] = ...`
    """
    stmt = alloc_cursor._impl
    for dim_idx in [hi_dim_idx, lo_dim_idx]:
        if not (0 <= dim_idx < len(stmt._node.type.shape())):
            raise ValueError(f"Cannot multiply out-of-bounds dimension index {dim_idx}")
    if hi_dim_idx == lo_dim_idx:
        raise ValueError(f"Cannot multiply dimension {hi_dim_idx} by itself")

    ir, _fwd = scheduling.DoMultiplyDim(stmt, hi_dim_idx, lo_dim_idx)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([AllocCursorA, PosIntA])
def lift_alloc(proc, alloc_cursor, n_lifts=1):
    """
    Lift a buffer allocation up and out of various Loops / If-statements.

    args:
        alloc_cursor    - cursor to the allocation to lift up
        n_lifts         - number of times to try to move the allocation up

    rewrite:
        `for i in _:`
        `    buf : T` <- alloc_cursor
        `    ...`
        ->
        `buf : T`
        `for i in _:`
        `    ...`
    """
    proc_c = ic.Cursor.create(proc)
    stmt = alloc_cursor._impl

    ir, _fwd = scheduling.DoLiftAllocSimple(stmt, n_lifts)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([AllocCursorA, PosIntA, EnumA(["row", "col"]), OptionalA(PosIntA), BoolA])
def autolift_alloc(
    proc, alloc_cursor, n_lifts=1, mode="row", size=None, keep_dims=False
):
    """
    Lift a buffer allocation up and out of various Loops / If-statements.

    Has some additional special legacy behavior.  Use lift_alloc instead for
    all new code.

    args:
        alloc_cursor    - cursor to the allocation to lift up
        n_lifts         - number of times to try to move the allocation up
        mode            - whether to expand the buffer's dimensions
                          on the inner or outer position
        size            - dimension extents to expand to?
        keep_dims       - ???

    rewrite:
        `for i in _:`
        `    buf : T` <- alloc_cursor
        `    ...`
        ->
        `buf : T`
        `for i in _:`
        `    ...`
    """
    proc_c = ic.Cursor.create(proc)
    stmt = alloc_cursor._impl

    return scheduling.DoLiftAlloc(proc_c, stmt, n_lifts, mode, size, keep_dims).result()


@sched_op([AllocCursorA, AllocCursorA])
def reuse_buffer(proc, buf_cursor, replace_cursor):
    """
    reuse existing buffer (`buf_cursor`) instead of
    allocating a new buffer (`replace_cursor`).

    Old Name: data_reuse

    args:
        buf_cursor      - cursor pointing to the Alloc to reuse
        replace_cursor  - cursor pointing to the Alloc to eliminate

    rewrite:
        `x : T ; ... ; y : T ; s`
          ->
        `x : T ; ... ; s[ y -> x ]`
    checks:
        Can only be performed if the variable `x` is dead at the statement
        `y : T`.
    """
    buf_s = buf_cursor._impl
    rep_s = replace_cursor._impl
    ir, _fwd = scheduling.DoDataReuse(buf_s, rep_s)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([WindowStmtCursorA])
def inline_window(proc, winstmt_cursor):
    """
    Eliminate use of a window by inlining its definition and expanding
    it at all use-sites

    args:
        winstmt_cursor  - cursor pointing to the WindowStmt to inline

    rewrite:
        `y = x[...] ; s` -> `s[ y -> x[...] ]`
    """
    stmt = winstmt_cursor._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoInlineWindow(proc_c, stmt).result()


@sched_op([ExprCursorA, NameA, OptionalA(MemoryA)])
def stage_window(proc, expr_cursor, win_name, memory=None):
    """
    TODO: Describe this scheduling operation.

    Do we want to keep this operation?

    Should it resemble `stage_mem` instead?
    """
    e = expr_cursor._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoStageWindow(proc_c, win_name, memory, e).result()


@sched_op([BlockCursorA, CustomWindowExprA("block_cursor"), NameA, BoolA])
def stage_mem(proc, block_cursor, win_expr, new_buf_name, accum=False):
    """
    Stage the window of memory specified by `win_expr` into a new buffer
    before the indicated code block and move the memory back after the
    indicated code block.  If code analysis allows one to omit either
    the load or store between the original buffer and staging buffer, then
    the load/store loops/statements will be omitted.

    In the event that the indicated block of code strictly reduces into
    the specified window, then the optional argument `accum` can be set
    to initialize the staging memory to zero, accumulate into it, and
    then accumulate that result back to the original buffer, rather than
    loading and storing.  This is especially valuable when one's target
    platform can more easily zero out memory and thereby either
    reduce memory traffic outright, or at least improve locality of access.

    args:
        block_cursor    - the block of statements to stage around
        win_expr        - (string) of the form `name[pt_or_slice*]`
                          e.g. 'x[32, i:i+4]'
                          In this case `x` should be accessed in the
                          block, but only at locations
                          (32, i), (32, i+1), (32, i+2), or (32, i+3)
        new_buf_name    - the name of the newly created staging buffer
        accum           - (optional, bool) see above

    rewrite:
        stage_mem(..., 'x[0:n,j-1:j]', 'xtmp')
        `for i in seq(0,n-1):`
        `    x[i,j] = 2 * x[i+1,j-1]`
        -->
        `for k0 in seq(0,n):`
        `    for k1 in seq(0,2):`
        `        xtmp[k0,k1] = x[k0,j-1+k1]`
        `for i in seq(0,n-1):`
        `    xtmp[i,j-(j-1)] = 2 * xtmp[i+1,(j-1)-(j-1)]`
        `for k0 in seq(0,n):`
        `    for k1 in seq(0,2):`
        `        x[k0,j-1+k1] = xtmp[k0,k1]`

    """
    buf_name, w_exprs = win_expr
    stmt_start = block_cursor[0]._impl
    stmt_end = block_cursor[-1]._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoStageMem(
        proc_c,
        buf_name,
        new_buf_name,
        w_exprs,
        stmt_start,
        stmt_end,
        use_accum_zero=accum,
    ).result()


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Loop and Guard Rewriting


@sched_op(
    [
        ForSeqCursorA,
        PosIntA,
        ListA(NameA, length=2),
        EnumA(["cut", "guard", "cut_and_guard"]),
        BoolA,
    ]
)
def divide_loop(proc, loop_cursor, div_const, new_iters, tail="guard", perfect=False):
    """
    Divide a loop into an outer and inner loop, where the inner loop
    iterates over the range 0 to `div_const`.

    Old Name: In Halide and TVM, this was called "split"

    args:
        loop_cursor     - cursor pointing to the loop to split ;
                          can also be specified using the special shorthands
                          pattern: <loop-iterator-name>
                               or: <loop-iterator-name> #<int>
        div_const       - integer > 1 specifying what to "divide by"
        new_iters       - list or tuple of two strings specifying the new
                          outer and inner iteration variable names
        tail (opt)      - specifies the strategy for handling the "remainder"
                          of the loop division (called the tail of the loop).
                          value can be "cut", "guard", or "cut_and_guard".
                          Default value: "guard"
        perfect (opt)   - Boolean (default False) that can be set to true
                          to assert that you know the remainder will always
                          be zero (i.e. there is no tail).  You will get an
                          error if the compiler cannot verify this fact itself.

    rewrite:
        divide(..., div_const=q, new_iters=['hi','lo'], tail='cut')
        `for i in seq(0,e):`
        `    s`
            ->
        `for hi in seq(0,e / q):`
        `    for lo in seq(0, q):`
        `        s[ i -> q*hi + lo ]`
        `for lo in seq(0,e - q * (e / q)):`
        `    s[ i -> q * (e / q) + lo ]
    """
    if div_const == 1:
        raise ValueError("why are you trying to split by 1?")

    stmt = loop_cursor._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoSplit(
        proc_c,
        stmt,
        quot=div_const,
        hi=new_iters[0],
        lo=new_iters[1],
        tail=tail,
        perfect=perfect,
    ).result()


@sched_op([NestedForSeqCursorA, NameA])
def mult_loops(proc, nested_loops, new_iter_name):
    """
    Perform the inverse operation to `divide_loop`.  Take two loops,
    the innermost of which has a literal bound. (e.g. 5, 8, etc.) and
    replace them by a single loop that iterates over the product of their
    iteration spaces (e.g. 5*n, 8*n, etc.)

    args:
        nested_loops    - cursor pointing to a loop whose body is also a loop
        new_iter_name   - string with name of the new iteration variable

    rewrite:
        `for i in seq(0,e):`
        `    for j in seq(0,c):`    # c is a literal integer
        `        s`
        ->
        `for k in seq(0,e*c):`      # k is new_iter_name
        `    s[ i -> k/c, j -> k%c ]`
    """
    ir, _fwd = scheduling.DoProductLoop(nested_loops._impl, new_iter_name)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([ForSeqCursorA, PosIntA])
def cut_loop(proc, loop, cut_point):
    """
    Cut a loop into two loops, one iterating from 0 to `cut_point` and
    the second iterating from `cut_point` to the original loop upper bound.

    Right now, cut_point has to be an integer.
    TODO: support expressions for the cut_point.

    args:
        loop            - cursor pointing to the loop to split
        cut_point       - integer saying which iteration to cut at

    rewrite:
        `for i in seq(0,n):`
        `    s`
        ->
        `for i in seq(0,cut):`
        `    s`
        `for i in seq(0,n-cut):`
        `    s[i -> i+cut]`
    """
    ir, _fwd = scheduling.DoPartitionLoop(loop._impl, cut_point)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([NestedForSeqCursorA])
def reorder_loops(proc, nested_loops):
    """
    Reorder two loops that are directly nested with each other.
    This is the primitive loop reordering operation, out of which
    other reordering operations can be built.

    args:
        nested_loops    - cursor pointing to the outer loop of the
                          two loops to reorder; a pattern to find said
                          cursor with; or a 'name name' shorthand where
                          the first name is the iteration variable of the
                          outer loop and the second name is the iteration
                          variable of the inner loop.  An optional '#int'
                          can be added to the end of this shorthand to
                          specify which match you want,

    rewrite:
        `for outer in _:`
        `    for inner in _:`
        `        s`
            ->
        `for inner in _:`
        `    for outer in _:`
        `        s`
    """

    stmt_c = nested_loops._impl
    if len(stmt_c.body()) != 1 or not isinstance(stmt_c.body()[0]._node, LoopIR.Seq):
        raise ValueError(f"expected loop directly inside of {stmt_c._node.iter} loop")

    ir, _fwd = scheduling.DoLiftScope(stmt_c.body()[0])
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([BlockCursorA(block_size=2)])
def merge_writes(proc, block_cursor):
    """
    Merge consecutive assign and reduce statement into a single statement.
    Handles all 4 cases of (assign, reduce) x (reduce, assign).

    args:
        block_cursor          - cursor pointing to the block of two consecutive
                                assign/reduce statement.

    rewrite:
        `a = b`
        `a = c`
            ->
        `a = c`
        ----------------------
        `a += b`
        `a = c`
            ->
        `a = c`
        ----------------------
        `a = b`
        `a += c`
            ->
        `a = b + c`
        ----------------------
        `a += b`
        `a += c`
            ->
        `a += b + c`
        ----------------------

    """
    stmt1 = block_cursor[0]._impl._node
    stmt2 = block_cursor[1]._impl._node

    # TODO: We should seriously consider how to improve Scheduling errors in general
    if not isinstance(stmt1, (LoopIR.Assign, LoopIR.Reduce)) or not isinstance(
        stmt2, (LoopIR.Assign, LoopIR.Reduce)
    ):
        raise ValueError(
            f"expected two consecutive assign/reduce statements, "
            f"got {type(stmt1)} and {type(stmt2)} instead."
        )
    if stmt1.name != stmt2.name or stmt1.type != stmt2.type:
        raise ValueError(
            "expected the two statements' left hand sides to have the same name & type"
        )
    if not stmt1.rhs.type.is_numeric() or not stmt2.rhs.type.is_numeric():
        raise ValueError(
            "expected the two statements' right hand sides to have numeric types."
        )

    ir, _fwd = scheduling.DoMergeWrites(block_cursor[0]._impl, block_cursor[1]._impl)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([BlockCursorA(block_size=2)])
def lift_reduce_constant(proc, block_cursor):
    """
    Lift a constant scaling factor out of a loop.

    args:
        block_cursor       - block of size 2 containing the zero assignment and the for loop to lift the constant out of

    rewrite:
        `x = 0.0`
        `for i in _:`
        `    x += c * y[i]`
        ->
        `x = 0.0`
        `for i in _:`
        `    x += y[i]`
        `x = c * x`
    """
    stmt_c = block_cursor[0]._impl
    loop_c = block_cursor[1]._impl
    proc_c = ic.Cursor.create(proc)

    ir, _fwd = scheduling.DoLiftConstant(stmt_c, loop_c)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([GapCursorA, PosIntA])
def fission(proc, gap_cursor, n_lifts=1):
    """
    fission apart the ForSeq and If statements wrapped around
    this block of statements into two copies; the first containing all
    statements before the cursor, and the second all statements after the
    cursor.

    args:
        gap_cursor          - a cursor pointing to the point in the
                              statement block that we want to fission at.
        n_lifts (optional)  - number of levels to fission upwards (default=1)

    rewrite:
        `for i in _:`
        `    s1`
        `      ` <- gap
        `    s2`
            ->
        `for i in _:`
        `    s1`
        `for i in _:`
        `    s2`
    """

    if not (stmtc := gap_cursor.before()) or not gap_cursor.after():
        raise ValueError("expected cursor to point to " "a gap between statements")
    stmt = stmtc._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoFissionAfterSimple(proc_c, stmt, n_lifts).result()


@sched_op([GapCursorA, PosIntA])
def autofission(proc, gap_cursor, n_lifts=1):
    """
    Split the enclosing ForSeq and If statements wrapped around
    this block of statements at the indicated point.

    If doing so splits a loop, this version of fission attempts
    to remove those loops as well.

    args:
        gap_cursor          - a cursor pointing to the point in the
                              statement block that we want to fission at.
        n_lifts (optional)  - number of levels to fission upwards (default=1)

    rewrite:
        `for i in _:`
        `    s1`
        `      ` <- gap
        `    s2`
            ->
        `for i in _:`
        `    s1`
        `for i in _:`
        `    s2`
    """

    if not (stmtc := gap_cursor.before()) or not gap_cursor.after():
        raise ValueError("expected cursor to point to " "a gap between statements")
    stmt = stmtc._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoFissionLoops(proc_c, stmt, n_lifts).result()


@sched_op([ForSeqOrIfCursorA, ForSeqOrIfCursorA])
def fuse(proc, stmt1, stmt2):
    """
    fuse together two loops or if-guards, provided that the loop bounds
    or guard conditions are compatible.

    args:
        stmt1, stmt2        - cursors to the two loops or if-statements
                              that are being fused

    rewrite:
        `for i in e:` <- stmt1
        `    s1`
        `for j in e:` <- stmt2
        `    s2`
            ->
        `for i in e:`
        `    s1`
        `    s2[ j -> i ]`
    or
        `if cond:` <- stmt1
        `    s1`
        `if cond:` <- stmt2
        `    s2`
            ->
        `if cond:`
        `    s1`
        `    s2`
    """
    if isinstance(stmt1, PC.IfCursor) != isinstance(stmt2, PC.IfCursor):
        raise ValueError(
            "expected the two argument cursors to either both "
            "point to loops or both point to if-guards"
        )
    s1 = stmt1._impl
    s2 = stmt2._impl
    if isinstance(stmt1, PC.IfCursor):
        ir, _fwd = scheduling.DoFuseIf(s1, s2)
    else:
        ir, _fwd = scheduling.DoFuseLoop(s1, s2)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([ForSeqCursorA])
def remove_loop(proc, loop_cursor):
    """
    Remove the loop around some block of statements.
    This operation is allowable when the block of statements in question
    can be proven to be idempotent.

    args:
        loop_cursor     - cursor pointing to the loop to remove

    rewrite:
        `for i in _:`
        `    s`
            ->
        `s`
    """
    ir, _fwd = scheduling.DoRemoveLoop(loop_cursor._impl)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([BlockCursorA, NameA, NewExprA("block_cursor"), BoolA])
def add_loop(proc, block_cursor, iter_name, hi_expr, guard=False):
    """
    Add a loop around some block of statements.
    This operation is allowable when the block of statements in question
    can be proven to be idempotent.

    args:
        block_cursor    - cursor pointing to the block to wrap in a loop
        iter_name       - string name for the new iteration variable
        hi_expr         - string to be parsed into the upper bound expression
                          for the new loop
        guard           - Boolean (default False) signaling whether to
                          wrap the block in a `if iter_name == 0: block`
                          condition; in which case idempotency need not
                          be proven.

    rewrite:
        `s`  <--- block_cursor
        ->
        `for iter_name in hi_expr:`
        `    s`
    """

    if len(block_cursor) != 1:
        raise NotImplementedError("TODO: support blocks of size > 1")

    stmt_c = block_cursor[0]._impl
    ir, _fwd = scheduling.DoAddLoop(stmt_c, iter_name, hi_expr, guard)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([ForSeqCursorA])
def unroll_loop(proc, loop_cursor):
    """
    Unroll a loop with a constant, literal loop bound

    args:
        loop_curosr     - cursor pointing to the loop to unroll

    rewrite:
        `for i in seq(0,3):`
        `    s`
            ->
        `s[ i -> 0 ]`
        `s[ i -> 1 ]`
        `s[ i -> 2 ]`
    """
    ir, _fwd = scheduling.DoUnroll(loop_cursor._impl)
    return Procedure(ir, _provenance_eq_Procedure=proc)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Guard Conditions


@sched_op([ForSeqOrIfCursorA])
def lift_scope(proc, scope_cursor):
    """
    Lift the indicated For/If-statement upwards one scope.

    args:
        scope_cursor       - cursor to the inner scope statement to lift up

    rewrite: (one example)
        `for i in _:`
        `    if p:`
        `        s1`
        `    else:`
        `        s2`
        ->
        `if p:`
        `    for i in _:`
        `        s1`
        `else:`
        `    for i in _:`
        `        s2`
    """
    stmt_c = scope_cursor._impl

    # return scheduling.DoLiftScope(proc_c, stmt_c).result()
    ir, _fwd = scheduling.DoLiftScope(stmt_c)
    return Procedure(ir, _provenance_eq_Procedure=proc)


@sched_op([IfCursorA, BoolA])
def assert_if(proc, if_cursor, cond):
    """
    Eliminate the if-statement by determining either that it is always
    True or always False

    DEPRECATED
    TODO: This directive should drop the extra conditional argument
          and be renamed something like "remove_if"

    args:
        if_cursor       - cursor to the if-statement to simplify
        cond            - True or False: what the condition should always be

    rewrite:
        `if p:`
        `    s1`
        `else:`
        `    s2`
        -> (assuming cond=True)
        `s1`
    """
    stmt = if_cursor._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoAssertIf(proc_c, stmt, cond).result()


@sched_op([BlockCursorA, ListOrElemA(NewExprA("block_cursor"))])
def specialize(proc, block_cursor, conds):
    """
    Duplicate a statement block multiple times, with the provided
    `cond`itions indictaing when each copy should be invoked.
    Doing this allows one to then schedule differently the "specialized"
    variants of the blocks in different ways.

    If `n` conditions are given, then `n+1` specialized copies of the block
    are created (with the last copy as a "default" version).

    args:
        block_cursor    - cursor pointing to the block to duplicate/specialize
        conds           - list of strings or string to be parsed into
                          guard conditions for the

    rewrite:
        `s`
            ->
        `if cond_0:`
        `    s`
        `elif cond_1:`
        `    s`
        ...
        `else:`
        `    s`
    """

    if len(block_cursor) != 1:
        raise NotImplementedError("TODO: support blocks of size > 1")

    stmt = block_cursor[0]._impl

    ir, _fwd = scheduling.DoSpecialize(stmt, conds)
    return Procedure(ir, _provenance_eq_Procedure=proc)


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Deprecated Operations


@sched_op([BlockCursorA, NewExprA("block_cursor")])
def add_unsafe_guard(proc, block_cursor, var_expr):
    """
    DEPRECATED
    This operation is deprecated, and will be removed soon.
    """
    stmt = block_cursor._impl[0]
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoAddUnsafeGuard(proc_c, stmt, var_expr).result()


@sched_op([ForSeqCursorA])
def bound_and_guard(proc, loop):
    """
    DEPRECATED
    recommendation: replace with similar but more general primitive

    Replace
      for i in par(0, e): ...
    with
      for i in par(0, c):
        if i < e: ...
    where c is the tightest constant bound on e

    This currently only works when e is of the form x % n
    """
    stmt = loop._impl
    proc_c = ic.Cursor.create(proc)

    return scheduling.DoBoundAndGuard(proc_c, stmt).result()
