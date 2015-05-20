#!/usr/bin/python
# -*- coding: latin-1 -*-
"""JRC: Java NETCONF Client plug-in

   Copyright 2012 Tail-f Systems AB

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

For complete functionality, invoke with:
> pyang \
    --path <yang search path> \
    --format jrc \
    --jrc-output <package.name> \
    --jrc-verbose \
    --jrc-ignore-errors \
    --jrc-import-on-demand \
    <file.yang>

Or, if you like to keep things simple:
> pyang -f jrc -d <package.name> <file.yang>

"""

import optparse
import os
import errno
import sys
import collections
import re

from datetime import date
from pyang import plugin, util, error

OSSep = "/"

def pyang_plugin_init():
    """Registers an instance of the jnc plugin"""
    plugin.register_plugin(JRCPlugin())


class JRCPlugin(plugin.PyangPlugin):
    """The plug-in class of JRC.

    The methods of this class are invoked by pyang during initialization. The
    emit method is of particular interest if you are new to writing plugins to
    pyang. It is from there that the parsing of the YANG statement tree
    emanates, producing the generated classes that constitutes the output of
    this plug-in.

    """

    def __init__(self):
        self.done = set([])  # Helps avoiding processing modules more than once

    def add_output_format(self, fmts):
        """Adds 'jnc' as a valid output format and sets the format to jnc if
        the -d/--jnc-output option is set, but -f/--format is not.

        """
        self.multiple_modules = False
        fmts['jrc'] = self

        args = sys.argv[1:]
        if not any(x in args for x in ('-f', '--format')):
            if any(x in args for x in ('-d', '--jnc-output')):
                sys.argv.insert(1, '--format')
                sys.argv.insert(2, 'jrc')

    def add_opts(self, optparser):
        """Adds options to pyang, displayed in the pyang CLI help message"""
        optlist = [
            optparse.make_option(
                '--jrc-output',
                dest='directory',
                help='Generate output to DIRECTORY.'),
            optparse.make_option(
                '--jrc-help',
                dest='jrc_help',
                action='store_true',
                help='Print help on usage of the JNC plugin and exit'),
            optparse.make_option(
                '--jrc-serial',
                dest='serial',
                action='store_true',
                help='Turn off usage of multiple threads.'),
            optparse.make_option(
                '--jrc-verbose',
                dest='verbose',
                action='store_true',
                help='Verbose mode: Print detailed debug messages.'),
            optparse.make_option(
                '--jrc-debug',
                dest='debug',
                action='store_true',
                help='Print debug messages. Redundant if verbose mode is on.'),
            optparse.make_option(
                '--jrc-no-classes',
                dest='no_classes',
                action='store_true',
                help='Do not generate classes.'),
            optparse.make_option(
                '--jrc-no-schema',
                dest='no_schema',
                action='store_true',
                help='Do not generate schema.'),
            optparse.make_option(
                '--jrc-no-pkginfo',
                dest='no_pkginfo',
                action='store_true',
                help='Do not generate package-info files.'),
            optparse.make_option(
                '--jrc-ignore-errors',
                dest='ignore',
                action='store_true',
                help='Ignore errors from validation.'),
            optparse.make_option(
                '--jrc-import-on-demand',
                dest='import_on_demand',
                action='store_true',
                help='Use non explicit imports where possible.'),
           optparse.make_option(
                '--jrc-classpath-schema-loading',
                dest='classpath_schema_loading',
                action='store_true',
                help='Load schema files using classpath rather than location.')
            ]
        g = optparser.add_option_group('JRC output specific options')
        g.add_options(optlist)

    def setup_ctx(self, ctx):
        """Called after ctx has been set up in main module. Checks if the
        jnc help option was supplied and if not, that the -d or
        --java-package was used.

        ctx -- Context object as defined in __init__.py

        """
        if ctx.opts.jnc_help:
            self.print_help()
            sys.exit(0)
        if ctx.opts.format == 'jrc':
            if not ctx.opts.directory:
                ctx.opts.directory = 'src/gen'
                print_warning(msg=('Option -d (or --java-package) not set, ' +
                    'defaulting to "src/gen".'))
            #elif 'src' not in ctx.opts.directory:
            #    ctx.opts.directory = 'src/gen'
            #    print_warning(msg=('No "src" in output directory path, ' +
            #        'defaulting to "src/gen".'))

            # Fix path issue, the path in --jnc-output must contain src_managed/main
            if 'src_managed/main' in ctx.opts.directory:
                ctx.rootpkg = ctx.opts.directory.partition('src_managed/main')[2][1:]
                self.ctx = ctx
                self.d = ctx.opts.directory
            elif 'src' in ctx.opts.directory:
                ctx.rootpkg = ctx.opts.directory.rpartition('src')[2][1:]
                self.ctx = ctx
                self.d = ctx.opts.directory

    def setup_fmt(self, ctx):
        """Disables implicit errors for the Context"""
        ctx.implicit_errors = False

    def emit(self, ctx, modules, fd):
        """Generates Java classes from the YANG module supplied to pyang.

        The generated classes are placed in the directory specified by the '-d'
        or '--java-package' flag, or in "gen" if no such flag was provided,
        using the 'directory' attribute of ctx. If there are existing files
        in the output directory with the same name as the generated classes,
        they are silently overwritten.

        ctx     -- Context used to get output directory, verbosity mode, error
                   handling policy (the ignore attribute) and whether or not a
                   schema file should be generated.
        modules -- A list containing a module statement parsed from the YANG
                   module supplied to pyang.
        fd      -- File descriptor (ignored).

        """
        if ctx.opts.debug or ctx.opts.verbose:
            print('JRC plugin starting')
        if not ctx.opts.ignore:
            for (epos, etag, _) in ctx.errors:
                if (error.is_error(error.err_level(etag)) and
                    etag in ('MODULE_NOT_FOUND', 'MODULE_NOT_FOUND_REV')):
                    self.fatal("%s contains errors" % epos.top.arg)
                if (etag in ('TYPE_NOT_FOUND', 'FEATURE_NOT_FOUND',
                    'IDENTITY_NOT_FOUND', 'GROUPING_NOT_FOUND')):
                    print_warning(msg=(etag.lower() + ', generated class ' +
                        'hierarchy might be incomplete.'), key=etag)
                else:
                    print_warning(msg=(etag.lower() + ', aborting.'), key=etag)
                    self.fatal("%s contains errors" % epos.top.arg)

        # Sweep, adding included and imported modules, until no change
        module_set = set(modules)
        # num_modules = 0
        # while num_modules != len(module_set):
        #     num_modules = len(module_set)
        #     for module in list(module_set):
        #         imported = map(lambda x: x.arg, search(module, 'import'))
        #         included = map(lambda x: x.arg, search(module, 'include'))
        #         for (module_stmt, rev) in self.ctx.modules:
        #             if module_stmt in (imported + included):
        #                 module_set.add(self.ctx.modules[(module_stmt, rev)])

        # Generate files from main modules
        for module in filter(lambda s: s.keyword == 'module', module_set):
            self.generate_from(module)

        # Generate files from augmented modules
        for aug_module in augmented_modules.values():
            self.generate_from(aug_module)

        # Print debug messages saying that we're done.
        if ctx.opts.debug or ctx.opts.verbose:
            if not self.ctx.opts.no_classes:
                print('Scala classes generation COMPLETE.')
            #if not self.ctx.opts.no_schema:
            #    print('Schema generation COMPLETE.')

    def generate_from(self, module):
        """Generates classes, schema file and pkginfo files for module,
        according to options set in self.ctx. The attributes self.directory
        and self.d are used to determine where to generate the files.

        module -- Module statement to generate files from

        """
        if module in self.done:
            return
        self.done.add(module)
        subpkg = camelize(module.arg)
        if self.ctx.rootpkg:
            fullpkg = '.'.join([self.ctx.rootpkg, 'api', subpkg]).replace('/', '.')
            mopkg = '.'.join([self.ctx.rootpkg, 'mo', subpkg]).replace('/', '.')
        else:
            fullpkg = subpkg
        d = OSSep.join([self.d , subpkg])
        if not self.ctx.opts.no_classes:
            # Generate Java classes
            src = ('module "' + module.arg + '", revision: "' +
                util.get_latest_revision(module) + '".')
            generator = ClassGenerator(module,
                path=OSSep.join([self.ctx.opts.directory, 'api', subpkg]),
                package=fullpkg, mopackage=mopkg, src=src, ctx=self.ctx)
            generator.generate()

        # if not self.ctx.opts.no_schema:
        #     # Generate external schema
        #     schema_nodes = ['<schema>']
        #     stmts = search(module, node_stmts)
        #     module_root = SchemaNode(module, '/')
        #     schema_nodes.extend(module_root.as_list())
        #     if self.ctx.opts.verbose:
        #         print('Generating schema node "/"...')
        #     schema_generator = SchemaGenerator(stmts, '/', self.ctx)
        #     schema_nodes.extend(schema_generator.schema_nodes())
        #     for i in range(1, len(schema_nodes)):
        #         # Indent all but the first and last line
        #         if schema_nodes[i] in ('<node>', '</node>'):
        #             schema_nodes[i] = ' ' * 4 + schema_nodes[i]
        #         else:
        #             schema_nodes[i] = ' ' * 8 + schema_nodes[i]
        #     schema_nodes.append('</schema>')
        #
        #     name = normalize(search_one(module, 'prefix').arg)
        #     write_file(d, name + '.schema', '\n'.join(schema_nodes), self.ctx)

        # if not self.ctx.opts.no_pkginfo:
        #     # Generate package-info.java for javadoc
        #     pkginfo_generator = PackageInfoGenerator(d, module, self.ctx)
        #     pkginfo_generator.generate_package_info()

        if self.ctx.opts.debug or self.ctx.opts.verbose:
            print('pkg ' + fullpkg + ' generated')

    def fatal(self, exitCode=1):
        """Raise an EmitError"""
        raise error.EmitError(self, exitCode)

    def print_help(self):
        """Prints a description of what JNC is and how to use it"""
        print('''
The JNC (Java NETCONF Client) plug-in can be used to generate a Java class
hierarchy from a single YANG data model. Together with the JNC library, these
generated Java classes may be used as the foundation for a NETCONF client
(AKA manager) written in Java.

The different types of generated files are:

Root class  -- This class has the name of the prefix of the YANG module, and
               contains fields with the prefix and namespace as well as methods
               that enables the JNC library to use the other generated classes
               when interacting with a NETCONF server.

YangElement -- Each YangElement corresponds to a container, list or
               notification in the YANG model. They represent tree nodes of a
               configuration and provides methods to modify the configuration
               in accordance with the YANG model that they were generated from.

               The top-level nodes in the YANG model will have their
               corresponding YangElement classes generated in the output
               directory together with the root class. Their respective
               subnodes are generated in subpackages with names corresponding
               to the name of the parent.

YangTypes   -- For each derived type in the YANG model, a class is generated to
               the root of the output directory. The derived type may either
               extend another derived type class, or the JNC type class
               corresponding to a built-in YANG type.

Packageinfo -- For each package in the generated Java class hierarchy, a
               package-info.java file is generated, which can be useful when
               generating javadoc for the hierarchy.

Schema file -- If enabled, an XML file containing structured information about
               the generated Java classes is generated. It contains tagpaths,
               namespace, primitive-type and other useful meta-information.

The typical use case for these classes is as part of a JAVA network management
system (EMS), to enable retrieval and/or storing of configurations on NETCONF
agents/servers with specific capabilities.

One way to use the JNC plug-in of pyang is
$ pyang -f jnc --jnc-output package.dir <file.yang>

Type '$ pyang --help' for more details on how to use pyang.
''')


