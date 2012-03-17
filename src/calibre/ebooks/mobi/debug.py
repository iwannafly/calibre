#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import struct, datetime, sys, os, shutil
from collections import OrderedDict, defaultdict

from lxml import html

from calibre.utils.date import utc_tz
from calibre.ebooks.mobi.langcodes import main_language, sub_language
from calibre.ebooks.mobi.reader.headers import NULL_INDEX
from calibre.ebooks.mobi.reader.index import (parse_index_record,
        parse_tagx_section)
from calibre.ebooks.mobi.utils import (decode_hex_number, decint,
        get_trailing_data, decode_tbs, read_font_record)
from calibre.utils.magick.draw import identify_data

def format_bytes(byts):
    byts = bytearray(byts)
    byts = [hex(b)[2:] for b in byts]
    return ' '.join(byts)

# PalmDB {{{
class PalmDOCAttributes(object):

    class Attr(object):

        def __init__(self, name, field, val):
            self.name = name
            self.val = val & field

        def __str__(self):
            return '%s: %s'%(self.name, bool(self.val))

    def __init__(self, raw):
        self.val = struct.unpack(b'<H', raw)[0]
        self.attributes = []
        for name, field in [('Read Only', 0x02), ('Dirty AppInfoArea', 0x04),
                ('Backup this database', 0x08),
                ('Okay to install newer over existing copy, if present on PalmPilot', 0x10),
                ('Force the PalmPilot to reset after this database is installed', 0x12),
                ('Don\'t allow copy of file to be beamed to other Pilot',
                    0x14)]:
            self.attributes.append(PalmDOCAttributes.Attr(name, field,
                self.val))

    def __str__(self):
        attrs = '\n\t'.join([str(x) for x in self.attributes])
        return 'PalmDOC Attributes: %s\n\t%s'%(bin(self.val), attrs)

class PalmDB(object):

    def __init__(self, raw):
        self.raw = raw

        if self.raw.startswith(b'TPZ'):
            raise ValueError('This is a Topaz file')

        self.name     = self.raw[:32].replace(b'\x00', b'')
        self.attributes = PalmDOCAttributes(self.raw[32:34])
        self.version = struct.unpack(b'>H', self.raw[34:36])[0]

        palm_epoch = datetime.datetime(1904, 1, 1, tzinfo=utc_tz)
        self.creation_date_raw = struct.unpack(b'>I', self.raw[36:40])[0]
        self.creation_date = (palm_epoch +
                datetime.timedelta(seconds=self.creation_date_raw))
        self.modification_date_raw = struct.unpack(b'>I', self.raw[40:44])[0]
        self.modification_date = (palm_epoch +
                datetime.timedelta(seconds=self.modification_date_raw))
        self.last_backup_date_raw = struct.unpack(b'>I', self.raw[44:48])[0]
        self.last_backup_date = (palm_epoch +
                datetime.timedelta(seconds=self.last_backup_date_raw))
        self.modification_number = struct.unpack(b'>I', self.raw[48:52])[0]
        self.app_info_id = self.raw[52:56]
        self.sort_info_id = self.raw[56:60]
        self.type = self.raw[60:64]
        self.creator = self.raw[64:68]
        self.ident = self.type + self.creator
        if self.ident not in (b'BOOKMOBI', b'TEXTREAD'):
            raise ValueError('Unknown book ident: %r'%self.ident)
        self.last_record_uid, = struct.unpack(b'>I', self.raw[68:72])
        self.next_rec_list_id = self.raw[72:76]

        self.number_of_records, = struct.unpack(b'>H', self.raw[76:78])

    def __str__(self):
        ans = ['*'*20 + ' PalmDB Header '+ '*'*20]
        ans.append('Name: %r'%self.name)
        ans.append(str(self.attributes))
        ans.append('Version: %s'%self.version)
        ans.append('Creation date: %s (%s)'%(self.creation_date.isoformat(),
            self.creation_date_raw))
        ans.append('Modification date: %s (%s)'%(self.modification_date.isoformat(),
            self.modification_date_raw))
        ans.append('Backup date: %s (%s)'%(self.last_backup_date.isoformat(),
            self.last_backup_date_raw))
        ans.append('Modification number: %s'%self.modification_number)
        ans.append('App Info ID: %r'%self.app_info_id)
        ans.append('Sort Info ID: %r'%self.sort_info_id)
        ans.append('Type: %r'%self.type)
        ans.append('Creator: %r'%self.creator)
        ans.append('Last record UID +1: %r'%self.last_record_uid)
        ans.append('Next record list id: %r'%self.next_rec_list_id)
        ans.append('Number of records: %s'%self.number_of_records)

        return '\n'.join(ans)
# }}}

class Record(object): # {{{

    def __init__(self, raw, header):
        self.offset, self.flags, self.uid = header
        self.raw = raw

    @property
    def header(self):
        return 'Offset: %d Flags: %d UID: %d First 4 bytes: %r Size: %d'%(self.offset, self.flags,
                self.uid, self.raw[:4], len(self.raw))
# }}}

# EXTH {{{
class EXTHRecord(object):

    def __init__(self, type_, data):
        self.type = type_
        self.data = data
        self.name = {
                1 : 'DRM Server id',
                2 : 'DRM Commerce id',
                3 : 'DRM ebookbase book id',
                100 : 'author',
                101 : 'publisher',
                102 : 'imprint',
                103 : 'description',
                104 : 'isbn',
                105 : 'subject',
                106 : 'publishingdate',
                107 : 'review',
                108 : 'contributor',
                109 : 'rights',
                110 : 'subjectcode',
                111 : 'type',
                112 : 'source',
                113 : 'asin',
                114 : 'versionnumber',
                115 : 'sample',
                116 : 'startreading',
                117 : 'adult',
                118 : 'retailprice',
                119 : 'retailpricecurrency',
                121 : 'KF8 header section index',
                125 : 'KF8 resources (images/fonts) count',
                129 : 'KF8 cover URI',
                131 : 'KF8 unknown count',
                201 : 'coveroffset',
                202 : 'thumboffset',
                203 : 'hasfakecover',
                204 : 'Creator Software',
                205 : 'Creator Major Version', # '>I'
                206 : 'Creator Minor Version', # '>I'
                207 : 'Creator Build Number', # '>I'
                208 : 'watermark',
                209 : 'tamper_proof_keys',
                300 : 'fontsignature',
                301 : 'clippinglimit', # percentage '>B'
                402 : 'publisherlimit',
                404 : 'TTS flag', # '>B' 1 - TTS disabled 0 - TTS enabled
                501 : 'cdetype', # 4 chars (PDOC or EBOK)
                502 : 'lastupdatetime',
                503 : 'updatedtitle',
        }.get(self.type, repr(self.type))

        if (self.name in {'coveroffset', 'thumboffset', 'hasfakecover',
                'Creator Major Version', 'Creator Minor Version',
                'Creator Build Number', 'Creator Software', 'startreading'} or
                self.type in {121, 125, 131}):
            self.data, = struct.unpack(b'>I', self.data)

    def __str__(self):
        return '%s (%d): %r'%(self.name, self.type, self.data)

