##    Copyright (C) 2006 Kovid Goyal kovid@kovidgoyal.net
##    This program is free software; you can redistribute it and/or modify
##    it under the terms of the GNU General Public License as published by
##    the Free Software Foundation; either version 2 of the License, or
##    (at your option) any later version.
##
##    This program is distributed in the hope that it will be useful,
##    but WITHOUT ANY WARRANTY; without even the implied warranty of
##    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##    GNU General Public License for more details.
##
##    You should have received a copy of the GNU General Public License along
##    with this program; if not, write to the Free Software Foundation, Inc.,
##    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

"""
This module presents an easy to use interface for getting and setting 
meta information in LRF files.
Just create an L{LRFMetaFile} object and use its properties 
to get and set meta information. For example:

>>> lrf = LRFMetaFile("mybook.lrf")
>>> print lrf.title, lrf.author
>>> lrf.category = "History"
"""

import struct, array, zlib, StringIO
import xml.dom.minidom as dom
from xml.dom.ext import Print as Print
from libprs500.prstypes import field

BYTE          = "<B"  #: Unsigned char little endian encoded in 1 byte 
WORD        = "<H"  #: Unsigned short little endian encoded in 2 bytes 
DWORD     = "<I"    #: Unsigned integer little endian encoded in 4 bytes
QWORD     = "<Q"  #: Unsigned long long little endian encoded in 8 bytes

class versioned_field(field):
    def __init__(self, vfield, version, start=0, fmt=WORD):
        field.__init__(self, start=start, fmt=fmt)
        self.vfield, self.version = vfield, version
    
    def enabled(self):
        return self.vfield > self.version
    
    def __get__(self, obj, typ=None):
        if self.enabled(): 
            return field.__get__(self, obj, typ=typ)
        else: 
            return None
    
    def __set__(self, obj, val):
        if not self.enabled(): 
            raise LRFException("Trying to set disabled field")
        else: 
            field.__set__(self, obj, val)

class LRFException(Exception):
    pass

class fixed_stringfield(object):
    """ A field storing a variable length string. """
    def __init__(self, length=8, start=0):
        """
        @param length: Size of this string 
        @param start: The byte at which this field is stored in the buffer
        """
        self._length = length
        self._start = start
    
    def __get__(self, obj, typ=None):    
        length = str(self._length)
        return obj.unpack(start=self._start, fmt="<"+length+"s")[0]
    
    def __set__(self, obj, val):
        if val.__class__.__name__ != 'str': val = str(val)
        if len(val) != self._length: 
            raise LRFException("Trying to set fixed_stringfield with a " + \
                               "string of  incorrect length")
        obj.pack(val, start=self._start, fmt="<"+str(len(val))+"s")
    
    def __repr__(self):
        return "A string of length " + str(self._length) + \
                " starting at byte " + str(self._start)

class xml_field(object):
    """ 
    Descriptor that gets and sets XML based meta information from an LRF file. 
    Works for simple XML fields of the form <tagname>data</tagname>
    """
    def __init__(self, tag_name):
        """ @param tag_name: The XML tag whoose data we operate on """
        self.tag_name = tag_name
    
    def __get__(self, obj, typ=None):
        document = dom.parseString(obj.info)
        elem = document.getElementsByTagName(self.tag_name)[0]
        elem.normalize() 
        if not elem.hasChildNodes(): 
            return ""      
        return elem.firstChild.data.strip()
    
    def __set__(self, obj, val):
        document = dom.parseString(obj.info)
        elem = document.getElementsByTagName(self.tag_name)[0]      
        elem.normalize()
        while elem.hasChildNodes(): 
            elem.removeChild(elem.lastChild)
        elem.appendChild(dom.Text())
        elem.firstChild.data = val
        s = StringIO.StringIO()
        Print(document, s)
        obj.info = s.getvalue()
        s.close()
    
    def __str__(self):
        return self.tag_name
    
    def __repr__(self):
        return "XML Field: " + self.tag_name

