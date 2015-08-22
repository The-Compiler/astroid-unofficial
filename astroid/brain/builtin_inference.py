"""Astroid hooks for various builtins."""

from functools import partial
import sys
from textwrap import dedent

import six
from astroid import (MANAGER, UseInferenceDefault, NotFoundError,
                     inference_tip, InferenceError, UnresolvableName)
from astroid.builder import AstroidBuilder
from astroid import helpers
from astroid import nodes
from astroid import objects
from astroid import scoped_nodes
from astroid import util

def _extend_str(class_node, rvalue):
    """function to extend builtin str/unicode class"""
    # TODO(cpopa): this approach will make astroid to believe
    # that some arguments can be passed by keyword, but
    # unfortunately, strings and bytes don't accept keyword arguments.
    code = dedent('''
    class whatever(object):
        def join(self, iterable):
            return {rvalue}
        def replace(self, old, new, count=None):
            return {rvalue}
        def format(self, *args, **kwargs):
            return {rvalue}
        def encode(self, encoding='ascii', errors=None):
            return ''
        def decode(self, encoding='ascii', errors=None):
            return u''
        def capitalize(self):
            return {rvalue}
        def title(self):
            return {rvalue}
        def lower(self):
            return {rvalue}
        def upper(self):
            return {rvalue}
        def swapcase(self):
            return {rvalue}
        def index(self, sub, start=None, end=None):
            return 0
        def find(self, sub, start=None, end=None):
            return 0
        def count(self, sub, start=None, end=None):
            return 0
        def strip(self, chars=None):
            return {rvalue}
        def lstrip(self, chars=None):
            return {rvalue}
        def rstrip(self, chars=None):
            return {rvalue}
        def rjust(self, width, fillchar=None):
            return {rvalue}
        def center(self, width, fillchar=None):
            return {rvalue}
        def ljust(self, width, fillchar=None):
            return {rvalue}
    ''')
    code = code.format(rvalue=rvalue)
    fake = AstroidBuilder(MANAGER).string_build(code)['whatever']
    for method in fake.mymethods():
        class_node.locals[method.name] = [method]
        method.parent = class_node

def extend_builtins(class_transforms):
    from astroid.bases import BUILTINS
    builtin_ast = MANAGER.astroid_cache[BUILTINS]
    for class_name, transform in class_transforms.items():
        transform(builtin_ast[class_name])

if sys.version_info > (3, 0):
    extend_builtins({'bytes': partial(_extend_str, rvalue="b''"),
                     'str': partial(_extend_str, rvalue="''")})
else:
    extend_builtins({'str': partial(_extend_str, rvalue="''"),
                     'unicode': partial(_extend_str, rvalue="u''")})


def register_builtin_transform(transform, builtin_name):
    """Register a new transform function for the given *builtin_name*.

    The transform function must accept two parameters, a node and
    an optional context.
    """
    def _transform_wrapper(node, context=None):
        result = transform(node, context=context)
        if result:
            if not result.parent:
                # Let the transformation function determine
                # the parent for its result. Otherwise,
                # we set it to be the node we transformed from.
                result.parent = node

            result.lineno = node.lineno
            result.col_offset = node.col_offset
        return iter([result])

    MANAGER.register_transform(nodes.Call,
                               inference_tip(_transform_wrapper),
                               lambda n: (isinstance(n.func, nodes.Name) and
                                          n.func.name == builtin_name))


def _generic_inference(node, context, node_type, transform):
    args = node.args
    if not args:
        return node_type()
    if len(node.args) > 1:
        raise UseInferenceDefault()

    arg, = args
    transformed = transform(arg)
    if not transformed:
        try:
            inferred = next(arg.infer(context=context))
        except (InferenceError, StopIteration):
            raise UseInferenceDefault()
        if inferred is util.YES:
            raise UseInferenceDefault()
        transformed = transform(inferred)
    if not transformed or transformed is util.YES:
        raise UseInferenceDefault()
    return transformed


def _generic_transform(arg, klass, iterables, build_elts):
    if isinstance(arg, klass):
        return arg
    elif isinstance(arg, iterables):
        if not all(isinstance(elt, nodes.Const)
                   for elt in arg.elts):
            # TODO(cpopa): Don't support heterogenous elements.
            # Not yet, though.
            raise UseInferenceDefault()
        elts = [elt.value for elt in arg.elts]
    elif isinstance(arg, nodes.Dict):
        if not all(isinstance(elt[0], nodes.Const)
                   for elt in arg.items):
            raise UseInferenceDefault()
        elts = [item[0].value for item in arg.items]
    elif (isinstance(arg, nodes.Const) and
          isinstance(arg.value, (six.string_types, six.binary_type))):
        elts = arg.value
    else:
        return
    return klass.from_constants(elts=build_elts(elts))


