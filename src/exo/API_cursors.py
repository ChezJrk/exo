#from __future__ import annotations
#
#import weakref
#from abc import ABC, abstractmethod
#from dataclasses import dataclass
#from enum import Enum, auto
#from functools import cached_property
from typing import Optional, Iterable, Union, List
#from weakref import ReferenceType
#
from . import API
from .LoopIR import LoopIR
from .config import Config
from .memory import Memory

from . import cursors as C

# expose this particular exception as part of the API
from .cursors import InvalidCursorError 


# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# General Cursor Interface

@dataclass
class Cursor:
    """
    This is the base class for all cursors.  Cursors are objects that are
    used in scheduling to point to different parts of a Procedure's AST.
    You can think of a cursor as defined by the data pair
        (Procedure, Location)

    You can navigate a cursor around within a Procedure using its various
    methods.  However, note that a valid Cursor pointing into one Procedure
    p1 is not inherently a valid Cursor pointing into another Procedure p2,
    even if p2 was created from p1 using scheduling transformations.

    If p2 was created from p1, then we can `update` a Cursor c1 pointing
    to p1 to a cursor c2 pointing to p2.  (TODO: implement `update`)

    The sub-class hierarchy looks like:
    - Cursor
        - NodeCursor
            - StmtCursor    - cursors to individual statements
                - ...
            - ExprCursor    - cursors to individual expressions
                - ...
        - BlockCursor       - cursor to a contiguous sequence of statements
        - ArgsCursor        - cursor to a contiguous sequence of expressions
        - GapCursor         - cursor pointing to between two statements,
                              to after a statement, or before a statement
                              (think of this as a blinking vertical line)

    The grammar for statements and expressions looks something like:
    - TODO
    """
    _impl : C.Cursor

    def __init__(self, impl):
        if not isinstance(impl, C.Cursor):
            raise TypeError("Do not try to directly construct a Cursor.  "
                            "Use the provided methods to obtain cursors "
                            "from Procedures, and from other Cursors")
        self._impl = impl

    # -------------------------------------------------------------------- #
    # methods copied from the underlying implementation

    def proc(self):
        """
        Get the Procedure object that this Cursor points into
        """
        return self._impl.proc()

    def parent(self) -> NodeCursor:
        """
        Get a Cursor to the parent node in the syntax tree.

        Raises InvalidCursorError if no parent exists
        """
        impl_parent = self._impl.parent()
        if isinstance(impl_parent._node(), LoopIR.w_access):
            impl_parent = impl_parent.parent()
        elif isinstance(impl_parent._node(), LoopIR.proc):
            raise InvalidCursorError("cursor does not have a parent")
        return new_Cursor(impl_parent)

    def before(self, dist=1) -> Cursor:
        """
        If this is a statement or block Cursor, return a gap Cursor
            pointing to immediately before the first statement.
        If this is a gap Cursor, return a statement Cursor, pointing to
            the statement immediately before the gap.

        If dist > 1, then return the gap/statement dist-many spots before
            the cursor, rather than immediately (1-many) before the cursor

        Raises InvalidCursorError if there is no such statement or gap
            to point to.
        """
        assert dist >= 1
        return new_Cursor(self._impl.before())

    def after(self, dist=1) -> Cursor:
        """
        If this is a statement or block Cursor, return a gap Cursor
            pointing to immediately after the first statement.
        If this is a gap Cursor, return a statement Cursor, pointing to
            the statement immediately after the gap.

        If dist > 1, then return the gap/statement dist-many spots after
            the cursor, rather than immediately (1-many) after the cursor

        Raises InvalidCursorError if there is no such statement or gap
            to point to.
        """
        assert dist >= 1
        return new_Cursor(self._impl.after())

    def prev(self, dist=1) -> Cursor:
        """
        If this is a statement Cursor, return a statement cursor to
            the previous statement in the block (or dist-many previous)
        If this is a gap Cursor, return a gap cursor to
            the previous gap in the block (or dist-many previous)

        Raises InvalidCursorError if there is no such statement or gap
            to point to.
        """
        assert dist >= 1
        return new_Cursor(self._impl.prev())

    def next(self, dist=1) -> Cursor:
        """
        If this is a statement Cursor, return a statement cursor to
            the next statement in the block (or dist-many next)
        If this is a gap Cursor, return a gap cursor to
            the next gap in the block (or dist-many next)

        Raises InvalidCursorError if there is no such statement or gap
            to point to.
        """
        assert dist >= 1
        return new_Cursor(self._impl.next())



class NodeCursor(Cursor):
    """
    Cursor pointing to an individual statement or expression.
    See `help(Cursor)` for more details.
    """

class StmtCursor(NodeCursor):
    """
    Cursor pointing to an individual statement or expression.
    See `help(Cursor)` for more details.
    """

    def as_block(self) -> BlockC
        return BlockC( self._impl.as_block() )