class EXTHHeader(object):

    def __init__(self, raw):
        self.raw = raw
        if not self.raw.startswith(b'EXTH'):
            raise ValueError('EXTH header does not start with EXTH')
        self.length, = struct.unpack(b'>I', self.raw[4:8])
        self.count,  = struct.unpack(b'>I', self.raw[8:12])

        pos = 12
        self.records = []
        for i in xrange(self.count):
            pos = self.read_record(pos)
        self.records.sort(key=lambda x:x.type)

    def read_record(self, pos):
        type_, length = struct.unpack(b'>II', self.raw[pos:pos+8])
        data = self.raw[(pos+8):(pos+length)]
        self.records.append(EXTHRecord(type_, data))
        return pos + length

    def __str__(self):
        ans = ['*'*20 + ' EXTH Header '+ '*'*20]
        ans.append('EXTH header length: %d'%self.length)
        ans.append('Number of EXTH records: %d'%self.count)
        ans.append('EXTH records...')
        for r in self.records:
            ans.append(str(r))
        return '\n'.join(ans)
# }}}

class MOBIHeader(object): # {{{

    def __init__(self, record0):
        self.raw = record0.raw

        self.compression_raw = self.raw[:2]
        self.compression = {1: 'No compression', 2: 'PalmDoc compression',
                17480: 'HUFF/CDIC compression'}.get(struct.unpack(b'>H',
                    self.compression_raw)[0],
                    repr(self.compression_raw))
        self.unused = self.raw[2:4]
        self.text_length, = struct.unpack(b'>I', self.raw[4:8])
        self.number_of_text_records, self.text_record_size = \
                struct.unpack(b'>HH', self.raw[8:12])
        self.encryption_type_raw, = struct.unpack(b'>H', self.raw[12:14])
        self.encryption_type = {
                0: 'No encryption',
                1: 'Old mobipocket encryption',
                2: 'Mobipocket encryption'
            }.get(self.encryption_type_raw, repr(self.encryption_type_raw))
        self.unknown = self.raw[14:16]

        self.identifier = self.raw[16:20]
        if self.identifier != b'MOBI':
            raise ValueError('Identifier %r unknown'%self.identifier)

        self.length, = struct.unpack(b'>I', self.raw[20:24])
        self.type_raw, = struct.unpack(b'>I', self.raw[24:28])
        self.type = {
                2 : 'Mobipocket book',
                3 : 'PalmDOC book',
                4 : 'Audio',
                257 : 'News',
                258 : 'News Feed',
                259 : 'News magazine',
                513 : 'PICS',
                514 : 'Word',
                515 : 'XLS',
                516 : 'PPT',
                517 : 'TEXT',
                518 : 'HTML',
            }.get(self.type_raw, repr(self.type_raw))

        self.encoding_raw, = struct.unpack(b'>I', self.raw[28:32])
        self.encoding = {
                1252 : 'cp1252',
                65001: 'utf-8',
            }.get(self.encoding_raw, repr(self.encoding_raw))
        self.uid = self.raw[32:36]
        self.file_version = struct.unpack(b'>I', self.raw[36:40])
        self.reserved = self.raw[40:48]
        self.secondary_index_record, = struct.unpack(b'>I', self.raw[48:52])
        self.reserved2 = self.raw[52:80]
        self.first_non_book_record, = struct.unpack(b'>I', self.raw[80:84])
        self.fullname_offset, = struct.unpack(b'>I', self.raw[84:88])
        self.fullname_length, = struct.unpack(b'>I', self.raw[88:92])
        self.locale_raw, = struct.unpack(b'>I', self.raw[92:96])
        langcode = self.locale_raw
        langid    = langcode & 0xFF
        sublangid = (langcode >> 10) & 0xFF
        self.language = main_language.get(langid, 'ENGLISH')
        self.sublanguage = sub_language.get(sublangid, 'NEUTRAL')

        self.input_language = self.raw[96:100]
        self.output_langauage = self.raw[100:104]
        self.min_version, = struct.unpack(b'>I', self.raw[104:108])
        self.first_image_index, = struct.unpack(b'>I', self.raw[108:112])
        self.huffman_record_offset, = struct.unpack(b'>I', self.raw[112:116])
        self.huffman_record_count, = struct.unpack(b'>I', self.raw[116:120])
        self.datp_record_offset, = struct.unpack(b'>I', self.raw[120:124])
        self.datp_record_count, = struct.unpack(b'>I', self.raw[124:128])
        self.exth_flags, = struct.unpack(b'>I', self.raw[128:132])
        self.has_exth = bool(self.exth_flags & 0x40)
        self.has_drm_data = self.length >= 174 and len(self.raw) >= 180
        if self.has_drm_data:
            self.unknown3 = self.raw[132:164]
            self.drm_offset, = struct.unpack(b'>I', self.raw[164:168])
            self.drm_count, = struct.unpack(b'>I', self.raw[168:172])
            self.drm_size, = struct.unpack(b'>I', self.raw[172:176])
            self.drm_flags = bin(struct.unpack(b'>I', self.raw[176:180])[0])
        self.has_extra_data_flags = self.length >= 232 and len(self.raw) >= 232+16
        self.has_fcis_flis = False
        self.has_multibytes = self.has_indexing_bytes = self.has_uncrossable_breaks = False
        self.extra_data_flags = 0
        if self.has_extra_data_flags:
            self.unknown4 = self.raw[180:192]
            self.first_content_record, self.last_content_record = \
                    struct.unpack(b'>HH', self.raw[192:196])
            self.unknown5, = struct.unpack(b'>I', self.raw[196:200])
            (self.fcis_number, self.fcis_count, self.flis_number,
                    self.flis_count) = struct.unpack(b'>IIII',
                            self.raw[200:216])
            self.unknown6 = self.raw[216:224]
            self.srcs_record_index = struct.unpack(b'>I',
                self.raw[224:228])[0]
            self.num_srcs_records = struct.unpack(b'>I',
                self.raw[228:232])[0]
            self.unknown7 = self.raw[232:240]
            self.extra_data_flags = struct.unpack(b'>I',
                self.raw[240:244])[0]
            self.has_multibytes = bool(self.extra_data_flags & 0b1)
            self.has_indexing_bytes = bool(self.extra_data_flags & 0b10)
            self.has_uncrossable_breaks = bool(self.extra_data_flags & 0b100)
            self.primary_index_record, = struct.unpack(b'>I',
                    self.raw[244:248])

        if self.has_exth:
            self.exth_offset = 16 + self.length

            self.exth = EXTHHeader(self.raw[self.exth_offset:])

            self.end_of_exth = self.exth_offset + self.exth.length
            self.bytes_after_exth = self.raw[self.end_of_exth:self.fullname_offset]

    def __str__(self):
        ans = ['*'*20 + ' MOBI Header '+ '*'*20]
        ans.append('Compression: %s'%self.compression)
        ans.append('Unused: %r'%self.unused)
        ans.append('Number of text records: %d'%self.number_of_text_records)
        ans.append('Text record size: %d'%self.text_record_size)
        ans.append('Encryption: %s'%self.encryption_type)
        ans.append('Unknown: %r'%self.unknown)
        ans.append('Identifier: %r'%self.identifier)
        ans.append('Header length: %d'% self.length)
        ans.append('Type: %s'%self.type)
        ans.append('Encoding: %s'%self.encoding)
        ans.append('UID: %r'%self.uid)
        ans.append('File version: %d'%self.file_version)
        ans.append('Reserved: %r'%self.reserved)
        ans.append('Secondary index record: %d (null val: %d)'%(
            self.secondary_index_record, NULL_INDEX))
        ans.append('Reserved2: %r'%self.reserved2)
        ans.append('First non-book record (null value: %d): %d'%(NULL_INDEX,
            self.first_non_book_record))
        ans.append('Full name offset: %d'%self.fullname_offset)
        ans.append('Full name length: %d bytes'%self.fullname_length)
        ans.append('Langcode: %r'%self.locale_raw)
        ans.append('Language: %s'%self.language)
        ans.append('Sub language: %s'%self.sublanguage)
        ans.append('Input language: %r'%self.input_language)
        ans.append('Output language: %r'%self.output_langauage)
        ans.append('Min version: %d'%self.min_version)
        ans.append('First Image index: %d'%self.first_image_index)
        ans.append('Huffman record offset: %d'%self.huffman_record_offset)
        ans.append('Huffman record count: %d'%self.huffman_record_count)
        ans.append('DATP record offset: %r'%self.datp_record_offset)
        ans.append('DATP record count: %r'%self.datp_record_count)
        ans.append('EXTH flags: %s (%s)'%(bin(self.exth_flags)[2:], self.has_exth))
        if self.has_drm_data:
            ans.append('Unknown3: %r'%self.unknown3)
            ans.append('DRM Offset: %s'%self.drm_offset)
            ans.append('DRM Count: %s'%self.drm_count)
            ans.append('DRM Size: %s'%self.drm_size)
            ans.append('DRM Flags: %r'%self.drm_flags)
        if self.has_extra_data_flags:
            ans.append('Unknown4: %r'%self.unknown4)
            ans.append('First content record: %d'% self.first_content_record)
            ans.append('Last content record: %d'% self.last_content_record)
            ans.append('Unknown5: %d'% self.unknown5)
            ans.append('FCIS number: %d'% self.fcis_number)
            ans.append('FCIS count: %d'% self.fcis_count)
            ans.append('FLIS number: %d'% self.flis_number)
            ans.append('FLIS count: %d'% self.flis_count)
            ans.append('Unknown6: %r'% self.unknown6)
            ans.append('SRCS record index: %d'%self.srcs_record_index)
            ans.append('Number of SRCS records?: %d'%self.num_srcs_records)
            ans.append('Unknown7: %r'%self.unknown7)
            ans.append(('Extra data flags: %s (has multibyte: %s) '
                '(has indexing: %s) (has uncrossable breaks: %s)')%(
                    bin(self.extra_data_flags), self.has_multibytes,
                    self.has_indexing_bytes, self.has_uncrossable_breaks ))
            ans.append('Primary index record (null value: %d): %d'%(NULL_INDEX,
                self.primary_index_record))

        ans = '\n'.join(ans)

        if self.has_exth:
            ans += '\n\n' + str(self.exth)
            ans += '\n\nBytes after EXTH (%d bytes): %s'%(
                    len(self.bytes_after_exth),
                    format_bytes(self.bytes_after_exth))

        ans += '\nNumber of bytes after full name: %d' % (len(self.raw) - (self.fullname_offset +
                self.fullname_length))

        ans += '\nRecord 0 length: %d'%len(self.raw)
        return ans
