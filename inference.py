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
"""this module contains a set of functions to handle inference on astng trees

:author:    Sylvain Thenault
:copyright: 2003-2009 LOGILAB S.A. (Paris, FRANCE)
:contact:   http://www.logilab.fr/ -- mailto:python-projects@logilab.org
:copyright: 2003-2009 Sylvain Thenault
:contact:   mailto:thenault@gmail.com
"""

from __future__ import generators

__doctype__ = "restructuredtext en"

from copy import copy
from types import NoneType

from logilab.common.compat import imap, chain, set

from logilab.astng import nodes, raw_building, MANAGER, \
     unpack_infer, copy_context, path_wrapper, raise_if_nothing_infered
from logilab.astng import ASTNGError, InferenceError, UnresolvableName, \
     NoDefault, NotFoundError, ASTNGBuildingException
from logilab.astng.nodes import _infer_stmts, YES, InferenceContext, Instance, \
     Generator
from logilab.astng.protocols import _arguments_infer_argname

_CONST_PROXY = {
    NoneType: raw_building.build_class('NoneType'),
    bool: MANAGER.astng_from_class(bool),
    int: MANAGER.astng_from_class(int),
    long: MANAGER.astng_from_class(long),
    float: MANAGER.astng_from_class(float),
    complex: MANAGER.astng_from_class(complex),
    str: MANAGER.astng_from_class(str),
    unicode: MANAGER.astng_from_class(unicode),
    }
_CONST_PROXY[NoneType].parent = _CONST_PROXY[bool].parent

def _set_proxied(const):
    if not hasattr(const, '__proxied'):
        const.__proxied = _CONST_PROXY[const.value.__class__]
    return const.__proxied
nodes.Const._proxied = property(_set_proxied)

nodes.Const.__bases__ += (Instance,)

def Const_pytype(self):
    return self._proxied.qname()
nodes.Const.pytype = Const_pytype

def Const_getattr(self, name, context=None, lookupclass=None):
    return self._proxied.getattr(name, context)
nodes.Const.getattr = Const_getattr
nodes.Const.has_dynamic_getattr = lambda x: False

    
nodes.List._proxied = MANAGER.astng_from_class(list)
nodes.List.__bases__ += (Instance,)
nodes.List.pytype = lambda x: '__builtin__.list'
nodes.Tuple._proxied = MANAGER.astng_from_class(tuple)
nodes.Tuple.__bases__ += (Instance,)
nodes.Tuple.pytype = lambda x: '__builtin__.tuple'
nodes.Dict.__bases__ += (Instance,)
nodes.Dict._proxied = MANAGER.astng_from_class(dict)
nodes.Dict.pytype = lambda x: '__builtin__.dict'


class CallContext:
    """when infering a function call, this class is used to remember values
    given as argument
    """
    def __init__(self, args, starargs, dstarargs):
        self.args = []
        self.nargs = {}
        for arg in args:
            if isinstance(arg, nodes.Keyword):
                self.nargs[arg.arg] = arg.value
            else:
                self.args.append(arg)
        self.starargs = starargs
        self.dstarargs = dstarargs

    def infer_argument(self, funcnode, name, context):
        """infer a function argument value according the the call context"""
        # 1. search in named keywords
        try:
            return self.nargs[name].infer(context)
        except KeyError:
            # Function.args.args can be None in astng (means that we don't have
            # information on argnames)
            argindex, argnode = funcnode.args.find_argname(name)
            if argindex is not None:
                # 2. first argument of instance/class method
                if argindex == 0 and funcnode.type in ('method', 'classmethod'):
                    if context.boundnode is not None:
                        boundnode = context.boundnode
                    else:
                        # XXX can do better ?
                        boundnode = funcnode.parent.frame()
                    if funcnode.type == 'method':
                        return iter((Instance(boundnode),))
                    if funcnode.type == 'classmethod':
                        return iter((boundnode,))                            
                # 2. search arg index
                try:
                    return self.args[argindex].infer(context)
                except IndexError:
                    pass
                # 3. search in *args (.starargs)
                if self.starargs is not None:
                    its = []
                    for infered in self.starargs.infer(context):
                        if infered is YES:
                            its.append((YES,))
                            continue
                        try:
                            its.append(infered.getitem(argindex).infer(context))
                        except (InferenceError, AttributeError):
                            its.append((YES,))
                        except (IndexError, TypeError):
                            continue
                    if its:
                        return chain(*its)
        # 4. XXX search in **kwargs (.dstarargs)
        if self.dstarargs is not None:
            its = []
            for infered in self.dstarargs.infer(context):
                if infered is YES:
                    its.append((YES,))
                    continue
                try:
                    its.append(infered.getitem(name).infer(context))
                except (InferenceError, AttributeError):
                    its.append((YES,))
                except (IndexError, TypeError):
                    continue
            if its:
                return chain(*its)
        # 5. */** argument, (Tuple or Dict)
        if name == funcnode.args.vararg:
            return iter((nodes.const_factory(())))
        if name == funcnode.args.kwarg:
            return iter((nodes.const_factory({})))
        # 6. return default value if any
        try:
            return funcnode.args.default_value(name).infer(context)
        except NoDefault:
            raise InferenceError(name)
        

