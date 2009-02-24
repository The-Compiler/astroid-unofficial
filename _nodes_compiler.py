# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
"""python < 2.5 compiler package compatibility module [1]


 [1] http://docs.python.org/lib/module-compiler.ast.html

:author:    Sylvain Thenault
:copyright: 2003-2008 LOGILAB S.A. (Paris, FRANCE)
:contact:   http://www.logilab.fr/ -- mailto:python-projects@logilab.org
:copyright: 2003-2008 Sylvain Thenault
:contact:   mailto:thenault@gmail.com
"""
from __future__ import generators

__docformat__ = "restructuredtext en"

import sys
from compiler.ast import AssAttr, AssList, AssName, \
     AssTuple, Assert, Assign, AugAssign, \
     Backquote, Break, CallFunc, Class, \
     Compare, Const, Continue, Dict, Discard, \
     Ellipsis, EmptyNode, Exec, \
     For, From, Function, Getattr, Global, \
     If, Import, Keyword, Lambda, \
     List, ListComp, ListCompFor, ListCompIf, Module, Name, Node, \
     Pass, Print, Raise, Return, Slice, \
     Sliceobj, Stmt, Subscript, TryExcept, TryFinally, Tuple, \
     While, Yield


try:
    # introduced in python 2.4
    from compiler.ast import GenExpr, GenExprFor, GenExprIf, GenExprInner
except:
    class GenExpr:
        """dummy GenExpr node, shouldn't be used with py < 2.4"""
    class GenExprFor: 
        """dummy GenExprFor node, shouldn't be used with py < 2.4"""
    class GenExprIf: 
        """dummy GenExprIf node, shouldn't be used with py < 2.4"""
    class GenExprInner: 
        """dummy GenExprInner node, shouldn't be used with py < 2.4"""
try:
    # introduced in python 2.4
    from compiler.ast import Decorators
except:
    class Decorators:
        """dummy Decorators node, shouldn't be used with py < 2.4"""

try:
    # introduced in python 2.5
    from compiler.ast import With
except:
    class With:
        """dummy With node, shouldn't be used since py < 2.5"""

# additional nodes

class ExceptHandler(Node):
    def __init__(self, type, name, body, lineno):
        self.type = type
        self.name = name
        self.body = body
        self.lineno = lineno

class BinOp(Node):
    """replace Add, Div, FloorDiv, Mod, Mul, Power, Sub nodes"""
    from compiler.ast import Add, Div, FloorDiv, Mod, Mul, Power, Sub
    from compiler.ast import Bitand, Bitor, Bitxor, LeftShift, RightShift
    OP_CLASSES = {Add: '+',
                  Div: '/',
                  FloorDiv: '//',
                  Mod: '%',
                  Mul: '*',
                  Power: '**',
                  Sub: '-',
                  Bitand: '&',
                  Bitor: '|',
                  Bitxor: '^',
                  LeftShift: '<<',
                  RightShift: '>>'}
    BIT_CLASSES = {'&': Bitand, '|': Bitor, '^': Bitxor}

class BoolOp(Node):
    """replace And, Or"""
    from compiler.ast import And, Or
    OP_CLASSES = {And: 'and',
                  Or: 'or'}
    
class UnaryOp(Node):
    """replace UnaryAdd, UnarySub, Not"""
    from compiler.ast import UnaryAdd, UnarySub, Not, Invert
    OP_CLASSES = {UnaryAdd: '+',
                  UnarySub: '-',
                  Not: 'not',
                  Invert: '~'}


from logilab.astng.utils import ASTVisitor


class Delete(Node):
    """represent del statements"""


###############################################################################
        

COMPREHENSIONS_SCOPES = (GenExprFor, ListCompFor)


Const.eq = lambda self, value: self.value == value

def decorators_scope(self):
    # skip the function node to go directly to the upper level scope
    return self.parent.parent.scope()
Decorators.scope = decorators_scope

EmptyNode.getChildNodes = lambda self: ()

# introduced in python 2.5
From.level = 0 # will be overiden by instance attribute with py>=2.5


##  some auxiliary functions ##########################

def _init_ass_more(node, more_class ):
    if node.nodes[0].flags  == 'OP_DELETE':
        node.__class__ = Delete
        node.targets = [Name(item.name) for item in node.nodes]
    elif node.nodes[0].flags  == 'OP_ASSIGN':
        node.__class__ = more_class
        node.elts = node.nodes
    else:
        msg = "Error on node %s " % repr(node)
        raise msg
    del node.nodes

