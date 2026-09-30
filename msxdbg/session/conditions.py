"""Parse a small predicate language and emit generated openMSX expressions."""
from __future__ import annotations

from dataclasses import dataclass
import re

from msxdbg.debuginfo.index import Project, SymbolContext
from msxdbg.debuginfo.model import AbsoluteStorage, ResolutionStatus
from .breakpoints import MappingQualifier


class ConditionSyntaxError(ValueError): pass


_TOKEN = re.compile(r"\s*(?:(0[xX][0-9a-fA-F]+|[0-9]+)|([A-Za-z_]\w*)|(==|!=|<=|>=|&&|\|\||<<|>>|[-+*/%&|^~!<>()]))")
_REGISTERS = frozenset("PC SP AF BC DE HL IX IY A F B C D E H L I R IM IFF IXH IXL IYH IYL".split())
_BINDING = {"||":1, "&&":2, "|":3, "^":4, "&":5, "==":6, "!=":6,
            "<":7, "<=":7, ">":7, ">=":7, "<<":8, ">>":8,
            "+":9, "-":9, "*":10, "/":10, "%":10}


@dataclass(frozen=True)
class CompiledCondition:
    source: str
    tcl_expression: str


class ConditionCompiler:
    def __init__(self, project: Project): self.project = project

    def compile(self, source: str) -> CompiledCondition:
        self.tokens = self._tokens(source); self.index = 0
        expression = self._expression(0)
        if self.index != len(self.tokens):
            raise ConditionSyntaxError(f"unexpected token: {self.tokens[self.index]}")
        return CompiledCondition(source.strip(), expression)

    @staticmethod
    def _tokens(source):
        result=[]; position=0
        while position < len(source):
            match=_TOKEN.match(source,position)
            if not match: raise ConditionSyntaxError(f"unsupported condition syntax at column {position+1}")
            result.append(match.group(1) or match.group(2) or match.group(3)); position=match.end()
        if not result: raise ConditionSyntaxError("condition must not be empty")
        return result

    def _expression(self, minimum):
        if self.index >= len(self.tokens): raise ConditionSyntaxError("missing operand")
        token=self.tokens[self.index]; self.index+=1
        if token in ("+","-","~","!"):
            left=f"({token}{self._expression(11)})"
        elif token == "(":
            left=self._expression(0)
            if self.index >= len(self.tokens) or self.tokens[self.index] != ")":
                raise ConditionSyntaxError("missing closing parenthesis")
            self.index+=1; left=f"({left})"
        elif re.fullmatch(r"0[xX][0-9a-fA-F]+|[0-9]+",token):
            left=str(int(token,0))
        elif re.fullmatch(r"[A-Za-z_]\w*",token):
            left=self._name(token)
        else: raise ConditionSyntaxError(f"unexpected token: {token}")
        while self.index < len(self.tokens):
            operator=self.tokens[self.index]; binding=_BINDING.get(operator)
            if binding is None or binding < minimum: break
            self.index+=1; right=self._expression(binding+1)
            left=f"({left} {operator} {right})"
        return left

    def _name(self, name):
        upper=name.upper()
        if upper in _REGISTERS: return f"[reg {upper}]"
        symbol=self.project.lookup_symbol(name)
        if symbol.status == ResolutionStatus.UNIQUE:
            return str(symbol.candidates[0].address)
        variable=self.project.find_variable(name, SymbolContext(None,None,None,0))
        if variable.status != ResolutionStatus.UNIQUE:
            raise ConditionSyntaxError(f"condition name is unknown or ambiguous: {name}")
        item=variable.candidates[0]
        if not isinstance(item.storage, AbsoluteStorage) or item.type_id is None:
            raise ConditionSyntaxError(f"condition variable has no fixed typed location: {name}")
        type_=self.project.type_by_id(item.type_id)
        if type_.category not in ("integer","character","pointer") or type_.size not in (1,2):
            raise ConditionSyntaxError(f"condition variable type is unsupported: {name}")
        address=item.storage.address
        raw=f"[debug read memory {address}]"
        if type_.size == 2:
            raw=f"({raw} | ([debug read memory {address+1}] << 8))"
        if type_.signed:
            sign=1 << (type_.size*8-1)
            raw=f"(({raw} ^ {sign}) - {sign})"
        return raw


def compile_mapping_qualifier(qualifier: MappingQualifier) -> str:
    checks=[]
    if qualifier.primary_slot is not None:
        checks.append(f"[lindex [get_selected_slot {qualifier.page}] 0] == {qualifier.primary_slot}")
    if qualifier.secondary_slot is not None:
        checks.append(f"[lindex [get_selected_slot {qualifier.page}] 1] == {qualifier.secondary_slot}")
    if qualifier.segment is not None:
        checks.append(f"[debug read MapperIO {qualifier.page}] == {qualifier.segment}")
    return " && ".join(f"({item})" for item in checks)


__all__=["CompiledCondition","ConditionCompiler","ConditionSyntaxError",
         "compile_mapping_qualifier"]