# }}}

class TagX(object): # {{{

    def __init__(self, tag, num_values, bitmask, eof):
        self.tag, self.num_values, self.bitmask, self.eof = (tag, num_values,
                bitmask, eof)
        self.num_of_values = num_values
        self.is_eof = (self.eof == 1 and self.tag == 0 and self.num_values == 0
                and self.bitmask == 0)

    def __repr__(self):
        return 'TAGX(tag=%02d, num_values=%d, bitmask=%r, eof=%d)' % (self.tag,
                self.num_values, bin(self.bitmask), self.eof)
    # }}}

class SecondaryIndexHeader(object): # {{{

    def __init__(self, record):
        self.record = record
        raw = self.record.raw
        #open('/t/index_header.bin', 'wb').write(raw)
        if raw[:4] != b'INDX':
            raise ValueError('Invalid Secondary Index Record')
        self.header_length, = struct.unpack('>I', raw[4:8])
        self.unknown1 = raw[8:16]
        self.index_type, = struct.unpack('>I', raw[16:20])
        self.index_type_desc = {0: 'normal', 2:
                'inflection', 6: 'calibre'}.get(self.index_type, 'unknown')
        self.idxt_start, = struct.unpack('>I', raw[20:24])
        self.index_count, = struct.unpack('>I', raw[24:28])
        self.index_encoding_num, = struct.unpack('>I', raw[28:32])
        self.index_encoding = {65001: 'utf-8', 1252:
                'cp1252'}.get(self.index_encoding_num, 'unknown')
        if self.index_encoding == 'unknown':
            raise ValueError(
                'Unknown index encoding: %d'%self.index_encoding_num)
        self.unknown2 = raw[32:36]
        self.num_index_entries, = struct.unpack('>I', raw[36:40])
        self.ordt_start, = struct.unpack('>I', raw[40:44])
        self.ligt_start, = struct.unpack('>I', raw[44:48])
        self.num_of_ligt_entries, = struct.unpack('>I', raw[48:52])
        self.num_of_cncx_blocks, = struct.unpack('>I', raw[52:56])
        self.unknown3 = raw[56:180]
        self.tagx_offset, = struct.unpack(b'>I', raw[180:184])
        if self.tagx_offset != self.header_length:
            raise ValueError('TAGX offset and header length disagree')
        self.unknown4 = raw[184:self.header_length]

        tagx = raw[self.header_length:]
        if not tagx.startswith(b'TAGX'):
            raise ValueError('Invalid TAGX section')
        self.tagx_header_length, = struct.unpack('>I', tagx[4:8])
        self.tagx_control_byte_count, = struct.unpack('>I', tagx[8:12])
        self.tagx_entries = [TagX(*x) for x in parse_tagx_section(tagx)[1]]
        if self.tagx_entries and not self.tagx_entries[-1].is_eof:
            raise ValueError('TAGX last entry is not EOF')

        idxt0_pos = self.header_length+self.tagx_header_length
        num = ord(raw[idxt0_pos])
        count_pos = idxt0_pos+1+num
        self.last_entry = raw[idxt0_pos+1:count_pos]
        self.ncx_count, = struct.unpack(b'>H', raw[count_pos:count_pos+2])

        # There may be some alignment zero bytes between the end of the idxt0
        # and self.idxt_start
        idxt = raw[self.idxt_start:]
        if idxt[:4] != b'IDXT':
            raise ValueError('Invalid IDXT header')
        length_check, = struct.unpack(b'>H', idxt[4:6])
        if length_check != self.header_length + self.tagx_header_length:
            raise ValueError('Length check failed')
        if idxt[6:].replace(b'\0', b''):
            raise ValueError('Non null trailing bytes after IDXT')


    def __str__(self):
        ans = ['*'*20 + ' Secondary Index Header '+ '*'*20]
        a = ans.append
        def u(w):
            a('Unknown: %r (%d bytes) (All zeros: %r)'%(w,
                len(w), not bool(w.replace(b'\0', b'')) ))

        a('Header length: %d'%self.header_length)
        u(self.unknown1)
        a('Index Type: %s (%d)'%(self.index_type_desc, self.index_type))
        a('Offset to IDXT start: %d'%self.idxt_start)
        a('Number of index records: %d'%self.index_count)
        a('Index encoding: %s (%d)'%(self.index_encoding,
                self.index_encoding_num))
        u(self.unknown2)
        a('Number of index entries: %d'% self.num_index_entries)
        a('ORDT start: %d'%self.ordt_start)
        a('LIGT start: %d'%self.ligt_start)
        a('Number of LIGT entries: %d'%self.num_of_ligt_entries)
        a('Number of cncx blocks: %d'%self.num_of_cncx_blocks)
        u(self.unknown3)
        a('TAGX offset: %d'%self.tagx_offset)
        u(self.unknown4)
        a('\n\n')
        a('*'*20 + ' TAGX Header (%d bytes)'%self.tagx_header_length+ '*'*20)
        a('Header length: %d'%self.tagx_header_length)
        a('Control byte count: %d'%self.tagx_control_byte_count)
        for i in self.tagx_entries:
            a('\t' + repr(i))
        a('Index of last IndexEntry in secondary index record: %s'% self.last_entry)
        a('Number of entries in the NCX: %d'% self.ncx_count)

        return '\n'.join(ans)

