def grad(n):
    s = 0x08
    r = 0xff
    g = 0x00
    b = 0x00
    for i in range(n):
        if r >= s and b < s:
            r -= s
            g += s
        elif g >= s and r < s:
            g -= s
            b += s
        elif b >= s and g < s:
            b -= s
            r += s
    return f'#{r:02x}{g:02x}{b:02x}'

def fancy_greet(version):
    from rich.console import Console
    from rich.text import Text
    zc_msg = fr'''
|||   . . _  _._|_     _. . . _ .__ _.. _.  . __.. _  __.  .
|||  //\|/ |/_| |  == /  / \|/ |(  /_||/ |  | __||/ |/   \_|
|||  \_/|  |\_  |.    \__\_/|  |_) \_ |   \/ |__||  |\__ _/
|||
|||  v{version}
'''
    lns = zc_msg.split('\n')
    console = Console()
    for l in lns:
        txt = Text(l)
        txt.stylize('bold')
        for i in range(len(l)):
            txt.stylize(grad(i), i, i+1)
        console.print(txt)
