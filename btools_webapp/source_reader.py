"""Read DOCX body blocks, run bold, lists and merged tables without AI rewriting."""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET
try:
    from job_store import JobProcessingError
except ImportError:
    from .job_store import JobProcessingError

NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W = '{' + NS + '}'
MAX_DOCX_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 64 * 1024 * 1024


def source_from_docx_bytes(data):
    if not isinstance(data, bytes) or len(data) > MAX_DOCX_BYTES:
        raise JobProcessingError('DOCX exceeds the 20 MB input limit.')
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_XML_BYTES:
                raise JobProcessingError('DOCX expanded contents exceed the safe input limit.')
            xml = archive.read('word/document.xml')
            if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                raise JobProcessingError('DOCX XML contains unsupported entities.')
            body = ET.fromstring(xml).find(W + 'body')
            if body is None: raise JobProcessingError('DOCX has no document body.')
            styles, style_info = {}, {}
            numbering, abstract_numbering, counters = {}, {}, {}
            if 'word/numbering.xml' in archive.namelist():
                nr = ET.fromstring(archive.read('word/numbering.xml'))
                for abstract in nr.findall(W + 'abstractNum'):
                    levels = {}
                    for lvl in abstract.findall(W + 'lvl'):
                        def value(name, default):
                            e = lvl.find(W + name)
                            return e.get(W + 'val', default) if e is not None else default
                        levels[int(lvl.get(W + 'ilvl', '0'))] = {
                            'format': value('numFmt', 'bullet'), 'text': value('lvlText', '•'),
                            'start': int(value('start', '1'))}
                    abstract_numbering[abstract.get(W + 'abstractNumId')] = levels
                for num in nr.findall(W + 'num'):
                    a = num.find(W + 'abstractNumId')
                    if a is None: continue
                    levels = {k: dict(v) for k, v in abstract_numbering.get(a.get(W + 'val'), {}).items()}
                    for override in num.findall(W + 'lvlOverride'):
                        start = override.find(W + 'startOverride')
                        level = int(override.get(W + 'ilvl', '0'))
                        if start is not None and level in levels: levels[level]['start'] = int(start.get(W + 'val', '1'))
                    numbering[num.get(W + 'numId')] = levels
            if 'word/styles.xml' in archive.namelist():
                style_root = ET.fromstring(archive.read('word/styles.xml'))
                for style in style_root.findall(W + 'style'):
                    sid = style.get(W + 'styleId')
                    style_info[sid] = style
                    bold = style.find('./' + W + 'rPr/' + W + 'b')
                    styles[sid] = bold is not None and bold.get(W + 'val', '1') not in ('0', 'false', 'off')
            warnings = []
            for name in archive.namelist():
                if name.startswith(('word/header', 'word/footer', 'word/footnotes', 'word/endnotes')) and name.endswith('.xml'):
                    ancillary = ET.fromstring(archive.read(name))
                    if any((e.text or '').strip() for e in ancillary.iter(W + 't')):
                        warnings.append('พบข้อความใน ' + name + ' ที่อยู่นอกเนื้อหาเอกสาร กรุณาตรวจต้นฉบับเพิ่มเติม')
            if body.find('.//' + W + 'drawing') is not None or body.find('.//' + W + 'pict') is not None:
                warnings.append('ต้นฉบับมีภาพหรือวัตถุกราฟิก รุ่นนี้เก็บข้อความและตารางในเนื้อหา กรุณาตรวจภาพเพิ่มเติม')
            if body.find('.//' + W + 'del') is not None or body.find('.//' + W + 'ins') is not None:
                warnings.append('ต้นฉบับมี Track Changes ระบบอ่านข้อความที่เพิ่มและไม่รวมข้อความที่ลบ กรุณาตรวจการแก้ไข')
    except (BadZipFile, KeyError, ET.ParseError, RuntimeError, OSError):
        raise JobProcessingError('Cannot read DOCX structure; check the source file.')
    source = {'version': 1, 'blocks': [], 'tables': [], 'warnings': warnings,
              'scope': 'document_body', 'format': 'docx'}

    def style_property(sid, group, name):
        seen = set()
        while sid in style_info and sid not in seen:
            seen.add(sid)
            style = style_info[sid]
            prop = style.find('./' + W + group + '/' + W + name)
            if prop is not None: return prop
            parent = style.find(W + 'basedOn')
            sid = parent.get(W + 'val') if parent is not None else None
        return None
    for sid in style_info:
        bold = style_property(sid, 'rPr', 'b')
        styles[sid] = bold is not None and bold.get(W + 'val', '1') not in ('0', 'false', 'off')

    def number_label(value, kind):
        if kind == 'decimal': return str(value)
        if kind in ('lowerLetter', 'upperLetter'):
            letters = ''
            while value > 0:
                value, digit = divmod(value - 1, 26); letters = chr(65 + digit) + letters
            return letters.lower() if kind == 'lowerLetter' else letters
        if kind in ('lowerRoman', 'upperRoman'):
            result = ''
            for amount, letters in [(1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]:
                while value >= amount: result += letters; value -= amount
            return result.lower() if kind == 'lowerRoman' else result
        return str(value)

    def paragraph(element):
        pieces, bold_ranges, position = [], [], 0
        p_style = element.find('./' + W + 'pPr/' + W + 'pStyle')
        style_name = p_style.get(W + 'val', '') if p_style is not None else ''
        default_bold = styles.get(style_name, False)
        # Iterate in XML order, ignoring deleted text, and retaining tabs/line breaks.
        def walk(node, inherited_bold=False):
            nonlocal position
            if node.tag in (W + 'del', W + 'moveFrom'): return
            if node.tag == W + 'r':
                b = node.find('./' + W + 'rPr/' + W + 'b')
                r_style = node.find('./' + W + 'rPr/' + W + 'rStyle')
                inherited_bold = styles.get(r_style.get(W + 'val'), default_bold) if r_style is not None else default_bold
                if b is not None: inherited_bold = b.get(W + 'val', '1') not in ('0', 'false', 'off')
            text = None
            if node.tag == W + 't': text = node.text or ''
            elif node.tag == W + 'tab': text = '\t'
            elif node.tag in (W + 'br', W + 'cr'): text = '\n'
            if text is not None:
                if text and inherited_bold: bold_ranges.append({'start': position, 'end': position + len(text)})
                pieces.append(text); position += len(text)
            else:
                for child in node: walk(child, inherited_bold)
        walk(element)
        text = ''.join(pieces)
        if not text.strip(): return None
        kind, level, label = 'paragraph', 0, ''
        num = element.find('./' + W + 'pPr/' + W + 'numPr')
        heading = element.find('./' + W + 'pPr/' + W + 'outlineLvl')
        if num is None: num = style_property(style_name, 'pPr', 'numPr')
        if heading is None: heading = style_property(style_name, 'pPr', 'outlineLvl')
        if num is not None:
            kind = 'bullet'
            ilvl = num.find(W + 'ilvl')
            level = int(ilvl.get(W + 'val', '0')) if ilvl is not None else 0
            num_id = num.find(W + 'numId')
            num_key = num_id.get(W + 'val') if num_id is not None else None
            levels = numbering.get(num_key, {})
            definition = levels.get(level)
            if definition:
                count = counters.setdefault(num_key, {})
                count[level] = count.get(level, definition['start'] - 1) + 1
                for deeper in list(count):
                    if deeper > level: del count[deeper]
                if definition['format'] != 'bullet':
                    label = definition['text']
                    for li, ld in levels.items():
                        label = label.replace('%' + str(li + 1), number_label(count.get(li, ld['start']), ld['format']))
                    if definition['format'] not in ('decimal', 'lowerLetter', 'upperLetter', 'lowerRoman', 'upperRoman'):
                        source['warnings'].append('มีรูปแบบเลขรายการที่ต้องตรวจ: ' + definition['format'])
            elif num_key not in ('0', None):
                source['warnings'].append('ไม่พบคำนิยามรายการ Word กรุณาตรวจเลขหรือสัญลักษณ์รายการ')
        elif heading is not None or style_name.lower().startswith('heading'):
            kind = 'heading'
            level = int(heading.get(W + 'val', '0')) + 1 if heading is not None else 1
        bid = 'B' + str(len(source['blocks']) + 1).zfill(6)
        source['blocks'].append({'id': bid, 'text': text, 'bold': bold_ranges,
                                 'kind': kind, 'level': level, 'list_label': label})
        return bid

    def table(element):
        tid = 'T' + str(len(source['tables']) + 1).zfill(6)
        result = {'id': tid, 'rows': []}
        source['tables'].append(result)
        vertical = {}
        for ri, tr in enumerate(element.findall(W + 'tr')):
            row = {'cells': []}; result['rows'].append(row)
            before = tr.find('./' + W + 'trPr/' + W + 'gridBefore')
            col = int(before.get(W + 'val', '0')) if before is not None else 0
            next_vertical = {}
            for tc in tr.findall(W + 'tc'):
                span = tc.find('./' + W + 'tcPr/' + W + 'gridSpan')
                cs = int(span.get(W + 'val', '1')) if span is not None else 1
                vm = tc.find('./' + W + 'tcPr/' + W + 'vMerge')
                ids = []
                for child in tc:
                    if child.tag == W + 'p':
                        bid = paragraph(child)
                        if bid: ids.append(bid)
                    elif child.tag == W + 'tbl':
                        # Keep nested text, explicitly flag that nested grid layout needs review.
                        source['warnings'].append('มีตารางซ้อนในเซลล์ ระบบเก็บข้อความไว้ในเซลล์เดิม แต่ต้องตรวจรูปแบบตารางซ้อน')
                        for p in child.iter(W + 'p'):
                            bid = paragraph(p)
                            if bid: ids.append(bid)
                if vm is not None and vm.get(W + 'val', 'continue') == 'continue':
                    origin = vertical.get(col)
                    if origin is None or origin['col_span'] != cs:
                        raise JobProcessingError('DOCX has an unsupported merged-cell layout.')
                    origin['row_span'] += 1
                    origin['block_ids'].extend(ids)
                    next_vertical[col] = origin
                else:
                    entry = {'column': col, 'col_span': cs, 'row_span': 1, 'block_ids': ids}
                    row['cells'].append(entry)
                    if vm is not None: next_vertical[col] = entry
                col += cs
            vertical = next_vertical
        return tid

    def walk_body(element):
        for child in element:
            if child.tag == W + 'p': paragraph(child)
            elif child.tag == W + 'tbl': table(child)
            elif child.tag in (W + 'sdt', W + 'sdtContent', W + 'customXml', W + 'ins'):
                walk_body(child)
            elif child.tag == W + 'altChunk':
                source['warnings'].append('มีเนื้อหาแทรกแบบ altChunk ซึ่งยังอ่านไม่ได้ กรุณาตรวจต้นฉบับ')
    try:
        walk_body(body)
    except (ValueError, TypeError):
        raise JobProcessingError('DOCX has invalid list/table attributes.')
    return source
