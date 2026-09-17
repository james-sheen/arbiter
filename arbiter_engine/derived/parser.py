"""Safe arithmetic expression parser.

Evaluates arithmetic formulas without eval(). Uses Python's ast module
to parse formula strings, then walks the AST rejecting any node type
outside a strict arithmetic allowlist.

Security: no attribute access, no imports, no subscripts, no lambdas.
"""

import ast
import math
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

MAX_FORMULA_LENGTH = 1024

ALLOWED_FUNCTIONS = {
    'abs': abs,
    'min': min,
    'max': max,
    'sqrt': math.sqrt,
    'log': math.log,
}


class SafeExpressionParser:
    """Parse and evaluate arithmetic expressions safely.

    Supported: +, -, *, /, **, //, %, abs(), min(), max(), sqrt(), log(), ()
    Rejected: attribute access, imports, subscripts, lambdas, everything else.
    """

    def parse(self, formula: str) -> ast.AST:
        """Parse formula string into a validated AST.

        Raises ValueError on invalid syntax or disallowed operations.
        """
        if len(formula) > MAX_FORMULA_LENGTH:
            raise ValueError(
                f"Formula exceeds maximum length ({len(formula)} > {MAX_FORMULA_LENGTH})"
            )

        try:
            tree = ast.parse(formula, mode='eval')
        except SyntaxError as e:
            raise ValueError(f"Invalid formula syntax: {e}") from e

        self._validate(tree.body)
        return tree.body

    def evaluate(self, node: ast.AST, variables: Dict[str, float]) -> float:
        """Evaluate a parsed AST with concrete variable bindings.

        Raises:
            KeyError: if a required variable is missing
            ArithmeticError: on domain errors (negative sqrt, etc.)
        """
        if isinstance(node, ast.BinOp):
            left = self.evaluate(node.left, variables)
            right = self.evaluate(node.right, variables)
            return self._apply_binop(node.op, left, right)

        if isinstance(node, ast.UnaryOp):
            operand = self.evaluate(node.operand, variables)
            if isinstance(node.op, ast.USub):
                return -operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            raise ValueError(f"Unsupported unary op: {type(node.op).__name__}")

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"Non-numeric constant: {node.value!r}")

        # Python 3.7 compat
        if isinstance(node, ast.Num):  # pragma: no cover
            return float(node.n)

        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise KeyError(f"Unknown variable: {node.id}")
            return float(variables[node.id])

        if isinstance(node, ast.Call):
            func_name = getattr(node.func, 'id', None)
            if func_name not in ALLOWED_FUNCTIONS:
                raise ValueError(f"Disallowed function: {func_name}")
            func = ALLOWED_FUNCTIONS[func_name]
            args = [self.evaluate(arg, variables) for arg in node.args]
            return float(func(*args))

        raise ValueError(f"Unsupported AST node: {type(node).__name__}")

    def _validate(self, node: ast.AST) -> None:
        """Recursively validate that all AST nodes are in the allowlist."""
        if isinstance(node, ast.BinOp):
            if not isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div,
                                        ast.Pow, ast.FloorDiv, ast.Mod)):
                raise ValueError(f"Disallowed binary op: {type(node.op).__name__}")
            self._validate(node.left)
            self._validate(node.right)

        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd)):
                raise ValueError(f"Disallowed unary op: {type(node.op).__name__}")
            self._validate(node.operand)

        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError(f"Non-numeric constant: {node.value!r}")

        elif isinstance(node, ast.Num):  # Python 3.7 compat
            pass  # pragma: no cover

        elif isinstance(node, ast.Name):
            pass  # Variable reference — validated at evaluation time

        elif isinstance(node, ast.Call):
            func_name = getattr(node.func, 'id', None)
            if func_name not in ALLOWED_FUNCTIONS:
                raise ValueError(f"Disallowed function call: {func_name}")
            for arg in node.args:
                self._validate(arg)
            if node.keywords:
                raise ValueError("Keyword arguments not allowed")

        else:
            raise ValueError(
                f"Disallowed AST node type: {type(node).__name__}"
            )

    @staticmethod
    def _apply_binop(op: ast.operator, left: float, right: float) -> float:
        """Apply a binary operator."""
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            if right == 0:
                raise ArithmeticError("Division by zero")
            return left / right
        if isinstance(op, ast.Pow):
            return left ** right
        if isinstance(op, ast.FloorDiv):
            if right == 0:
                raise ArithmeticError("Division by zero")
            return left // right
        if isinstance(op, ast.Mod):
            if right == 0:
                raise ArithmeticError("Division by zero")
            return left % right
        raise ValueError(f"Unknown binary op: {type(op).__name__}")