com_tailf_jnc = {'Attribute', 'Capabilities', 'ConfDSession',
                 'DefaultIOSubscriber', 'Device', 'DeviceUser', 'DummyElement',
                 'Element', 'ElementChildrenIterator', 'ElementHandler',
                 'ElementLeafListValueIterator', 'IOSubscriber',
                 'JNCException', 'Leaf', 'NetconfSession', 'NodeSet', 'Path',
                 'PathCreate', 'Prefix', 'PrefixMap', 'RevisionInfo',
                 'RpcError', 'SchemaNode', 'SchemaParser', 'SchemaTree',
                 'SSHConnection', 'SSHSession', 'Tagpath', 'TCPConnection',
                 'TCPSession', 'Transport', 'Utils', 'XMLParser',
                 'YangBaseInt', 'YangBaseString', 'YangBaseType', 'YangBinary',
                 'YangBits', 'YangBoolean', 'YangDecimal64', 'YangElement',
                 'YangEmpty', 'YangEnumeration', 'YangException',
                 'YangIdentityref', 'YangInt16', 'YangInt32', 'YangInt64',
                 'YangInt8', 'YangLeafref', 'YangString', 'YangType',
                 'YangUInt16', 'YangUInt32', 'YangUInt64', 'YangUInt8',
                 'YangUnion', 'YangXMLParser', 'YangJsonParser'}


java_reserved_words = {'abstract', 'assert', 'boolean', 'break', 'byte',
                       'case', 'catch', 'char', 'class', 'const', 'continue',
                       'default', 'double', 'do', 'else', 'enum', 'extends',
                       'false','final', 'finally', 'float', 'for', 'goto',
                       'if', 'implements', 'import', 'instanceof', 'int',
                       'interface', 'long', 'native', 'new', 'null', 'package',
                       'private', 'protected', 'public', 'return', 'short',
                       'static', 'strictfp', 'super', 'switch', 'synchronized',
                       'this', 'throw', 'throws', 'transient', 'true', 'try',
                       'void', 'volatile', 'while'}
"""A set of all identifiers that are reserved in Java"""


java_literals = {'true', 'false', 'null'}
"""The boolean and null literals of Java"""


java_lang = {'Appendable', 'CharSequence', 'Cloneable', 'Comparable',
             'Iterable', 'Readable', 'Runnable', 'Boolean', 'Byte',
             'Character', 'Class', 'ClassLoader', 'Compiler', 'Double',
             'Enum', 'Float', 'Integer', 'Long', 'Math', 'Number',
             'Object', 'Package', 'Process', 'ProcessBuilder',
             'Runtime', 'RuntimePermission', 'SecurityManager',
             'Short', 'StackTraceElement', 'StrictMath', 'String',
             'StringBuffer', 'StringBuilder', 'System', 'Thread',
             'ThreadGroup', 'ThreadLocal', 'Throwable', 'Void'}
"""A subset of the java.lang classes"""


java_util = {'Collection', 'Enumeration', 'Iterator', 'List', 'ListIterator',
             'Map', 'Queue', 'Set', 'ArrayList', 'Arrays', 'HashMap',
             'HashSet', 'Hashtable', 'LinkedList', 'Properties', 'Random',
             'Scanner', 'Stack', 'StringTokenizer', 'Timer', 'TreeMap',
             'TreeSet', 'UUID', 'Vector'}
"""A subset of the java.util interfaces and classes"""


java_built_in = java_reserved_words | java_literals | java_lang
"""Identifiers that shouldn't be imported in Java"""


yangelement_stmts = {'container', 'list', 'notification', 'rpc'}
"""Keywords of statements that YangElement classes are generated from"""


leaf_stmts = {'leaf', 'leaf-list'}
"""Leaf and leaf-list statement keywords"""


module_stmts = {'module', 'submodule'}
"""Module and submodule statement keywords"""


node_stmts = module_stmts | yangelement_stmts | leaf_stmts
"""Keywords of statements that make up a configuration tree"""


package_info = '''/**
 * This class hierarchy was generated from the Yang module{0}
 * by the <a target="_top" href="https://github.com/tail-f-systems/JNC">JNC</a> plugin of <a target="_top" href="http://code.google.com/p/pyang/">pyang</a>.
 * The generated classes may be used to manipulate pieces of configuration data
 * with NETCONF operations such as edit-config, delete-config and lock. These
 * operations are typically accessed through the JNC Java library by
 * instantiating Device objects and setting up NETCONF sessions with real
 * devices using a compatible YANG model.
 * <p>{1}
 * @see <a target="_top" href="https://github.com/tail-f-systems/JNC">JNC project page</a>
 * @see <a target="_top" href="ftp://ftp.rfc-editor.org/in-notes/rfc6020.txt">RFC 6020: YANG - A Data Modeling Language for the Network Configuration Protocol (NETCONF)</a>
 * @see <a target="_top" href="ftp://ftp.rfc-editor.org/in-notes/rfc6241.txt">RFC 6241: Network Configuration Protocol (NETCONF)</a>
 * @see <a target="_top" href="ftp://ftp.rfc-editor.org/in-notes/rfc6242.txt">RFC 6242: Using the NETCONF Protocol over Secure Shell (SSH)</a>
 * @see <a target="_top" href="http://www.tail-f.com">Tail-f Systems</a>
 */
 package '''
"""Format string used in package-info files"""


outputted_warnings = []
"""A list of warning message IDs that are used to avoid duplicate warnings"""


augmented_modules = {}
"""A dict of external modules that are augmented by the YANG module"""


camelized_stmt_args = {}
"""Cache containing camelized versions of statement identifiers"""


normalized_stmt_args = {}
"""Cache containing normalized versions of statement identifiers"""


class_hierarchy = {}
"""Dict that map package names to sets of names of classes to be generated"""


def print_warning(msg='', key='', ctx=None):
    """Prints msg to stderr if ctx is None or the debug or verbose flags are
    set in context ctx and key is empty or not in outputted_warnings. If key is
    not empty and not in outputted_warnings, it is added to it. If msg is empty
    'No support for type "' + key + '", defaulting to string.' is printed.

    """
    if ((not key or key not in outputted_warnings) and
        (not ctx or ctx.opts.debug or ctx.opts.verbose)):
        if msg:
            sys.stderr.write('WARNING: ' + msg)
            if key:
                outputted_warnings.append(key)
        else:
            print_warning(('No support for type "' + key + '", defaulting ' +
                'to string.'), key, ctx)


def write_file(d, file_name, file_content, ctx):
    """Creates the directory d if it does not yet exist and writes a file to it
    named file_name with file_content in it.

    """
    #d = d.replace('.', OSSep)
    wd = os.getcwd()
    try:
        os.makedirs(d, 0o777)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            pass  # The directory already exists
        else:
            raise
    try:
        os.chdir(d)
    except OSError as exc:
        if exc.errno == errno.ENOTDIR:
            print_warning(msg=('Unable to change directory to ' + d +
                '. Probably a non-directory file with same name as one of ' +
                'the subdirectories already exists.'), key=d, ctx=ctx)
        else:
            raise
    finally:
        if ctx.opts.verbose:
            print('Writing file to: ' + os.getcwd() + OSSep + file_name)
        os.chdir(wd)
    with open(d + OSSep + file_name, 'w+') as f:
        if isinstance(file_content, str):
            f.write(file_content)
        else:
            for line in file_content:
                f.write(line)
                f.write('\n')


def get_module(stmt):
    """Returns the module to which stmt belongs to"""
    if stmt.top is not None:
        return get_module(stmt.top)
    elif stmt.keyword == 'module':
        return stmt
    else:  # stmt.keyword == 'submodule':
        belongs_to = search_one(stmt, 'belongs-to')
        for (module_name, revision) in stmt.i_ctx.modules:
            if module_name == belongs_to.arg:
                return stmt.i_ctx.modules[(module_name, revision)]


def get_parent(stmt):
    """Returns closest parent which is not a choice, case or submodule
    statement. If the parent is a submodule statement, the corresponding main
    module is returned instead.

    """
    if stmt.parent is None:
        return None
    elif stmt.parent.keyword == 'submodule':
        return get_module(stmt)
    elif stmt.parent.parent is None:
        return stmt.parent
    elif stmt.parent.keyword in ('choice', 'case'):
        return get_parent(stmt.parent)
    else:
        return stmt.parent


def get_package(stmt, ctx):
    """Returns a string representing the package name of a java class generated
    from stmt, assuming that it has been or will be generated by JNC.

    """
    sub_packages = collections.deque()
    parent = get_parent(stmt)
    while parent is not None:
        if stmt.i_orig_module.keyword == "submodule" and stmt.keyword != "typedef" and get_parent(parent) is None:
            sub_packages.appendleft(camelize(stmt.i_orig_module.arg))
        stmt = parent
        parent = get_parent(stmt)
        sub_packages.appendleft(camelize(stmt.arg))

    full_package = ctx.rootpkg.split(OSSep)
    full_package.extend(['mo'])
    full_package.extend(sub_packages)
    return '.'.join(full_package)

def get_api_package(stmt, ctx):
    """Returns a string representing the package name of a java class generated
    from stmt, assuming that it has been or will be generated by JNC.

    """
    sub_packages = collections.deque()
    parent = get_parent(stmt)
    while parent is not None:
        if stmt.i_orig_module.keyword == "submodule" and stmt.keyword != "typedef" and get_parent(parent) is None:
            sub_packages.appendleft(camelize(stmt.i_orig_module.arg))
        stmt = parent
        parent = get_parent(stmt)
        sub_packages.appendleft(camelize(stmt.arg))

    full_package = ctx.rootpkg.split(OSSep)
    full_package.extend(['api'])
    full_package.extend(sub_packages)
    return '.'.join(full_package)

def get_parents(stmt):
    sub_packages = collections.deque()
    parent = get_parent(stmt)
    while parent is not None and parent.keyword != "submodule" and parent.keyword != "module":
        stmt = parent
        parent = get_parent(stmt)
        sub_packages.appendleft(stmt)

    return sub_packages

def pairwise(iterable):
    """Returns an iterator that includes the next item also"""
    iterator = iter(iterable)
    item = next(iterator)  # throws StopIteration if empty.
    for next_item in iterator:
        yield (item, next_item)
        item = next_item
    yield (item, None)


def capitalize_first(string):
    """Returns string with its first character capitalized (if any)"""
    return string[:1].capitalize() + string[1:]


def decapitalize_first(string):
    """Returns string with its first character decapitalized (if any)"""
    return string[:1].lower() + string[1:]


def camelize(string):
    """Converts string to lower camel case

    Removes hyphens and dots and replaces following character (if any) with
    its upper-case counterpart. Does not remove consecutive or trailing hyphens
    or dots.

    If the resulting string is reserved in Java, an underline is appended

    Returns an empty string if string argument is None. Otherwise, returns
    string decapitalized and with no consecutive upper case letters.

    """
    try:  # Fetch from cache
        return camelized_stmt_args[string]
    except KeyError:
        pass
    camelized_str = collections.deque()
    if string is not None:
        iterator = pairwise(decapitalize_first(string))
        for character, next_character in iterator:
            if next_character is None:
                if (len(string) > 1):
                    camelized_str.append(character)
                else:
                    if(string.isupper()):
                        camelized_str.append(character.upper())
                    else:
                        camelized_str.append(character.lower())
            elif character in '-._':
                camelized_str.append(capitalize_first(next_character))
                next(iterator)
            elif (character.isupper()
                  and (next_character.isupper()
                       or not next_character.isalpha())):
                camelized_str.append(character.lower())
            else:
                camelized_str.append(character)
    res = ''.join(camelized_str)
    if res in java_reserved_words | java_literals:
        camelized_str.append('_')
    if re.match(r'\d', res):
        camelized_str.appendleft('_')
    res = ''.join(camelized_str)
    camelized_stmt_args[string] = res  # Add to cache
    return res


def normalize(string):
    """returns capitalize_first(camelize(string)), except if camelize(string)
    begins with and/or ends with a single underline: then they are/it is
    removed and a 'J' is prepended. Mimics normalize in YangElement of JNC.

    """
    try:  # Fetch from cache
        return normalized_stmt_args[string]
    except KeyError:
        pass
    res = camelize(string)
    start = 1 if res.startswith('_') else 0
    end = -1 if res.endswith('_') else 0
    if start or end:
        res = 'J' + capitalize_first(res[start:end])
    else:
        res = capitalize_first(res)
    normalized_stmt_args[string] = res  # Add to cache
    return res


