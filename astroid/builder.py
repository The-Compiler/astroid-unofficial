# copyright 2003-2014 LOGILAB S.A. (Paris, FRANCE), all rights reserved.
# contact http://www.logilab.fr/ -- mailto:contact@logilab.fr
#
# This file is part of astroid.
#
# astroid is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by the
# Free Software Foundation, either version 2.1 of the License, or (at your
# option) any later version.
#
# astroid is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License
# for more details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with astroid. If not, see <http://www.gnu.org/licenses/>.
"""The AstroidBuilder makes astroid from living object and / or from _ast

The builder is not thread safe and can't be used to parse different sources
at the same time.
"""

import _ast
import os
import sys
import textwrap

from astroid import bases
from astroid import exceptions
from astroid import manager
from astroid import modutils
from astroid import nodes
from astroid import raw_building
from astroid import rebuilder
from astroid import util


def _parse(string):
    return compile(string, "<string>", 'exec', _ast.PyCF_ONLY_AST)


if sys.version_info >= (3, 0):
    # pylint: disable=no-name-in-module; We don't understand flows yet.
    from tokenize import detect_encoding

    def open_source_file(filename):
        with open(filename, 'rb') as byte_stream:
            encoding = detect_encoding(byte_stream.readline)[0]
        stream = open(filename, 'r', newline=None, encoding=encoding)
        try:
            data = stream.read()
        except UnicodeError:  # wrong encoding
            # detect_encoding returns utf-8 if no encoding specified
            util.reraise(exceptions.AstroidBuildingException(
                'Wrong ({encoding}) or no encoding specified for {filename}.',
                encoding=encoding, filename=filename))
        return stream, encoding, data

else:
    import re

    _ENCODING_RGX = re.compile(r"\s*#+.*coding[:=]\s*([-\w.]+)")

    def _guess_encoding(string):
        """get encoding from a python file as string or return None if not found"""
        # check for UTF-8 byte-order mark
        if string.startswith('\xef\xbb\xbf'):
            return 'UTF-8'
        for line in string.split('\n', 2)[:2]:
            # check for encoding declaration
            match = _ENCODING_RGX.match(line)
            if match is not None:
                return match.group(1)

    def open_source_file(filename):
        """get data for parsing a file"""
        stream = open(filename, 'U')
        data = stream.read()
        encoding = _guess_encoding(data)
        return stream, encoding, data


MANAGER = manager.AstroidManager()