class LRFMetaFile(object):
    """ Has properties to read and write all Meta information in a LRF file. """
    LRF_HEADER = "L\0R\0F\0\0\0" #: The first 8 bytes of all valid LRF files
    
    lrf_header               = fixed_stringfield(length=8, start=0)
    version                    = field(fmt=WORD, start=8)
    xor_key                   = field(fmt=WORD, start=10)
    root_object_id         = field(fmt=DWORD, start=12)
    number_of_objets   = field(fmt=QWORD, start=16)
    object_index_offset = field(fmt=QWORD, start=24)
    binding                    = field(fmt=BYTE, start=36)
    dpi                           = field(fmt=WORD, start=38)
    width                       = field(fmt=WORD, start=42)
    height                     = field(fmt=WORD, start=44)
    color_depth            = field(fmt=BYTE, start=46)
    toc_object_id          = field(fmt=DWORD, start=0x44)
    toc_object_offset    = field(fmt=DWORD, start=0x48)
    compressed_info_size = field(fmt=WORD, start=0x4c)
    thumbnail_type        = versioned_field(version, 800, fmt=WORD, start=0x4e)
    thumbnail_size         = versioned_field(version, 800, fmt=DWORD, start=0x50)
    uncompressed_info_size = versioned_field(compressed_info_size, 0, \
                                             fmt=DWORD, start=0x54)
    
    title                          = xml_field("Title")
    author                     = xml_field("Author")
    book_id                   = xml_field("BookID")
    publisher                 = xml_field("Publisher")
    label                        = xml_field("Label")
    category                 = xml_field("Category")
    
    language                 = xml_field("Language")
    creator                    = xml_field("Creator")
    creation_date          = xml_field("CreationDate") #: Format is %Y-%m-%d
    producer                  = xml_field("Producer")
    page                        = xml_field("Page")
    
    def safe(func):
        """ 
        Decorator that ensures that function calls leave the pos 
        in the underlying file unchanged 
        """
        def restore_pos(*args, **kwargs):      
            obj = args[0]
            pos = obj._file.tell()
            res = func(*args, **kwargs)
            obj._file.seek(0, 2)
            if obj._file.tell() >= pos:
                obj._file.seek(pos)
            return res
        return restore_pos
    
    def safe_property(func):
        """ 
        Decorator that ensures that read or writing a property leaves 
        the position in the underlying file unchanged 
        """
        def decorator(f):
            def restore_pos(*args, **kwargs):      
                obj = args[0]
                pos = obj._file.tell()
                res = f(*args, **kwargs)
                obj._file.seek(0, 2)
                if obj._file.tell() >= pos:  
                    obj._file.seek(pos)
                return res
            return restore_pos
        locals_ = func()
        if locals_.has_key("fget"): 
            locals_["fget"] = decorator(locals_["fget"])
        if locals_.has_key("fset"): 
            locals_["fset"] = decorator(locals_["fset"])
        return property(**locals_)
    
    @safe_property
    def info():
        doc = """ Document meta information in raw XML format """
        def fget(self):
            if self.compressed_info_size == 0:
                raise LRFException("This document has no meta info")      
            size = self.compressed_info_size - 4
            self._file.seek(self.info_start)      
            try:
                stream =  zlib.decompress(self._file.read(size))        
                if len(stream) != self.uncompressed_info_size:          
                    raise LRFException("Decompression of document meta info\
                                        yielded unexpected results")
                return stream
            except zlib.error, e:
                raise LRFException("Unable to decompress document meta information")
        
        def fset(self, info):
            self.uncompressed_info_size = len(info)
            stream = zlib.compress(info)
            self.compressed_info_size = len(stream) + 4
            self._file.seek(self.info_start)
            self._file.write(stream)
            self._file.flush()
        return { "fget":fget, "fset":fset, "doc":doc }
    
    @safe_property
    def thumbnail_pos():
        doc = """ The position of the thumbnail in the LRF file """ 
        def fget(self):
            return self.info_start+ self.compressed_info_size-4
        return { "fget":fget, "doc":doc }
    
    @safe_property
    def thumbnail():
        doc = \
        """ 
        The thumbnail. 
        Represented as a string. 
        The string you would get from the file read function. 
        """    
        def fget(self):
            size = self.thumbnail_size
            if size:
                self._file.seek(self.thumbnail_pos)
                return self._file.read(size)
        
        def fset(self, data):
            if self.version <= 800: 
                raise LRFException("Cannot store thumbnails in LRF files \
                                    of version <= 800")
            orig_size = self.thumbnail_size
            self._file.seek(self.toc_object_offset)
            toc = self._file.read(self.object_index_offset - self.toc_object_offset)
            self._file.seek(self.object_index_offset)
            objects = self._file.read()      
            self.thumbnail_size = len(data)
            self._file.seek(self.thumbnail_pos)
            self._file.write(data)
            orig_offset = self.toc_object_offset
            self.toc_object_offset = self._file.tell()
            self._file.write(toc)
            self.object_index_offset  = self._file.tell()
            self._file.write(objects)
            self._file.flush()
            self._file.truncate() # Incase old thumbnail was bigger than new
            ttype = 0x14
            if data[1:4] == "PNG": 
                ttype = 0x12
            if data[0:2] == "BM": 
                ttype = 0x13
            if data[0:4] == "JIFF": 
                ttype = 0x11
            self.thumbnail_type = ttype            
            # Needed as new thumbnail may have different size than old thumbnail
            self.update_object_offsets(self.toc_object_offset - orig_offset)           
        return { "fget":fget, "fset":fset, "doc":doc }
    
    def __init__(self, file):
        """ @param file: A file object opened in the r+b mode """
        file.seek(0, 2)
        self.size = file.tell()
        self._file = file
        if self.lrf_header != LRFMetaFile.LRF_HEADER:
            raise LRFException(file.name + \
                " has an invalid LRF header. Are you sure it is an LRF file?")    
        # Byte at which the compressed meta information starts
        self.info_start = 0x58 if self.version > 800 else 0x53 
    
    @safe
    def update_object_offsets(self, delta):
        """ Run through the LRF Object index changing the offset by C{delta}. """
        self._file.seek(self.object_index_offset)    
        while(True):
            try: 
                self._file.read(4)
            except EOFError: 
                break
            pos = self._file.tell()
            try: 
                offset = self.unpack(fmt=DWORD, start=pos)[0] + delta
            except struct.error: 
                break
            self.pack(offset, fmt=DWORD, start=pos)
            try: 
                self._file.read(12)
            except EOFError: 
                break
        self._file.flush()
    
    @safe
    def unpack(self, fmt=DWORD, start=0):
        """ 
        Return decoded data from file.
        
        @param fmt: See U{struct<http://docs.python.org/lib/module-struct.html>}
        @param start: Position in file from which to decode
        """
        end = start + struct.calcsize(fmt)
        self._file.seek(start)
        self._file.seek(start)
        ret =  struct.unpack(fmt, self._file.read(end-start))
        return ret
    
    @safe
    def pack(self, *args, **kwargs):
        """ 
        Encode C{args} and write them to file. 
        C{kwargs} must contain the keywords C{fmt} and C{start}
        
        @param args: The values to pack
        @param fmt: See U{struct<http://docs.python.org/lib/module-struct.html>}
        @param start: Position in file at which to write encoded data
        """        
        encoded = struct.pack(kwargs["fmt"], *args)
        self._file.seek(kwargs["start"])
        self._file.write(encoded)
        self._file.flush()
    
    def thumbail_extension(self):
        ext = "gif"
        ttype = self.thumbnail_type
        if ttype == 0x11: 
            ext = "jpeg"
        elif ttype == 0x12:
            ext = "png"
        elif ttype == 0x13:
            ext = "bm"
        return ext