def flatten(l):
    """Returns a flattened version of iterable l

    l must not have an attribute named values unless the return value values()
    is a valid substitution of l. Same applies to all items in l.

    Example: flatten([['12', '34'], ['56', ['7']]]) = ['12', '34', '56', '7']
    """
    res = []
    while hasattr(l, 'values'):
        l = list(l.values())
    for item in l:
        try:
            assert not isinstance(item, str)
            iter(item)
        except (AssertionError, TypeError):
            res.append(item)
        else:
            res.extend(flatten(item))
    return res


def get_types(yang_type, ctx):
    """Returns jnc and primitive counterparts of yang_type, which is a type,
    typedef, leaf or leaf-list statement.

    """
    if yang_type.keyword in leaf_stmts:
        yang_type = search_one(yang_type, 'type')
    assert yang_type.keyword in ('type', 'typedef'), 'argument is type, typedef or leaf'
    if yang_type.arg == 'leafref':
        return get_types(yang_type.parent.i_leafref.i_target_node, ctx)
    primitive = normalize(yang_type.arg)
    if yang_type.keyword == 'typedef':
        primitive = normalize(get_base_type(yang_type).arg)
    if primitive == 'JBoolean':
        primitive = 'Boolean'
    jnc = 'com.tailf.jnc.Yang' + primitive
    if yang_type.arg in ('string', 'boolean'):
        pass
    elif yang_type.arg in ('enumeration', 'binary', 'union', 'empty',
                           'instance-identifier', 'identityref'):
        primitive = 'String'
    elif yang_type.arg in ('bits',):  # uint64 handled below
        primitive = 'BigInteger'
    elif yang_type.arg == 'decimal64':
        primitive = 'BigDecimal'
    elif yang_type.arg in ('int8', 'int16', 'int32', 'int64', 'uint8',
            'uint16', 'uint32', 'uint64'):
        integer_type = ['long', 'int', 'short', 'byte']
        if yang_type.arg[:1] == 'u':  # Unsigned
            integer_type.pop()
            integer_type.insert(0, 'BigInteger')
            jnc = 'com.tailf.jnc.YangUI' + yang_type.arg[2:]
        if yang_type.arg[-2:] == '64':
            primitive = integer_type[0]
        elif yang_type.arg[-2:] == '32':
            primitive = integer_type[1]
        elif yang_type.arg[-2:] == '16':
            primitive = integer_type[2]
        else:  # 8 bits
            primitive = integer_type[3]
    else:
        try:
            typedef = yang_type.i_typedef
        except AttributeError:
            if yang_type.keyword == 'typedef':
                primitive = normalize(yang_type.arg)
            else:
                pkg = get_package(yang_type, ctx)
                name = normalize(yang_type.arg)
                print_warning(key=pkg  + '.' + name, ctx=ctx)
        else:
            basetype = get_base_type(typedef)
            jnc, primitive = get_types(basetype, ctx)
            if get_parent(typedef).keyword in ('module', 'submodule'):
                package = get_package(typedef, ctx)
                typedef_arg = normalize(typedef.arg)
                jnc = package + '.' + typedef_arg
    return jnc, primitive


def get_base_type(stmt):
    """Returns the built in type that stmt is derived from"""
    if stmt.keyword == 'type' and stmt.arg == 'union':
        return stmt
    type_stmt = search_one(stmt, 'type')
    if type_stmt is None:
        return stmt
    try:
        typedef = type_stmt.i_typedef
    except AttributeError:
        return type_stmt
    else:
        if typedef is not None:
            return get_base_type(typedef)
        else:
            return type_stmt


def get_import(string):
    """Returns a string representing a class that can be imported in Java.

    Does not handle Generics or Array types and is data model agnostic.

    """
    if string.startswith(('java.math', 'java.util', 'com.tailf.jnc')):
        return string
    elif string in ('BigInteger', 'BigDecimal'):
        return '.'.join(['java.math', string])
    elif string in java_util:
        return '.'.join(['java.util', string])
    else:
        return '.'.join(['com.tailf.jnc', string])


def search(stmt, keywords):
    """Utility for calling Statement.search. If stmt has an i_children
    attribute, they are searched for keywords as well.

    stmt     -- Statement to search for children in
    keywords -- A string, or a tuple, list or set of strings, to search for

    Returns a set (without duplicates) of children with matching keywords.
    If choice or case is not in keywords, substatements of choice and case
    are searched as well.

    """
    if isinstance(keywords, str):
        keywords = keywords.split()
    bypassed = ('choice', 'case')
    bypass = all(x not in keywords for x in bypassed)
    dict_ = collections.OrderedDict()

    def iterate(children, acc):
        for ch in children:
            if bypass and ch.keyword in bypassed:
                _search(ch, keywords, acc)
                continue
            try:
                key = ' '.join([ch.keyword, camelize(ch.arg)])
            except TypeError:
                if ch.arg is None:  # Extension
                    key = ' '.join(ch.keyword)
                else:
                    key = ' '.join([':'.join(ch.keyword), camelize(ch.arg)])
            if key in acc:
                continue
            for keyword in keywords:
                if ch.keyword == keyword:
                    acc[key] = ch
                    break

    def _search(stmt, keywords, acc):
        if any(x in keywords for x in ('typedef', 'import',
                                       'augment', 'include')):
            old_keywords = keywords[:]
            keywords = ['typedef', 'import', 'augment', 'include']
            iterate(stmt.substmts, acc)
            keywords = old_keywords
        try:
            iterate(stmt.i_children, acc)
        except AttributeError:
            iterate(stmt.substmts, acc)

    _search(stmt, keywords, dict_)
    return list(dict_.values())


def search_one(stmt, keyword, arg=None):
    """Utility for calling Statement.search_one, including i_children."""
    res = stmt.search_one(keyword, arg=arg)
    if res is None:
        try:
            res = stmt.search_one(keyword, arg=arg, children=stmt.i_children)
        except AttributeError:
            pass
    if res is None:
        try:
            return search(stmt, keyword)[0]
        except IndexError:
            return None
    return res

def search_one_raw(self, raw_keyword, arg=None, children=None):
    """Return receiver's substmt with `keyword` and optionally `arg`.
    """
    if children is None:
        children = self.substmts
    for ch in children:
        if ch.raw_keyword == raw_keyword and (arg is None or ch.arg == arg):
            return ch
    return None

def is_config(stmt):
    """Returns True if stmt is a configuration data statement"""
    config = None
    while config is None and stmt is not None:
        if stmt.keyword == 'notification':
            return False # stmt is not config if part of a notification tree
        config = search_one(stmt, 'config')
        stmt = get_parent(stmt)
    return config is None or config.arg == 'true'

def is_include_yangelement(stmt):
    """Returns True if stmt include a yangelement_stmt data statement"""
    for ch in stmt.substmts:
        for keyword in yangelement_stmts:
            if ch.keyword == keyword:
                return True
    return False

def get_typename(stmt):
    t = search_one(stmt, 'type')
    if t is not None:
        return t.arg
    else:
       return ''

class YangType(object):
    """Provides an interface to maintain a list of defined yang types"""

    def __init__(self):
        self.defined_types = ['empty', 'int8', 'int16', 'int32', 'int64',
            'uint8', 'uint16', 'uint32', 'uint64', 'binary', 'bits', 'boolean',
            'decimal64', 'enumeration', 'identityref', 'instance-identifier',
            'leafref', 'string', 'union']  # Use set instead!
        """List of types represented by a jnc or generated class"""

    def defined(self, yang_type):
        """Returns true if yang_type is defined, else false"""
        return (yang_type in self.defined_types)

    def add(self, yang_type):
        """Gives yang_type "defined" status in this instance of YangType"""
        self.defined_types.append(yang_type)