def _infer_builtin(node, context,
                   klass=None, iterables=None,
                   build_elts=None):
    transform_func = partial(
        _generic_transform,
        klass=klass,
        iterables=iterables,
        build_elts=build_elts)

    return _generic_inference(node, context, klass, transform_func)

# pylint: disable=invalid-name
infer_tuple = partial(
    _infer_builtin,
    klass=nodes.Tuple,
    iterables=(nodes.List, nodes.Set, objects.FrozenSet),
    build_elts=tuple)

infer_list = partial(
    _infer_builtin,
    klass=nodes.List,
    iterables=(nodes.Tuple, nodes.Set, objects.FrozenSet),
    build_elts=list)

infer_set = partial(
    _infer_builtin,
    klass=nodes.Set,
    iterables=(nodes.List, nodes.Tuple, objects.FrozenSet),
    build_elts=set)

infer_frozenset = partial(
    _infer_builtin,
    klass=objects.FrozenSet,
    iterables=(nodes.List, nodes.Tuple, nodes.Set, objects.FrozenSet),
    build_elts=frozenset)


def _get_elts(arg, context):
    is_iterable = lambda n: isinstance(n,
                                       (nodes.List, nodes.Tuple, nodes.Set))
    try:
        inferred = next(arg.infer(context))
    except (InferenceError, UnresolvableName):
        raise UseInferenceDefault()
    if isinstance(inferred, nodes.Dict):
        items = inferred.items
    elif is_iterable(inferred):
        items = []
        for elt in inferred.elts:
            # If an item is not a pair of two items,
            # then fallback to the default inference.
            # Also, take in consideration only hashable items,
            # tuples and consts. We are choosing Names as well.
            if not is_iterable(elt):
                raise UseInferenceDefault()
            if len(elt.elts) != 2:
                raise UseInferenceDefault()
            if not isinstance(elt.elts[0],
                              (nodes.Tuple, nodes.Const, nodes.Name)):
                raise UseInferenceDefault()
            items.append(tuple(elt.elts))
    else:
        raise UseInferenceDefault()
    return items

def infer_dict(node, context=None):
    """Try to infer a dict call to a Dict node.

    The function treats the following cases:

        * dict()
        * dict(mapping)
        * dict(iterable)
        * dict(iterable, **kwargs)
        * dict(mapping, **kwargs)
        * dict(**kwargs)

    If a case can't be inferred, we'll fallback to default inference.
    """
    if not node.args and not node.kwargs and not node.keywords:
        # dict()
        return nodes.Dict()
    elif node.keywords and not node.args:
        # dict(a=1, b=2, c=4)
        items = [(nodes.Const(arg.arg), arg.value) for arg in node.keywords]
    elif len(node.args) == 1 and node.keywords:
        # dict(some_iterable, b=2, c=4)
        elts = _get_elts(node.args[0], context)
        keys = [(nodes.Const(arg.arg), arg.value) for arg in node.keywords]
        items = elts + keys
    elif len(node.args) == 1:
        items = _get_elts(node.args[0], context)
    else:
        raise UseInferenceDefault()

    empty = nodes.Dict()
    empty.items = items
    return empty


def infer_super(node, context=None):
    """Understand super calls.

    There are some restrictions for what can be understood:

        * unbounded super (one argument form) is not understood.

        * if the super call is not inside a function (classmethod or method),
          then the default inference will be used.

        * if the super arguments can't be inferred, the default inference
          will be used.
    """
    if len(node.args) == 1:
        # Ignore unbounded super.
        raise UseInferenceDefault

    scope = node.scope()
    if not isinstance(scope, nodes.FunctionDef):
        # Ignore non-method uses of super.
        raise UseInferenceDefault
    if scope.type not in ('classmethod', 'method'):
        # Not interested in staticmethods.
        raise UseInferenceDefault

    cls = scoped_nodes.get_wrapping_class(scope)
    if not len(node.args):
        mro_pointer = cls
        # In we are in a classmethod, the interpreter will fill
        # automatically the class as the second argument, not an instance.
        if scope.type == 'classmethod':
            mro_type = cls
        else:
            mro_type = cls.instanciate_class()
    else:
        # TODO(cpopa): support flow control (multiple inference values).
        try:
            mro_pointer = next(node.args[0].infer(context=context))
        except InferenceError:
            raise UseInferenceDefault
        try:
            mro_type = next(node.args[1].infer(context=context))
        except InferenceError:
            raise UseInferenceDefault

    if mro_pointer is util.YES or mro_type is util.YES:
        # No way we could understand this.
        raise UseInferenceDefault

    super_obj = objects.Super(mro_pointer=mro_pointer,
                              mro_type=mro_type,
                              self_class=cls,
                              scope=scope)
    super_obj.parent = node
    return super_obj


