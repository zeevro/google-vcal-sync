from __future__ import unicode_literals

import urllib
import json

from dateutil import parser


from constants import MY_ICS_URL


def j(o, pretty=False):
    if pretty:
        print(json.dumps(o, separators=(',', ': '), indent=2, sort_keys=True))
    else:
        print(json.dumps(o, separators=(',', ':')))


def unescape_str(s):
    D = {'\\': '\\',
         "'": "'",
         '"': '"',
         'b': '\b',
         'f': '\f',
         't': '\t',
         'n': '\n',
         'r': '\r',
         'v': '\v',
         'a': '\a'}

    ret = ''
    i = 0
    while True:
        n = s.find('\\', i)
        if n == -1 or n == len(s) - 1:
            ret += s[i:]
            break

        ret += s[i: n]
        i = n + 1
        c = s[i]

        if c in D:
            ret += D[c]
            i += 1
        elif c == 'x':
            ret += unichr(int(s[i + 1: i + 3], 16))
            i += 3
        elif c.isdigit():
            ret += unichr(int(s[i: i + 3], 8))
            i += 3
        else:
            ret += c
            i += 1

    return ret


def get_file_tree(file_obj):
    ret = []
    stack = []
    obj = None
    lines = iter(file_obj)
    whole_line = lines.next()
    while True:
        # TODO: Support UTF-8 decoding with line-breaks mid-multibyte characters
        try:
            line = lines.next().decode('utf8').strip('\r\n')
            if line[0] in ' \t':
                whole_line += line[1:]
                continue
        except StopIteration:
            line = None

        try:
            field, value = whole_line.split(':', 1)
            value = unescape_str(value)

            if field == 'BEGIN':
                if obj is not None:
                    stack.append(obj)
                obj = {'_type': value}
                continue

            if obj is None:
                obj = stack.pop()

            if field == 'END':
                if stack:
                    stack[-1].setdefault('_items', []).append(obj)
                else:
                    ret.append(obj)
                obj = None
                continue

            if field:
                if ';' in field:
                    # TODO: Support quoted string values
                    # TODO: Support multiple values (comma-separated)
                    values = field.split(';')
                    field = values.pop(0)
                    values = dict(v.split('=') for v in values)
                    values['_value'] = value
                    obj.setdefault(field, []).append(values)
                else:
                    obj[field] = value
        except Exception as e:
            print(line, e.__class__.__name__, e)
        finally:
            if line is None:
                break
            whole_line = line

    return ret


def get_url_tree(url):
    class ChromeOpener(urllib.FancyURLopener):
        version = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36'
    urllib._urlopener = ChromeOpener()
    return get_file_tree(urllib.urlopen(url))


def test():
    tree = get_url_tree(MY_ICS_URL)

    if 0:
        j(tree, True)
        return

    if 0:
        j({event['UID'][:event['UID'].find('@')]:
           parser.parse(event['LAST-MODIFIED']).strftime('%Y-%m-%dT%H:%M:%S%z')
           for event in tree[0]['_items']}, True)
        return

    for calendar in tree:
        for event in reversed(calendar['_items']):
            print '<%s> [%-12s] {%8s} %s by %s' % (
                parser.parse(event['DTSTART']).strftime('%Y-%m-%d %H:%M'),
                (event.get('PARTSTAT', '').replace('-', ' ').capitalize() or 'N/A').center(12),
                event.get('SEQUENCE', '   N/A  '),
                event['SUMMARY'],
                event.get('ORGANIZER', [{'CN': 'Facebook'}])[0]['CN'],
            )


if __name__ == '__main__':
    test()