# }}}

class IndexHeader(object): # {{{

    def __init__(self, record):
        self.record = record
        raw = self.record.raw
        #open('/t/index_header.bin', 'wb').write(raw)
        if raw[:4] != b'INDX':
            raise ValueError('Invalid Primary Index Record')

        self.header_length, = struct.unpack('>I', raw[4:8])
        self.unknown1 = raw[8:12]
        self.header_type, = struct.unpack('>I', raw[12:16])
        self.index_type, = struct.unpack('>I', raw[16:20])
        self.index_type_desc = {0: 'normal', 2:
                'inflection', 6: 'calibre'}.get(self.index_type, 'unknown')
        self.idxt_start, = struct.unpack('>I', raw[20:24])
        self.index_count, = struct.unpack('>I', raw[24:28])
        self.index_encoding_num, = struct.unpack('>I', raw[28:32])
        self.index_encoding = {65001: 'utf-8', 1252:
                'cp1252'}.get(self.index_encoding_num, 'unknown')
        if self.index_encoding == 'unknown':
            raise ValueError(
                'Unknown index encoding: %d'%self.index_encoding_num)
        self.possibly_language = raw[32:36]
        self.num_index_entries, = struct.unpack('>I', raw[36:40])
        self.ordt_start, = struct.unpack('>I', raw[40:44])
        self.ligt_start, = struct.unpack('>I', raw[44:48])
        self.num_of_ligt_entries, = struct.unpack('>I', raw[48:52])
        self.num_of_cncx_blocks, = struct.unpack('>I', raw[52:56])
        self.unknown2 = raw[56:180]
        self.tagx_offset, = struct.unpack(b'>I', raw[180:184])
        if self.tagx_offset != self.header_length:
            raise ValueError('TAGX offset and header length disagree')
        self.unknown3 = raw[184:self.header_length]

        tagx = raw[self.header_length:]
        if not tagx.startswith(b'TAGX'):
            raise ValueError('Invalid TAGX section')
        self.tagx_header_length, = struct.unpack('>I', tagx[4:8])
        self.tagx_control_byte_count, = struct.unpack('>I', tagx[8:12])
        self.tagx_entries = [TagX(*x) for x in parse_tagx_section(tagx)[1]]
        if self.tagx_entries and not self.tagx_entries[-1].is_eof:
            raise ValueError('TAGX last entry is not EOF')

        idxt0_pos = self.header_length+self.tagx_header_length
        last_num, consumed = decode_hex_number(raw[idxt0_pos:])
        count_pos = idxt0_pos + consumed
        self.ncx_count, = struct.unpack(b'>H', raw[count_pos:count_pos+2])
        self.last_entry = last_num

        if last_num != self.ncx_count - 1:
            raise ValueError('Last id number in the NCX != NCX count - 1')
        # There may be some alignment zero bytes between the end of the idxt0
        # and self.idxt_start

        idxt = raw[self.idxt_start:]
        if idxt[:4] != b'IDXT':
            raise ValueError('Invalid IDXT header')
        length_check, = struct.unpack(b'>H', idxt[4:6])
        if length_check != self.header_length + self.tagx_header_length:
            raise ValueError('Length check failed')
        if idxt[6:].replace(b'\0', b''):
            raise ValueError('Non null trailing bytes after IDXT')


    def __str__(self):
        ans = ['*'*20 + ' Index Header (%d bytes)'%len(self.record.raw)+ '*'*20]
        a = ans.append
        def u(w):
            a('Unknown: %r (%d bytes) (All zeros: %r)'%(w,
                len(w), not bool(w.replace(b'\0', b'')) ))

        a('Header length: %d'%self.header_length)
        u(self.unknown1)
        a('Header type: %d'%self.header_type)
        a('Index Type: %s (%d)'%(self.index_type_desc, self.index_type))
        a('Offset to IDXT start: %d'%self.idxt_start)
        a('Number of index records: %d'%self.index_count)
        a('Index encoding: %s (%d)'%(self.index_encoding,
                self.index_encoding_num))
        a('Unknown (possibly language?): %r'%(self.possibly_language))
        a('Number of index entries: %d'% self.num_index_entries)
        a('ORDT start: %d'%self.ordt_start)
        a('LIGT start: %d'%self.ligt_start)
        a('Number of LIGT entries: %d'%self.num_of_ligt_entries)
        a('Number of cncx blocks: %d'%self.num_of_cncx_blocks)
        u(self.unknown2)
        a('TAGX offset: %d'%self.tagx_offset)
        u(self.unknown3)
        a('\n\n')
        a('*'*20 + ' TAGX Header (%d bytes)'%self.tagx_header_length+ '*'*20)
        a('Header length: %d'%self.tagx_header_length)
        a('Control byte count: %d'%self.tagx_control_byte_count)
        for i in self.tagx_entries:
            a('\t' + repr(i))
        a('Index of last IndexEntry in primary index record: %s'% self.last_entry)
        a('Number of entries in the NCX: %d'% self.ncx_count)

        return '\n'.join(ans)
    # }}}