class ExprCursor(NodeCursor):
    """
    Cursor pointing to an individual statement or expression.
    See `help(Cursor)` for more details.
    """

    def before(self, dist=1):
        """
        undefined for expressions
        """
        raise NotImplementedError("ExprCursor does not support before()")

    def after(self, dist=1):
        """
        undefined for expressions
        """
        raise NotImplementedError("ExprCursor does not support after()")

class GapCursor(Cursor):
    """
    Cursor pointing to a gap before, after, or between statements.
    See `help(Cursor)` for more details.
    """

class BlockCursor(Cursor):
    """
    Cursor pointing to a contiguous sequence of statements.
    See `help(Cursor)` for more details.
    """

    def __iter__(self):
        """
        iterate over all statement cursors contained in the block
        """
        yield from iter(self._impl)

    def __getitem__(self, i) -> StmtCursor:
        """
        get a cursor to the i-th statement
        """
        return self._impl[i]

    def __len__(self) -> int:
        """
        get the number of statements in the block
        """
        return len(self._impl)

class ArgsCursor(Cursor):
    """
    Cursor pointing to a contiguous sequence of expressions.
    See `help(Cursor)` for more details.
    """

    def __iter__(self):
        """
        iterate over all expression cursors contained in the argument list
        """
        yield from iter(self._impl)

    def __getitem__(self, i) -> ExprCursor:
        """
        get a cursor to the i-th argument
        """
        return self._impl[i]

    def __len__(self) -> int:
        """
        get the number of arguments
        """
        return len(self._impl)

    def before(self, dist=1): -> Cursor:
        """
        undefined for expressions
        """
        raise NotImplementedError("ArgsCursor does not support before()")

    def after(self, dist=1): -> Cursor:
        """
        undefined for expressions
        """
        raise NotImplementedError("ArgsCursor does not support after()")

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Specific Statement Cursor Types

class AssignCursor(StmtCursor):
    """
    Cursor pointing to an assignment statement:
        `name [ idx ] = rhs`
    """

    def name(self) -> Sym:
        return self._impl._node().name

    def idx(self) -> ArgsCursor:
        return ArgsCursor( self._impl._child_block('idx') )

    def rhs(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('rhs') )

class ReduceCursor(StmtCursor):
    """
    Cursor pointing to a reduction statement:
        `name [ idx ] += rhs`
    """

    def name(self) -> Sym:
        return self._impl._node().name

    def idx(self) -> ArgsCursor:
        return ArgsCursor( self._impl._child_block('idx') )

    def rhs(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('rhs') )

class AssignConfigCursor(StmtCursor):
    """
    Cursor pointing to a configuration assignment statement:
        `config.field = rhs`
    """

    def config(self) -> Config:
        return self._impl._node().config

    def field(self) -> str:
        return self._impl._node().field

    def rhs(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('rhs') )

class PassCursor(StmtCursor):
    """
    Cursor pointing to a no-op statement:
        `pass`
    """

class IfCursor(StmtCursor):
    """
    Cursor pointing to an if statement:
        ```
        if condition:
            body
        ```
    or
        ```
        if condition:
            body
        else:
            orelse
        ```
    """

    def cond(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('cond') )

    def body(self) -> BlockCursor:
        return BlockCursor( self._impl.body() )

    def orelse(self) -> Optional[BlockCursor]:
        orelse = self._impl.orelse()
        return BlockCursor(orelse) if len(orelse) > 0 else None

class ForSeqCursor(StmtCursor):
    """
    Cursor pointing to a loop statement:
        ```
        for name in seq(0,hi):
            body
        ```
    """

    def name(self) -> Sym:
        return self._impl._node().name

    def hi(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('hi') )

    def body(self) -> BlockCursor:
        return BlockCursor( self._impl.body() )

class AllocCursor(StmtCursor):
    """
    Cursor pointing to a buffer definition statement:
        ```
        name : type @ mem
        ```
    """

    def name(self) -> Sym:
        return self._impl._node().name

    def mem(self) -> Optional[Memory]:
        return self._impl._node().mem

class CallCursor(StmtCursor):
    """
    Cursor pointing to a sub-procedure call statement:
        ```
        subproc( args )
        ```
    """

    def subproc(self):
        return API.Procedure(self._impl._node().f)

    def args(self) -> ArgsCursor:
        return ArgsCursor( self._impl._child_block('args') )

class WindowStmtCursor(StmtCursor):
    """
    Cursor pointing to a window declaration statement:
        ```
        name = winexpr
        ```
    """

    def name(self) -> Sym:
        return self._impl._node().name

    def winexpr(self) -> WindowExprCursor:
        return WindowExprCursor( self._impl._child_node('rhs') )

# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Specific Expression Cursor Types


class ReadCursor(ExprCursor):
    """
    Cursor pointing to a read expression:
        `name`
    or
        `name [ idx ]`
    """

    def name(self) -> Sym:
        return self._impl._node().name

    def idx(self) -> ArgsCursor:
        return ArgsCursor( self._impl._child_block('idx') )

class ReadConfigCursor(ExprCursor):
    """
    Cursor pointing to a Config read expression:
        `config.field`
    """

    def config(self) -> Config:
        return self._impl._node().config

    def field(self) -> str:
        return self._impl._node().field