class ClassGenerator(object):
    """Used to generate java classes from a yang module"""

    def __init__(self, stmt, path=None, package=None, mopackage=None, src=None, ctx=None,
                 ns='', prefix_name='', yang_types=None, parent=None):
        """Constructor.

        stmt        -- A statement (sub)tree, parsed from a YANG model
        path        -- Full path to where the class should be written
        package     -- Name of Java package
        src         -- Filename of parsed yang module, or the module name and
                       revision if filename is unknown
        ctx         -- Context used to fetch option parameters
        ns          -- The XML namespace of the module
        prefix_name -- The module prefix
        yang_types  -- An instance of the YangType class
        parent      -- ClassGenerator to copy arguments that were not supplied
                       from (if applicable)

        """
        self.stmt = stmt
        self.path = path
        self.package = None if package is None else package.replace(OSSep, '.')
        self.mopackage = None if mopackage is None else mopackage.replace(OSSep, '.')
        self.src = src
        self.ctx = ctx
        self.ns = ns
        self.prefix_name = prefix_name
        self.yang_types = yang_types

        self.n = normalize(stmt.arg.replace("_","-"))
        self.n2 = camelize(stmt.arg.replace("_","-"))

        if stmt.keyword in module_stmts:
            self.filename = normalize(stmt.arg) + 'Routes.scala'
        if stmt.keyword in ('rpc'):
            if self.stmt.i_module.keyword in ("submodule", "module"):
                self.filename=normalize(self.stmt.i_module.arg)+"RpcApi.scala"
            else:
                self.filename=normalize(self.n2)+"RpcApi.scala"
        else:
            self.filename = self.n + 'Api.scala'

        if yang_types is None:
            self.yang_types = YangType()
        if parent is not None:
            for attr in ('package', 'src', 'ctx', 'path', 'ns',
                         'prefix_name', 'yang_types'):
                if getattr(self, attr) is None:
                    setattr(self, attr, getattr(parent, attr))

            module = get_module(stmt)
            if self.ctx.rootpkg:
                self.rootpkg = '.'.join([self.ctx.rootpkg.replace(OSSep, '.'),
                                         camelize(module.arg)])
            else:
                self.rootpkg = camelize(module.arg)
        else:
            self.rootpkg = package

    def generate(self):
        """Generates class(es) for self.stmt"""
        if self.stmt.keyword in ('module', 'submodule'):
            self.generate_classes()
        elif self.stmt.keyword in ('list', 'container'):
            if search_one(self.stmt, ('csp-common', 'vertex')) or search_one(self.stmt, ('csp-common', 'edge')) :
                self.generate_class()

    def generate_classes(self):
        """Generates a Java class hierarchy from a module statement, allowing
        for netconf communication using the jnc library.

        """
        assert(self.stmt.keyword == 'module')

        is_yangelement = is_include_yangelement(self.stmt)

        if is_yangelement:
            module_stmts = set([self.stmt])
        else:
            module_stmts = set([])
        included = map(lambda x: x.arg, search(self.stmt, 'include'))

        for (module, rev) in self.ctx.modules:
             if module in included:
                 module_stmts.add(self.ctx.modules[(module, rev)])

        for module in module_stmts:
            self.generate_routeclass(module)

    def generate_routeclass(self, module):
        """Generates a Scala routes class hierarchy from a module or submodule statement

        module        -- A statement (sub)tree represent module or submodule, parsed from a YANG model
        """
        filename = normalize(module.arg) + 'Routes.scala'
        schema_route_filename = normalize(module.arg) + 'SchemaRoutes.scala'
        self.body = []
        self.schema_body = []

        if module.keyword == "module":
            path = self.path
            mopackage = self.mopackage
            package = self.package
            namespace_stmt = search_one(module, "namespace")
            namespace = namespace_stmt.arg
        elif module.keyword == "submodule":
            path = self.path + "/" + camelize(module.arg)
            mopackage = self.mopackage + "." + camelize(module.arg)
            package = self.package + "." + camelize(module.arg)
            main_module = get_module(self.stmt)
            namespace_stmt = search_one(main_module, "namespace")
            namespace = namespace_stmt.arg

        # Generate routes class
        if self.ctx.opts.verbose:
            print('Generating REST API Routes class "' + filename + '"...')

        self.java_class = JavaClass(filename=filename,
                package=package, description=('The routes class for namespace ' +
                    module.arg),
                source=module.arg,
                superclass='EasyRestRoutingDSL with LazyLogging with HttpService')

        self.schema_class = JavaClass(filename=schema_route_filename,
                package=package, description=('The routes class for namespace ' +
                    module.arg),
                source=module.arg,
                superclass='EasyRestRoutingDSL with LazyLogging with HttpService')

        self.java_class.imports.add("net.juniper.easyrest.util.JsonUtil")
        
        rpc_class = None

        dispatcher_import = [' ' * 4 + "import net.juniper.easyrest.core.EasyRestActionSystem.system.dispatcher"]
        dispatcher = JavaValue(dispatcher_import)
        self.java_class.append_access_method("dispatcher", dispatcher)
        self.schema_class.append_access_method("dispatcher", dispatcher)

        namespace_def = [' ' * 4 + "private val modelNS = \"" + namespace + "\""]
        namespace_str = JavaValue(namespace_def)
        self.java_class.append_access_method("namespace", namespace_str)

        schema_namespace_def = [' ' * 4 + "private val namespace = \"" + namespace + "\""]
        schema_namespace = JavaValue(schema_namespace_def)
        self.schema_class.append_access_method("namespace", schema_namespace)

        model_def = [' ' * 4 + "private val modelPrefix = \"" + module.arg + "\""]
        model = JavaValue(model_def)
        self.java_class.append_access_method("model", model)

        prefixmap_def = [' ' * 4 + "private val prefixs = new PrefixMap(Array(new Prefix(\"\", modelNS),new Prefix(modelPrefix, modelNS)))"]
        prefixmap = JavaValue(prefixmap_def)
        self.java_class.append_access_method("prefixmap", prefixmap)
        self.java_class.imports.add("com.tailf.jnc.Prefix")
        self.java_class.imports.add("com.tailf.jnc.PrefixMap")

        module_prefix = normalize(search_one(self.stmt, 'prefix').arg)
        enable_def = [' ' * 4 + module_prefix+".enable"]
        enable_method = JavaValue(enable_def)
        self.java_class.append_access_method("enable", enable_method)
        self.java_class.imports.add(self.mopackage +"."+ normalize(module_prefix))
        self.schema_class.append_access_method("enable", enable_method)
        self.schema_class.imports.add(self.mopackage +"."+ normalize(module_prefix))


        api = [' ' * 4 + 'lazy val schemaReadFunctionApiImpl = new SchemaReadApiImpl()']
        apiimpl = JavaValue(api)
        self.schema_class.append_access_method("api", apiimpl)
        self.schema_class.imports.add("net.juniper.easyrest.yang.schema.SchemaReadApiImpl")

        import_rpc_impl = False

        res = search(module, list(yangelement_stmts | {'augment'}))

        if (len(res) > 0):
            # Generate classes for children of module/submodule
            for stmt in search(module, list(yangelement_stmts)):
                # Do not generate include stmt in submodule
                if stmt.i_orig_module.arg == module.arg:
                    if stmt.keyword == 'rpc':
                        self.generate_rpc_routes(stmt)
                        if rpc_class == None:
                            rpc_class = JavaClass(filename=normalize(module.arg+"RpcApi")+".scala",
                                package=package,
                                description=''.join(['This class represents rpc api']),
                                source=self.src)
                        self.generate_rpc_class(stmt, rpc_class, mopackage)
                        import_rpc_impl = True
                    elif stmt.keyword == 'notification':
                        self.generate_notification_routes(stmt)
                    else:
                        if search_one(stmt, ('csp-common', 'vertex')) or search_one(stmt, ('csp-common', 'edge')):
                            self.generate_routes(stmt)
                            self.generate_schema_routes(stmt)
                            child_generator = ClassGenerator(stmt, path=path, package=package, mopackage=mopackage,
                                                     ns=module.arg, prefix_name=module.arg, parent=self)
                            child_generator.generate()

            #self.path = path
            if rpc_class is not None:
                self.write_rpc_to_file(path, rpc_class)

            if self.body:
                if import_rpc_impl:
                    rpcapi = [' ' * 4 + 'lazy val '+camelize(module.arg)+'RpcApiImpl = ApiImplRegistry.getImplementation(classOf['+normalize(module.arg)+'RpcApi])']
                    rpcapiimpl = JavaValue(rpcapi)
                    self.java_class.append_access_method("apiimpl", rpcapiimpl)

                routing = [' ' * 4 + "val " + camelize(module.arg) + "RestApiRouting = compressResponseIfRequested(new RefFactoryMagnet()) {"]
                routing.extend(self.body)
                routing[len(routing)-1] = ' ' * 6 + '}'
                routing.append(' ' * 4 + '}')
                res = JavaValue(routing)
                self.java_class.append_access_method("routing", res)
            else:
                routing = [' ' * 4 + "val " + camelize(module.arg) + "RestApiRouting = PLACE_HOLDER_ROUTE"]
                res = JavaValue(routing)
                self.java_class.append_access_method("routing", res)
                self.java_class.imports.add("net.juniper.easyrest.rest.EasyRestRoutingDSL")
                self.java_class.imports.add("spray.routing.HttpService")
                self.java_class.imports.add("com.typesafe.scalalogging.LazyLogging")

            write_file(path,
                   filename,
                   self.java_class.as_list(),
                   self.ctx)

            if self.schema_body:
                schema_routing = [' ' * 4 + "val " + camelize(module.arg) + "RestApiSchemaRouting = compressResponseIfRequested(new RefFactoryMagnet()) {"]
                schema_routing.append(' ' * 6 + 'get {')
                schema_routing.extend(self.schema_body)
                schema_routing[len(schema_routing)-1] = ' ' * 8 + '}'
                schema_routing.append(' ' * 6 + '}')
                schema_routing.append(' ' * 4 + '}')
                schema_res = JavaValue(schema_routing)
                self.schema_class.append_access_method("routing", schema_res)
            else:
                schema_routing = [' ' * 4 + "val " + camelize(module.arg) + "RestApiSchemaRouting = PLACE_HOLDER_ROUTE"]
                schema_res = JavaValue(schema_routing)
                self.schema_class.append_access_method("routing", schema_res)
                self.schema_class.imports.add("net.juniper.easyrest.rest.EasyRestRoutingDSL")
                self.schema_class.imports.add("spray.routing.HttpService")
                self.schema_class.imports.add("com.typesafe.scalalogging.LazyLogging")

            write_file(path,
                   schema_route_filename,
                   self.schema_class.as_list(),
                   self.ctx)
        else:
            print('There is no list, container, rpc or notification in "'+ module.arg + '"')

    def generate_class(self):
        """Generates a Java class hierarchy providing an interface to a YANG
        module. Uses mutual recursion with generate_child.

        """
        if self.stmt.keyword == "container":
            return

        stmt = self.stmt
        stmt_arg = stmt.arg.replace("_","-")
        if stmt.i_orig_module.keyword == "submodule":
            source = stmt.i_orig_module.arg
        else:
            source = self.rootpkg[self.rootpkg.rfind('.') + 1:]

        # If augment, add target module to augmented_modules dict
        if stmt.keyword == 'augment':
            if not hasattr(stmt, "i_target_node"):
                warn_msg = 'Target missing from augment statement'
                print_warning(warn_msg, warn_msg, self.ctx)
            else:
                target = stmt.i_target_node
                target_module = get_module(target)
                augmented_modules[target_module.arg] = target_module
            return  # XXX: Do not generate a class for the augment statement

        package_generated = False

        for ch in search(stmt, list(yangelement_stmts)):
            path_value = self.path+'/'+camelize(stmt_arg)
            package_value = self.package+'.'+camelize(stmt_arg)
            mopackage_value = self.mopackage+'.'+camelize(stmt_arg)
            child_generator = ClassGenerator(ch, path=path_value, package=package_value, mopackage=mopackage_value, parent=self)
            child_generator.generate()

        self.java_class = JavaClass(filename=self.filename,
                package=self.package,
                description=''.join(['This class represents an element from ',
                                     '\n * the namespace ', self.ns,
                                     '\n * generated to "',
                                     self.path, OSSep, stmt.arg,
                                     '"\n * <p>\n * See line ',
                                     str(stmt.pos.line), ' in\n * ',
                                     stmt.pos.ref]),
                source=source)

        if self.ctx.opts.debug or self.ctx.opts.verbose:
            if package_generated:
                print('pkg ' + '.'.join([self.package, self.n2]) + ' generated')
            if self.ctx.opts.verbose:
                print('Generating "' + self.filename + '"...')

        key_arg, value = self.get_stmt_key(stmt)

        indent =  ' ' * 4
        body_indent = ' ' * 6

        parent_keyname_list = []

        packages = get_parents(stmt)
        while packages:
            parent_stmt = packages.popleft()
            parent_name = camelize(parent_stmt.arg)
            parent_key, parent_keyclass = self.get_parent_stmt_key(parent_stmt, parent_name)
            parent_keyname_list.append(parent_key)

        parent_para= ', '.join(parent_keyname_list)

        getall_body=[indent + "def get" + normalize(self.n2) + "List("]
        if parent_para:
            getall_body.append(body_indent+parent_para+',')
        getall_body.append(body_indent + "apiCtx: ApiContext)(implicit ec: ExecutionContext): Future[Seq[" +
                                        normalize(self.n2) + "]]")
        getall_field = JavaValue(getall_body)
        self.java_class.add_field(getall_field)

        getsize_body=[indent + "def get" + normalize(self.n2) + "Count("]
        if parent_para:
            getsize_body.append(body_indent+parent_para+',')
        getsize_body.append(body_indent + "apiCtx: ApiContext)(implicit ec: ExecutionContext): Future[Long]")
        getsize_field = JavaValue(getsize_body)
        self.java_class.add_field(getsize_field)

        if len(key_arg.split(',')) > 1:
            key_name = "Key"
        else:
            key_name = normalize(key_arg)
        get_body=[indent + "def get" + normalize(self.n2) + "ById("]
        if parent_para:
            get_body.append(body_indent+parent_para+',')
        get_body.append(body_indent + value + ",")
        get_body.append(body_indent + "apiCtx: ApiContext)(implicit ec: ExecutionContext): Future[Option[" +
                                     normalize(self.n2) + "]]")
        get_field = JavaValue(get_body)
        self.java_class.add_field(get_field)

        create_body = [indent + "def create" + normalize(self.n2) + "("]
        if parent_para:
            create_body.append(body_indent+parent_para+',')
        create_body.append(body_indent + self.n2 + ": " + normalize(self.n2) + ",")
        create_body.append(body_indent + "apiCtx: ApiContext)(implicit ec: ExecutionContext): Future[" +
                                     normalize(self.n2) + "]")
        create_field = JavaValue(create_body)
        self.java_class.add_field(create_field)

        update_body = [indent + "def update" + normalize(self.n2) + "("]
        if parent_para:
            update_body.append(body_indent+parent_para+',')
        update_body.append(body_indent + self.n2 + ": " + normalize(self.n2) + ",")
        update_body.append(body_indent + "apiCtx: ApiContext)(implicit ec: ExecutionContext): Future[Option[" +
                                     normalize(self.n2) + "]]")
        update_field = JavaValue(update_body)
        self.java_class.add_field(update_field)

        delete_body = [indent + "def delete" + normalize(self.n2) + "("]
        if parent_para:
            delete_body.append(body_indent+parent_para+',')
        delete_body.append(body_indent + value + ",")
        delete_body.append(body_indent + "apiCtx: ApiContext)(implicit ec: ExecutionContext): Future[Boolean]")
        delete_field = JavaValue(delete_body)
        self.java_class.add_field(delete_field)

        self.java_class.imports.add('net.juniper.easyrest.ctx.ApiContext')
        self.java_class.imports.add(self.mopackage +  '.' + normalize(self.n2))
        self.java_class.imports.add('scala.concurrent.{ExecutionContext, Future}')

        self.write_to_file()

    def generate_rpc_class(self, stmt, rpc_class, mopackage):
        rpc_name = normalize(stmt.arg.replace("_","-"))
        add = rpc_class.append_access_method
        if self.ctx.opts.debug or self.ctx.opts.verbose:
            print('Generating "' + rpc_name+"Rpc" + '"...')

        indent =  ' ' * 4
        input_para = False
        output_para = False
        for sub in stmt.substmts:
            if sub.keyword == "input":
                input_para = True
            elif sub.keyword == "output":
                output_para = True

        if input_para:
            rpc_input = "(input: " + rpc_name + "Input, apiCtx: ApiContext)"
            rpc_class.imports.add(mopackage+"."+rpc_name+"Input")
        else:
            rpc_input = "(apiCtx: ApiContext)"

        if output_para:
            rpc_output = "Future[" + rpc_name + "Output"+"]"
            rpc_class.imports.add(mopackage+"."+rpc_name+"Output")
        else:
            rpc_output = "Future[Unit]"

        rpc_method = JavaValue(exact=[indent + "def " + camelize(rpc_name) + "Rpc"+rpc_input + "(implicit ec: ExecutionContext): " + rpc_output])

        add("rpc", rpc_method)

        # Generate RPC API class
        rpc_class.imports.add('net.juniper.easyrest.ctx.ApiContext')
        rpc_class.imports.add('scala.concurrent.{ExecutionContext, Future}')

    def generate_schema_routes(self, stmt):
        add = self.schema_class.append_access_method  # XXX: add is a function

        if stmt.keyword == "container":
            return
        module_name = get_module(stmt).arg
        class_name = normalize(stmt.arg)

        package_name = get_package(stmt, self.ctx)
        api_package_name = get_api_package(stmt, self.ctx)

        file_indent = ' ' * 4
        indent = ' ' * 6
        body_indent = ' ' * 8

        if api_package_name != self.package:
            self.java_class.imports.add(api_package_name+'.'+class_name+"Api")

        key_arg, value = self.get_stmt_key_route(stmt)

        if (len(key_arg.split(","))>1):
            key_name = "Key"
        else:
            key_name = normalize(key_arg)

        packages = get_parents(stmt)
        parent_para = ""
        parent_keyname_list = []
        parent_paralist = []
        while packages:
            parent_stmt = packages.popleft()
            parent_name = camelize(parent_stmt.arg)
            parent_para = parent_para + '/ "'+module_name.lower()+":"+parent_stmt.arg+'=" ~ Rest'
            parent_key_list, parent_para_list = self.get_parent_stmt_key_route(parent_stmt, parent_name)
            parent_keyname_list.append(parent_key_list)
            parent_paralist.append(parent_para_list)

        exact = []
        if parent_para:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_API_PREFIX '+ parent_para+' / "'+module_name.lower()+":"+stmt.arg.lower()+'") {'
        else:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_API_PREFIX / "'+ module_name.lower()+":"+stmt.arg.lower()+'") {'
        exact.append(content)


        exact.append(body_indent + '  authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '    authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "      intercept(apiCtx) {")
        exact.append(body_indent + "        respondWithMediaType(YangMediaType.YangApiMediaType) {")
        exact.append(body_indent + "          onComplete(OnCompleteFutureMagnet[Option[String]] {")
        exact.append(body_indent + '            schemaReadFunctionApiImpl.getschemaElements("'+stmt.arg.lower()+'", namespace)')
        exact.append(body_indent + "          }) {")
        exact.append(body_indent + "            case Success(result) => complete(result)")
        exact.append(body_indent + "            case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "  }")
        exact.append(body_indent + "} ~")


        self.schema_class.imports.add("com.typesafe.scalalogging.LazyLogging")
        self.schema_class.imports.add("net.juniper.easyrest.auth.EasyRestAuthenticator")
        self.schema_class.imports.add("net.juniper.easyrest.mimetype.YangMediaType")
        self.schema_class.imports.add("net.juniper.easyrest.rest.EasyRestRoutingDSL")
        self.schema_class.imports.add(package_name + '.' + class_name)
        self.schema_class.imports.add("spray.http._")
        self.schema_class.imports.add("spray.routing.HttpService")
        self.schema_class.imports.add("spray.routing.directives.{OnCompleteFutureMagnet, RefFactoryMagnet}")
        self.schema_class.imports.add("scala.util.{Failure, Success}")

        self.schema_body.extend(exact)


    def generate_routes(self, stmt):
        add = self.java_class.append_access_method  # XXX: add is a function
        stmt_arg = stmt.arg.replace("_", "-")

        if stmt.keyword == "container":
            return
        module_name = get_module(stmt).arg

        package_name = get_package(stmt, self.ctx)
        api_package_name = get_api_package(stmt, self.ctx)
        full_name = package_name+"."+normalize(stmt_arg)
        full_api_name = api_package_name+"."+ normalize(stmt_arg)+"Api"

        packages = get_parents(stmt)
        parent_name = ""
        while packages:
            parent_stmt = packages.popleft()
            parent_name = parent_name+normalize(parent_stmt.arg)

        class_name = parent_name + normalize(stmt_arg)
        api_impl_name = camelize(class_name)+"ApiImpl"
        lower_name = camelize(stmt_arg)
        object_name = normalize(stmt_arg)

        file_indent = ' ' * 4
        indent = ' ' * 6
        body_indent = ' ' * 8


        marshell = [file_indent + 'implicit object '+class_name+'UnMarshaller extends FromRequestUnmarshaller['+full_name+'] {']
        marshell.append(file_indent + '  override def apply(req: HttpRequest): Deserialized['+full_name +
                       '] = Right((new YangJsonParser()).parse("' + stmt_arg + '", req.entity.asString(HttpCharsets.`UTF-8`), prefixs).asInstanceOf[' +
                        full_name + '])')
        marshell.append(file_indent + '}')
        marsheller = JavaValue(marshell)

        api = [file_indent + 'lazy val '+api_impl_name+' = ApiImplRegistry.getImplementation(classOf['+full_api_name+'], classOf['+full_name+'])']
        apiimpl = JavaValue(api)

        key_arg, value = self.get_stmt_key_route(stmt)

        if (len(key_arg.split(","))>1):
            key_name = "Key"
        else:
            key_name = normalize(key_arg)

        packages = get_parents(stmt)
        parent_para = ""
        parent_keyname_list = []
        parent_paralist = []
        while packages:
            parent_stmt = packages.popleft()
            parent_name = camelize(parent_stmt.arg)
            parent_para = parent_para + '/ "'+module_name.lower()+":"+parent_stmt.arg+'=" ~ Rest'
            parent_key_list, parent_para_list = self.get_parent_stmt_key_route(parent_stmt, parent_name)
            parent_keyname_list.append(parent_key_list)
            parent_paralist.append(parent_para_list)

        parent_key_name = ', '.join(parent_keyname_list)
        parent_para_instance = ', '.join(parent_paralist)

        exact = [indent + "get {"]
        if parent_para:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX '+ parent_para+' / "'+module_name.lower()+":"+stmt_arg.lower()+'") {'
        else:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX / "'+ module_name.lower()+":"+stmt_arg.lower()+'") {'
        exact.append(content)

        if parent_para:
            exact.append(body_indent + '('+parent_key_name+') =>')
        exact.append(body_indent + '  authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '    authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "      intercept(apiCtx) {")
        exact.append(body_indent + "        respondWithMediaType(YangMediaType.YangDataMediaType) {")
        exact.append(body_indent + "          onComplete(OnCompleteFutureMagnet[Seq["+full_name+"]] {")
        if parent_para:
            exact.append(body_indent + "            "+api_impl_name+".get"+object_name+"List(" + parent_para_instance +", apiCtx)")
        else:
            exact.append(body_indent + "            "+api_impl_name+".get"+object_name+"List(apiCtx)")
        exact.append(body_indent + "          }) {")
        exact.append(body_indent + "            case Success(result) => complete(JsonUtil.elementSeqToJson(result, classOf["+full_name+"]))")
        exact.append(body_indent + "            case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "  }")
        exact.append(body_indent + "} ~")

        if parent_para:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX '+ parent_para+' / "'+module_name.lower()+":"+stmt_arg.lower()+'" / "_total") {'
        else:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX / "'+ module_name.lower()+":"+stmt_arg.lower()+'" / "_total") {'
        exact.append(content)

        if parent_para:
            exact.append(body_indent + '('+parent_key_name+') =>')

        exact.append(body_indent + '  authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '    authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "      intercept(apiCtx) {")
        exact.append(body_indent + "        respondWithMediaType(YangMediaType.YangDataMediaType) {")
        exact.append(body_indent + "          onComplete(OnCompleteFutureMagnet[Long] {")
        if parent_para:
            exact.append(body_indent + "            "+api_impl_name+".get"+object_name+"Count(" + parent_para_instance +", apiCtx)")
        else:
            exact.append(body_indent + "            "+api_impl_name+".get"+object_name+"Count(apiCtx)")
        exact.append(body_indent + "          }) {")
        exact.append(body_indent + "            case Success(result) => complete(\"{\\\"total\\\":\" + result.toString + \"}\")")
        exact.append(body_indent + "            case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "  }")
        exact.append(body_indent + "} ~")

        if parent_para:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX '+ parent_para+' / "'+module_name.lower()+":"+stmt_arg.lower()+'=" ~ Rest) {'
        else:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX / "'+ module_name.lower()+":"+stmt_arg.lower()+'=" ~ Rest) {'
        exact.append(content)

        if (len(key_arg.split(","))>1):
            keys = "keys"
        else:
            keys = key_arg

        if parent_para:
            exact.append(body_indent + '  (' +parent_key_name + ', '+keys+ ') =>')
        else:
            exact.append(body_indent + '  (' + keys+ ') =>')

        if (len(key_arg.split(","))>1):
            exact.append(body_indent + '    val pair = keys.split(",")')

        exact.append(body_indent + '    authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '      authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "        intercept(apiCtx) {")
        exact.append(body_indent + "          respondWithMediaType(YangMediaType.YangDataMediaType) {")
        exact.append(body_indent + "            onComplete(OnCompleteFutureMagnet[Option["+full_name+"]] {")


        if parent_para:
            exact.append(body_indent + "              "+api_impl_name+".get"+object_name+ "ById("+parent_para_instance+", " + value + ", apiCtx)")
        else:
            exact.append(body_indent + "              "+api_impl_name+".get"+object_name+ "ById("+ value + ", apiCtx)")
        exact.append(body_indent + "            }) {")
        exact.append(body_indent + "              case Success(result) => {")
        exact.append(body_indent + "               result match {")
        exact.append(body_indent + "                case Some(result) => complete(result.toJson(true))")
        exact.append(body_indent + "                case None => respondWithStatus(StatusCodes.NotFound) {")
        exact.append(body_indent + '                 complete("No '+ object_name + ' object was found for id " + '+ keys +')')
        exact.append(body_indent + "                }")
        exact.append(body_indent + "               }")
        exact.append(body_indent + "              }")
        exact.append(body_indent + "              case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "            }")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "}")
        exact.append(indent + "} ~")

        exact.append(indent + "post {")

        if parent_para:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX'+ parent_para+' / "'+module_name.lower()+":"+stmt_arg.lower()+'") {'
        else:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX / "'+ module_name.lower()+":"+stmt_arg.lower()+'") {'
        exact.append(content)

        if parent_para:
            exact.append(body_indent + '('+parent_key_name+') =>')
        exact.append(body_indent + '  authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '    authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "      intercept(apiCtx) {")
        exact.append(body_indent + "        respondWithMediaType(YangMediaType.YangDataMediaType) {")
        exact.append(body_indent + "          entity(as["+full_name+"]) {" + lower_name +" =>")
        exact.append(body_indent + "            onComplete(OnCompleteFutureMagnet["+full_name+"] {")
        if parent_para:
            exact.append(body_indent + "              "+api_impl_name+".create"+object_name+"(" + parent_para_instance + ', '+lower_name + ", apiCtx)")
        else:
            exact.append(body_indent + "              "+api_impl_name+".create"+object_name+"(" + lower_name + ", apiCtx)")

        exact.append(body_indent + "            }) {")
        exact.append(body_indent + "              case Success(result) => complete(result.toJson(true))")
        exact.append(body_indent + "              case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "            }")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "  }")
        exact.append(body_indent + "}")
        exact.append(indent + "} ~")

        exact.append(indent + "put {")

        if parent_para:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX '+ parent_para+' / "'+module_name.lower()+":"+stmt_arg.lower()+'") {'
        else:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX / "'+ module_name.lower()+":"+stmt_arg.lower()+'") {'
        exact.append(content)
        if parent_para:
            exact.append(body_indent + '('+parent_key_name+') =>')
        exact.append(body_indent + '  authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '    authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "      intercept(apiCtx) {")
        exact.append(body_indent + "        respondWithMediaType(YangMediaType.YangDataMediaType) {")
        exact.append(body_indent + "          entity(as["+full_name+"]) {" + lower_name +" =>")
        exact.append(body_indent + "            onComplete(OnCompleteFutureMagnet[Option["+full_name+"]] {")
        if parent_para:
            exact.append(body_indent + "              "+api_impl_name+".update"+object_name+"(" + parent_para_instance + ', '+lower_name + ", apiCtx)")
        else:
            exact.append(body_indent + "              "+api_impl_name+".update"+object_name+"(" + lower_name + ", apiCtx)")
        exact.append(body_indent + "            }) {")
        exact.append(body_indent + "              case Success(result) => {")
        exact.append(body_indent + "               result match {")
        exact.append(body_indent + "                case Some(result) => complete(result.toJson(true))")
        exact.append(body_indent + "                case None => respondWithStatus(StatusCodes.NotFound) {")
        exact.append(body_indent + '                 complete("No '+ object_name + ' object was found to update")')
        exact.append(body_indent + "                }")
        exact.append(body_indent + "               }")
        exact.append(body_indent + "              }")
        exact.append(body_indent + "              case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "            }")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "  }")
        exact.append(body_indent + "}")
        exact.append(indent + "} ~")
        exact.append(indent + "delete {")

        if parent_para:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX'+ parent_para+' / "'+module_name.lower()+":"+stmt_arg.lower()+'=" ~ Rest) {'
        else:
            content = body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX / "'+ module_name.lower()+":"+stmt_arg.lower()+'=" ~ Rest) {'
        exact.append(content)

        if (len(key_arg.split(","))>1):
            keys = "keys"
        else:
            keys = key_arg

        if parent_para:
            exact.append(body_indent + '  (' +parent_key_name + ', '+keys+ ') =>')
        else:
            exact.append(body_indent + '  (' + keys+ ') =>')

        if (len(key_arg.split(","))>1):
            exact.append(body_indent + '    val pair = keys.split(",")')

        exact.append(body_indent + '    authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '      authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "        intercept(apiCtx) {")
        exact.append(body_indent + "          respondWithMediaType(YangMediaType.YangDataMediaType) {")
        exact.append(body_indent + "            onComplete(OnCompleteFutureMagnet[Boolean] {")

        if parent_para:
            exact.append(body_indent + "              "+api_impl_name+".delete"+object_name+"(" + parent_para_instance+", " + value + ", apiCtx)")
        else:
            exact.append(body_indent + "              "+api_impl_name+".delete"+object_name+ "("+ value + ", apiCtx)")

        exact.append(body_indent + "            }) {")
        exact.append(body_indent + "              case Success(result) => {")
        exact.append(body_indent + "               if(result.booleanValue) {")
        exact.append(body_indent + '                 complete(\"{\\"id\\": \\"\" + ' + keys + ' + \"\\"}\")')
        exact.append(body_indent + "               }")
        exact.append(body_indent + "               else {")
        exact.append(body_indent + "                 respondWithStatus(StatusCodes.NotFound) {")
        exact.append(body_indent + '                   complete("No '+ object_name + ' object was found for id " + '+ keys +')')
        exact.append(body_indent + "                 }")
        exact.append(body_indent + "               }")
        exact.append(body_indent + "              }")
        exact.append(body_indent + "              case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "            }")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "}")
        exact.append(indent + "} ~")

        add('marsheller', marsheller)
        add('apiimpl', apiimpl)

        self.java_class.imports.add("com.typesafe.scalalogging.LazyLogging")
        self.java_class.imports.add("net.juniper.easyrest.auth.EasyRestAuthenticator")
        self.java_class.imports.add("net.juniper.easyrest.core.ApiImplRegistry")
        self.java_class.imports.add("net.juniper.easyrest.mimetype.YangMediaType")
        self.java_class.imports.add("net.juniper.easyrest.rest.EasyRestRoutingDSL")

        self.java_class.imports.add("spray.http._")
        self.java_class.imports.add("spray.httpx.unmarshalling.{Deserialized, FromRequestUnmarshaller}")
        self.java_class.imports.add("spray.routing.HttpService")
        self.java_class.imports.add("spray.routing.directives.{OnCompleteFutureMagnet, RefFactoryMagnet}")
        self.java_class.imports.add("scala.util.{Failure, Success}")
        self.java_class.imports.add("com.tailf.jnc.YangJsonParser")

        self.body.extend(exact)

        for ch in search(stmt, list(yangelement_stmts)):
            if search_one(ch, ('csp-common', 'vertex')) or search_one(ch, ('csp-common', 'edge')):
                self.generate_routes(ch)

    def get_stmt_key(self, stmt):
        is_config_value = is_config(stmt)
        keys = []
        if is_config_value:
            key = search_one(stmt, 'key')
            try:
                keys = key.arg.split(' ')
            except AttributeError:
                print_warning(msg='Unknown attribute: ' + key, key=key)  # is_config produced wrong value

        findkey = lambda k: search_one(stmt, 'leaf', arg=k)
        key_stmts = [findkey(k) for k in keys]

        key_arg = []
        para = []
        for key in key_stmts:
            key_arg.append(camelize(key.arg))
            key_type = search_one(key, 'type')
            jnc, primitive = get_types(key_type, self.ctx)
            self.java_class.imports.add(jnc)
            key_class = jnc[jnc.rfind('.')+1:]
            para.append(camelize(key.arg)+": "+key_class)

        return ', '.join(key_arg), ', '.join(para)

    def get_stmt_key_route(self, stmt):
        is_config_value = is_config(stmt)
        keys = []
        if is_config_value:
            key = search_one(stmt, 'key')
            try:
                keys = key.arg.split(' ')
            except AttributeError:
                print_warning(msg='Unknown attribute: ' + key, key=key)  # is_config produced wrong value

        findkey = lambda k: search_one(stmt, 'leaf', arg=k)
        key_stmts = [findkey(k) for k in keys]

        key_arg = []
        para = []
        i = 0

        if len(key_stmts) > 1:
            for key in key_stmts:
                key_arg.append(camelize(key.arg))
                key_type = search_one(key, 'type')
                jnc, primitive = get_types(key_type, self.ctx)
                self.java_class.imports.add(jnc)
                key_class = jnc[jnc.rfind('.')+1:]
                para.append("new "+ key_class+"(pair("+str(i)+"))")
                i = i+1
        else:
            key_stmt = key_stmts[0]
            key_arg.append(camelize(key_stmt.arg))
            key_type = search_one(key_stmt, 'type')
            jnc, primitive = get_types(key_type, self.ctx)
            self.java_class.imports.add(jnc)
            key_class = jnc[jnc.rfind('.')+1:]
            para.append("new "+ key_class+"("+camelize(key_stmt.arg)+")")

        return ', '.join(key_arg), ', '.join(para)

    def get_parent_stmt_key(self, stmt, parent_name):
        is_config_value = is_config(stmt)
        keys = []
        if is_config_value:
            key = search_one(stmt, 'key')
            try:
                keys = key.arg.split(' ')
            except AttributeError:
                print_warning(msg='Unknown attribute: ' + key, key=key)  # is_config produced wrong value

        findkey = lambda k: search_one(stmt, 'leaf', arg=k)
        key_stmts = [findkey(k) for k in keys]

        key_arg = []
        para = []

        for key in key_stmts:
            key_type = search_one(key, 'type')
            jnc, primitive = get_types(key_type, self.ctx)
            self.java_class.imports.add(jnc)
            key_class = jnc[jnc.rfind('.')+1:]
            para.append("new "+ key_class+"("+parent_name+normalize(key.arg)+")")
            key_arg.append(parent_name+normalize(key.arg)+ ": " + key_class)

        return ', '.join(key_arg), ', '.join(para)

    def get_parent_stmt_key_route(self, stmt, parent_name):
        is_config_value = is_config(stmt)
        keys = []
        if is_config_value:
            key = search_one(stmt, 'key')
            try:
                keys = key.arg.split(' ')
            except AttributeError:
                print_warning(msg='Unknown attribute: ' + key, key=key)  # is_config produced wrong value

        findkey = lambda k: search_one(stmt, 'leaf', arg=k)
        key_stmts = [findkey(k) for k in keys]

        key_arg = []
        para = []

        for key in key_stmts:
            key_type = search_one(key, 'type')
            jnc, primitive = get_types(key_type, self.ctx)
            self.java_class.imports.add(jnc)
            key_class = jnc[jnc.rfind('.')+1:]
            para.append("new "+ key_class+"("+parent_name+normalize(key.arg)+")")
            key_arg.append(parent_name+normalize(key.arg))

        return ', '.join(key_arg), ', '.join(para)

    def generate_rpc_routes(self, stmt):
        add = self.java_class.append_access_method  # XXX: add is a function

        if stmt.i_orig_module.keyword == "submodule":
            module_name = stmt.i_orig_module.arg
        else:
            module_name = get_module(stmt).arg

        input_para = False
        output_para = False

        package_name = get_package(stmt, self.ctx)

        rpc_class_name = normalize(stmt.arg)
        rpc_method_name = camelize(stmt.arg)

        for sub in stmt.substmts:
            if sub.keyword == "input":
                input_para = True
                self.java_class.imports.add(package_name+'.'+rpc_class_name+"Input")
                marshell = [' ' * 4 + 'implicit object '+rpc_class_name+'InputUnMarshaller extends FromRequestUnmarshaller['+rpc_class_name+'Input] {']
                marshell.append(' ' * 4 + '  override def apply(req: HttpRequest): Deserialized['+rpc_class_name+'Input' +
                       '] = Right((new YangJsonParser()).parse("' + stmt.arg + '-input", req.entity.asString(HttpCharsets.`UTF-8`), prefixs).asInstanceOf[' +
                        rpc_class_name+'Input])')
                marshell.append(' ' * 4 + '}')
                marsheller = JavaValue(marshell)
                add('marsheller', marsheller)
            elif sub.keyword == "output":
                output_para = True
                self.java_class.imports.add(package_name+'.'+rpc_class_name+"Output")
                marshell = [' ' * 4 + 'implicit object '+rpc_class_name+'OutputUnMarshaller extends FromRequestUnmarshaller['+rpc_class_name+'Output] {']
                marshell.append(' ' * 4 + '  override def apply(req: HttpRequest): Deserialized['+rpc_class_name+'Output' +
                       '] = Right((new YangJsonParser()).parse("' + stmt.arg + '-output", req.entity.asString(HttpCharsets.`UTF-8`), prefixs).asInstanceOf[' +
                        rpc_class_name+'Output])')
                marshell.append(' ' * 4 + '}')
                marsheller = JavaValue(marshell)
                add('marsheller', marsheller)

        indent = ' ' * 6
        body_indent = ' ' * 8

        exact = [indent + "post {"]
        exact.append(body_indent + 'path(ROUTING_PREFIX / ROUTING_DATA_PREFIX / "'+get_module(stmt).arg.lower()+':rpc" / "'+stmt.arg.lower()+'") {')
        exact.append(body_indent + '  authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '    authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "      intercept(apiCtx) {")
        exact.append(body_indent + "        respondWithMediaType(YangMediaType.YangDataMediaType) {")

        if input_para:
            exact.append(body_indent + "          entity(as["+rpc_class_name+"Input]) {input =>")

        if output_para:
            exact.append(body_indent + "            onComplete(OnCompleteFutureMagnet["+rpc_class_name+"Output] {")
        else:
            exact.append(body_indent + "            onComplete(OnCompleteFutureMagnet[Unit] {")

        if input_para:
            exact.append(body_indent + "              "+camelize(module_name)+"RpcApiImpl."+rpc_method_name+"Rpc(input, apiCtx)")
        else:
            exact.append(body_indent + "              "+camelize(module_name)+"RpcApiImpl."+rpc_method_name+"Rpc(apiCtx)")
            
        exact.append(body_indent + "            }) {")

        if output_para:
            exact.append(body_indent + "              case Success(result) => complete(result.toJson(true))")
        else:
            exact.append(body_indent + '              case Success(result) => complete("")')

        exact.append(body_indent + "              case Failure(ex) => failWith(ex)")
        exact.append(body_indent + "            }")

        if input_para:
            exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "  }")
        exact.append(body_indent + "}")
        exact.append(indent + "} ~")

        self.java_class.imports.add("com.tailf.jnc.{YangJsonParser, Prefix, PrefixMap}")
        self.java_class.imports.add("com.typesafe.scalalogging.LazyLogging")
        self.java_class.imports.add("net.juniper.easyrest.auth.EasyRestAuthenticator")
        self.java_class.imports.add("net.juniper.easyrest.core.ApiImplRegistry")
        self.java_class.imports.add("net.juniper.easyrest.mimetype.YangMediaType")
        self.java_class.imports.add("net.juniper.easyrest.rest.EasyRestRoutingDSL")
        self.java_class.imports.add("spray.http.{HttpCharsets, HttpRequest}")
        self.java_class.imports.add("spray.httpx.unmarshalling.{Deserialized, FromRequestUnmarshaller}")
        self.java_class.imports.add("spray.routing.HttpService")
        self.java_class.imports.add("scala.util.{Failure, Success}")
        self.java_class.imports.add("com.tailf.jnc.YangJsonParser")
        self.java_class.imports.add("spray.routing.directives.{OnCompleteFutureMagnet, RefFactoryMagnet}")

        self.body.extend(exact)

    def generate_notification_routes(self, stmt):
        add = self.java_class.append_access_method  # XXX: add is a function

        streamregistry = [' ' * 4 + 'StreamRegistry.registerStream(']
        streamregistry.append(' ' * 6 + 'StreamBuilder()')
        streamregistry.append(' ' * 8 + '.name("'+stmt.arg+'")')
        for sub in stmt.substmts:
            if sub.keyword == 'description':
                streamregistry.append(' ' * 8 + '.description("'+sub.arg+'")')
        streamregistry.append(' ' * 8 + '.replaySupport("false")')
        streamregistry.append(' ' * 8 + '.events("").build()')
        streamregistry.append(' ' * 4 + ')')
        streamregistry_value = JavaValue(streamregistry)

        indent = ' ' * 6
        body_indent = ' ' * 8

        exact = [indent + "get {"]
        exact.append(body_indent + 'path(ROUTING_PREFIX / ROUTING_STREAMS_PREFIX / ROUTING_STREAM_PREFIX / "'+ stmt.arg +'" / ROUTING_EVENTS_PREFIX) {')
        exact.append(body_indent + '  authenticate(EasyRestAuthenticator()) { apiCtx =>')
        exact.append(body_indent + '    authorize(enforce(apiCtx)) {')
        exact.append(body_indent + "      intercept(apiCtx) {")
        exact.append(body_indent + "        compressResponse(Gzip) {")
        exact.append(body_indent + "          sse { (channel, lastEventId, ctx) =>")
        exact.append(body_indent + "            {")
        exact.append(body_indent + '              NotificationSubscriptionManager.addSubscriber(channel, "'+ stmt.arg+'", ctx.request.uri.query.get("stream-filter"))')
        exact.append(body_indent + "            }")
        exact.append(body_indent + "          }")
        exact.append(body_indent + "        }")
        exact.append(body_indent + "      }")
        exact.append(body_indent + "    }")
        exact.append(body_indent + "  }")
        exact.append(body_indent + "}")
        exact.append(indent + "} ~")

        add('streamregistry', streamregistry_value)

        self.java_class.imports.add("com.typesafe.scalalogging.LazyLogging")
        self.java_class.imports.add("net.juniper.easyrest.notification.NotificationSubscriptionManager")
        self.java_class.imports.add("net.juniper.easyrest.rest.EasyRestRoutingDSL")
        self.java_class.imports.add("net.juniper.easyrest.rest.EasyRestServerSideEventDirective._")
        self.java_class.imports.add("net.juniper.easyrest.streams.spray.StreamRegistry")
        self.java_class.imports.add("net.juniper.easyrest.streams.yang.StreamBuilder")
        self.java_class.imports.add("spray.httpx.encoding.Gzip")
        self.java_class.imports.add("spray.routing.HttpService")
        self.java_class.imports.add("spray.routing.directives.{OnCompleteFutureMagnet, RefFactoryMagnet}")
        self.java_class.imports.add("net.juniper.easyrest.auth.EasyRestAuthenticator")

        self.body.extend(exact)

    def write_to_file(self):
        write_file(self.path,
                   self.filename,
                   self.java_class.as_list(),
                   self.ctx)

    def write_rpc_to_file(self, path, rpc_class):
        if self.ctx.opts.debug or self.ctx.opts.verbose:
            print('Generating "' + rpc_class.filename + '"...')

        write_file(path,
            rpc_class.filename,
            rpc_class.as_list(),
            self.ctx)

