# Metaprogramming

In the context of Exo, metaprogramming refers to the composition of [object code](object_code.md) fragments, similar to macros in languages like C. Unlike scheduling operations, metaprogramming does not seek to preserve equivalence as it transforms the object code - instead, it stitches together Exo code fragments, allowing the user to make code more concise or parametrizable.

The user can get a reference to one of these Exo code fragments through *quoting*, which produces a Python reference to the code fragment. After manipulating this code fragment as a Python object, the user can then paste in a code fragment from Python through *unquoting*.

## Quoting and Unquoting Statements

An unquote statement composes any quoted fragments that are executed within it. Syntactically, it is a block of *Python* code which is wrapped in a `with python:` block. Within this block, there may be multiple quoted *Exo* fragments which get executed, which are represented as `with exo:` blocks.

Note that we are carefully distinguishing *Python* code from *Exo* code here. The Python code inside the `with python:` block does not describe any operations in Exo. Instead, it describes how the Exo fragments within it are composed. Thus, this code can use familiar Python constructs, such as `range(...)` loops (as opposed to Exo's `seq(...)` loops).

An unquote statement will only read a quoted fragment when its corresponding `with exo:` block gets executed in the Python code. So, the following example results in an empty Exo procedure:
```python
@proc
def foo(a: i32):
    with python:
        if False:
            with exo:
                a += 1
```

A `with exo:` may also be executed multiple times. The following example compiles to 10 `a += 1` statements in a row:
```python
@proc
def foo(a: i32):
    with python:
        for i in range(10):
            with exo:
                a += 1
```

## Quoting and Unquoting Expressions

An unquote expression reads the Exo expression that is referred to by a Python object. This is syntactically represented as `{...}`, where the insides of the braces are interpreted as a Python object. To obtain a Python object that refers to an Exo expression, one can use an unquote expression, represented as `~{...}`.

As a simple example, we can try iterating through a list of Exo expressions. The following example should be equivalent to `a += a; a += b * 2`:
```python
@proc
def foo(a: i32, b: i32):
    with python:
        exprs = [~{a}, ~{b * 2}]
        for expr in exprs:
            with exo:
                a += {expr}
```

### Implicit Quotes and Unquotes

As we can see from the example, it is often the case that quote and unquote expressions will consist of a single variable. For convenience, if a variable name would otherwise be an invalid reference, the parser will try unquoting or quoting it before throwing an error. So, the following code is equivalent to the previous example:
```python
@proc
def foo(a: i32, b: i32):
    with python:
        exprs = [a, ~{b * 2}]
        for expr in exprs:
            with exo:
                a += expr
```

### Unquoting Numbers

Besides quoted expressions, a Python number can also be unquoted and converted into the corresponding numeric literal in Exo. The following example will alternate between `a += 1` and `a += 2` 10 times:
```python
@proc
def foo(a: i32):
    with python:
        for i in range(10):
            with exo:
                a += {i % 2}
```

### Unquoting Types

When an unquote expression occurs in the place that a type would normally be used in Exo, for instance in the declaration of function arguments, the unquote expression will read the Python object as a string and parse it as the corresponding type. The following example will take an argument whose type depends on the first statement:
```python
T = "i32"

@proc
def foo(a: {T}, b: {T}):
    a += b
```

### Unquoting Indices

Unquote expressions can also be used to index into a buffer. The Python object that gets unquoted may be a single Exo expression, a number, or a slice object. 

### Unquoting Memories

Memory objects can also be unquoted. Note that memories in Exo correspond to Python objects in the base language anyway, so the process of unquoting an object representing a type of memory in Exo is relatively straightforward. For instance, the memory used to pass in the arguments to this function are determined by the first line:
```python
mem = DRAM

@proc
def foo(a: i32 @ {mem}, b: i32 @ {mem}):
    a += b
```

## Binding Quoted Statements to Variables

A quoted Exo statement does not have to be executed immediately in the place that it is declared. Instead, the quote may be stored in a Python variable using the syntax `with exo as ...:`. It can then be unquoted with the `{...}` operator if it appears as a statement.

The following example is equivalent to `a += b; a += b`:
```python
@proc
def foo(a: i32, b: i32):
    with python:
        with exo as stmt:
            a += b
        {stmt}
        {stmt}
```

## Limitations

- There is currently no support for defining quotes outside of an Exo procedure. Thus, it is difficult to share metaprogramming logic between two different Exo procedures.
- Attempting to execute a quoted statement while unquoting an expression will result in an error being thrown. Since Exo expressions do not have side effects, the semantics of such a program would be unclear if allowed. For instance: 
```python
@proc
def foo(a: i32):
    with python:
        def bar():
            with exo:
                a += 1
            return 2
        a *= {bar()} # illegal!
```
- Identifiers that appear on the left hand side of assignment and reductions in Exo cannot be unquoted. This is partly due to limitations in the Python grammar, which Exo must conform to.