def _init_else_node(node):
    # remove Stmt node if exists
    if node.else_:
        node.orelse = node.else_.nodes
    else:
        node.orelse = []
    del node.else_

def _remove_none(sub): # XXX
    if isinstance(sub, Const) and sub.value == None:
        return None
    return sub

class TreeRebuilder(ASTVisitor):
    """Rebuilds the compiler tree to become an ASTNG tree"""

    # scoped nodes #######################################################
    
    def visit_function(self, node):
        # remove Stmt node
        node.body = node.code.nodes
        node.argnames = list(node.argnames)
        node.defaults = list(node.defaults)
        del node.code
    
    def visit_lambda(self, node):
        node.body = node.code
        node.argnames = list(node.argnames)
        node.defaults = list(node.defaults)
        del node.code
    
    def visit_class(self, node):
        # remove Stmt node
        node.body = node.code.nodes
        del node.code
    
    def visit_module(self, node):
        # remove Stmt node
        node.body = node.node.nodes
        del node.node
    
    ##  init_<node> functions #####################################################
    
    def visit_assattr(self, node):
        if node.flags == 'OP_ASSIGN':
            node.__class__ = Getattr
        elif node.flags == 'OP_DELETE':
            node.__class__ = Delete
            node.targets = [Getattr(node.expr, node.attrname)]
            del node.attrname, node.expr
        else:
            msg = "Error on node %s " % repr(node)
            raise msg
        del node.flags

    def visit_assign(self, node):
        node.value = node.expr
        node.targets = node.nodes
        del node.nodes, node.expr
        for target in node.targets:
            if isinstance(target, AssName):
                target.__class__ = Name
                del target.flags
            elif isinstance(target, AssTuple):
                target.__class__ = Tuple
            elif isinstance(target, AssList):
                target.__class__ = List
            else:
                msg = "Error : Assign node.targets %s" % target
                assert isinstance(target, (AssAttr, Subscript, Slice)), msg
    
    def visit_asslist(self, node):
        _init_ass_more(node, List)
    
    def visit_assname(self, node):
        if node.flags == 'OP_ASSIGN':
            node.__class__ = Name
        elif node.flags == 'OP_DELETE':
            node.targets = [Name(node.name)]
            node.__class__ = Delete
        else:
            msg = "Error on node %s " % repr(node)
            raise msg
        del node.flags
    
    def visit_asstuple(self, node):
        _init_ass_more(node, Tuple)
    
    def visit_augassign(self, node):
        node.value = node.expr
        del node.expr
        node.target = node.node
        del node.node
    
    def visit_backquote(self, node):
        node.value = node.expr
        del node.expr
    
    def visit_binop(self, node):
        node.op = BinOp.OP_CLASSES[node.__class__]
        node.__class__ = BinOp
        if node.op in ('&', '|', '^'):
            node.right = node.nodes[-1]
            bitop = BinOp.BIT_CLASSES[node.op]
            if len(node.nodes) > 2:
                node.left = bitop(node.nodes[:-1])
            else:
                node.left = node.nodes[0]
            del node.nodes
    
    def visit_boolop(self, node):
        node.op = BoolOp.OP_CLASSES[node.__class__]
        node.__class__ = BoolOp
        node.values = node.nodes
        del node.nodes
    
    def visit_callfunc(self, node):
        node.func = node.node
        node.starargs = node.star_args
        node.kwargs = node.dstar_args
        del node.node, node.star_args, node.dstar_args
    
    def visit_compare(self, node):
        node.left = node.expr
        del node.expr

    def visit_decorators(self, node):
        node.items = node.nodes
        del node.nodes

    def visit_dict(self, node):
        node.items = list(node.items)
    
    def visit_discard(self, node):
        node.value = node.expr
        del node.expr
    
    def visit_for(self, node):
        node.target = node.assign
        del node.assign
        node.iter = node.list
        del node.list
        node.body = node.body.nodes
        _init_else_node(node)
    
    def visit_genexpr(self, node):
        # remove GenExprInner node
        node.elt = node.code.expr
        node.generators = node.code.quals
        for gen in node.generators:
            gen.__class__ = ListCompFor # XXX _ast.comprehension
            gen.list = gen.iter # XXX
        del node.code
    
    def visit_if(self, node):
        node.tests = [(cond, expr.nodes) for cond, expr in node.tests]
        _init_else_node(node)
    
    def visit_list(self, node):
        node.elts = list(node.nodes) # tuple if empty list
        del node.nodes
    
    def visit_keyword(self, node):
        node.value = node.expr
        node.arg = node.name
        del node.expr, node.name
    
    def visit_listcomp(self, node):
        node.elt = node.expr
        node.generators = node.quals
        del node.expr, node.quals
    
    def visit_listcompfor(self, node):
        node.iter = node.list
        node.target = node.assign
        if node.ifs:
            node.ifs = [iff.test for iff in node.ifs ]
        del node.assign, node.list

    def visit_print(self, node):
        node.values = node.nodes
        del node.nodes
        node.nl = False
    
    def visit_printnl(self, node):
        node.__class__ = Print
        node.values = node.nodes
        del node.nodes
        node.nl = True

    def visit_raise(self, node):
        node.type = node.expr1
        node.inst = node.expr2
        node.tback = node.expr3
        del node.expr1, node.expr2, node.expr3
    
    def visit_slice(self, node):
        node.__class__ = Subscript
        node.subs = [node.lower, node.upper]
        node.sliceflag = 'slice'
        del node.lower, node.upper
    
    def visit_subscript(self, node):
        if hasattr(node.subs[0], "nodes"): # Sliceobj
            subs = [_remove_none(sub) for sub in node.subs[0].nodes]
            node.subs = subs
            node.sliceflag = 'slice'
        else:
            node.sliceflag = 'index'

    def visit_tryexcept(self, node):
        node.body = node.body.nodes
        # remove Stmt node
        node.handlers = [ExceptHandler(exctype, excobj, body.nodes, node.lineno)
                        for exctype, excobj, body in node.handlers]
        _init_else_node(node)
    
    def visit_tryfinally(self, node):
        # remove Stmt nodes
        node.body = node.body.nodes
        node.finalbody = node.final.nodes
        del node.final

    visit_tuple = visit_list

    def visit_unaryop(self, node):
        node.op = UnaryOp.OP_CLASSES[node.__class__]
        node.__class__ = UnaryOp
        node.operand = node.expr
        del node.expr

    def visit_while(self, node):
        node.body = node.body.nodes
        _init_else_node(node)