class Tag(object): # {{{

    '''
    Index entries are a collection of tags. Each tag is represented by this
    class.
    '''

    TAG_MAP = {
            1: ('offset', 'Offset in HTML'),
            2: ('size', 'Size in HTML'),
            3: ('label_offset', 'Label offset in CNCX'),
            4: ('depth', 'Depth of this entry in TOC'),
            5: ('class_offset', 'Class offset in CNCX'),
            6: ('pos_fid', 'File Index'),

            11: ('secondary', '[unknown, unknown, '
                'tag type from TAGX in primary index header]'),

            21: ('parent_index', 'Parent'),
            22: ('first_child_index', 'First child'),
            23: ('last_child_index', 'Last child'),

            69 : ('image_index', 'Offset from first image record to the'
                                ' image record associated with this entry'
                                ' (masthead for periodical or thumbnail for'
                                ' article entry).'),
            70 : ('desc_offset', 'Description offset in cncx'),
            71 : ('author_offset', 'Author offset in cncx'),
            72 : ('image_caption_offset', 'Image caption offset in cncx'),
            73 : ('image_attr_offset', 'Image attribution offset in cncx'),

    }

    def __init__(self, tag_type, vals, cncx):
        self.value = vals if len(vals) > 1 else vals[0] if vals else None

        self.cncx_value = None
        if tag_type in self.TAG_MAP:
            self.attr, self.desc = self.TAG_MAP[tag_type]
        else:
            print ('Unknown tag value: %%s'%tag_type)
            self.desc = '??Unknown (tag value: %d)'%tag_type
            self.attr = 'unknown'

        if '_offset' in self.attr:
            self.cncx_value = cncx[self.value]

    def __str__(self):
        if self.cncx_value is not None:
            return '%s : %r [%r]'%(self.desc, self.value, self.cncx_value)
        return '%s : %r'%(self.desc, self.value)

# }}}

class IndexEntry(object): # {{{

    '''
    The index is made up of entries, each of which is represented by an
    instance of this class. Index entries typically point to offsets in the
    HTML, specify HTML sizes and point to text strings in the CNCX that are
    used in the navigation UI.
    '''

    def __init__(self, ident, entry, cncx):
        try:
            self.index = int(ident, 16)
        except ValueError:
            self.index = ident
        self.tags = [Tag(tag_type, vals, cncx) for tag_type, vals in
                entry.iteritems()]

    @property
    def label(self):
        for tag in self.tags:
            if tag.attr == 'label_offset':
                return tag.cncx_value
        return ''

    @property
    def offset(self):
        for tag in self.tags:
            if tag.attr == 'offset':
                return tag.value
        return 0

    @property
    def size(self):
        for tag in self.tags:
            if tag.attr == 'size':
                return tag.value
        return 0

    @property
    def depth(self):
        for tag in self.tags:
            if tag.attr == 'depth':
                return tag.value
        return 0

    @property
    def parent_index(self):
        for tag in self.tags:
            if tag.attr == 'parent_index':
                return tag.value
        return -1

    @property
    def first_child_index(self):
        for tag in self.tags:
            if tag.attr == 'first_child_index':
                return tag.value
        return -1

    @property
    def last_child_index(self):
        for tag in self.tags:
            if tag.attr == 'last_child_index':
                return tag.value
        return -1

    @property
    def pos_fid(self):
        for tag in self.tags:
            if tag.attr == 'pos_fid':
                return tag.value
        return [0, 0]

    def __str__(self):
        ans = ['Index Entry(index=%s, length=%d)'%(
            self.index, len(self.tags))]
        for tag in self.tags:
            if tag.value is not None:
                ans.append('\t'+str(tag))
        if self.first_child_index != -1:
            ans.append('\tNumber of children: %d'%(self.last_child_index -
                self.first_child_index + 1))
        return '\n'.join(ans)

# }}}

