"""Minimal Tkinter desktop UI; all engine work runs outside Tk's thread."""
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .client import AnalysisSession, format_event, format_header
from .model import DEFAULT_ENGINE, HISTORY_NOTE, load_suite, save_suite, validate_case

START_FEN = 'W:W31-50:B1-20'


class PositionApp:
    def __init__(self, root):
        self.root = root
        root.title('Frisian Draughts - Position Suite')
        root.geometry('1120x820')
        root.minsize(900, 680)
        self.cases = []
        self.selected = None
        self.session = None
        self.events = queue.Queue()
        self.loaded = None
        self.busy_widgets = []
        self.engine = tk.StringVar(value=str(DEFAULT_ENGINE))
        self.name = tk.StringVar(value='New position')
        self.fen = tk.StringVar(value=START_FEN)
        self.depth = tk.StringVar(value='10')
        self.accepted = tk.StringVar()
        self.replay = tk.StringVar()
        self.restrictions = tk.StringVar(value='{}')
        self.tt_enabled = tk.BooleanVar(value=True)
        self.tt_megabytes = tk.StringVar(value='16')
        self.status = tk.StringVar(value='Paste a draughts FEN, then Import / Preview.')
        outer = ttk.Frame(root, padding=10)
        outer.pack(fill='both', expand=True)
        engine_row = ttk.Frame(outer)
        engine_row.pack(fill='x')
        ttk.Label(engine_row, text='Engine executable').pack(side='left')
        self._entry(engine_row, self.engine).pack(side='left', fill='x', expand=True, padx=6)
        self._button(engine_row, 'Browse...', self.choose_engine).pack(side='left')
        body = ttk.Panedwindow(outer, orient='horizontal')
        body.pack(fill='both', expand=True, pady=8)
        sidebar = ttk.Frame(body)
        body.add(sidebar, weight=1)
        ttk.Label(sidebar, text='Saved position cases').pack(anchor='w')
        self.listbox = tk.Listbox(sidebar, exportselection=False, width=24)
        self.listbox.pack(fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.select_case)
        self.busy_widgets.append(self.listbox)
        for title, command in [('New case', self.new_case), ('Add / Update case', self.store_case),
                               ('Remove case', self.remove_case), ('Load suite...', self.load),
                               ('Save suite...', self.save)]:
            self._button(sidebar, title, command).pack(fill='x', pady=2)
        main = ttk.Frame(body, padding=(10, 0))
        body.add(main, weight=4)
        form = ttk.Frame(main)
        form.pack(fill='x')
        self._field(form, 0, 'Name', self.name)
        self._field(form, 1, 'FEN', self.fen)
        self._field(form, 2, 'Accepted moves (optional, comma/space separated)', self.accepted)
        self._field(form, 3, 'Replay moves (optional, space separated)', self.replay)
        self._field(form, 4, 'Initial restrictions JSON (optional)', self.restrictions)
        ttk.Label(form, text='Notes').grid(row=5, column=0, sticky='w')
        self.notes = tk.Text(form, height=2, width=30, wrap='word')
        self.notes.grid(row=5, column=1, sticky='ew', pady=2)
        self.busy_widgets.append(self.notes)
        form.columnconfigure(1, weight=1)
        controls = ttk.Frame(main)
        controls.pack(fill='x', pady=6)
        ttk.Label(controls, text='Depth').pack(side='left')
        depth = ttk.Spinbox(controls, from_=1, to=64, width=4, textvariable=self.depth)
        depth.pack(side='left', padx=4)
        self.busy_widgets.append(depth)
        tt = ttk.Checkbutton(controls, text='Use TT', variable=self.tt_enabled)
        tt.pack(side='left', padx=4)
        self.busy_widgets.append(tt)
        ttk.Label(controls, text='MiB').pack(side='left')
        memory = ttk.Spinbox(controls, from_=1, to=256, width=4, textvariable=self.tt_megabytes)
        memory.pack(side='left', padx=4)
        self.busy_widgets.append(memory)
        self._button(controls, 'Import / Preview', lambda: self.start('inspect')).pack(side='left', padx=3)
        self._button(controls, 'Analyze', lambda: self.start('analyze')).pack(side='left', padx=3)
        self.cancel_button = ttk.Button(controls, text='Cancel', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=3)
        ttk.Button(controls, text='Export log...', command=self.export).pack(side='right')
        ttk.Label(main, text=HISTORY_NOTE, wraplength=760, foreground='#765110').pack(fill='x', pady=3)
        center = ttk.Panedwindow(main, orient='horizontal')
        center.pack(fill='both', expand=True)
        board_frame = ttk.Frame(center)
        center.add(board_frame, weight=1)
        self.board = tk.Canvas(board_frame, width=360, height=360, background='#f0e4cc', highlightthickness=0)
        self.board.pack(fill='both', expand=True)
        self.board.bind('<Configure>', lambda event: self.draw_board())
        log_frame = ttk.Frame(center)
        center.add(log_frame, weight=2)
        ttk.Label(log_frame, text='Search log (score from side to move)').pack(anchor='w')
        self.log = tk.Text(log_frame, width=55, wrap='word', state='disabled')
        scrollbar = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.log.pack(fill='both', expand=True)
        ttk.Label(outer, textvariable=self.status, wraplength=1050).pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.poll)
        self.draw_board()

    def _button(self, parent, text, command):
        widget = ttk.Button(parent, text=text, command=command)
        self.busy_widgets.append(widget)
        return widget

    def _entry(self, parent, variable):
        widget = ttk.Entry(parent, textvariable=variable)
        self.busy_widgets.append(widget)
        return widget

    def _field(self, parent, row, label, variable):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', padx=(0, 5))
        self._entry(parent, variable).grid(row=row, column=1, sticky='ew', pady=2)

    def append_log(self, text, clear=False):
        self.log.configure(state='normal')
        if clear:
            self.log.delete('1.0', 'end')
        self.log.insert('end', text)
        self.log.see('end')
        self.log.configure(state='disabled')

    def current_case(self):
        try:
            depth = int(self.depth.get())
            memory = int(self.tt_megabytes.get())
            restrictions = json.loads(self.restrictions.get().strip() or '{}')
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f'Invalid depth or restriction JSON: {exc}') from exc
        accepted = self.accepted.get().replace(',', ' ').split()
        return validate_case({'name': self.name.get(), 'fen': self.fen.get(), 'depth': depth,
                              'accepted_moves': accepted, 'notes': self.notes.get('1.0', 'end-1c'),
                              'restrictions': restrictions, 'moves': self.replay.get().split(),
                              'tt_enabled': self.tt_enabled.get(), 'tt_megabytes': memory})

    def choose_engine(self):
        path = filedialog.askopenfilename(title='Choose the compiled Rust engine')
        if path:
            self.engine.set(path)

    def set_busy(self, busy):
        for widget in self.busy_widgets:
            widget.configure(state='disabled' if busy else 'normal')
        self.cancel_button.configure(state='normal' if busy else 'disabled')

    def start(self, command):
        if self.session:
            return
        try:
            case = self.current_case()
        except ValueError as exc:
            messagebox.showerror('Invalid position case', str(exc))
            return
        self.session = AnalysisSession(self.engine.get())
        session = self.session
        self.loaded = None
        self.draw_board()
        self.append_log(format_header(case, self.engine.get()), clear=True)
        self.set_busy(True)
        self.status.set('Importing...' if command == 'inspect' else 'Analyzing...')
        def work():
            try:
                outcome = session.run(case, lambda event: self.events.put(('event', event)), command)
                self.events.put(('done', outcome))
            except Exception as exc:  # Surface worker failures rather than freezing the UI.
                self.events.put(('exception', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def cancel(self):
        if self.session:
            self.session.cancel()
            self.status.set('Cancelling...')
            self.cancel_button.configure(state='disabled')

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == 'event':
                    self.append_log(format_event(payload))
                    if payload['type'] == 'loaded':
                        self.loaded = payload
                        self.draw_board()
                else:
                    self.session = None
                    self.set_busy(False)
                    if kind == 'done':
                        text = payload.status.upper() + (f': {payload.message}' if payload.message else '')
                    else:
                        text = f'ERROR: {payload}'
                    self.status.set(text)
                    self.append_log('\nSTATUS: ' + text + '\n')
        except queue.Empty:
            pass
        self.root.after(50, self.poll)

    def draw_board(self):
        self.board.delete('all')
        size = max(100, min(self.board.winfo_width(), self.board.winfo_height()))
        step = size / 10
        pieces = {p['square']: p for p in (self.loaded or {}).get('pieces', [])}
        for row in range(10):
            for col in range(10):
                x, y = col * step, row * step
                dark = (row + col) % 2 == 1
                self.board.create_rectangle(x, y, x + step, y + step,
                                            fill='#89765e' if dark else '#f0e4cc', outline='')
                if not dark:
                    continue
                square = row * 5 + col // 2 + 1
                self.board.create_text(x + 3, y + 2, text=str(square), anchor='nw', fill='#211d18',
                                       font=('TkDefaultFont', max(7, int(step * .20))))
                piece = pieces.get(square)
                if piece:
                    fill = '#fafafa' if piece['side'] == 'white' else '#242424'
                    margin = step * .19
                    self.board.create_oval(x + margin, y + margin, x + step - margin, y + step - margin,
                                           fill=fill, outline='#111111', width=2)
                    if piece['piece'] == 'king':
                        self.board.create_text(x + step / 2, y + step / 2, text='K',
                                               fill='#111111' if piece['side'] == 'white' else '#ffffff')
        if not self.loaded:
            self.board.create_text(size / 2, size / 2, text='Import / Preview to load the position',
                                   fill='white', width=size - 20, justify='center')

    def refresh_list(self):
        self.listbox.delete(0, 'end')
        for case in self.cases:
            self.listbox.insert('end', case['name'])
        if self.selected is not None:
            self.listbox.selection_set(self.selected)

    def select_case(self, event=None):
        selection = self.listbox.curselection()
        if not selection:
            return
        self.selected = selection[0]
        case = self.cases[self.selected]
        self.name.set(case['name']); self.fen.set(case['fen']); self.depth.set(str(case['depth']))
        self.accepted.set(', '.join(case.get('accepted_moves', [])))
        self.replay.set(' '.join(case.get('moves', [])))
        self.restrictions.set(json.dumps(case.get('restrictions', {})))
        self.tt_enabled.set(case.get('tt_enabled', True))
        self.tt_megabytes.set(str(case.get('tt_megabytes', 16)))
        self.notes.delete('1.0', 'end'); self.notes.insert('1.0', case.get('notes', ''))
        self.loaded = None; self.draw_board()
        self.status.set('Case selected. Import / Preview or Analyze to validate it.')

    def new_case(self):
        self.selected = None
        self.listbox.selection_clear(0, 'end')
        self.name.set('New position'); self.fen.set(START_FEN); self.depth.set('10')
        self.accepted.set(''); self.replay.set(''); self.restrictions.set('{}'); self.tt_enabled.set(True)
        self.tt_megabytes.set('16')
        self.notes.delete('1.0', 'end')
        self.loaded = None; self.draw_board()

    def store_case(self):
        try:
            case = self.current_case()
            if self.selected is None:
                self.cases.append(case); self.selected = len(self.cases) - 1
            else:
                self.cases[self.selected] = case
            self.refresh_list()
            self.status.set('Case stored in memory. Save suite to write it to disk.')
        except ValueError as exc:
            messagebox.showerror('Invalid case', str(exc))

    def remove_case(self):
        if self.selected is not None:
            self.cases.pop(self.selected)
            self.new_case(); self.refresh_list()

    def load(self):
        path = filedialog.askopenfilename(title='Load suite', filetypes=[('JSON suites', '*.json')])
        if not path:
            return
        try:
            self.cases = load_suite(path)
            self.new_case(); self.refresh_list()
            self.status.set(f'Loaded {len(self.cases)} cases from {path}')
        except (OSError, ValueError) as exc:
            messagebox.showerror('Cannot load suite', str(exc))

    def save(self):
        if not self.cases:
            messagebox.showinfo('No cases', 'Use Add / Update case before saving a suite.')
            return
        path = filedialog.asksaveasfilename(title='Save suite', defaultextension='.json', filetypes=[('JSON suites', '*.json')])
        if path:
            try:
                save_suite(path, self.cases)
                self.status.set(f'Saved {len(self.cases)} cases to {path}')
            except (OSError, ValueError) as exc:
                messagebox.showerror('Cannot save suite', str(exc))

    def export(self):
        path = filedialog.asksaveasfilename(title='Export search log', defaultextension='.txt', filetypes=[('Text logs', '*.txt')])
        if path:
            try:
                Path(path).write_text(self.log.get('1.0', 'end-1c'), encoding='utf-8')
            except OSError as exc:
                messagebox.showerror('Cannot export log', str(exc))

    def close(self):
        if self.session:
            self.session.cancel()
        self.root.destroy()


def launch():
    root = tk.Tk()
    PositionApp(root)
    root.mainloop()
