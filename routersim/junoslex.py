from .ply import lex

reserved = {
   'show': 'SHOW',
   'route': 'ROUTE',
   'ethernet-switching': 'ETHERNETSWITCHING',
   'table': 'TABLE',
}

tokens = ['ID', 'PREFIX', 'NEWLINE'] + list(reserved.values())

t_PREFIX = r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}(\/[0-9]{1,2})?'

t_ignore = ' \t'


def t_ID(t):
    r'[-A-Za-z]+'
    t.type = reserved.get(t.value,'ID')    # Check for reserved words
    return t

def t_NEWLINE(t):
    r'\n'
    t.lexer.lineno += 1
    return t

def t_error(t):
    print("Illegal character %s" % t.value[0])
    t.lexer.skip(1)
    return t


lex.lex(debug=1)