def _infer_getattr_args(node, context):
    if len(node.args) not in (2, 3):
        # Not a valid getattr call.
        raise UseInferenceDefault

    try:
        # TODO(cpopa): follow all the values of the first argument?
        obj = next(node.args[0].infer(context=context))
        attr = next(node.args[1].infer(context=context))
    except InferenceError:
        raise UseInferenceDefault

    if obj is util.YES or attr is util.YES:
        # If one of the arguments is something we can't infer,
        # then also make the result of the getattr call something
        # which is unknown.
        return util.YES, util.YES

    is_string = (isinstance(attr, nodes.Const) and
                 isinstance(attr.value, six.string_types))
    if not is_string:
        raise UseInferenceDefault

    return obj, attr.value


def infer_getattr(node, context=None):
    """Understand getattr calls

    If one of the arguments is an YES object, then the
    result will be an YES object. Otherwise, the normal attribute
    lookup will be done.
    """
    obj, attr = _infer_getattr_args(node, context)
    if obj is util.YES or attr is util.YES or not hasattr(obj, 'igetattr'):
        return util.YES

    try:
        return next(obj.igetattr(attr, context=context))
    except (StopIteration, InferenceError, NotFoundError):
        if len(node.args) == 3:
            # Try to infer the default and return it instead.
            try:
                return next(node.args[2].infer(context=context))
            except InferenceError:
                raise UseInferenceDefault

    raise UseInferenceDefault


def infer_hasattr(node, context=None):
    """Understand hasattr calls

    This always guarantees three possible outcomes for calling
    hasattr: Const(False) when we are sure that the object
    doesn't have the intended attribute, Const(True) when
    we know that the object has the attribute and YES
    when we are unsure of the outcome of the function call.
    """
    try:
        obj, attr = _infer_getattr_args(node, context)
        if obj is util.YES or attr is util.YES or not hasattr(obj, 'getattr'):
            return util.YES
        obj.getattr(attr, context=context)
    except UseInferenceDefault:
        # Can't infer something from this function call.
        return util.YES
    except NotFoundError:
        # Doesn't have it.
        return nodes.Const(False)
    return nodes.Const(True)


def infer_callable(node, context=None):
    """Understand callable calls

    This follows Python's semantics, where an object
    is callable if it provides an attribute __call__,
    even though that attribute is something which can't be
    called.
    """
    if len(node.args) != 1:
        # Invalid callable call.
        raise UseInferenceDefault

    argument = node.args[0]
    try:
        inferred = next(argument.infer(context=context))
    except InferenceError:
        return util.YES
    if inferred is util.YES:
        return util.YES
    return nodes.Const(inferred.callable())


def infer_bool(node, context=None):
    """Understand bool calls."""
    if len(node.args) > 1:
        # Invalid bool call.
        raise UseInferenceDefault

    if not node.args:
        return nodes.Const(False)

    argument = node.args[0]
    try:
        inferred = next(argument.infer(context=context))
    except InferenceError:
        return util.YES
    if inferred is util.YES:
        return util.YES

    bool_value = inferred.bool_value()
    if bool_value is util.YES:
        return util.YES
    return nodes.Const(bool_value)


def infer_type(node, context=None):
    """Understand the one-argument form of *type*."""
    if len(node.args) != 1:
        raise UseInferenceDefault

    return helpers.object_type(node.args[0], context)


# Builtins inference
register_builtin_transform(infer_bool, 'bool')
register_builtin_transform(infer_super, 'super')
register_builtin_transform(infer_callable, 'callable')
register_builtin_transform(infer_getattr, 'getattr')
register_builtin_transform(infer_hasattr, 'hasattr')
register_builtin_transform(infer_tuple, 'tuple')
register_builtin_transform(infer_set, 'set')
register_builtin_transform(infer_list, 'list')
register_builtin_transform(infer_dict, 'dict')
register_builtin_transform(infer_frozenset, 'frozenset')
register_builtin_transform(infer_type, 'type')
