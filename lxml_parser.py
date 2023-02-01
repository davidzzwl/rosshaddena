from lxml.sax import ElementTreeContentHandler
from lxml import etree
from xml.sax import make_parser
from lxml.html import fromstring as fromhtmlstring
from xml.sax.handler import feature_external_pes, feature_external_ges
import collections

ns_loc = 'lxml'

def clean_html(html_soup):
    """Convert the given html tag soup string into a valid xml string."""
    root = fromhtmlstring(html_soup)
    return etree.tostring(root, encoding='unicode')

def lxml_etree_parse_xml_string_with_location(xml_string, line_number_offset, should_stop = None):
    """Parse the specified xml_string in chunks, adding location attributes to the tree it returns. If the should_stop method is provided, stop/interrupt parsing if it returns True."""
    parser = make_parser()
    parser.setFeature(feature_external_pes, False)
    parser.setFeature(feature_external_ges, False)
    global ns_loc
    
    class ETreeContent(ElementTreeContentHandler):
        _locator = None
        _prefix_hierarchy = []
        _last_action = None
        _prefixes_doc_order = []
        
        def setDocumentLocator(self, locator):
            self._locator = locator
        
        def _splitPrefixAndGetNamespaceURI(self, fullName):
            prefix = None
            local_name = None
            
            split_pos = fullName.find(':')
            if split_pos > -1:
                prefix = fullName[0:split_pos]
                local_name = fullName[split_pos + 1:]
            else:
                local_name = fullName
            
            return (prefix, local_name, self._getNamespaceURI(prefix))
        
        def _getNamespaceURI(self, prefix):
            for mappings in reversed(self._prefix_hierarchy):
                if prefix in mappings:
                    return mappings[prefix]
            return None
        
        def _getNamespaceMap(self):
            flattened = {}
            for mappings in self._prefix_hierarchy:
                for prefix in mappings:
                    flattened[prefix] = mappings[prefix]
            return flattened
        
        def _getParsePosition(self):
            locator = self._locator or parser
            return str(locator.getLineNumber() - 1 + line_number_offset) + '/' + str(locator.getColumnNumber())
        
        def startElementNS(self, name, tagName, attrs):
            self._recordEndPosition()
            
            self._last_action = 'open'
            # correct missing element and attribute namespaceURIs, using known prefixes and new prefixes declared with this element
            self._prefix_hierarchy.append({})
            
            nsmap = []
            attrmap = []
            for attr_name, attr_value in attrs.items():
                if attr_name[0] is None: # if there is no namespace URI associated with the attribute already
                    if attr_name[1].startswith('xmlns:'): # map the prefix to the namespace URI
                        nsmap.append((attr_name, attr_name[1][len('xmlns:'):], attr_value))
                    elif attr_name[1] == 'xmlns': # map the default namespace URI
                        nsmap.append((attr_name, None, attr_value))
                    elif ':' in attr_name[1]: # separate the prefix from the local name
                        attrmap.append((attr_name, self._splitPrefixAndGetNamespaceURI(attr_name[1]), attr_value))
            
            for ns in nsmap:
                attrs.pop(ns[0]) # remove the xmlns attribute
                self.startPrefixMapping(ns[1], ns[2]) # map the prefix to the URI
            
            for attr in attrmap:
                attrs.pop(attr[0]) # remove the attribute
                attrs[(attr[1][2], attr[1][1])] = attr[2] # re-add the attribute with the correct qualified name
            
            tag = self._splitPrefixAndGetNamespaceURI(tagName)
            name = (tag[2], tag[1])
            
            self._new_mappings = self._getNamespaceMap()
            super().startElementNS(name, tagName, attrs)
            
            current = self._element_stack[-1]
            self._recordPosition(current, 'open_tag_start_pos')
            
        def startPrefixMapping(self, prefix, uri):
            self._prefix_hierarchy[-1][prefix] = uri
            if prefix is None:
                self._default_ns = uri
            # record all used unique namespace uri and prefix combinations used in document, to avoid any need to look them all up again later
            if (prefix, uri) not in self._prefixes_doc_order:
                self._prefixes_doc_order.append((prefix, uri))
        
        def endPrefixMapping(self, prefix):
            self._prefix_hierarchy[-1].pop(prefix)
            if prefix is None:
                self._default_ns = self._getNamespaceURI(None)
        
        def endElementNS(self, name, tagName):
            self._recordEndPosition()
            
            self._last_action = 'close'
            
            current = self._element_stack[-1]
            self._recordPosition(current, 'close_tag_start_pos')
            
            tag = self._splitPrefixAndGetNamespaceURI(tagName)
            name = (tag[2], tag[1])
            super().endElementNS(name, tagName)
            if None in self._prefix_hierarchy[-1]: # re-map default namespace if applicable
                self.endPrefixMapping(None)
            self._prefix_hierarchy.pop()
        
        def _recordPosition(self, node, position_name, position = None):
            position_name = '{' + ns_loc + '}' + position_name
            if position is not None or position_name not in node.attrib.keys():
                node.set(position_name, position or self._getParsePosition())
        
        def _recordEndPosition(self):
            if len(self._element_stack) > 0:
                current = self._element_stack[-1]
                if len(current) == 0: # current element has no children
                    if current.text is None:
                        self._recordPosition(current, 'open_tag_end_pos')
                else: # current element has children
                    if len(current) > 0: # current element has children
                        last_child = current[-1] # get the last child
                        if last_child.tail is None and self._last_action is not None:
                            self._recordPosition(last_child, self._last_action + '_tag_end_pos')
                            if self._last_action == 'close' and last_child.get('{' + ns_loc + '}close_tag_end_pos') == last_child.get('{' + ns_loc + '}open_tag_end_pos'): # self-closing tag, update the start position of the "close tag" to the start position of the open tag
                                self._recordPosition(last_child, 'close_tag_start_pos', last_child.get('{' + ns_loc + '}open_tag_start_pos'))
        
        def characters(self, data):
            self._recordEndPosition()
            super().characters(data)
        
        def processingInstruction(self, target, data):
            pass # ignore processing instructions
        
        def endDocument(self):
            self._recordPosition(self.etree.getroot(), 'close_tag_end_pos')
    
    createETree = ETreeContent()
    
    parser.setContentHandler(createETree)
    
    for chunk in chunks(xml_string, 1024 * 8): # read in 8 KiB chunks
        if should_stop is not None:
            if should_stop():
                break
        parser.feed(chunk)
    
    parser.close()
    return (createETree.etree, createETree._prefixes_doc_order)