class JavaClass(object):
    """Encapsulates package name, imports, class declaration, constructors,
    fields, access methods, etc. for a Java Class. Also includes javadoc
    documentation where applicable.

    Implementation: Unless the 'body' attribute is used, different kind of
    methods and fields are stored in separate dictionaries so that the order of
    them in the generated class does not depend on the order in which they were
    added.

    """

    def __init__(self, filename=None, package=None, imports=None,
                 description=None, body=None, version='1.0',
                 superclass=None, interfaces=None, source='<unknown>.yang', implement=False):
        """Constructor.

        filename    -- Should preferably not contain a complete path since it is
                       displayed in a Java comment in the beginning of the code.
        package     -- Should be just the name of the package in which the class
                       will be included.
        imports     -- Should be a list of names of imported libraries.
        description -- Defines the class semantics.
        body        -- Should contain the actual code of the class if it is not
                       supplied through the add-methods
        version     -- Version number, defaults to '1.0'.
        superclass  -- Parent class of this Java class, or None
        interaces   -- List of interfaces implemented by this Java class
        source      -- A string somehow representing the origin of the class

        """
        if imports is None:
            imports = []
        self.filename = filename
        self.package = package if package[:3] != 'src' else package[4:]
        self.imports = OrderedSet()
        for i in range(len(imports)):
            self.imports.add(imports[i])
        self.description = description
        self.body = body
        self.version = version
        self.superclass = superclass
        self.interfaces = interfaces
        if interfaces is None:
            self.interfaces = []
        self.source = source
        self.fields = OrderedSet()
        self.constructors = OrderedSet()
        self.cloners = OrderedSet()
        self.enablers = OrderedSet()
        self.schema_registrators = OrderedSet()
        self.name_getters = OrderedSet()
        self.access_methods = collections.OrderedDict()
        self.support_methods = OrderedSet()
        self.attrs = [self.fields, self.constructors, self.cloners,
                      self.enablers, self.schema_registrators,
                      self.name_getters, self.access_methods,
                      self.support_methods]
        self.implement_class = implement

    def add_field(self, field):
        """Adds a field represented as a string"""
        self.fields.add(field)

    def add_constructor(self, constructor):
        """Adds a constructor represented as a string"""
        self.constructors.add(constructor)

    def add_cloner(self, cloner):
        """Adds a clone method represented as a string"""
        if not isinstance(cloner, str):
            for import_ in cloner.imports:
                self.imports.add(import_)
        self.cloners.add(cloner)

    def add_enabler(self, enabler):
        """Adds an 'enable'-method as a string"""
        self.imports.add('com.tailf.jnc.JNCException')
        self.imports.add('com.tailf.jnc.YangElement')
        self.enablers.add(enabler)

    def add_schema_registrator(self, schema_registrator):
        """Adds a register schema method"""
        self.imports.add('com.tailf.jnc.JNCException')
        self.imports.add('com.tailf.jnc.SchemaParser')
        self.imports.add('com.tailf.jnc.Tagpath')
        self.imports.add('com.tailf.jnc.SchemaNode')
        self.imports.add('com.tailf.jnc.SchemaTree')
        self.imports.add('java.util.HashMap')
        self.schema_registrators.add(schema_registrator)

    def add_name_getter(self, name_getter):
        """Adds a keyNames or childrenNames method represented as a string"""
        self.name_getters.add(name_getter)

    def append_access_method(self, key, access_method):
        """Adds an access method represented as a string"""
        if self.access_methods.get(key) is None:
            self.access_methods[key] = []
        self.access_methods[key].append(access_method)

    def add_support_method(self, support_method):
        """Adds a support method represented as a string"""
        self.support_methods.add(support_method)

    def get_body(self):
        """Returns self.body. If it is None, fields and methods are added to it
        before it is returned."""
        if self.body is None:
             self.body = []
             # if self.superclass is not None or 'Serializable' in self.interfaces:
             #     self.body.extend(JavaValue(
             #         modifiers=['private', 'static', 'final', 'long'],
             #         name='serialVersionUID', value='1L').as_list())
             #     self.body.append('')
             for method in flatten(self.attrs):
                 if hasattr(method, 'as_list'):
                     self.body.extend(method.as_list())
                 else:
                     self.body.append(method)
                 self.body.append('')
             self.body.append('}')
        return self.body

    def get_superclass_and_interfaces(self):
        """Returns a string with extends and implements"""
        res = []
        if self.superclass:
            res.append(' extends ')
            res.append(self.superclass)
        if self.interfaces:
            res.append(' implements ')
            res.append(', '.join(self.interfaces))
        return ''.join(res)

    def as_list(self):
        """Returns a string representing complete Java code for this class.

        It is vital that either self.body contains the complete code body of
        the class being generated, or that it is None and methods have been
        added using the JavaClass.add methods prior to calling this method.
        Otherwise the class will be empty.

        The class name is the filename without the file extension.

        """
        # The header is placed in the beginning of the Java file
        header = [' '.join(['/* \n * @(#)' + self.filename, '      ',
                            self.version, date.today().strftime('%d/%m/%y')])]
        header.append(' *')
        header.append(' * This file has been auto-generated by JRC, the')
        header.append(' * Restconf output format plug-in of pyang.')
        header.append(' * Origin: ' + self.source)
        header.append(' */')

        # package and import statement goes here
        header.append('')
        header.append('package ' + self.package)# + ';')
        if self.body is None:
            for method in flatten(self.attrs):
                if hasattr(method, 'imports'):
                    self.imports |= method.imports
                if hasattr(method, 'exceptions'):
                    self.imports |= ['com.tailf.jnc.' + s for s in method.exceptions]
        if self.superclass:
            self.imports.add(get_import(self.superclass))
        imported_classes = []
        if self.imports:
            prevpkg = ''
            for import_ in self.imports.as_sorted_list():
                pkg, _, cls = import_.rpartition('.')
                #if (cls != self.filename.split('.')[0]
                #        and (pkg != 'com.tailf.jnc' or cls in com_tailf_jnc
                #            or cls == '*')):
                if (pkg != 'com.tailf.jnc' or cls in com_tailf_jnc
                            or cls == '*'):
                    if cls in imported_classes and cls != "_":
                        continue
                    else:
                        imported_classes.append(cls)
                    basepkg = import_[:import_.find('.')]
                    if basepkg != prevpkg:
                        header.append('')
                    header.append('import ' + import_) # + ';')
                    prevpkg = basepkg

        # Class doc-comment and declaration, with modifiers
        header.append('')
        header.append('/**')
        header.append(' * ' + self.description)
        header.append(' *')
        header.append(' '.join([' * @version',
                                self.version,
                                date.today().isoformat()]))
        header.append(' * @author Auto Generated')
        header.append(' */')
        if self.implement_class:
            class_body = 'class '
        else:
            class_body = 'trait '
        header.append(''.join([class_body,
                               self.filename.split('.')[0],
                               self.get_superclass_and_interfaces(),
                               ' {']))
        header.append('')
        return header + self.get_body()


