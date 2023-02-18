from .ply import yacc
from .junoslex import tokens


# command returns a function that can be executed in the context
# of a router (or whatever device)
def p_command(p):
    '''command : showcommand'''
    p[0] = p[1]


def p_showcommand(p):
    '''showcommand : SHOW showroute
                   | SHOW showethernet
    '''
    p[0] = p[2]


def p_showroute(p):
    '''showroute : ROUTE
                 | ROUTE PREFIX
    '''
                     
    p[0] = lambda router: router.show_route_table()

def p_showethernet(p):
    '''showethernet : ETHERNETSWITCHING TABLE'''

    p[0] = lambda device: device._bridging.bridging.print_bridging_table()

#def p_eterror(p):
#    '''eterror :'''
#    print("Specify table")

def p_error(p):
    if p:
         print("Syntax error at token", p.type)

parser = yacc.yacc()

#while True:
#    try:
#        s = input('calc > ')
#    except EOFError:
#        break
#    if not s:
#        continue
#    result = parser.parse(s)
#    print(result)