class LiteralCursor(ExprCursor):
    """
    Cursor pointing to a literal expression:
        `value`

    `value` should have Python type `bool`, `int` or `float`.
    If `value` has type `float` then it is a data-value literal.
    Otherwise, it should be a control-value literal.
    """

    def value(self) -> Any:
        n = self._impl._node()
        assert ( (n.type == T.bool and type(n.val) == bool) or
                 (n.type.is_indexable() and type(n.val) == int) or
                 (n.type.is_real_scalar() and type(n.val) == float) )
        return n.val

class UnaryMinusCursor(ExprCursor):
    """
    Cursor pointing to a unary minus-sign expression:
        `- arg`
    """

    def arg(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('arg') )

class BinaryOpCursor(ExprCursor):
    """
    Cursor pointing to an in-fix binary operation expression:
        `lhs op rhs`
    where `op` is one of:
        + - * / % < > <= >= == and or
    """

    def op(self) -> str:
        return self._impl._node().op

    def lhs(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('lhs') )

    def rhs(self) -> ExprCursor:
        return new_Cursor( self._impl._child_node('rhs') )

class BuiltInFunctionCursor(ExprCursor):
    """
    Cursor pointing to the call to some built-in function
        `name ( args )`
    """

    def name(self) -> str:
        return self._impl._node().f.name()

    def args(self) -> ArgsCursor:
        return ArgsCursor( self._impl._child_block('args') )

class WindowExprCursor(ExprCursor):
    """
    Cursor pointing to a windowing expression:
        `name [ w_args ]`

    Note that w_args is not an argument cursor.  Instead it is a list
    of "w-expressions" which are either an ExprCursor, or a pair of
    ExprCursors.
    """

    def name(self) -> str:
        return self._impl._node().f.name()

    def idx(self) -> List:
        def convert_w(w):
            if isinstance(w._node(), LoopIR.Interval):
                return ( new_Cursor(w._child_node('lo')),
                         new_Cursor(w._child_node('hi')) )
            else:
                return new_Cursor(w._child_node('pt'))
        return [ convert_w(w) for w in self._impl._child_block('idx') ]

class StrideExprCursor(ExprCursor):
    """
    Cursor pointing to a stride expression:
        `stride ( name , dim )`
    (note that stride is a keyword, and not data/a sub-expression)
    `name` is the name of some buffer or window
    """

    def name(self) -> Sym:
        return self._impl._node().name

    def dim(self) -> int:
        return self._impl._node().dim







# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Internal Functions; Not for Exposure to Users

# helper function to dispatch to constructors
def new_Cursor(impl):
    assert isinstance(impl, C.Cursor)

    # dispatch to the correct constructor...
    if isinstance(impl, C.Gap):
        return GapCursor(impl)

    elif isinstance(impl, C.Block):
        # TODO: Rename internal Cursor type to Sequence?
        assert len(impl) > 0
        n0 = impl[0]._node()
        if isinstance(n0, LoopIR.stmt):
            assert all( isinstance(c._node(), LoopIR.stmt) for c in impl )
            return BlockCursor(impl)
        elif isinstance(n0, LoopIR.expr):
            assert all( isinstance(c._node(), LoopIR.expr) for c in impl )
            return ArgsCursor(impl)
        else: assert False, "bad case"

    elif isinstance(impl, C.Node):
        n = impl._node()

        # statements
        if isinstance(n, LoopIR.Assign):
            return AssignCursor(impl)
        elif isinstance(n, LoopIR.Reduce):
            return ReduceCursor(impl)
        elif isinstance(n, LoopIR.WriteConfig):
            return AssignConfigCursor(impl)
        elif isinstance(n, LoopIR.Pass):
            return PassCursor(impl)
        elif isinstance(n, LoopIR.If):
            return IfCursor(impl)
        elif isinstance(n, (LoopIR.ForAll,LoopIR.Seq)):
            return ForSeqCursor(impl)
        elif isinstance(n, LoopIR.Alloc):
            return AllocCursor(impl)
        elif isinstance(n, LoopIR.Call):
            return CallCursor(impl)
        elif isinstance(n, LoopIR.WindowStmt):
            return WindowStmtCursor(impl)

        # expressions
        elif isinstance(n, LoopIR.Assign):
            return ReadCursor(impl)
        elif isinstance(n, LoopIR.ReadConfig):
            return ReadConfigCursor(impl)
        elif isinstance(n, LoopIR.Const):
            return LiteralCursor(impl)
        elif isinstance(n, LoopIR.USub):
            return UnaryMinusCursor(impl)
        elif isinstance(n, LoopIR.BinOp):
            return BinaryOpCursor(impl)
        elif isinstance(n, LoopIR.BuiltIn):
            return BuiltInFunctionCursor(impl)
        elif isinstance(n, LoopIR.WindowExpr):
            return WindowExprCursor(impl)
        elif isinstance(n, LoopIR.StrideExpr):
            return StrideExprCursor(impl)

        else:
            assert False, f"bad case: {type(n)}"

    else: assert False, f"bad case: {type(impl)}"