class JavaValue(object):
    """A Java value, typically representing a field or a method in a Java
    class and optionally a javadoc comment.

    A JavaValue can have its attributes set using the optional keyword
    arguments of the constructor, or by using the add and set methods.

    Each instance of this class has an 'as_list' method which is used to get a
    list of strings representing lines of code that can be written to a Java
    file once all the attributes have been set set.

    """

    def __init__(self, exact=None, javadocs=None, modifiers=None, name=None,
                 value=None, imports=None, indent=4):
        """Initializes the attributes of a new Java value.

        Keyword arguments:
        exact (String list)     -- If supplied, the 'as_list' method will
                                   return this list until something has been
                                   added to this Java value.
        javadocs (String list)  -- A list of the lines in the javadoc
                                   declaration for this Java Value.
        modifiers (String list) -- A list of Java modifiers such as 'public'
                                   and 'static'. Also used to specify the type
                                   of fields.
        name (String)           -- The identifier used for this value.
        value (String)          -- Not used by methods, this is placed after
                                   the assignment operator in a field
                                   declaration.
        imports (String list)   -- A (possibly redundant) set of classes to
                                   import in the class declaring this value.
                                   This list is typically filtered by other
                                   classes so nothing gets imported unless it
                                   is required to for the Java class to
                                   compile.
        indent (Integer)        -- The indentation in the 'as_list'
                                   representation. Defaults to 4 spaces.

        """
        self.value = value
        self.indent = ' ' * indent
        self.default_modifiers = True

        self.javadocs = OrderedSet()
        if javadocs is not None:
            for javadoc in javadocs:
                self.add_javadoc(javadoc)

        self.modifiers = []
        if modifiers is not None:
            for modifier in modifiers:
                self.add_modifier(modifier)

        self.name = None
        if name is not None:
            self.set_name(name)

        self.imports = set([])
        if imports is not None:
            for import_ in imports:
                self.imports.add(import_)

        self.exact = exact
        self.default_modifiers = True

    def __eq__(self, other):
        """Returns True iff self and other represents an identical value"""
        for attr, value in vars(self).items():
            try:
                if getattr(other, attr) != value:
                    return False
            except AttributeError:
                return False
        return True

    def __ne__(self, other):
        """Returns True iff self and other represents different values"""
        return not self.__eq__(other)

    def _set_instance_data(self, attr, value):
        """Adds or assigns value to the attr attribute of this Java value.

        attr (String) -- The attribute to add or assign value to. If this Java
                         value does not have an attribute with this name, a
                         warning is printed with the msg "Unknown attribute"
                         followed by the attribute name. The value is added,
                         appended or assigned, depending on if the attribute is
                         a MutableSet, a list or something else, respectively.
        value         -- Typically a String, but can be anything, really.

        The 'exact' cache is invalidated is the attribute exists.

        """
        try:
            data = getattr(self, attr)
            if isinstance(data, list):
                data.append(value)
            elif isinstance(data, collections.MutableSet):
                data.add(value)
            else:
                setattr(self, attr, value)
        except AttributeError:
            print_warning(msg='Unknown attribute: ' + attr, key=attr)
        else:
            self.exact = None  # Invalidate cache

    def set_name(self, name):
        """Sets the identifier of this value"""
        self._set_instance_data('name', name)

    def set_indent(self, indent=4):
        """Sets indentation used in the as_list methods"""
        self._set_instance_data('indent', ' ' * indent)

    def add_modifier(self, modifier):
        """Adds modifier to end of list of modifiers. Overwrites modifiers set
        in constructor the first time it is invoked, to enable subclasses to
        have default modifiers.

        """
        if self.default_modifiers:
            self.modifiers = []
            self.default_modifiers = False
        self._set_instance_data('modifiers', modifier)

    def add_javadoc(self, line):
        """Adds line to javadoc comment, leading ' ', '*' and '/' removed"""
        self._set_instance_data('javadocs', line.lstrip(' */'))

    def add_dependency(self, import_):
        """Adds import_ to list of imports needed for value to compile."""
        _, sep, class_name = import_.rpartition('.')
        if sep:
            if class_name not in java_built_in:
                self.imports.add(import_)
                return class_name
        elif not any(x in java_built_in for x in (import_, import_[:-2])):
            self.imports.add(import_)
        return import_

    def javadoc_as_string(self):
        """Returns a list representing javadoc lines for this value"""
        lines = []
        if self.javadocs:
            lines.append(self.indent + '/**')
            lines.extend([self.indent + ' * ' + line for line in self.javadocs])
            lines.append(self.indent + ' */')
        return lines

    def as_list(self):
        """String list of code lines that this Java value consists of"""
        if self.exact is None:
            assert self.name is not None
            assert self.indent is not None
            self.exact = self.javadoc_as_string()
            declaration = self.modifiers + [self.name]
            if self.value is not None:
                declaration.append('=')
                declaration.append(self.value)
            self.exact.append(''.join([self.indent, ' '.join(declaration), ';']))
        return self.exact


