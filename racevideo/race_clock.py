"""Race elapsed display, independent of local daylight-saving interpretation."""
from datetime import datetime


def elapsed(ns,milliseconds=True,compact=False):
    negative=ns<0;value=abs(int(ns))//1_000_000
    seconds,ms=divmod(value,1000);minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    value=(f'{hours}:{minutes:02}:{seconds:02}' if hours else f'{minutes}:{seconds:02}') if compact else f'{hours:02}:{minutes:02}:{seconds:02}'
    return ('-' if negative else '')+value+(f'.{ms:03}' if milliseconds else '')


def display(ns,event=None,offset=0,camera=False,milliseconds=True,prefix=True,compact=False):
    if event is not None:
        corrected=ns-round(offset*1e9) if camera else ns
        value=elapsed(corrected-event['start_ns'],milliseconds,compact);label='Race '
    else:
        value=datetime.fromtimestamp(ns/1e9).strftime('%H:%M:%S.%f')[:-3] if milliseconds else datetime.fromtimestamp(ns/1e9).strftime('%H:%M:%S')
        if compact:value=value.lstrip('0') if not value.startswith('00:') else value[1:]
        label='Clock '
    return (label if prefix else '')+value


def context(ns,events,preferred=None,offset=0):
    if preferred is not None and preferred['start_ns']-30_000_000_000<=ns-round(offset*1e9)<=preferred['end_ns']+30_000_000_000:
        return preferred,offset
    matches=[e for e in events if e['start_ns']<=ns<=e['end_ns']]
    return (matches[0],0) if len(matches)==1 else (None,0)