class AstroidBuilder(object):
    """Class for building an astroid tree from source code or from a live module.

    The param *manager* specifies the manager class which should be used.
    If no manager is given, then the default one will be used. The
    param *apply_transforms* determines if the transforms should be
    applied after the tree was built from source or from a live object,
    by default being True.
    """

    def __init__(self, manager=None, apply_transforms=True):
        self._manager = manager or MANAGER
        self._apply_transforms = apply_transforms

    def module_build(self, module, modname=None):
        """Build an astroid from a living module instance."""
        node = None
        path = getattr(module, '__file__', None)
        if path is not None:
            path_, ext = os.path.splitext(modutils._path_from_filename(path))
            if ext in ('.py', '.pyc', '.pyo') and os.path.exists(path_ + '.py'):
                node = self.file_build(path_ + '.py', modname)
        if node is None:
            # this is a built-in module
            # get a partial representation by introspection
            node = raw_building.ast_from_object(module, name=modname)
            # FIXME
            node.source_file = path
            if self._apply_transforms:
                # We have to handle transformation by ourselves since the
                # rebuilder isn't called for builtin nodes
                node = self._manager.visit_transforms(node)
        return node

    def file_build(self, path, modname=None):
        """Build astroid from a source code file (i.e. from an ast)

        *path* is expected to be a python source file
        """
        try:
            stream, encoding, data = open_source_file(path)
        except IOError as exc:
            util.reraise(exceptions.AstroidBuildingException(
                'Unable to load file {path}:\n{error}',
                modname=modname, path=path, error=exc))
        except (SyntaxError, LookupError) as exc:
            util.reraise(exceptions.AstroidBuildingException(
                'Python 3 encoding specification error or unknown encoding:\n'
                '{error}', modname=modname, path=path, error=exc))
        with stream:
            # get module name if necessary
            if modname is None:
                try:
                    modname = '.'.join(modutils.modpath_from_file(path))
                except ImportError:
                    modname = os.path.splitext(os.path.basename(path))[0]
            # build astroid representation
            module = self._data_build(data, modname, path)
            return self._post_build(module, encoding)

    def string_build(self, data, modname='', path=None):
        """Build astroid from source code string."""
        module = self._data_build(data, modname, path)
        module.source_code = data.encode('utf-8')
        return self._post_build(module, 'utf-8')

    def _post_build(self, module, encoding):
        """Handles encoding and delayed nodes after a module has been built"""
        module.file_encoding = encoding
        self._manager.cache_module(module)
        delayed_assignments(module)

        # Visit the transforms
        if self._apply_transforms:
            module = self._manager.visit_transforms(module)
        return module

    def _data_build(self, data, modname, path):
        """Build tree node from data and add some informations"""
        try:
            node = _parse(data + '\n')
        except (TypeError, ValueError) as exc:
            util.reraise(exceptions.AstroidBuildingException(
                'Parsing Python code failed:\n{error}',
                source=data, modname=modname, path=path, error=exc))
        except SyntaxError as exc:
            # Pass the entire exception object to AstroidBuildingException,
            # since pylint uses this as an introspection method,
            # in order to find what error happened.
            util.reraise(exceptions.AstroidBuildingException(
                'Syntax error in Python source: {error}',
                source=data, modname=modname, path=path, error=exc))
        if path is not None:
            node_file = os.path.abspath(path)
        else:
            node_file = '<?>'
        if modname.endswith('.__init__'):
            modname = modname[:-9]
            package = True
        else:
            package = path and path.find('__init__.py') > -1 or False
        builder = rebuilder.TreeRebuilder(self._manager)
        module = builder.visit_module(node, modname, node_file, package)
        return module


def delayed_assignments(root):
    '''This function modifies nodes according to AssignAttr nodes.

    It traverses the entire AST, and when it encounters an AssignAttr
    node it modifies the instance_attrs or external_attrs of the node
    respresenting that object.  Because it uses inference functions
    that in turn depend on instance_attrs and external_attrs, calling
    it a tree that already have instance_attrs and external_attrs set
    may crash or fail to modify those variables correctly.

    Args:
        root (node_classes.NodeNG): The root of the AST that 
            delayed_assignments() is searching for assignments.

    '''
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.get_children())
        if isinstance(node, nodes.AssignAttr):
            # print('Method:', node.infer)
            # print('Inferred:', [i for i in node.expr.infer()])
            frame = node.frame()
            try:
                # Here, node.expr.infer() will return either the node
                # being assigned to itself, for Module, ClassDef,
                # FunctionDef, or Lambda nodes, or an Instance object
                # corresponding to a ClassDef node.
                for inferred in node.expr.infer():
                    if type(inferred) is bases.Instance:
                        values = inferred._proxied.instance_attrs[node.attrname]
                    elif isinstance(inferred, nodes.Lambda):
                        values = inferred.instance_attrs[node.attrname]
                    elif isinstance(inferred, (nodes.Module, nodes.ClassDef)):
                        values = inferred.external_attrs[node.attrname]
                    else:
                        continue
                    if node in values:
                        continue
                    else:
                        # I have no idea why there's a special case
                        # for __init__ that changes the order of the
                        # attributes or what that order means.
                        if (values and frame.name == '__init__' and not
                            values[0].frame().name == '__init__'):
                            values.insert(0, node)
                        else:
                            values.append(node)
            except exceptions.InferenceError:
                pass


def parse(code, module_name='', path=None, apply_transforms=True):
    """Parses a source string in order to obtain an astroid AST from it

    :param str code: The code for the module.
    :param str module_name: The name for the module, if any
    :param str path: The path for the module
    :param bool apply_transforms:
        Apply the transforms for the give code. Use it if you
        don't want the default transforms to be applied.
    """
    code = textwrap.dedent(code)
    builder = AstroidBuilder(manager=MANAGER,
                             apply_transforms=apply_transforms)
    return builder.string_build(code, modname=module_name, path=path)