class JavaMethod(JavaValue):
    """A Java method. Default behaviour is public void."""

    def __init__(self, exact=None, javadocs=None, modifiers=None,
                 return_type=None, name=None, params=None, exceptions=None,
                 body=None, indent=4):
        """Initializes the attributes of a new Java method.

        Keyword arguments:
        exact (String list)     -- If supplied, the 'as_list' method will
                                   return this list until something has been
                                   added to this Java value.
        javadocs (String list)  -- A list of the lines in the javadoc
                                   declaration for this Java Value.
        modifiers (String list) -- A list of Java modifiers such as 'public'
                                   and 'static'. Also used to specify the type
                                   of fields.
        return_type (String)    -- The return type of the method. To avoid
                                   adding the type as a required import,
                                   assign to the return_type attribute directly
                                   instead of using this argument.
        name (String)           -- The identifier used for this value.
        params (str tuple list) -- A list of 2-tuples representing the type and
                                   name of the parameters of this method. To
                                   avoid adding the type as a required import,
                                   assign to the parameters attribute directly
                                   instead of using this argument.
        exceptions (str list)   -- A list of exceptions thrown by the method.
        value (String)          -- Not used by methods, this is placed after
                                   the assignment operator in a field
                                   declaration.
        imports (String list)   -- A (possibly redundant) set of classes to
                                   import in the class declaring this value.
                                   This list is typically filtered by other
                                   classes so nothing gets imported unless it
                                   is required to for the Java class to
                                   compile.
        indent (Integer)        -- The indentation in the 'as_list'
                                   representation. Defaults to 4 spaces.

        """
        super(JavaMethod, self).__init__(exact=exact, javadocs=javadocs,
                                         modifiers=modifiers, name=name,
                                         value=None, indent=indent)
        if self.modifiers == []:
            self.add_modifier('public')

        self.return_type = 'void'
        if return_type is not None:
            self.set_return_type(return_type)

        self.parameters = OrderedSet()
        if params is not None:
            for param_type, param_name in params:
                self.add_parameter(param_type, param_name)

        self.exceptions = OrderedSet()
        if exceptions is not None:
            for exc in exceptions:
                self.add_exception(exc)

        self.body = []
        if body is not None:
            for line in body:
                self.add_line(line)

        self.exact = exact
        self.default_modifiers = True

    def set_return_type(self, return_type):
        """Sets the type of the return value of this method"""
        retval = None if not return_type else self.add_dependency(return_type)
        self._set_instance_data('return_type', retval)

    def add_parameter(self, param_type, param_name):
        """Adds a parameter to this method. The argument type is added to list
        of dependencies.

        param_type -- String representation of the argument type
        param_name -- String representation of the argument name
        """
        self._set_instance_data('parameters',
                                ' '.join([self.add_dependency(param_type),
                                          param_name]))

    def add_exception(self, exception):
        """Adds exception to method"""
        self._set_instance_data('exceptions',
                                self.add_dependency(exception))

    def add_line(self, line):
        """Adds line to method body"""
        self._set_instance_data('body', self.indent + ' ' * 4 + line)

    def as_list(self):
        """String list of code lines that this Java method consists of.
        Overrides JavaValue.as_list().

        """
        MAX_COLS = 80
        if self.exact is None:
            assert self.name is not None
            assert self.indent is not None
            self.exact = self.javadoc_as_string()
            header = self.modifiers[:]
            if self.return_type is not None:
                header.append(self.return_type)
            header.append(self.name)
            signature = [self.indent]
            signature.append(' '.join(header))
            signature.append('(')
            signature.append(', '.join(self.parameters))
            signature.append(')')
            if self.exceptions:
                signature.append(' throws ')
                signature.append(', '.join(self.exceptions))
                if sum(len(s) for s in signature) >= MAX_COLS:
                    signature.insert(-2, '\n' + (self.indent * 3)[:-1])
            signature.append(' {')
            self.exact.append(''.join(signature))
            self.exact.extend(self.body)
            self.exact.append(self.indent + '}')
        return self.exact