class IndexRecord(object): # {{{

    '''
    Represents all indexing information in the MOBI, apart from indexing info
    in the trailing data of the text records.
    '''

    def __init__(self, records, index_header, cncx):
        self.alltext = None
        table = OrderedDict()
        tags = [TagX(x.tag, x.num_values, x.bitmask, x.eof) for x in
                index_header.tagx_entries]
        for record in records:
            raw = record.raw

            if raw[:4] != b'INDX':
                raise ValueError('Invalid Primary Index Record')

            parse_index_record(table, record.raw,
                    index_header.tagx_control_byte_count, tags,
                    index_header.index_encoding, strict=True)

        self.indices = []

        for ident, entry in table.iteritems():
            self.indices.append(IndexEntry(ident, entry, cncx))

    def get_parent(self, index):
        if index.depth < 1:
            return None
        parent_depth = index.depth - 1
        for p in self.indices:
            if p.depth != parent_depth:
                continue

    def __str__(self):
        ans = ['*'*20 + ' Index Entries (%d entries) '%len(self.indices)+ '*'*20]
        a = ans.append
        def u(w):
            a('Unknown: %r (%d bytes) (All zeros: %r)'%(w,
                len(w), not bool(w.replace(b'\0', b'')) ))
        for entry in self.indices:
            offset = entry.offset
            a(str(entry))
            t = self.alltext
            if offset is not None and self.alltext is not None:
                a('\tHTML before offset: %r'%t[offset-50:offset])
                a('\tHTML after offset: %r'%t[offset:offset+50])
                p = offset+entry.size
                a('\tHTML before end: %r'%t[p-50:p])
                a('\tHTML after end: %r'%t[p:p+50])

            a('')

        return '\n'.join(ans)

# }}}

class CNCX(object): # {{{

    '''
    Parses the records that contain the compiled NCX (all strings from the
    NCX). Presents a simple offset : string mapping interface to access the
    data.
    '''

    def __init__(self, records, codec):
        self.records = OrderedDict()
        record_offset = 0
        for record in records:
            raw = record.raw
            pos = 0
            while pos < len(raw):
                length, consumed = decint(raw[pos:])
                if length > 0:
                    try:
                        self.records[pos+record_offset] = raw[
                            pos+consumed:pos+consumed+length].decode(codec)
                    except:
                        byts = raw[pos:]
                        r = format_bytes(byts)
                        print ('CNCX entry at offset %d has unknown format %s'%(
                            pos+record_offset, r))
                        self.records[pos+record_offset] = r
                        pos = len(raw)
                pos += consumed+length
            record_offset += 0x10000

    def __getitem__(self, offset):
        return self.records.get(offset)

    def __str__(self):
        ans = ['*'*20 + ' cncx (%d strings) '%len(self.records)+ '*'*20]
        for k, v in self.records.iteritems():
            ans.append('%10d : %s'%(k, v))
        return '\n'.join(ans)


# }}}

class TextRecord(object): # {{{

    def __init__(self, idx, record, extra_data_flags, decompress):
        self.trailing_data, self.raw = get_trailing_data(record.raw, extra_data_flags)
        raw_trailing_bytes = record.raw[len(self.raw):]
        self.raw = decompress(self.raw)

        if 0 in self.trailing_data:
            self.trailing_data['multibyte_overlap'] = self.trailing_data.pop(0)
        if 1 in self.trailing_data:
            self.trailing_data['indexing'] = self.trailing_data.pop(1)
        if 2 in self.trailing_data:
            self.trailing_data['uncrossable_breaks'] = self.trailing_data.pop(2)
        self.trailing_data['raw_bytes'] = raw_trailing_bytes

        for typ, val in self.trailing_data.iteritems():
            if isinstance(typ, int):
                print ('Record %d has unknown trailing data of type: %d : %r'%
                        (idx, typ, val))

        self.idx = idx

    def dump(self, folder):
        name = '%06d'%self.idx
        with open(os.path.join(folder, name+'.txt'), 'wb') as f:
            f.write(self.raw)
        with open(os.path.join(folder, name+'.trailing_data'), 'wb') as f:
            for k, v in self.trailing_data.iteritems():
                raw = '%s : %r\n\n'%(k, v)
                f.write(raw.encode('utf-8'))

# }}}

class ImageRecord(object): # {{{

    def __init__(self, idx, record, fmt):
        self.raw = record.raw
        self.fmt = fmt
        self.idx = idx

    def dump(self, folder):
        name = '%06d'%self.idx
        with open(os.path.join(folder, name+'.'+self.fmt), 'wb') as f:
            f.write(self.raw)

# }}}

class BinaryRecord(object): # {{{

    def __init__(self, idx, record):
        self.raw = record.raw
        sig = self.raw[:4]
        name = '%06d'%idx
        if sig in {b'FCIS', b'FLIS', b'SRCS', b'DATP', b'RESC', b'BOUN',
                b'FDST', b'AUDI', b'VIDE',}:
            name += '-' + sig.decode('ascii')
        elif sig == b'\xe9\x8e\r\n':
            name += '-' + 'EOF'
        self.name = name

    def dump(self, folder):
        with open(os.path.join(folder, self.name+'.bin'), 'wb') as f:
            f.write(self.raw)

# }}}

class FontRecord(object): # {{{

    def __init__(self, idx, record):
        self.raw = record.raw
        name = '%06d'%idx
        self.font = read_font_record(self.raw)
        if self.font['err']:
            raise ValueError('Failed to read font record: %s Headers: %s'%(
                self.font['err'], self.font['headers']))
        self.payload = (self.font['font_data'] if self.font['font_data'] else
                self.font['raw_data'])
        self.name = '%s.%s'%(name, self.font['ext'])

    def dump(self, folder):
        with open(os.path.join(folder, self.name), 'wb') as f:
            f.write(self.payload)

# }}}

