"""Astroid hooks for the Python 2 standard library.

Currently help understanding of :

* hashlib.md5 and hashlib.sha1
"""

from astroid import MANAGER, AsStringRegexpPredicate, UseInferenceDefault, inference_tip
from astroid import nodes
from astroid.builder import AstroidBuilder

MODULE_TRANSFORMS = {}


# module specific transformation functions #####################################

def transform(module):
    try:
        tr = MODULE_TRANSFORMS[module.name]
    except KeyError:
        pass
    else:
        tr(module)
MANAGER.register_transform(nodes.Module, transform)

# module specific transformation functions #####################################

def hashlib_transform(module):
    fake = AstroidBuilder(MANAGER).string_build('''

class md5(object):
  def __init__(self, value=''): pass
  def digest(self):
    return u''
  def update(self, value): pass
  def hexdigest(self):
    return u''

class sha1(object):
  def __init__(self, value=''): pass
  def digest(self):
    return u''
  def update(self, value): pass
  def hexdigest(self):
    return u''

''')
    for hashfunc in ('sha1', 'md5'):
        module.locals[hashfunc] = fake.locals[hashfunc]

def collections_transform(module):
    fake = AstroidBuilder(MANAGER).string_build('''

class defaultdict(dict):
    default_factory = None
    def __missing__(self, key): pass

class deque(object):
    maxlen = 0
    def __init__(iterable=None, maxlen=None): pass
    def append(self, x): pass
    def appendleft(self, x): pass
    def clear(self): pass
    def count(self, x): return 0
    def extend(self, iterable): pass
    def extendleft(self, iterable): pass
    def pop(self): pass
    def popleft(self): pass
    def remove(self, value): pass
    def reverse(self): pass
    def rotate(self, n): pass

''')

    for klass in ('deque', 'defaultdict'):
        module.locals[klass] = fake.locals[klass]

def pkg_resources_transform(module):
    fake = AstroidBuilder(MANAGER).string_build('''

def resource_exists(package_or_requirement, resource_name):
    pass

def resource_isdir(package_or_requirement, resource_name):
    pass

def resource_filename(package_or_requirement, resource_name):
    pass

def resource_stream(package_or_requirement, resource_name):
    pass

def resource_string(package_or_requirement, resource_name):
    pass

def resource_listdir(package_or_requirement, resource_name):
    pass

def extraction_error():
    pass

def get_cache_path(archive_name, names=()):
    pass

def postprocess(tempname, filename):
    pass

def set_extraction_path(path):
    pass

def cleanup_resources(force=False):
    pass

''')

    for func_name, func in fake.locals.items():
        module.locals[func_name] = func


def urlparse_transform(module):
    fake = AstroidBuilder(MANAGER).string_build('''

def urlparse(url, scheme='', allow_fragments=True):
    return ParseResult()

class ParseResult(object):
    def __init__(self):
        self.scheme = ''
        self.netloc = ''
        self.path = ''
        self.params = ''
        self.query = ''
        self.fragment = ''
        self.username = None
        self.password = None
        self.hostname = None
        self.port = None

    def geturl(self):
        return ''
''')

    for func_name, func in fake.locals.items():
        module.locals[func_name] = func

def subprocess_transform(module):
    fake = AstroidBuilder(MANAGER).string_build('''

class Popen(object):
    returncode = pid = 0
    stdin = stdout = stderr = file()

    def __init__(self, args, bufsize=0, executable=None,
                 stdin=None, stdout=None, stderr=None,
                 preexec_fn=None, close_fds=False, shell=False,
                 cwd=None, env=None, universal_newlines=False,
                 startupinfo=None, creationflags=0):
        pass

    def communicate(self, input=None):
        return ('string', 'string')
    def wait(self):
        return self.returncode
    def poll(self):
        return self.returncode
    def send_signal(self, signal):
        pass
    def terminate(self):
        pass
    def kill(self):
        pass
   ''')

    for func_name, func in fake.locals.items():
        module.locals[func_name] = func



MODULE_TRANSFORMS['hashlib'] = hashlib_transform
MODULE_TRANSFORMS['collections'] = collections_transform
MODULE_TRANSFORMS['pkg_resources'] = pkg_resources_transform
MODULE_TRANSFORMS['urlparse'] = urlparse_transform
MODULE_TRANSFORMS['subprocess'] = subprocess_transform

# namedtuple support ###########################################################

def infer_named_tuple(node, context=None):
    """Specific inference function for namedtuple CallFunc node"""
    # node is a CallFunc node, class name as first argument and generated class
    # attributes as second argument
    if len(node.args) != 2:
        # something weird here, go back to class implementation
        raise UseInferenceDefault()
    # namedtuple list of attributes can be a list of strings or a
    # whitespace-separate string
    try:
        name = node.args[0].value
        try:
            attributes = node.args[1].value.split()
        except AttributeError:
            attributes = [const.value for const in node.args[1].elts]
    except AttributeError:
        raise UseInferenceDefault()
    # we want to return a Class node instance with proper attributes set
    class_node = nodes.Class(name, 'docstring')
    # set base class=tuple
    class_node.bases.append(nodes.Tuple)
    # XXX add __init__(*attributes) method
    for attr in attributes:
        fake_node = nodes.EmptyNode()
        fake_node.parent = class_node
        class_node.instance_attrs[attr] = [fake_node]
    # we use UseInferenceDefault, we can't be a generator so return an iterator
    return iter([class_node])

MANAGER.register_transform(nodes.CallFunc, inference_tip(infer_named_tuple),
                           AsStringRegexpPredicate('namedtuple', 'func'))