# .infer method ###############################################################

def infer_default(self, context=None):
    """we don't know how to resolve a statement by default"""
    raise InferenceError(self.__class__.__name__)
nodes.Node.infer = infer_default


def infer_end(self, context=None):
    """inference's end for node such as Module, Class, Function, Const...
    """
    yield self
nodes.Module.infer = infer_end
nodes.Class.infer = infer_end        
nodes.Function.infer = infer_end
nodes.Lambda.infer = infer_end
nodes.Const.infer = infer_end
nodes.List.infer = infer_end
nodes.Tuple.infer = infer_end
nodes.Dict.infer = infer_end


def infer_name(self, context=None):
    """infer a Name: use name lookup rules"""
    frame, stmts = self.lookup(self.name)
    if not stmts:
        raise UnresolvableName(self.name)
    context = context.clone()
    context.lookupname = self.name
    return _infer_stmts(stmts, context, frame)
nodes.Name.infer = path_wrapper(infer_name)

        
def infer_callfunc(self, context=None):
    """infer a CallFunc node by trying to guess what the function returns"""
    context = context.clone()
    context.callcontext = CallContext(self.args, self.starargs, self.kwargs)
    for callee in self.func.infer(context):
        if callee is YES:
            yield callee
            continue
        try:
            if hasattr(callee, 'infer_call_result'):
                for infered in callee.infer_call_result(self, context):
                    yield infered
        except InferenceError:
            ## XXX log error ?
            continue
nodes.CallFunc.infer = path_wrapper(raise_if_nothing_infered(infer_callfunc))


def _imported_module_astng(node, modname):
    """return the ast for a module whose name is <modname> imported by <node>
    """
    # handle special case where we are on a package node importing a module
    # using the same name as the package, which may end in an infinite loop
    # on relative imports
    # XXX: no more needed ?
    mymodule = node.root()
    if mymodule.relative_name(modname) == mymodule.name:
        # FIXME: I don't know what to do here...
        raise InferenceError(modname)
    try:
        return mymodule.import_module(modname)
    except (ASTNGBuildingException, SyntaxError):
        raise InferenceError(modname)

        
def infer_import(self, context=None, asname=True):
    """infer an Import node: return the imported module/object"""
    name = context.lookupname
    if name is None:
        raise InferenceError()
    if asname:
        yield _imported_module_astng(self, self.real_name(name))
    else:
        yield _imported_module_astng(self, name)
nodes.Import.infer = path_wrapper(infer_import)


def infer_from(self, context=None, asname=True):
    """infer a From nodes: return the imported module/object"""
    name = context.lookupname
    if name is None:
        raise InferenceError()
    if asname:
        name = self.real_name(name)
    module = _imported_module_astng(self, self.modname)
    try:
        context = copy_context(context)
        context.lookupname = name
        return _infer_stmts(module.getattr(name), context)
    except NotFoundError:
        raise InferenceError(name)
nodes.From.infer = path_wrapper(infer_from)
    

def infer_getattr(self, context=None):
    """infer a Getattr node by using getattr on the associated object"""
    # XXX
    #context = context.clone()
    for owner in self.expr.infer(context):
        if owner is YES:
            yield owner
            continue
        try:
            context.boundnode = owner
            for obj in owner.igetattr(self.attrname, context):
                yield obj
            context.boundnode = None
        except (NotFoundError, InferenceError):
            continue
        except AttributeError:
            # XXX method / function
            continue