class OrderedSet(collections.MutableSet):
    """A set of unique items that preserves the insertion order.

    Created by: Raymond Hettinger 2009-03-19
    Edited by: Emil Wall 2012-08-03
    Licence: http://opensource.org/licenses/MIT
    Original source: http://code.activestate.com/recipes/576694/

    An ordered set is implemented as a wrapper class for a dictionary
    implementing a doubly linked list. It also has a pointer to the last item
    in the set (self.end) which is used by the add and _iterate methods to add
    items to the end of the list and to know when an iteration has finished,
    respectively.

    """

    def __init__(self, iterable=None):
        """Creates an ordered set.

        iterable -- A mutable iterable, typically a list or a set, containing
                    initial values of the set. If the default value (None) is
                    used, the set is initialized as empty.

        """
        self.ITEM, self.PREV, self.NEXT = list(range(3))
        self.end = end = []
        end += [None, end, end]         # sentinel node for doubly linked list
        self.map = {}                   # value --> [value, prev, next]
        if iterable is not None:
            self |= iterable

    def __len__(self):
        """Returns the number of items in this set."""
        return len(self.map)

    def __contains__(self, item):
        """Returns true if item is in this set; false otherwise."""
        return item in self.map

    def add(self, item):
        """Adds an item to the end of this set."""
        if item not in self:
            self.map[item] = [item, self.end[self.PREV], self.end]
            self.end[self.PREV][self.NEXT] = self.map[item]
            self.end[self.PREV] = self.map[item]

    def add_first(self, item):
        """Adds an item to the beginning of this set."""
        if item not in self:
            self.map[item] = [item, self.end, self.end[self.NEXT]]
            self.end[self.NEXT][self.PREV] = self.map[item]
            self.end[self.NEXT] = self.map[item]

    def discard(self, item):
        """Finds and discards an item from this set, amortized O(1) time."""
        if item in self:
            item, prev, after = self.map.pop(item)
            prev[self.NEXT] = after
            after[self.PREV] = prev

    def _iterate(self, iter_index):
        """Internal generator method to iterate through this set.

        iter_index -- If 1, the set is iterated in reverse order. If 2, the set
                      is iterated in order of insertion. Else IndexError.

        """
        curr = self.end[iter_index]
        while curr is not self.end:
            yield curr[self.ITEM]
            curr = curr[iter_index]

    def __iter__(self):
        """Returns a generator object for iterating the set in the same order
        as its items were added.

        """
        return self._iterate(self.NEXT)

    def __reversed__(self):
        """Returns a generator object for iterating the set, beginning with the
        most recently added item and ending with the first/oldest item.

        """
        return self._iterate(self.PREV)

    def pop(self, last=True):
        """Discards the first or last item of this set.

        last -- If True the last item is discarded, otherwise the first.

        """
        if not self:
            raise KeyError('set is empty')
        item = next(reversed(self)) if last else next(iter(self))
        self.discard(item)
        return item

    def as_sorted_list(self):
        """Returns a sorted list with the items in this set"""
        res = [x for x in self]
        res.sort()
        return res

    def __repr__(self):
        """Returns a string representing this set. If empty, the string
        returned is 'OrderedSet()', otherwise if the set contains items a, b
        and c: 'OrderedSet([a, b, c])'

        """
        if not self:
            return '%s()' % (self.__class__.__name__,)
        return '%s(%r)' % (self.__class__.__name__, list(self))

    def __eq__(self, other):
        """Returns True if other is an OrderedSet containing the same items as
        other, in the same order.

        """
        return isinstance(other, OrderedSet) and list(self) == list(other)

    def __del__(self):
        """Destructor, clears self to avoid circular reference which could
        otherwise occur due to the doubly linked list.

        """
        self.clear()
