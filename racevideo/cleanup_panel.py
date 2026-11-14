"""Deliberate date deletion: a preview, exact typed phrase, then explicit click."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk


def confirmation_phrase(preview):
    return f"DELETE {preview['day']} {preview['clips']}"


class CleanupPanel:
    def __init__(self,root,preview,database,finish):
        self.finish=finish;self.preview=preview;self.done=False
        self.window=tk.Toplevel(root);self.window.title('Permanently delete recordings')
        self.window.transient(root);self.window.resizable(False,False)
        body=ttk.Frame(self.window,padding=18);body.pack(fill='both',expand=True)
        ttk.Label(body,text=f"Delete {preview['clips']} captures from {preview['day']}",font=('TkDefaultFont',12,'bold')).pack(anchor='w')
        ttk.Label(body,text=f"{preview['frames']:,} original frames and associated OCR/reviews will be permanently deleted.\n"
            f"Keep {preview['starred']} starred captures and {preview['busy']} captures with active analysis.\n\n"
            'This applies to the whole date, regardless of bib/star filters.\n'
            'New captures arriving after this preview will be kept.\n'
            'A backup is needed to recover deleted recordings.\n'
            'SQLite may retain the allocated file space after deletion.',wraplength=650).pack(anchor='w',pady=12)
        ttk.Label(body,text='Database: '+str(Path(database).expanduser().resolve()),wraplength=650).pack(anchor='w')
        self.phrase=confirmation_phrase(preview)
        ttk.Label(body,text='To enable deletion, type exactly: '+self.phrase).pack(anchor='w',pady=(14,4))
        self.text=tk.StringVar();self.entry=ttk.Entry(body,textvariable=self.text,width=58);self.entry.pack(fill='x')
        buttons=ttk.Frame(body);buttons.pack(fill='x',pady=(16,0))
        self.cancel_button=ttk.Button(buttons,text='Cancel',command=self.cancel)
        self.cancel_button.pack(side='right',padx=4)
        self.delete_button=ttk.Button(buttons,text=f"Permanently delete {preview['clips']} captures",state='disabled',command=self.delete)
        self.delete_button.pack(side='right',padx=4)
        self.text.trace_add('write',self.changed)
        self.window.protocol('WM_DELETE_WINDOW',self.cancel)
        self.window.bind('<Escape>',lambda e:self.cancel())
        # Enter never submits deletion, even after the exact text is entered.
        self.entry.bind('<Return>',lambda e:'break')
        self.window.grab_set();self.cancel_button.focus_set()

    def changed(self,*args):
        self.delete_button.configure(state='normal' if self.text.get()==self.phrase else 'disabled')

    def complete(self,approved):
        if self.done:return
        self.done=True;self.window.grab_release();self.window.destroy();self.finish(approved)

    def cancel(self):self.complete(False)

    def delete(self):
        if self.text.get()==self.phrase:self.complete(True)