def chunks(entire, chunk_size): # http://stackoverflow.com/a/18854817/4473405
    """Return a generator that will split the input into chunks of the specified size."""
    return (entire[i : chunk_size + i] for i in range(0, len(entire), chunk_size))

# TODO: consider subclassing etree.ElementBase and adding as methods to that
def getSpecificNodePosition(node, position_name):
    """Given a node and a position name, return the row and column that relates to the node's position."""
    global ns_loc
    row, col = node.get('{' + ns_loc + '}' + position_name).split('/')
    return (int(row), int(col))

def getNodeTagRange(node, position_type):
    """Given a node and position type (open or close), return the rows and columns that relate to the node's position."""
    begin = getSpecificNodePosition(node, position_type + '_tag_start_pos')
    end = getSpecificNodePosition(node, position_type + '_tag_end_pos')
    return (begin, end)

def getRelativeNode(relative_to, direction):
    """Given a node and a direction, return the node that is relative to it in the specified direction, or None if there isn't one."""
    def return_specific(node):
        yield node
    generator = None
    if direction == 'next':
        generator = relative_to.itersiblings()
    elif direction in ('prev', 'previous'):
        generator = relative_to.itersiblings(preceding = True)
    elif direction in ('open', 'close', 'names', 'entire', 'content'):
        generator = return_specific(relative_to) # return self
    elif direction == 'parent':
        generator = return_specific(relative_to.getparent())
    
    if generator is None:
        raise ValueError('Unknown direction "' + direction + '"')
    else:
        return next(generator, None)

# TODO: move to Element subclass?
def getTagName(node):
    """Return the namespace URI, the local name of the element, and the full name of the element including the prefix."""
    items = node.tag.split('}')
    namespace = None
    local_name = items[-1]
    full_name = local_name
    if len(items) == 2:
        namespace = items[0][len('{'):]
        if node.prefix is not None:
            full_name = node.prefix + ':' + full_name
    
    return (namespace, local_name, full_name)

def collapseWhitespace(text, maxlen):
    """Replace tab characters and new line characters with spaces, trim the text and convert multiple spaces into a single space, and optionally truncate the result at maxlen characters."""
    text = (text or '').strip()[0:maxlen + 1].replace('\n', ' ').replace('\t', ' ')
    while '  ' in text:
        text = text.replace('  ', ' ')
    if maxlen < 0: # a negative maxlen means infinite/no limit
        return text
    else:
        append = ''
        if len(text) > maxlen:
            append = '...'
        return text[0:maxlen - len(append)] + append

def isTagSelfClosing(node):
    """If the start and end tag positions are the same, then it is self closing."""
    open_pos = getNodeTagRange(node, 'open')
    close_pos = getNodeTagRange(node, 'close')
    return open_pos == close_pos

def unique_namespace_prefixes(namespaces, replaceNoneWith = 'default', start = 1):
    """Given a list of unique namespace tuples in document order, make sure each prefix is unique and has a mapping back to the original prefix. Return a dictionary with the unique namespace prefixes and their mappings."""
    flattened = collections.OrderedDict()
    for item in namespaces:
        flattened.setdefault(item[0], []).append(item[1])
    
    unique = collections.OrderedDict()
    for key in flattened.keys():
        if len(flattened[key]) == 1:
            try_key = key or replaceNoneWith
            unique[try_key] = (flattened[key][0], key)
        else: # find next available number. we can't just append the number, because it is possible that the new numbered prefix already exists
            index = start - 1
            for item in flattened[key]: # for each item that has the same prefix but a different namespace
                while True:
                    index += 1 # try with the next index
                    try_key = (key or replaceNoneWith) + str(index)
                    if try_key not in unique.keys() and try_key not in flattened.keys():
                        break # the key we are trying is new
                unique[try_key] = (item, key)
    
    return unique

def get_results_for_xpath_query(query, tree, context = None, namespaces = None, **variables):
    """Given a query string and a document trees and optionally some context elements, compile the xpath query and execute it."""
    nsmap = {}
    if namespaces is not None:
        for prefix in namespaces.keys():
            nsmap[prefix] = namespaces[prefix][0]
    xpath = etree.XPath(query, namespaces = nsmap)
    
    results = execute_xpath_query(tree, xpath, context, **variables)
    return results

def execute_xpath_query(tree, xpath, context_node = None, **variables):
    """Execute the precompiled xpath query on the tree and return the results as a list."""
    if context_node is None: # explicitly check for None rather than using "or", because it is treated as a list
        context_node = tree
    result = xpath(context_node, **variables)
    if isinstance(result, list):
        return result
    else:
        return [result]