def main():
    import sys, os.path
    from optparse import OptionParser
    from libprs500 import __version__ as VERSION
    parser = OptionParser(usage="usage: %prog [options] mybook.lrf\n\
                    \nWARNING: Based on reverse engineering the LRF format."+\
                    " Making changes may render your LRF file unreadable. ", \
                    version=VERSION)
    parser.add_option("-t", "--title", action="store", type="string", \
                    dest="title", help="Set the book title")
    parser.add_option("-a", "--author", action="store", type="string", \
                    dest="author", help="Set the author")
    parser.add_option("-c", "--category", action="store", type="string", \
                    dest="category", help="The category this book belongs"+\
                    " to. E.g.: History")
    parser.add_option("--thumbnail", action="store", type="string", \
                    dest="thumbnail", help="Path to a graphic that will be"+\
                    " set as this files' thumbnail")
    parser.add_option("--get-thumbnail", action="store_true", \
                    dest="get_thumbnail", default=False, \
                    help="Extract thumbnail from LRF file")
    parser.add_option("-p", "--page", action="store", type="string", \
                    dest="page", help="Don't know what this is for")
    options, args = parser.parse_args()
    if len(args) != 1:
        parser.print_help()
        sys.exit(1)
    lrf = LRFMetaFile(open(args[0], "r+b"))
    if options.title:
        lrf.title        = options.title
    if options.author:
        lrf.author    = options.author
    if options.category: 
        lrf.category = options.category
    if options.page: 
        lrf.page = options.page
    if options.thumbnail:
        f = open(options.thumbnail, "r")
        lrf.thumbnail = f.read()
        f.close()
    
    if options.get_thumbnail:
        t = lrf.thumbnail
        td = "None"
        if t and len(t) > 0:
            td = os.path.basename(args[0])+"_thumbnail_."+lrf.thumbail_extension()
            f = open(td, "w")
            f.write(t)
            f.close()
    
    fields = LRFMetaFile.__dict__.items()
    for f in fields:
        if "XML" in str(f): 
            print str(f[1]) + ":", lrf.__getattribute__(f[0])
    if options.get_thumbnail: 
        print "Thumbnail:", td

# This turns overflow warnings into errors
import warnings
warnings.simplefilter("error", DeprecationWarning)