class TBSIndexing(object): # {{{

    def __init__(self, text_records, indices, doc_type):
        self.record_indices = OrderedDict()
        self.doc_type = doc_type
        self.indices = indices
        pos = 0
        for r in text_records:
            start = pos
            pos += len(r.raw)
            end = pos - 1
            self.record_indices[r] = x = {'starts':[], 'ends':[],
                    'complete':[], 'geom': (start, end)}
            for entry in indices:
                istart, sz = entry.offset, entry.size
                iend = istart + sz - 1
                has_start = istart >= start and istart <= end
                has_end = iend >= start and iend <= end
                rec = None
                if has_start and has_end:
                    rec = 'complete'
                elif has_start and not has_end:
                    rec = 'starts'
                elif not has_start and has_end:
                    rec = 'ends'
                if rec:
                    x[rec].append(entry)

    def get_index(self, idx):
        for i in self.indices:
            if i.index in {idx, unicode(idx)}: return i
        raise IndexError('Index %d not found'%idx)

    def __str__(self):
        ans = ['*'*20 + ' TBS Indexing (%d records) '%len(self.record_indices)+ '*'*20]
        for r, dat in self.record_indices.iteritems():
            ans += self.dump_record(r, dat)[-1]
        return '\n'.join(ans)

    def dump(self, bdir):
        types = defaultdict(list)
        for r, dat in self.record_indices.iteritems():
            tbs_type, strings = self.dump_record(r, dat)
            if tbs_type == 0: continue
            types[tbs_type] += strings
        for typ, strings in types.iteritems():
            with open(os.path.join(bdir, 'tbs_type_%d.txt'%typ), 'wb') as f:
                f.write('\n'.join(strings))

    def dump_record(self, r, dat):
        ans = []
        ans.append('\nRecord #%d: Starts at: %d Ends at: %d'%(r.idx,
            dat['geom'][0], dat['geom'][1]))
        s, e, c = dat['starts'], dat['ends'], dat['complete']
        ans.append(('\tContains: %d index entries '
            '(%d ends, %d complete, %d starts)')%tuple(map(len, (s+e+c, e,
                c, s))))
        byts = bytearray(r.trailing_data.get('indexing', b''))
        ans.append('TBS bytes: %s'%format_bytes(byts))
        for typ, entries in (('Ends', e), ('Complete', c), ('Starts', s)):
            if entries:
                ans.append('\t%s:'%typ)
                for x in entries:
                    ans.append(('\t\tIndex Entry: %s (Parent index: %s, '
                            'Depth: %d, Offset: %d, Size: %d) [%s]')%(
                        x.index, x.parent_index, x.depth, x.offset, x.size, x.label))
        def bin4(num):
            ans = bin(num)[2:]
            return bytes('0'*(4-len(ans)) + ans)

        def repr_extra(x):
            return str({bin4(k):v for k, v in extra.iteritems()})

        tbs_type = 0
        is_periodical = self.doc_type in (257, 258, 259)
        if len(byts):
            outermost_index, extra, consumed = decode_tbs(byts, flag_size=3)
            byts = byts[consumed:]
            for k in extra:
                tbs_type |= k
            ans.append('\nTBS: %d (%s)'%(tbs_type, bin4(tbs_type)))
            ans.append('Outermost index: %d'%outermost_index)
            ans.append('Unknown extra start bytes: %s'%repr_extra(extra))
            if is_periodical: # Hierarchical periodical
                try:
                    byts, a = self.interpret_periodical(tbs_type, byts,
                        dat['geom'][0])
                except:
                    import traceback
                    traceback.print_exc()
                    a = []
                    print ('Failed to decode TBS bytes for record: %d'%r.idx)
                ans += a
            if byts:
                sbyts = tuple(hex(b)[2:] for b in byts)
                ans.append('Remaining bytes: %s'%' '.join(sbyts))

        ans.append('')
        return tbs_type, ans

    def interpret_periodical(self, tbs_type, byts, record_offset):
        ans = []

        def read_section_transitions(byts, psi=None): # {{{
            if psi is None:
                # Assume previous section is 1
                psi = self.get_index(1)

            while byts:
                ai, extra, consumed = decode_tbs(byts)
                byts = byts[consumed:]
                if extra.get(0b0010, None) is not None:
                    raise ValueError('Dont know how to interpret flag 0b0010'
                            ' while reading section transitions')
                if extra.get(0b1000, None) is not None:
                    if len(extra) > 1:
                        raise ValueError('Dont know how to interpret flags'
                                ' %r while reading section transitions'%extra)
                    nsi = self.get_index(psi.index+1)
                    ans.append('Last article in this record of section %d'
                            ' (relative to next section index [%d]): '
                            '%d [%d absolute index]'%(psi.index, nsi.index, ai,
                                ai+nsi.index))
                    psi = nsi
                    continue

                ans.append('First article in this record of section %d'
                        ' (relative to its parent section): '
                        '%d [%d absolute index]'%(psi.index, ai, ai+psi.index))

                num = extra.get(0b0100, None)
                if num is None:
                    msg = ('The section %d has at most one article'
                            ' in this record')%psi.index
                else:
                    msg = ('Number of articles in this record of '
                        'section %d: %d')%(psi.index, num)
                ans.append(msg)

                offset = extra.get(0b0001, None)
                if offset is not None:
                    if offset == 0:
                        ans.append('This record is spanned by the article:'
                                '%d'%(ai+psi.index))
                    else:
                        ans.append('->Offset to start of next section (%d) from start'
                            ' of record: %d [%d absolute offset]'%(psi.index+1,
                                offset, offset+record_offset))
            return byts
        # }}}

        def read_starting_section(byts): # {{{
            orig = byts
            si, extra, consumed = decode_tbs(byts)
            byts = byts[consumed:]
            if len(extra) > 1 or 0b0010 in extra or 0b1000 in extra:
                raise ValueError('Dont know how to interpret flags %r'
                        ' when reading starting section'%extra)
            si = self.get_index(si)
            ans.append('The section at the start of this record is:'
                    ' %s'%si.index)
            if 0b0100 in extra:
                num = extra[0b0100]
                ans.append('The number of articles from the section %d'
                        ' in this record: %s'%(si.index, num))
            elif 0b0001 in extra:
                eof = extra[0b0001]
                if eof != 0:
                    raise ValueError('Unknown eof value %s when reading'
                            ' starting section. All bytes: %r'%(eof, orig))
                ans.append('??This record has more than one article from '
                        ' the section: %s'%si.index)
            return si, byts
        # }}}

        if tbs_type & 0b0100:
            # Starting section is the first section
            ssi = self.get_index(1)
        else:
            ssi, byts = read_starting_section(byts)

        byts = read_section_transitions(byts, ssi)

        return byts, ans

# }}}