nodes.Getattr.infer = path_wrapper(raise_if_nothing_infered(infer_getattr))


def infer_global(self, context=None):
    if context.lookupname is None:
        raise InferenceError()
    try:
        return _infer_stmts(self.root().getattr(context.lookupname), context)
    except NotFoundError:
        raise InferenceError()
nodes.Global.infer = path_wrapper(infer_global)


def infer_subscript(self, context=None):
    """infer simple subscription such as [1,2,3][0] or (1,2,3)[-1]
    """
    if len(self.subs) == 1:
        index = self.subs[0].infer(context).next()
        if index is YES:
            yield YES
            return
        try:
            # suppose it's a Tuple/List node (attribute error else)
            assigned = self.expr.getitem(index.value)
        except AttributeError:
            raise InferenceError()
        except (IndexError, TypeError):
            yield YES
            return
        for infered in assigned.infer(context):
            yield infered
    else:
        raise InferenceError()
nodes.Subscript.infer = path_wrapper(infer_subscript)


UNARY_OP_METHOD = {'+':  '__pos__',
                 '-':  '__neg__',
                 'not': None, # XXX not '__nonzero__'
                 }

def infer_unaryop(self, context=None):
    for operand in self.operand.infer(context):
        try:
            yield operand.infer_unary_op(self.op)
        except TypeError:
            continue
        except AttributeError, ex:
            meth = UNARY_OP_METHOD[self.op]
            if meth is None:
                yield YES
            else:
                try:
                    # XXX just suppose if the type implement meth, returned type
                    # will be the same
                    operand.getattr(meth)
                    yield operand
                except GeneratorExit:
                    raise
                except:
                    yield YES
nodes.UnaryOp.infer = path_wrapper(infer_unaryop)



BIN_OP_METHOD = {'+':  '__add__',
                 '-':  '__sub__',
                 '/':  '__div__',
                 '//': '__floordiv__',
                 '*':  '__mul__',
                 '**': '__power__',
                 '%':  '__mod__',
                 '&':  '__and__',
                 '|':  '__or__',
                 '^':  '__xor__',
                 '<<': '__lshift__',
                 '>>': '__rshift__',
                 }

def _infer_binop(operator, operand1, operand2, context, failures=None):
    if operand1 is YES:
        yield operand1
    try:
        for valnode in operand1.infer_binary_op(operator, operand2, context):
            yield valnode
    except AttributeError:
        try:
            # XXX just suppose if the type implement meth, returned type
            # will be the same
            operand1.getattr(BIN_OP_METHOD[operator])
            yield operand1
        except:
            if failures is None:
                yield YES
            else:
                failures.append(operand1)
    
def infer_binop(self, context=None):
    failures = []
    for lhs in self.left.infer(context):
        for val in _infer_binop(self.op, lhs, self.right, context, failures):
            yield val
    for lhs in failures:
        for rhs in self.right.infer(context):
            for val in _infer_binop(self.op, rhs, lhs, context):
                yield val
nodes.BinOp.infer = path_wrapper(infer_binop)


def infer_arguments(self, context=None):
    name = context.lookupname
    if name is None:
        raise InferenceError()
    return _arguments_infer_argname(self, name, context)
nodes.Arguments.infer = infer_arguments


def infer_ass(self, context=None):
    """infer a AssName/AssAttr: need to inspect the RHS part of the
    assign node
    """
    stmts = list(self.assigned_stmts(context=context))
    return nodes._infer_stmts(stmts, context)
nodes.AssName.infer = path_wrapper(infer_ass)
nodes.AssAttr.infer = path_wrapper(infer_ass)
# no infer method on DelName and DelAttr (expected InferenceError)


def infer_empty_node(self, context=None):
    if not self.has_underlying_object():
        yield YES
    else:
        try:
            for infered in MANAGER.infer_astng_from_something(self.object,
                                                              context=context):
                yield infered
        except ASTNGError:
            yield YES
nodes.EmptyNode.infer = path_wrapper(infer_empty_node)