# raw building ################################################################

def module_factory(doc):
    node = Module(doc, None)
    del node.node
    node.body = []
    return node
    
def dict_factory():
    return Dict([])

if sys.version_info < (2, 5):
    def import_from_factory(modname, membername):
        return From(modname, ( (membername, None), ) )
else:
    def import_from_factory(modname, membername):
        return From(modname, ( (membername, None), ), 0)

def _const_factory(value):
    return Const(value)

# introduction of decorators has changed the Function initializer arguments
if sys.version_info >= (2, 4):
    def function_factory(name, args, defaults, flag=0, doc=None):
        """create and initialize a astng Function node"""
        # first argument is now a list of decorators
        func = Function(Decorators([]), name, args, defaults, flag, doc, None)
        del func.code
        func.body = []
        return func
    
else:    
    def function_factory(name, args, defaults, flag=0, doc=None):
        """create and initialize a astng Function node"""
        func = Function(name, args, defaults, flag, doc, None)
        del func.code
        func.body = []
        return func

def class_factory(name, basenames=None, doc=None):
    """create and initialize a astng Class node"""
    node = Class(name, [], doc, None)
    del node.code
    node.body = []
    bases = [Name(base) for base in basenames]
    for base in bases:
        base.parent = node
    node.bases = bases
    return node

class Proxy_: pass


def native_repr_tree(node, indent='', _done=None):
    """enhanced compiler.ast tree representation"""
    if _done is None:
        _done = set()
    if node in _done:
        print ('loop in tree: %r (%s)' % (node, getattr(node, 'lineno', None)))
        return
    _done.add(node)
    print indent + "<%s>" % node.__class__
    indent += '    '
    if not hasattr(node, "__dict__"): # XXX
        return
    for field, attr in node.__dict__.items():
        if attr is None or field == "_proxied":
            continue
        if type(attr) is list:
            if not attr: continue
            print indent + field + ' ['
            for elt in attr:
                if type(elt) is tuple:
                    for val in elt:
                        native_repr_tree(val, indent, _done)
                else:
                    native_repr_tree(elt, indent, _done)
            print indent + ']'
            continue
        if isinstance(attr, Node):
            print indent + field
            native_repr_tree(attr, indent, _done)
        else:
            print indent + field,  repr(attr)