class MOBIFile(object): # {{{

    def __init__(self, stream):
        self.raw = stream.read()

        self.palmdb = PalmDB(self.raw[:78])

        self.record_headers = []
        self.records = []
        for i in xrange(self.palmdb.number_of_records):
            pos = 78 + i * 8
            offset, a1, a2, a3, a4 = struct.unpack(b'>LBBBB', self.raw[pos:pos+8])
            flags, val = a1, a2 << 16 | a3 << 8 | a4
            self.record_headers.append((offset, flags, val))

        def section(section_number):
            if section_number == self.palmdb.number_of_records - 1:
                end_off = len(self.raw)
            else:
                end_off = self.record_headers[section_number + 1][0]
            off = self.record_headers[section_number][0]
            return self.raw[off:end_off]

        for i in range(self.palmdb.number_of_records):
            self.records.append(Record(section(i), self.record_headers[i]))

        self.mobi_header = MOBIHeader(self.records[0])
        self.huffman_record_nums = []

        if 'huff' in self.mobi_header.compression.lower():
            self.huffman_record_nums = list(xrange(self.mobi_header.huffman_record_offset,
                        self.mobi_header.huffman_record_offset +
                        self.mobi_header.huffman_record_count))
            huffrecs = [self.records[r].raw for r in self.huffman_record_nums]
            from calibre.ebooks.mobi.huffcdic import HuffReader
            huffs = HuffReader(huffrecs)
            decompress = huffs.unpack
        elif 'palmdoc' in self.mobi_header.compression.lower():
            from calibre.ebooks.compression.palmdoc import decompress_doc
            decompress = decompress_doc
        else:
            decompress = lambda x: x

        self.index_header = self.index_record = None
        self.indexing_record_nums = set()
        pir = self.mobi_header.primary_index_record
        if pir != NULL_INDEX:
            self.index_header = IndexHeader(self.records[pir])
            numi = self.index_header.index_count
            self.cncx = CNCX(self.records[
                pir+1+numi:pir+1+numi+self.index_header.num_of_cncx_blocks],
                self.index_header.index_encoding)
            self.index_record = IndexRecord(self.records[pir+1:pir+1+numi],
                    self.index_header, self.cncx)
            self.indexing_record_nums = set(xrange(pir,
                pir+1+numi+self.index_header.num_of_cncx_blocks))
        self.secondary_index_record = self.secondary_index_header = None
        sir = self.mobi_header.secondary_index_record
        if sir != NULL_INDEX:
            self.secondary_index_header = SecondaryIndexHeader(self.records[sir])
            numi = self.secondary_index_header.index_count
            self.indexing_record_nums.add(sir)
            self.secondary_index_record = IndexRecord(
                    self.records[sir+1:sir+1+numi], self.secondary_index_header, self.cncx)
            self.indexing_record_nums |= set(xrange(sir+1, sir+1+numi))


        ntr = self.mobi_header.number_of_text_records
        fntbr = self.mobi_header.first_non_book_record
        fii = self.mobi_header.first_image_index
        if fntbr == NULL_INDEX:
            fntbr = len(self.records)
        self.text_records = [TextRecord(r, self.records[r],
            self.mobi_header.extra_data_flags, decompress) for r in xrange(1,
            min(len(self.records), ntr+1))]
        self.image_records, self.binary_records = [], []
        self.font_records = []
        image_index = 0
        for i in xrange(fntbr, len(self.records)):
            if i in self.indexing_record_nums or i in self.huffman_record_nums:
                continue
            image_index += 1
            r = self.records[i]
            fmt = None
            if i >= fii and r.raw[:4] not in {b'FLIS', b'FCIS', b'SRCS',
                    b'\xe9\x8e\r\n', b'RESC', b'BOUN', b'FDST', b'DATP',
                    b'AUDI', b'VIDE', b'FONT'}:
                try:
                    width, height, fmt = identify_data(r.raw)
                except:
                    pass
            if fmt is not None:
                self.image_records.append(ImageRecord(image_index, r, fmt))
            elif r.raw[:4] == b'FONT':
                self.font_records.append(FontRecord(i, r))
            else:
                self.binary_records.append(BinaryRecord(i, r))

        if self.index_record is not None:
            self.tbs_indexing = TBSIndexing(self.text_records,
                    self.index_record.indices, self.mobi_header.type_raw)

    def print_header(self, f=sys.stdout):
        print (str(self.palmdb).encode('utf-8'), file=f)
        print (file=f)
        print ('Record headers:', file=f)
        for i, r in enumerate(self.records):
            print ('%6d. %s'%(i, r.header), file=f)

        print (file=f)
        print (str(self.mobi_header).encode('utf-8'), file=f)
# }}}

def inspect_mobi(path_or_stream, ddir=None): # {{{
    stream = (path_or_stream if hasattr(path_or_stream, 'read') else
            open(path_or_stream, 'rb'))
    f = MOBIFile(stream)
    if ddir is None:
        ddir = 'decompiled_' + os.path.splitext(os.path.basename(stream.name))[0]
    try:
        shutil.rmtree(ddir)
    except:
        pass
    os.makedirs(ddir)
    with open(os.path.join(ddir, 'header.txt'), 'wb') as out:
        f.print_header(f=out)

    alltext = os.path.join(ddir, 'text.html')
    with open(alltext, 'wb') as of:
        alltext = b''
        for rec in f.text_records:
            of.write(rec.raw)
            alltext += rec.raw
        of.seek(0)
    if f.mobi_header.file_version < 8:
        root = html.fromstring(alltext.decode('utf-8'))
        with open(os.path.join(ddir, 'pretty.html'), 'wb') as of:
            of.write(html.tostring(root, pretty_print=True, encoding='utf-8',
                include_meta_content_type=True))


    if f.index_header is not None:
        f.index_record.alltext = alltext
        with open(os.path.join(ddir, 'index.txt'), 'wb') as out:
            print(str(f.index_header), file=out)
            print('\n\n', file=out)
            if f.secondary_index_header is not None:
                print(str(f.secondary_index_header).encode('utf-8'), file=out)
                print('\n\n', file=out)
            if f.secondary_index_record is not None:
                print(str(f.secondary_index_record).encode('utf-8'), file=out)
                print('\n\n', file=out)
            print(str(f.cncx).encode('utf-8'), file=out)
            print('\n\n', file=out)
            print(str(f.index_record), file=out)
        with open(os.path.join(ddir, 'tbs_indexing.txt'), 'wb') as out:
            print(str(f.tbs_indexing), file=out)
        f.tbs_indexing.dump(ddir)

    for tdir, attr in [('text', 'text_records'), ('images', 'image_records'),
            ('binary', 'binary_records'), ('font', 'font_records')]:
        tdir = os.path.join(ddir, tdir)
        os.mkdir(tdir)
        for rec in getattr(f, attr):
            rec.dump(tdir)


    print ('Debug data saved to:', ddir)

# }}}

def main():
    inspect_mobi(sys.argv[1])

if __name__ == '__main__':
    main()

